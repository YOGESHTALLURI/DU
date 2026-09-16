"""
tests/unit/test_lease_utils.py
───────────────────────────────
Unit tests for backend/workers/lease_utils.py

LEASE-1  claim creates a BOUND row with non-null lease_token and lease_expires_at
LEASE-2  transition_to_in_progress succeeds for the owner
LEASE-3  transition_to_in_progress fails with wrong token
LEASE-4  heartbeat extends lease_expires_at for the owner
LEASE-5  heartbeat fails with wrong token
LEASE-6  heartbeat fails when lease_expires_at < now() (already expired)
LEASE-7  validate_lease_for_ods passes for a valid owner
LEASE-8  validate_lease_for_ods raises StaleLeaseError on wrong token
LEASE-9  validate_lease_for_ods raises StaleLeaseError on expired lease
LEASE-10 finish_success removes lease and sets SUCCESS; enforces expiry
LEASE-11 finish_failure removes lease and sets FAILED; enforces expiry
LEASE-12 finish_success with expired lease returns False (stale worker cannot finish)
LEASE-13 reclaim_stale_execution produces a new lease_token different from the old one
"""

import uuid
import pytest
from datetime import timedelta
from sqlalchemy import text

from backend.exceptions import StaleLeaseError
from backend.workers.lease_utils import (
    claim_ods_execution,
    transition_to_in_progress,
    heartbeat,
    validate_lease_for_ods,
    finish_success,
    finish_failure,
    reclaim_stale_execution,
    STAGE_NAME,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _force_expire(session, execution_id: uuid.UUID) -> None:
    """Back-date lease_expires_at to 1 hour ago to simulate expiry."""
    session.execute(
        text(
            "UPDATE batch_stage_checkpoint "
            "SET lease_expires_at = now() - interval '1 hour' "
            "WHERE execution_id = :eid"
        ),
        {"eid": str(execution_id)},
    )


def _get_row(session, execution_id: uuid.UUID) -> dict:
    row = session.execute(
        text(
            "SELECT execution_id, execution_state, lease_token, lease_expires_at "
            "FROM batch_stage_checkpoint WHERE execution_id = :eid"
        ),
        {"eid": str(execution_id)},
    ).mappings().one()
    return dict(row)


# ── LEASE-1 ──────────────────────────────────────────────────────────────────

def test_lease1_claim_creates_bound_row(db):
    batch_id = uuid.uuid4()
    result = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()

    row = _get_row(db, result["execution_id"])
    assert row["execution_state"] == "BOUND"
    assert row["lease_token"] is not None
    assert row["lease_expires_at"] is not None


# ── LEASE-2 ──────────────────────────────────────────────────────────────────

def test_lease2_transition_to_in_progress_succeeds(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()

    ok = transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    assert ok is True
    assert _get_row(db, cred["execution_id"])["execution_state"] == "IN_PROGRESS"


# ── LEASE-3 ──────────────────────────────────────────────────────────────────

def test_lease3_transition_fails_wrong_token(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()

    wrong_token = uuid.uuid4()
    ok = transition_to_in_progress(db, cred["execution_id"], wrong_token)
    assert ok is False
    assert _get_row(db, cred["execution_id"])["execution_state"] == "BOUND"


# ── LEASE-4 ──────────────────────────────────────────────────────────────────

def test_lease4_heartbeat_extends_expiry(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])

    before = _get_row(db, cred["execution_id"])["lease_expires_at"]
    ok = heartbeat(db, cred["execution_id"], cred["lease_token"])
    after = _get_row(db, cred["execution_id"])["lease_expires_at"]

    assert ok is True
    assert after >= before


# ── LEASE-5 ──────────────────────────────────────────────────────────────────

def test_lease5_heartbeat_fails_wrong_token(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])

    ok = heartbeat(db, cred["execution_id"], uuid.uuid4())
    assert ok is False


# ── LEASE-6 ──────────────────────────────────────────────────────────────────

def test_lease6_heartbeat_fails_when_expired(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    ok = heartbeat(db, cred["execution_id"], cred["lease_token"])
    assert ok is False


# ── LEASE-7 ──────────────────────────────────────────────────────────────────

def test_lease7_validate_passes_for_valid_owner(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])

    # Must not raise
    validate_lease_for_ods(db, cred["execution_id"], cred["lease_token"])


# ── LEASE-8 ──────────────────────────────────────────────────────────────────

def test_lease8_validate_raises_on_wrong_token(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])

    with pytest.raises(StaleLeaseError, match="token mismatch"):
        validate_lease_for_ods(db, cred["execution_id"], uuid.uuid4())


# ── LEASE-9 ──────────────────────────────────────────────────────────────────

def test_lease9_validate_raises_on_expired_lease(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    with pytest.raises(StaleLeaseError, match="expired"):
        validate_lease_for_ods(db, cred["execution_id"], cred["lease_token"])


# ── LEASE-10 ─────────────────────────────────────────────────────────────────

def test_lease10_finish_success_clears_lease(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])

    ok = finish_success(db, cred["execution_id"], cred["lease_token"])
    assert ok is True
    row = _get_row(db, cred["execution_id"])
    assert row["execution_state"] == "SUCCESS"
    assert row["lease_token"] is None
    assert row["lease_expires_at"] is None


# ── LEASE-11 ─────────────────────────────────────────────────────────────────

def test_lease11_finish_failure_clears_lease(db):
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])

    ok = finish_failure(db, cred["execution_id"], cred["lease_token"])
    assert ok is True
    row = _get_row(db, cred["execution_id"])
    assert row["execution_state"] == "FAILED"
    assert row["lease_token"] is None


# ── LEASE-12 ─────────────────────────────────────────────────────────────────

def test_lease12_finish_success_blocked_when_expired(db):
    """FINISH-EXP-1: expired worker cannot finish successfully."""
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    ok = finish_success(db, cred["execution_id"], cred["lease_token"])
    assert ok is False  # lease expired — row not updated
    assert _get_row(db, cred["execution_id"])["execution_state"] == "IN_PROGRESS"


# ── LEASE-13 ─────────────────────────────────────────────────────────────────

def test_lease13_reclaim_produces_new_token(db):
    """Reclaim atomically replaces the old lease_token with a new one."""
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    old_token = cred["lease_token"]
    _force_expire(db, cred["execution_id"])

    reclaimed = reclaim_stale_execution(db, batch_id)

    assert reclaimed is not None
    assert reclaimed["execution_id"] == cred["execution_id"]
    assert str(reclaimed["lease_token"]) != str(old_token), (
        "Reclaim must generate a NEW lease_token"
    )
    # Old token is now invalid for heartbeat
    ok = heartbeat(db, cred["execution_id"], old_token)
    assert ok is False, "Old token must be invalid after reclaim"


# ── FINISH-EXP-1 (explicit) ───────────────────────────────────────────────────

def test_finish_exp_1_expired_owner_cannot_finish_success(db):
    """FINISH-EXP-1: An expired worker cannot call finish_success.
    finish_success must return False when lease_expires_at < now().
    The row must remain IN_PROGRESS.
    """
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    ok = finish_success(db, cred["execution_id"], cred["lease_token"])

    assert ok is False, "FINISH-EXP-1: finish_success must return False when lease expired"
    assert _get_row(db, cred["execution_id"])["execution_state"] == "IN_PROGRESS"


# ── FINISH-EXP-2 (explicit) ───────────────────────────────────────────────────

def test_finish_exp_2_expired_owner_cannot_finish_failure(db):
    """FINISH-EXP-2: An expired worker cannot call finish_failure.
    finish_failure must return False when lease_expires_at < now().
    The row must remain IN_PROGRESS.
    """
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])
    _force_expire(db, cred["execution_id"])

    ok = finish_failure(db, cred["execution_id"], cred["lease_token"])

    assert ok is False, "FINISH-EXP-2: finish_failure must return False when lease expired"
    assert _get_row(db, cred["execution_id"])["execution_state"] == "IN_PROGRESS"


# ── FINISH-EXP-4 (explicit) ───────────────────────────────────────────────────

def test_finish_exp_4_non_expired_owner_can_finish(db):
    """FINISH-EXP-4: A current non-expired owner can finish successfully.
    finish_success must return True and transition to SUCCESS.
    finish_failure must return True and transition to FAILED.
    """
    # SUCCESS path
    batch_id = uuid.uuid4()
    cred = claim_ods_execution(db, batch_id, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred["execution_id"], cred["lease_token"])

    ok_success = finish_success(db, cred["execution_id"], cred["lease_token"])
    assert ok_success is True, "FINISH-EXP-4: finish_success must return True for valid lease"
    assert _get_row(db, cred["execution_id"])["execution_state"] == "SUCCESS"

    # FAILURE path
    batch_id2 = uuid.uuid4()
    cred2 = claim_ods_execution(db, batch_id2, "k", "v")
    db.flush()
    transition_to_in_progress(db, cred2["execution_id"], cred2["lease_token"])

    ok_failure = finish_failure(db, cred2["execution_id"], cred2["lease_token"])
    assert ok_failure is True, "FINISH-EXP-4: finish_failure must return True for valid lease"
    assert _get_row(db, cred2["execution_id"])["execution_state"] == "FAILED"
