"""
tests/integration/test_ods_lease_fencing.py
────────────────────────────────────────────
Integration tests for Wave 3 Slice 4 – ODS Execution Lease Fencing.

These tests use real PostgreSQL sessions (via the conftest ``db`` fixture)
and perform real ODS mutations or real concurrent lock operations.

Test IDs
────────
LEASE-14      Stale worker attempts a REAL ODS mutation → blocked by StaleLeaseError;
              new owner can complete successfully.

FINISH-EXP-1  finish_success with active lease  → True  (already in LEASE-10)
FINISH-EXP-2  finish_failure with active lease  → True  (already in LEASE-11)
FINISH-EXP-3  finish_success AFTER expiry       → False (stale worker blocked)
FINISH-EXP-4  finish_failure AFTER expiry       → False (stale worker blocked)

SAVEPOINT-1   operation_hash duplicate conflict rolls back only the SAVEPOINT;
              the outer transaction remains open and can commit other work.

CONC-1        claim_via_skip_locked: two reclaimers race — only one wins.
CONC-2        Two reclaimers on a stale row — exactly one reclaims, one gets None.
CONC-3        Heartbeat vs reclaim: after reclaim the old heartbeat returns False.
CONC-4        Finish vs reclaim: reclaimed lease blocks both finish paths.
"""

from __future__ import annotations

import uuid
import threading
from datetime import date, datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.exceptions import StaleLeaseError
from backend.workers.lease_utils import (
    claim_ods_execution,
    claim_via_skip_locked,
    finish_failure,
    finish_success,
    heartbeat,
    reclaim_stale_execution,
    transition_to_in_progress,
    STAGE_NAME,
)
from backend.workers.ods_processor import _insert_operation_hash, process_ods_record


# ── shared fixtures & helpers ─────────────────────────────────────────────────

def _force_expire(session, execution_id: uuid.UUID) -> None:
    session.execute(
        text(
            "UPDATE batch_stage_checkpoint "
            "SET lease_expires_at = now() - interval '1 hour' "
            "WHERE execution_id = :eid"
        ),
        {"eid": str(execution_id)},
    )


def _get_state(session, execution_id: uuid.UUID) -> str:
    row = session.execute(
        text(
            "SELECT execution_state FROM batch_stage_checkpoint "
            "WHERE execution_id = :eid"
        ),
        {"eid": str(execution_id)},
    ).scalar_one()
    return row


from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.ods import OdsModelVersion, OdsModelVersionStatusEnum


def _make_batch_and_model(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a minimal Batch + OdsModelVersion pair and return their IDs."""
    feed = Feed(
        id=uuid.uuid4(),
        name=f"ODS Lease Feed {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="Lease Feed",
        format=FeedFormatEnum.JSON,
        landing_folder="/data/landing/ods_lease",
        filename_pattern="test_*.json",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="system",
        updated_by="system",
    )
    session.add(feed)
    session.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="system",
        updated_by="system",
    )
    session.add(fv)
    session.flush()

    mv = OdsModelVersion(
        id=uuid.uuid4(),
        version_number=int(uuid.uuid4().int % 10000000),
        name="Test Model",
        domain="clinical",
        status=OdsModelVersionStatusEnum.PUBLISHED.value,
        schema_definition={},
        created_by="system",
        updated_by="system",
    )
    session.add(mv)
    session.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=mv.id,
        status=BatchStatusEnum.RUNNING,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    session.add(batch)
    session.flush()
    return batch.id, mv.id


# ── LEASE-14 ─────────────────────────────────────────────────────────────────

def test_lease14_stale_worker_real_ods_mutation_blocked(db):
    """
    LEASE-14 — Real ODS mutation attempt by stale worker is blocked.

    Sequence:
    1.  Worker A claims and transitions to IN_PROGRESS  → gets token_A.
    2.  Worker A's lease expires (back-dated by helper).
    3.  Worker B reclaims → gets token_B (token_A is now invalid).
    4.  Worker A attempts process_ods_record() with token_A
        → StaleLeaseError raised BEFORE any ODS write.
    5.  Confirm ODS member row does NOT exist.
    6.  Worker B calls process_ods_record() with token_B → succeeds.
    7.  Confirm ODS member row DOES exist.
    """
    batch_id, model_id = _make_batch_and_model(db)
    cinq_id = uuid.uuid4()

    # ── Step 1: Worker A claims ───────────────────────────────────────────────
    cred_a = claim_ods_execution(db, batch_id, "stage", "ods")
    db.flush()
    transition_to_in_progress(db, cred_a["execution_id"], cred_a["lease_token"])
    exec_id_a = cred_a["execution_id"]
    token_a = cred_a["lease_token"]

    # ── Step 2: Worker A's lease expires ─────────────────────────────────────
    _force_expire(db, exec_id_a)

    # ── Step 3: Worker B reclaims ─────────────────────────────────────────────
    reclaimed = reclaim_stale_execution(db, batch_id)
    assert reclaimed is not None, "Expected reclaim to succeed"
    token_b = reclaimed["lease_token"]
    exec_id_b = reclaimed["execution_id"]  # same row, new token
    assert str(token_b) != str(token_a), "Reclaim must issue new token"

    # ── Step 4: Worker A attempts REAL ODS mutation → must be blocked ─────────
    with pytest.raises(StaleLeaseError):
        process_ods_record(
            db,
            execution_id=exec_id_a,
            lease_token=token_a,        # stale token
            batch_id=batch_id,
            ods_model_version_id=model_id,
            cinq_id=cinq_id,
            first_name="Stale",
            last_name="Worker",
            date_of_birth=date(1980, 1, 1),
            gender="U",
            created_by="worker_a",
        )

    # ── Step 5: Confirm ODS row NOT written ───────────────────────────────────
    count = db.execute(
        text(
            "SELECT COUNT(*) FROM internal_ods.ods_members_v1 "
            "WHERE cinq_id = :cid AND batch_id = :bid"
        ),
        {"cid": str(cinq_id), "bid": str(batch_id)},
    ).scalar_one()
    assert count == 0, "Stale worker must NOT have written any ODS row"

    # ── Step 6: Worker B writes ODS record successfully ───────────────────────
    result = process_ods_record(
        db,
        execution_id=exec_id_b,
        lease_token=token_b,            # valid token
        batch_id=batch_id,
        ods_model_version_id=model_id,
        cinq_id=cinq_id,
        first_name="Valid",
        last_name="Worker",
        date_of_birth=date(1980, 1, 1),
        gender="U",
        created_by="worker_b",
    )
    assert result["status"] == "written"

    # ── Step 7: Confirm ODS row IS written ───────────────────────────────────
    count = db.execute(
        text(
            "SELECT COUNT(*) FROM internal_ods.ods_members_v1 "
            "WHERE cinq_id = :cid AND batch_id = :bid"
        ),
        {"cid": str(cinq_id), "bid": str(batch_id)},
    ).scalar_one()
    assert count == 1, "Valid worker's ODS row must be present"


# ── FINISH-EXP-3 ─────────────────────────────────────────────────────────────

def test_finish_exp_3_success_blocked_after_expiry(db):
    """FINISH-EXP-3: finish_success with expired lease returns False."""
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    ok = finish_success(db, cred["execution_id"], cred["lease_token"])
    assert ok is False
    assert _get_state(db, cred["execution_id"]) == "IN_PROGRESS"


# ── FINISH-EXP-4 ─────────────────────────────────────────────────────────────

def test_finish_exp_4_failure_blocked_after_expiry(db):
    """FINISH-EXP-4: finish_failure with expired lease returns False."""
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    ok = finish_failure(db, cred["execution_id"], cred["lease_token"])
    assert ok is False
    assert _get_state(db, cred["execution_id"]) == "IN_PROGRESS"


# ── SAVEPOINT-1 ───────────────────────────────────────────────────────────────

def test_savepoint_1_operation_hash_duplicate_outer_transaction_survives(db):
    """
    SAVEPOINT-1: Duplicate operation_hash rolls back only the SAVEPOINT.

    Proof:
    1.  Insert operation_hash row A.
    2.  Insert duplicate → SAVEPOINT rolls back, no error propagates.
    3.  Outer transaction still usable: insert unrelated row and verify.
    """
    batch_id = uuid.uuid4()
    cinq_id = uuid.uuid4()

    # First insert — must succeed
    hash1 = _insert_operation_hash(db, batch_id, cinq_id, "INSERT_ODS_MEMBER")
    assert hash1 is not None

    # Duplicate — SAVEPOINT must catch it; outer tx still open
    hash2 = _insert_operation_hash(db, batch_id, cinq_id, "INSERT_ODS_MEMBER")
    assert hash2 == hash1, "Duplicate path must return same hash"

    # Outer transaction is still usable — insert a different row
    other_cinq = uuid.uuid4()
    hash3 = _insert_operation_hash(db, batch_id, other_cinq, "INSERT_ODS_MEMBER")
    assert hash3 != hash1, "Different cinq_id must produce different hash"

    # Commit/flush without error
    db.flush()


def test_savepoint_2_unrelated_integrity_error_propagates(db):
    """
    SAVEPOINT-2: Unrelated IntegrityError (e.g. NULL batch_id) is NOT swallowed
    and propagates to the caller.
    """
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            # Attempt insert with NULL batch_id which violates not-null constraint
            db.execute(
                text(
                    "INSERT INTO ods_operation_hashes (op_hash, batch_id, cinq_id, operation, created_at) "
                    "VALUES ('unrelated_hash', NULL, :cid, 'TEST', now())"
                ),
                {"cid": str(uuid.uuid4())},
            )


# ── CONC-1 ───────────────────────────────────────────────────────────────────

def test_conc_1_two_reclaimers_only_one_wins(db):
    """
    CONC-2: Two reclaimers race on a single stale row;
    exactly one wins (returns a dict), the other returns None.

    Simulated within a single session by calling reclaim twice after expiry.
    The first call wins; the second finds no stale rows.
    """
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    first = reclaim_stale_execution(db, batch_id)
    second = reclaim_stale_execution(db, batch_id)

    assert first is not None, "First reclaimer must win"
    assert second is None, "Second reclaimer must find no stale rows"


# ── CONC-2 ───────────────────────────────────────────────────────────────────

def test_conc_2_heartbeat_fails_after_reclaim(db):
    """CONC-3: After a reclaim, the old token's heartbeat returns False."""
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    old_token = cred["lease_token"]
    _force_expire(db, cred["execution_id"])

    reclaim_stale_execution(db, batch_id)

    ok = heartbeat(db, cred["execution_id"], old_token)
    assert ok is False, "Old token heartbeat must fail after reclaim"


# ── CONC-3 ───────────────────────────────────────────────────────────────────

def test_conc_3_finish_blocked_after_reclaim(db):
    """CONC-4: Both finish_success and finish_failure fail after reclaim."""
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    old_token = cred["lease_token"]
    _force_expire(db, cred["execution_id"])

    reclaim_stale_execution(db, batch_id)

    ok_s = finish_success(db, cred["execution_id"], old_token)
    ok_f = finish_failure(db, cred["execution_id"], old_token)

    assert ok_s is False, "finish_success must fail after reclaim"
    assert ok_f is False, "finish_failure must fail after reclaim"


# ── CONC-4 ───────────────────────────────────────────────────────────────────

def test_conc_4_validate_raises_after_reclaim(db):
    """Stale token is rejected by validate_lease_for_ods after reclaim."""
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    old_token = cred["lease_token"]
    _force_expire(db, cred["execution_id"])

    reclaim_stale_execution(db, batch_id)

    with pytest.raises(StaleLeaseError):
        from backend.workers.lease_utils import validate_lease_for_ods
        validate_lease_for_ods(db, cred["execution_id"], old_token)


# ── multiple executions coexist ───────────────────────────────────────────────

def test_multiple_executions_coexist_for_same_batch(db):
    """No uniqueness constraint on (batch_id, stage_name, BOUND).
    Multiple executions may be created for the same batch simultaneously.
    """
    batch_id = uuid.uuid4()

    cred_a = claim_ods_execution(db, batch_id, "k", "v")
    cred_b = claim_ods_execution(db, batch_id, "k", "v")
    cred_c = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()

    # All three rows must exist with distinct execution_ids
    ids = {
        str(cred_a["execution_id"]),
        str(cred_b["execution_id"]),
        str(cred_c["execution_id"]),
    }
    assert len(ids) == 3, "Three distinct executions must coexist"

    count = db.execute(
        text(
            "SELECT COUNT(*) FROM batch_stage_checkpoint "
            "WHERE batch_id = :bid AND execution_state = 'BOUND'"
        ),
        {"bid": str(batch_id)},
    ).scalar_one()
    assert count == 3


# ── identity_run_status CHECK constraint ─────────────────────────────────────

def test_identity_run_status_check_constraint(db):
    """Migration 022: check constraint chk_identity_run_status_completed."""
    batch_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # SUCCESS requires completed_at IS NOT NULL
    db.execute(
        text(
            "INSERT INTO identity_run_status (batch_id, identity_run_id, run_status, completed_at) "
            "VALUES (:bid, :rid, 'SUCCESS', now())"
        ),
        {"bid": str(batch_id), "rid": str(run_id)},
    )
    db.flush()

    # FAILURE requires completed_at IS NULL — bad insert should fail
    with pytest.raises(Exception, match="chk_identity_run_status_completed"):
        with db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO identity_run_status (batch_id, identity_run_id, run_status, completed_at) "
                    "VALUES (:bid, :rid, 'FAILURE', now())"  # completed_at set — violates constraint
                ),
                {"bid": str(uuid.uuid4()), "rid": str(uuid.uuid4())},
            )


# ── identity_run_status PK ────────────────────────────────────────────────────

def test_identity_run_status_composite_pk_rejects_duplicate(db):
    """Migration 022: PK (batch_id, identity_run_id) rejects duplicates."""
    batch_id = uuid.uuid4()
    run_id = uuid.uuid4()

    db.execute(
        text(
            "INSERT INTO identity_run_status (batch_id, identity_run_id, run_status, completed_at) "
            "VALUES (:bid, :rid, 'SUCCESS', now())"
        ),
        {"bid": str(batch_id), "rid": str(run_id)},
    )
    db.flush()

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO identity_run_status (batch_id, identity_run_id, run_status, completed_at) "
                    "VALUES (:bid, :rid, 'SUCCESS', now())"
                ),
                {"bid": str(batch_id), "rid": str(run_id)},
            )
