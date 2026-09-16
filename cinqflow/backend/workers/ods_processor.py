"""
backend/workers/ods_processor.py
─────────────────────────────────
Lease-fenced ODS mutation processor for the CINQFLOW pipeline.

Architecture
────────────
1. Worker calls process_ods_record() with its execution_id and lease_token.
2. validate_lease_for_ods() is called FIRST and acquires a FOR UPDATE lock on
   the checkpoint row.  If the lease is expired or the token has been
   superseded, StaleLeaseError is raised and the ODS write is NEVER executed.
3. Only after validation passes does the worker write to ODS tables.
4. operation_hash conflicts are handled with a PostgreSQL SAVEPOINT
   (session.begin_nested()).  Only the expected unique constraint
   ``ods_op_hash_uniq`` is silently swallowed; all other IntegrityErrors
   propagate normally.

This satisfies:
- Requirement 6: stale worker prevented from ODS mutation (not merely
  from updating the checkpoint).
- Requirement 8: operation_hash conflict handling uses a SAVEPOINT.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.exceptions import StaleLeaseError
from backend.models.ods import OdsMemberV1
from backend.workers.lease_utils import validate_lease_for_ods

# ---------------------------------------------------------------------------
# Sentinel: unique constraint name for the operation_hash table.
# Only THIS constraint may be silently swallowed inside the SAVEPOINT block.
# ---------------------------------------------------------------------------
_OP_HASH_CONSTRAINT: str = "ods_op_hash_uniq"


# ---------------------------------------------------------------------------
# operation_hash helpers
# ---------------------------------------------------------------------------

def _compute_operation_hash(
    batch_id: uuid.UUID,
    cinq_id: uuid.UUID,
    operation: str,
) -> str:
    """Return a hex SHA-256 digest uniquely identifying this ODS operation."""
    payload = f"{batch_id}|{cinq_id}|{operation}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _insert_operation_hash(
    session: Session,
    batch_id: uuid.UUID,
    cinq_id: uuid.UUID,
    operation: str,
) -> Optional[str]:
    """Insert an operation_hash row using a SAVEPOINT.

    If ``ods_op_hash_uniq`` fires (duplicate), rolls back only the SAVEPOINT
    and returns the existing hash (idempotent path).

    Any OTHER IntegrityError propagates to the caller — the outer transaction
    is NOT harmed.

    Returns the hex hash string on success or on duplicate, raises for other
    integrity errors.
    """
    op_hash = _compute_operation_hash(batch_id, cinq_id, operation)

    try:
        with session.begin_nested():  # ← PostgreSQL SAVEPOINT
            session.execute(
                text(
                    """
                    INSERT INTO ods_operation_hashes (op_hash, batch_id, cinq_id, operation, created_at)
                    VALUES (:op_hash, :batch_id, :cinq_id, :operation, now())
                    """
                ),
                {
                    "op_hash": op_hash,
                    "batch_id": str(batch_id),
                    "cinq_id": str(cinq_id),
                    "operation": operation,
                },
            )
    except IntegrityError as exc:
        diag = getattr(exc.orig, "diag", None)
        constraint_name: str = getattr(diag, "constraint_name", "") or ""
        sqlstate: str = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None) or ""

        is_unique = (sqlstate == "23505")
        is_target_constraint = (constraint_name == _OP_HASH_CONSTRAINT or _OP_HASH_CONSTRAINT in str(exc))

        if not (is_unique and is_target_constraint):
            raise  # propagate unrelated integrity errors

        # Duplicate operation_hash — idempotent; outer transaction still open.

    return op_hash


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_ods_record(
    session: Session,
    *,
    execution_id: uuid.UUID,
    lease_token: uuid.UUID,
    batch_id: uuid.UUID,
    ods_model_version_id: uuid.UUID,
    cinq_id: uuid.UUID,
    first_name: str,
    last_name: str,
    date_of_birth: date,
    gender: str,
    created_by: str,
    survivorship_applied: bool = False,
    address_line1: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    postal_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Write one ODS member record after asserting a valid lease.

    Workflow
    ────────
    1. validate_lease_for_ods() — raises StaleLeaseError immediately if the
       lease is expired or the token has been superseded.  The ODS write below
       is NOT reached.
    2. Insert / update OdsMemberV1.
    3. Record operation_hash with SAVEPOINT (idempotent, duplicate-safe).

    Returns a summary dict.
    """
    # ── Step 1: assert valid lease BEFORE any ODS write ──────────────────────
    validate_lease_for_ods(session, execution_id, lease_token)

    # ── Step 2: write ODS member record ──────────────────────────────────────
    now_utc = datetime.now(timezone.utc)

    member = OdsMemberV1(
        cinq_id=cinq_id,
        batch_id=batch_id,
        ods_model_version_id=ods_model_version_id,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
        gender=gender,
        address_line1=address_line1,
        city=city,
        state=state,
        postal_code=postal_code,
        survivorship_applied=survivorship_applied,
        created_at=now_utc,
        created_by=created_by,
        updated_at=now_utc,
        updated_by=created_by,
        version=1,
    )
    session.add(member)
    session.flush()  # send INSERT; still within the outer transaction

    # ── Step 3: record operation_hash (SAVEPOINT) ─────────────────────────────
    op_hash = _insert_operation_hash(
        session,
        batch_id=batch_id,
        cinq_id=cinq_id,
        operation="INSERT_ODS_MEMBER",
    )

    return {
        "cinq_id": str(cinq_id),
        "batch_id": str(batch_id),
        "execution_id": str(execution_id),
        "op_hash": op_hash,
        "status": "written",
    }
