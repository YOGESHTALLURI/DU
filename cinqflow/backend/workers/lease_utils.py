"""
backend/workers/lease_utils.py
──────────────────────────────
Lease-fencing utilities for the ODS pipeline stage checkpoint.

All database mutations that advance an ODS execution must pass through
validate_lease_for_ods() BEFORE touching any ODS table.  If the lease
has expired or the token has been superseded the function raises
StaleLeaseError and the caller must not proceed with the ODS write.

Claim and reclaim both use the approved CTE pattern:

    WITH cte AS (
        SELECT execution_id, lease_token
        FROM   batch_stage_checkpoint
        WHERE  ...
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE batch_stage_checkpoint bsc
    SET    ...
    FROM   cte
    WHERE  bsc.execution_id = cte.execution_id
    RETURNING bsc.*;

This avoids the invalid ``UPDATE … LIMIT`` syntax and provides correct
PostgreSQL SKIP LOCKED semantics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.exceptions import StaleLeaseError

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------
LEASE_DURATION_SECONDS: int = 300   # 5 minutes
STAGE_NAME: str = "ODS"


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Core lease operations
# ---------------------------------------------------------------------------

def claim_ods_execution(
    session: Session,
    batch_id: uuid.UUID,
    checkpoint_key: str,
    checkpoint_value: str,
) -> dict:
    """Create a new BOUND execution checkpoint and return its lease credentials.

    Multiple concurrent callers may each create their own row; no uniqueness
    is enforced on (batch_id, stage_name, BOUND).

    Returns a dict with keys: execution_id, lease_token, lease_expires_at.
    """
    execution_id = uuid.uuid4()
    lease_token = uuid.uuid4()

    stmt = text(
        """
        INSERT INTO batch_stage_checkpoint
            (execution_id, batch_id, stage_name, checkpoint_key, checkpoint_value,
             execution_state, lease_token, lease_expires_at, created_at, updated_at)
        VALUES
            (:execution_id, :batch_id, :stage_name, :checkpoint_key, :checkpoint_value,
             'BOUND', :lease_token,
             now() + make_interval(secs => :lease_secs),
             now(), now())
        RETURNING execution_id, lease_token, lease_expires_at
        """
    )
    row = session.execute(
        stmt,
        {
            "execution_id": str(execution_id),
            "batch_id": str(batch_id),
            "stage_name": STAGE_NAME,
            "checkpoint_key": checkpoint_key,
            "checkpoint_value": checkpoint_value,
            "lease_token": str(lease_token),
            "lease_secs": LEASE_DURATION_SECONDS,
        },
    ).mappings().one()

    return dict(row)


def transition_to_in_progress(
    session: Session,
    execution_id: uuid.UUID,
    lease_token: uuid.UUID,
) -> bool:
    """Advance an execution from BOUND → IN_PROGRESS.

    Returns True when the row was updated (lease still valid), False otherwise.
    """
    stmt = text(
        """
        UPDATE batch_stage_checkpoint
        SET    execution_state = 'IN_PROGRESS',
               updated_at      = now()
        WHERE  execution_id     = :execution_id
          AND  stage_name       = :stage_name
          AND  execution_state  = 'BOUND'
          AND  lease_token      = :lease_token
          AND  lease_expires_at >= now()
        """
    )
    result = session.execute(
        stmt,
        {
            "execution_id": str(execution_id),
            "stage_name": STAGE_NAME,
            "lease_token": str(lease_token),
        },
    )
    return result.rowcount == 1


def heartbeat(
    session: Session,
    execution_id: uuid.UUID,
    lease_token: uuid.UUID,
) -> bool:
    """Extend the lease expiry for an IN_PROGRESS execution.

    Returns True when the heartbeat succeeded (lease still valid and token
    matches), False when it was already expired or superseded.
    """
    stmt = text(
        """
        UPDATE batch_stage_checkpoint
        SET    lease_expires_at = now() + make_interval(secs => :lease_secs),
               updated_at       = now()
        WHERE  execution_id     = :execution_id
          AND  stage_name       = :stage_name
          AND  execution_state  = 'IN_PROGRESS'
          AND  lease_token      = :lease_token
          AND  lease_expires_at >= now()
        """
    )
    result = session.execute(
        stmt,
        {
            "execution_id": str(execution_id),
            "stage_name": STAGE_NAME,
            "lease_token": str(lease_token),
            "lease_secs": LEASE_DURATION_SECONDS,
        },
    )
    return result.rowcount == 1


def validate_lease_for_ods(
    session: Session,
    execution_id: uuid.UUID,
    lease_token: uuid.UUID,
) -> None:
    """Assert that the calling worker still holds a valid, non-expired lease.

    This is the PRIMARY GUARD that must be called BEFORE any ODS table write.
    If the lease has expired or the token has been superseded by a reclaim,
    StaleLeaseError is raised and the worker must not proceed.

    Implementation performs a SELECT FOR UPDATE on the checkpoint row inside
    the current transaction so that a concurrent reclaimer cannot slip between
    the validation and the ODS write within the same transaction.
    """
    stmt = text(
        """
        SELECT execution_id, lease_token, lease_expires_at, execution_state
        FROM   batch_stage_checkpoint
        WHERE  execution_id = :execution_id
          AND  stage_name   = :stage_name
        FOR UPDATE
        """
    )
    row = session.execute(
        stmt,
        {"execution_id": str(execution_id), "stage_name": STAGE_NAME},
    ).mappings().first()

    if row is None:
        raise StaleLeaseError(
            f"No checkpoint row found for execution_id={execution_id}"
        )

    if str(row["lease_token"]) != str(lease_token):
        raise StaleLeaseError(
            f"Lease token mismatch for execution_id={execution_id}: "
            f"expected {lease_token}, found {row['lease_token']}. "
            "Lease was likely reclaimed by another worker."
        )

    if row["execution_state"] != "IN_PROGRESS":
        raise StaleLeaseError(
            f"execution_id={execution_id} is in state {row['execution_state']!r}, "
            "expected IN_PROGRESS."
        )

    expires_at: datetime = row["lease_expires_at"]
    # Make timezone-aware if necessary (psycopg3 returns tz-aware datetimes,
    # but guard against naive values from test stubs).
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < _utcnow():
        raise StaleLeaseError(
            f"Lease for execution_id={execution_id} expired at {expires_at}."
        )


def finish_success(
    session: Session,
    execution_id: uuid.UUID,
    lease_token: uuid.UUID,
) -> bool:
    """Mark an IN_PROGRESS execution as SUCCESS.

    Requires:
    - execution_id matches
    - stage_name = 'ODS'
    - execution_state = 'IN_PROGRESS'
    - lease_token matches
    - lease_expires_at >= now()   ← expiry guard (Requirement 4)

    Returns True when the row was updated, False when any condition failed.
    """
    stmt = text(
        """
        UPDATE batch_stage_checkpoint
        SET    execution_state  = 'SUCCESS',
               lease_token      = NULL,
               lease_expires_at = NULL,
               updated_at       = now()
        WHERE  execution_id     = :execution_id
          AND  stage_name       = :stage_name
          AND  execution_state  = 'IN_PROGRESS'
          AND  lease_token      = :lease_token
          AND  lease_expires_at >= now()
        """
    )
    result = session.execute(
        stmt,
        {
            "execution_id": str(execution_id),
            "stage_name": STAGE_NAME,
            "lease_token": str(lease_token),
        },
    )
    return result.rowcount == 1


def finish_failure(
    session: Session,
    execution_id: uuid.UUID,
    lease_token: uuid.UUID,
) -> bool:
    """Mark an IN_PROGRESS execution as FAILED.

    Identical expiry guard to finish_success (Requirement 4).

    Returns True when the row was updated, False when any condition failed.
    """
    stmt = text(
        """
        UPDATE batch_stage_checkpoint
        SET    execution_state  = 'FAILED',
               lease_token      = NULL,
               lease_expires_at = NULL,
               updated_at       = now()
        WHERE  execution_id     = :execution_id
          AND  stage_name       = :stage_name
          AND  execution_state  = 'IN_PROGRESS'
          AND  lease_token      = :lease_token
          AND  lease_expires_at >= now()
        """
    )
    result = session.execute(
        stmt,
        {
            "execution_id": str(execution_id),
            "stage_name": STAGE_NAME,
            "lease_token": str(lease_token),
        },
    )
    return result.rowcount == 1


def reclaim_stale_execution(
    session: Session,
    batch_id: uuid.UUID,
) -> Optional[dict]:
    """Atomically reclaim the oldest stale IN_PROGRESS execution for a batch.

    Uses the approved CTE + FOR UPDATE SKIP LOCKED pattern to safely select
    exactly one stale row (lease_expires_at < now()) and atomically assign a
    new lease_token, invalidating the previous token.

    Returns a dict with keys: execution_id, lease_token, lease_expires_at when
    a stale row was reclaimed, or None when no stale rows exist.
    """
    stmt = text(
        """
        WITH cte AS (
            SELECT execution_id
            FROM   batch_stage_checkpoint
            WHERE  batch_id        = :batch_id
              AND  stage_name      = :stage_name
              AND  execution_state = 'IN_PROGRESS'
              AND  lease_expires_at < now()
            ORDER BY lease_expires_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE batch_stage_checkpoint bsc
        SET    lease_token      = gen_random_uuid(),
               lease_expires_at = now() + make_interval(secs => :lease_secs),
               updated_at       = now()
        FROM   cte
        WHERE  bsc.execution_id  = cte.execution_id
        RETURNING bsc.execution_id, bsc.lease_token, bsc.lease_expires_at
        """
    )
    row = session.execute(
        stmt,
        {
            "batch_id": str(batch_id),
            "stage_name": STAGE_NAME,
            "lease_secs": LEASE_DURATION_SECONDS,
        },
    ).mappings().first()

    return dict(row) if row is not None else None


def claim_via_skip_locked(
    session: Session,
    batch_id: uuid.UUID,
    checkpoint_key: str,
    checkpoint_value: str,
) -> Optional[dict]:
    """Attempt to claim an existing BOUND execution using FOR UPDATE SKIP LOCKED.

    This is the preferred concurrency-safe claim path when multiple workers
    race to start processing the same batch.  If no BOUND row is available
    (all are locked or none exist) returns None.

    Returns a dict with keys: execution_id, lease_token, lease_expires_at.
    """
    stmt = text(
        """
        WITH cte AS (
            SELECT execution_id
            FROM   batch_stage_checkpoint
            WHERE  batch_id        = :batch_id
              AND  stage_name      = :stage_name
              AND  execution_state = 'BOUND'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE batch_stage_checkpoint bsc
        SET    execution_state  = 'IN_PROGRESS',
               lease_token      = gen_random_uuid(),
               lease_expires_at = now() + make_interval(secs => :lease_secs),
               updated_at       = now()
        FROM   cte
        WHERE  bsc.execution_id  = cte.execution_id
        RETURNING bsc.execution_id, bsc.lease_token, bsc.lease_expires_at
        """
    )
    row = session.execute(
        stmt,
        {
            "batch_id": str(batch_id),
            "stage_name": STAGE_NAME,
            "checkpoint_key": checkpoint_key,
            "checkpoint_value": checkpoint_value,
            "lease_secs": LEASE_DURATION_SECONDS,
        },
    ).mappings().first()

    return dict(row) if row is not None else None
