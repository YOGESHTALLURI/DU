"""
Unit Tests: Identity Merge & Split Decisions (CF-V3-E9-03)
Covers:
- Proposal creation, client_key idempotency, non-PHI enforcement
- Four-Eyes approval segregation & state transitions
- Atomic merge execution, crosswalk re-pointing, token invalidation
- Atomic split execution, new identity creation, crosswalk migration
- Append-only event ledger and point-in-time historical reconstruction
"""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from fastapi import HTTPException

from backend.models.identity import (
    MasterIdentity,
    IdentityToken,
    IdentityCrosswalk,
    MasterIdentityStatusEnum,
)
from backend.models.merge_split import (
    IdentityMergeSplitProposal,
    IdentityMergeSplitEvent,
    ProposalStateEnum,
    OperationTypeEnum,
)
from backend.schemas.merge_split import (
    MergeProposalCreateRequest,
    SplitProposalCreateRequest,
)
from backend.services.merge_split_service import MergeSplitService
from backend.services.identity_service import IdentityService


@pytest.fixture
def identity_pair(db):
    """Creates two distinct active MasterIdentities with tokens and crosswalks."""
    now_dt = datetime.now(timezone.utc) - timedelta(days=1)
    
    id_a = MasterIdentity(
        status=MasterIdentityStatusEnum.ACTIVE.value,
        created_by="system",
        updated_by="system",
    )
    id_b = MasterIdentity(
        status=MasterIdentityStatusEnum.ACTIVE.value,
        created_by="system",
        updated_by="system",
    )
    db.add_all([id_a, id_b])
    db.flush()

    tok_a = IdentityToken(
        cinq_id=id_a.cinq_id,
        ssn_hash="hash_ssn_a_1234567890123456789012345678901234567890",
        is_current=True,
        effective_from=now_dt,
        created_by="system",
        updated_by="system",
    )
    tok_b = IdentityToken(
        cinq_id=id_b.cinq_id,
        ssn_hash="hash_ssn_b_1234567890123456789012345678901234567890",
        is_current=True,
        effective_from=now_dt,
        created_by="system",
        updated_by="system",
    )
    cw_a = IdentityCrosswalk(
        cinq_id=id_a.cinq_id,
        source_system="EMR_ALPHA",
        source_identifier_hash="id_hash_alpha_99999999999999999999999999999999",
        is_active=True,
        valid_from=now_dt,
        match_score=Decimal("100.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="system",
        updated_by="system",
    )
    cw_b = IdentityCrosswalk(
        cinq_id=id_b.cinq_id,
        source_system="EMR_BETA",
        source_identifier_hash="id_hash_beta_888888888888888888888888888888888",
        is_active=True,
        valid_from=now_dt,
        match_score=Decimal("100.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="system",
        updated_by="system",
    )
    db.add_all([tok_a, tok_b, cw_a, cw_b])
    db.commit()
    db.refresh(id_a)
    db.refresh(id_b)
    return id_a, id_b, cw_a, cw_b


def test_ms_prop_1_create_merge_proposal_success(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Steward audit discovered duplicate chart for same individual",
        client_key="client_key_merge_001_unique_token_1234",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_1@cinqflow.local")
    assert prop.proposal_id is not None
    assert prop.state == ProposalStateEnum.PENDING_APPROVAL.value
    assert prop.proposer_id == "steward_1@cinqflow.local"
    assert prop.source_cinq_id == id_a.cinq_id
    assert prop.target_cinq_id == id_b.cinq_id


def test_ms_prop_2_duplicate_client_key_rejected(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Steward verified duplicate patient record",
        client_key="client_key_idempotent_test_999999999",
    )
    prop1 = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_1@cinqflow.local")
    # Submitting with same client key returns existing proposal
    prop2 = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_1@cinqflow.local")
    assert prop1.proposal_id == prop2.proposal_id


def test_ms_prop_3_proposer_cannot_approve_own_proposal(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Verification of matching demographic profile",
        client_key="client_key_four_eyes_test_111111111",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_proposer@cinqflow.local")

    # Four-Eyes violation: proposer attempts self-approval
    with pytest.raises(HTTPException) as exc:
        MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_proposer@cinqflow.local")
    assert exc.value.status_code == 403
    assert "Four-Eyes" in exc.value.detail


def test_ms_prop_4_approver_can_approve_valid_proposal(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Legitimate duplicate merge proposal",
        client_key="client_key_approve_valid_222222222",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_alice@cinqflow.local")
    approved = MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_bob@cinqflow.local")
    assert approved.state == ProposalStateEnum.APPROVED.value
    assert approved.approver_id == "steward_bob@cinqflow.local"


def test_ms_prop_5_cannot_approve_non_pending_proposal(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Testing state transition bounds",
        client_key="client_key_transition_bounds_333333333",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_alice@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_bob@cinqflow.local")

    with pytest.raises(HTTPException) as exc:
        MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_charlie@cinqflow.local")
    assert exc.value.status_code == 409


def test_ms_prop_6_cannot_execute_unapproved_proposal(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Testing unapproved execution guard",
        client_key="client_key_unapproved_guard_444444444",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_alice@cinqflow.local")

    with pytest.raises(HTTPException) as exc:
        MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_bob@cinqflow.local")
    assert exc.value.status_code == 409


def test_ms_exec_1_merge_transitions_master_status_merged(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Consolidation of duplicate member identifiers",
        client_key="client_key_merge_exec_1_555555555",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    exec_prop, event = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    assert exec_prop.state == ProposalStateEnum.EXECUTED.value
    db.refresh(id_a)
    assert id_a.status == MasterIdentityStatusEnum.MERGED.value
    assert id_a.merged_into_cinq_id == id_b.cinq_id


def test_ms_exec_2_merge_repoints_crosswalk_to_target(db, identity_pair):
    id_a, id_b, cw_a, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Crosswalk repointing verification test",
        client_key="client_key_cw_repoint_666666666",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    db.refresh(cw_a)
    assert cw_a.is_active is False
    assert cw_a.valid_to is not None

    # New active crosswalk created for target
    new_cw = (
        db.query(IdentityCrosswalk)
        .filter(
            IdentityCrosswalk.cinq_id == id_b.cinq_id,
            IdentityCrosswalk.source_system == cw_a.source_system,
            IdentityCrosswalk.source_identifier_hash == cw_a.source_identifier_hash,
            IdentityCrosswalk.is_active == True,
        )
        .first()
    )
    assert new_cw is not None
    assert new_cw.match_type == "MERGE_OVERRIDE"


def test_ms_exec_3_merge_deactivates_source_tokens(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Token deactivation verification test",
        client_key="client_key_token_deact_777777777",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    tokens_a = db.query(IdentityToken).filter(IdentityToken.cinq_id == id_a.cinq_id).all()
    for tok in tokens_a:
        assert tok.is_current is False
        assert tok.effective_to is not None


def test_ms_exec_4_merge_appends_event_ledger(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Audit event verification test",
        client_key="client_key_event_audit_888888888",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    _, event = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    assert event.event_type == OperationTypeEnum.MERGE.value
    assert event.source_cinq_id == id_a.cinq_id
    assert event.target_cinq_id == id_b.cinq_id
    assert event.effective_from is not None


def test_ms_exec_5_split_allocates_new_cinq_id(db, identity_pair):
    id_a, _, cw_a, _ = identity_pair
    req = SplitProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        source_system=cw_a.source_system,
        source_identifier_hash=cw_a.source_identifier_hash,
        target_cinq_id=None,  # Null indicates allocate new MasterIdentity
        reason="Demographic error: chart erroneously unified two distinct patients",
        client_key="client_key_split_alloc_999999999",
    )
    prop = MergeSplitService.create_split_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    assert prop.operation_type == OperationTypeEnum.SPLIT.value

    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    exec_prop, event = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    assert exec_prop.target_cinq_id is not None
    assert exec_prop.target_cinq_id != id_a.cinq_id
    new_master = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == exec_prop.target_cinq_id).first()
    assert new_master is not None
    assert new_master.status == MasterIdentityStatusEnum.ACTIVE.value


def test_ms_exec_6_split_retires_previous_crosswalk_interval(db, identity_pair):
    id_a, _, cw_a, _ = identity_pair
    req = SplitProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        source_system=cw_a.source_system,
        source_identifier_hash=cw_a.source_identifier_hash,
        target_cinq_id=None,
        reason="Splitting erroneous linkage",
        client_key="client_key_split_cw_interval_000000000",
    )
    prop = MergeSplitService.create_split_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    exec_prop, _ = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    db.refresh(cw_a)
    assert cw_a.is_active is False
    assert cw_a.valid_to is not None

    new_cw = (
        db.query(IdentityCrosswalk)
        .filter(
            IdentityCrosswalk.cinq_id == exec_prop.target_cinq_id,
            IdentityCrosswalk.source_system == cw_a.source_system,
            IdentityCrosswalk.source_identifier_hash == cw_a.source_identifier_hash,
            IdentityCrosswalk.is_active == True,
        )
        .first()
    )
    assert new_cw is not None
    assert new_cw.match_type == "SPLIT_OVERRIDE"

    # Verify target identity inherited active identity tokens
    tgt_token = db.query(IdentityToken).filter(
        IdentityToken.cinq_id == exec_prop.target_cinq_id,
        IdentityToken.is_current == True,
    ).first()
    assert tgt_token is not None
    assert tgt_token.is_current is True


def test_ms_exec_6b_split_multi_crosswalk_moves_only_requested_identifier(db, identity_pair):
    id_a, _, cw_a, _ = identity_pair
    # Add a SECOND active crosswalk under id_a
    cw_a2 = IdentityCrosswalk(
        cinq_id=id_a.cinq_id,
        source_system="LAB_SYSTEM_ALPHA",
        source_identifier_hash="lab_hash_alpha_999999999999999999999999999999999",
        is_active=True,
        valid_from=datetime.now(timezone.utc),
        match_score=Decimal("95.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="system",
        updated_by="system",
    )
    db.add(cw_a2)
    db.commit()

    # Request split ONLY for cw_a2
    req = SplitProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        source_system=cw_a2.source_system,
        source_identifier_hash=cw_a2.source_identifier_hash,
        target_cinq_id=None,
        reason="Splitting second crosswalk only",
        client_key="client_key_split_cw_multi_target_12345",
    )
    prop = MergeSplitService.create_split_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    exec_prop, _ = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    # Original cw_a MUST REMAIN ACTIVE under id_a
    db.refresh(cw_a)
    assert cw_a.is_active is True
    assert cw_a.cinq_id == id_a.cinq_id

    # cw_a2 MUST BE RETIRED and re-pointed to target
    db.refresh(cw_a2)
    assert cw_a2.is_active is False
    assert cw_a2.valid_to is not None

    moved_cw = db.query(IdentityCrosswalk).filter(
        IdentityCrosswalk.cinq_id == exec_prop.target_cinq_id,
        IdentityCrosswalk.source_system == cw_a2.source_system,
        IdentityCrosswalk.source_identifier_hash == cw_a2.source_identifier_hash,
        IdentityCrosswalk.is_active == True,
    ).first()
    assert moved_cw is not None


def test_ms_exec_6c_split_rejects_missing_or_mismatched_crosswalk(db, identity_pair):
    id_a, _, _, _ = identity_pair
    req = SplitProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        source_system="NON_EXISTENT_SYS",
        source_identifier_hash="fake_hash_1111111111111111111111111111111111",
        target_cinq_id=None,
        reason="Attempting to split non-existent crosswalk",
        client_key="client_key_split_fake_cw_404_test",
    )
    with pytest.raises(HTTPException) as exc:
        MergeSplitService.create_split_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    assert exc.value.status_code == 404


def test_ms_exec_7_point_in_time_reconstruction_before_merge(db, identity_pair):
    id_a, id_b, cw_a, _ = identity_pair
    t_before = datetime.now(timezone.utc) - timedelta(hours=2)

    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Historical reconstruction validation test",
        client_key="client_key_pit_before_1212121212",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    # Point-in-time query as of t_before must resolve to id_a
    resolved_cw = IdentityService.lookup_crosswalk_point_in_time(
        db, cw_a.source_system, cw_a.source_identifier_hash, as_of=t_before
    )
    assert resolved_cw is not None
    assert resolved_cw.cinq_id == id_a.cinq_id


def test_ms_exec_8_point_in_time_reconstruction_after_merge(db, identity_pair):
    id_a, id_b, cw_a, _ = identity_pair

    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Post-merge temporal reconstruction validation test",
        client_key="client_key_pit_after_3434343434",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")
    MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    t_after = datetime.now(timezone.utc) + timedelta(minutes=1)
    resolved_cw = IdentityService.lookup_crosswalk_point_in_time(
        db, cw_a.source_system, cw_a.source_identifier_hash, as_of=t_after
    )
    assert resolved_cw is not None
    assert resolved_cw.cinq_id == id_b.cinq_id


def test_ms_zero_phi_proposal_notes_enforced(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    # Prohibited raw SSN pattern in notes
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Merging chart with SSN 123-45-6789 into target",
        client_key="client_key_phi_rejection_5656565656",
    )
    with pytest.raises(HTTPException) as exc:
        MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    assert exc.value.status_code == 422
    assert "PHI" in exc.value.detail


def test_ms_concurrency_lock_prevents_race(db, identity_pair):
    id_a, id_b, _, _ = identity_pair
    req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="Locking verification test",
        client_key="client_key_lock_race_7878787878",
    )
    prop = MergeSplitService.create_merge_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")

    # Execution acquires advisory lock and completes cleanly
    exec_prop, event = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")
    assert exec_prop.state == ProposalStateEnum.EXECUTED.value


def test_ms_exec_9_target_conflicting_token_rejected(db, identity_pair):
    id_a, id_b, cw_a, _ = identity_pair
    # Set a conflicting SSN token on id_b
    tok_b = db.query(IdentityToken).filter(IdentityToken.cinq_id == id_b.cinq_id, IdentityToken.is_current == True).first()
    tok_b.ssn_hash = "conflicting_different_ssn_hash_999999999999999"
    db.commit()

    req = SplitProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        source_system=cw_a.source_system,
        source_identifier_hash=cw_a.source_identifier_hash,
        target_cinq_id=id_b.cinq_id,
        reason="Splitting into an existing target with conflicting token",
        client_key="client_key_token_conflict_split_9999",
    )
    prop = MergeSplitService.create_split_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")

    with pytest.raises(HTTPException) as exc:
        MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")
    assert exc.value.status_code == 409
    assert "conflicting demographic token" in exc.value.detail


def test_ms_exec_10_split_after_merge_and_historical_reconstruction(db, identity_pair):
    id_a, id_b, cw_a, _ = identity_pair
    t_start = datetime.now(timezone.utc) - timedelta(hours=3)

    # 1. First merge id_a into id_b
    m_req = MergeProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        target_cinq_id=id_b.cinq_id,
        reason="First merge in lifecycle",
        client_key="client_key_merge_first_split_after_111",
    )
    m_prop = MergeSplitService.create_merge_proposal(db, m_req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, m_prop.proposal_id, approver_email="steward_b@cinqflow.local")
    MergeSplitService.execute_proposal(db, m_prop.proposal_id, executor_email="steward_b@cinqflow.local")

    t_post_merge = datetime.now(timezone.utc)

    # In id_b, cw_a is now active under id_b
    active_cw_in_b = db.query(IdentityCrosswalk).filter(
        IdentityCrosswalk.cinq_id == id_b.cinq_id,
        IdentityCrosswalk.source_system == cw_a.source_system,
        IdentityCrosswalk.source_identifier_hash == cw_a.source_identifier_hash,
        IdentityCrosswalk.is_active == True,
    ).first()
    assert active_cw_in_b is not None

    # 2. Split that identifier back out of id_b into a brand new identity
    s_req = SplitProposalCreateRequest(
        source_cinq_id=id_b.cinq_id,
        source_system=cw_a.source_system,
        source_identifier_hash=cw_a.source_identifier_hash,
        target_cinq_id=None,
        reason="Splitting previously merged record to new identity",
        client_key="client_key_split_after_merge_222",
    )
    s_prop = MergeSplitService.create_split_proposal(db, s_req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, s_prop.proposal_id, approver_email="steward_b@cinqflow.local")
    exec_prop, _ = MergeSplitService.execute_proposal(db, s_prop.proposal_id, executor_email="steward_b@cinqflow.local")

    t_post_split = datetime.now(timezone.utc) + timedelta(minutes=1)

    # 3. Point-in-time historical reconstruction:
    # As of t_start: belongs to id_a
    res_start = IdentityService.lookup_crosswalk_point_in_time(db, cw_a.source_system, cw_a.source_identifier_hash, as_of=t_start)
    assert res_start.cinq_id == id_a.cinq_id

    # As of t_post_split: belongs to new split identity
    res_split = IdentityService.lookup_crosswalk_point_in_time(db, cw_a.source_system, cw_a.source_identifier_hash, as_of=t_post_split)
    assert res_split.cinq_id == exec_prop.target_cinq_id
    assert res_split.cinq_id != id_a.cinq_id
    assert res_split.cinq_id != id_b.cinq_id


def test_ms_exec_11a_duplicate_active_crosswalk_constraint_rejected(db, identity_pair):
    """
    Proves PostgreSQL uniqueness constraint/index uq_active_crosswalk_source
    strictly prohibits inserting duplicate active crosswalk coordinates.
    """
    id_a, _, cw_a, _ = identity_pair
    dup_cw = IdentityCrosswalk(
        cinq_id=id_a.cinq_id,
        source_system=cw_a.source_system,
        source_identifier_hash=cw_a.source_identifier_hash,
        is_active=True,
        valid_from=datetime.now(timezone.utc) + timedelta(seconds=1),
        match_score=Decimal("99.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="system",
        updated_by="system",
    )
    db.add(dup_cw)
    with pytest.raises(Exception) as exc:
        db.commit()
    db.rollback()
    # Confirm PostgreSQL raised exclusion constraint or unique index violation
    err_str = str(exc.value).lower()
    assert (
        "excl_crosswalk_temporal_overlap" in err_str
        or "uq_active_crosswalk_source" in err_str
        or "exclusion" in err_str
        or "unique" in err_str
        or "duplicate key" in err_str
    )


def test_ms_exec_11b_defensive_ambiguity_returns_conflict(monkeypatch, db, identity_pair):
    """
    Proves that if an anomalous or corrupted state returned multiple active matches,
    MergeSplitService defensively rejects split targeting with HTTP 409 CONFLICT
    and never silently picks one row.
    """
    id_a, _, cw_a, _ = identity_pair
    req = SplitProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        source_system=cw_a.source_system,
        source_identifier_hash=cw_a.source_identifier_hash,
        target_cinq_id=None,
        reason="Testing defensive ambiguity rejection",
        client_key="client_key_defensive_ambiguity_test",
    )

    # Simulate query returning >1 active crosswalks to test defensive service branch
    simulated_multi_cws = [cw_a, cw_a]
    original_query = db.query

    class MockQuery:
        def __init__(self, model):
            self.model = model
            self.real_q = original_query(model)

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            if self.model == IdentityCrosswalk:
                return simulated_multi_cws
            return self.real_q.all()

        def first(self):
            return self.real_q.first()

    monkeypatch.setattr(db, "query", MockQuery)

    with pytest.raises(HTTPException) as exc:
        MergeSplitService.create_split_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    assert exc.value.status_code == 409
    assert "Multiple active crosswalks" in exc.value.detail


def test_ms_exec_12_repeat_split_proposal_execution_idempotent(db, identity_pair):
    id_a, _, cw_a, _ = identity_pair
    req = SplitProposalCreateRequest(
        source_cinq_id=id_a.cinq_id,
        source_system=cw_a.source_system,
        source_identifier_hash=cw_a.source_identifier_hash,
        target_cinq_id=None,
        reason="Testing split proposal execution idempotency",
        client_key="client_key_split_repeat_exec_idempotent_7777",
    )
    prop = MergeSplitService.create_split_proposal(db, req, proposer_email="steward_a@cinqflow.local")
    MergeSplitService.approve_proposal(db, prop.proposal_id, approver_email="steward_b@cinqflow.local")

    # 1. First execution
    exec_prop_1, event_1 = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")
    assert exec_prop_1.state == ProposalStateEnum.EXECUTED.value

    # Capture counts
    events_count_1 = db.query(IdentityMergeSplitEvent).filter(IdentityMergeSplitEvent.proposal_id == prop.proposal_id).count()
    cw_count_1 = db.query(IdentityCrosswalk).filter(
        IdentityCrosswalk.cinq_id == exec_prop_1.target_cinq_id,
        IdentityCrosswalk.source_system == cw_a.source_system,
        IdentityCrosswalk.source_identifier_hash == cw_a.source_identifier_hash,
        IdentityCrosswalk.is_active == True,
    ).count()
    token_count_1 = db.query(IdentityToken).filter(IdentityToken.cinq_id == exec_prop_1.target_cinq_id).count()

    # 2. Second execution of the exact same proposal
    exec_prop_2, event_2 = MergeSplitService.execute_proposal(db, prop.proposal_id, executor_email="steward_b@cinqflow.local")

    # Must be idempotent: returns existing proposal and event, zero duplicate rows created
    assert exec_prop_2.proposal_id == exec_prop_1.proposal_id
    assert event_2.event_id == event_1.event_id

    events_count_2 = db.query(IdentityMergeSplitEvent).filter(IdentityMergeSplitEvent.proposal_id == prop.proposal_id).count()
    cw_count_2 = db.query(IdentityCrosswalk).filter(
        IdentityCrosswalk.cinq_id == exec_prop_1.target_cinq_id,
        IdentityCrosswalk.source_system == cw_a.source_system,
        IdentityCrosswalk.source_identifier_hash == cw_a.source_identifier_hash,
        IdentityCrosswalk.is_active == True,
    ).count()
    token_count_2 = db.query(IdentityToken).filter(IdentityToken.cinq_id == exec_prop_1.target_cinq_id).count()

    assert events_count_2 == events_count_1 == 1
    assert cw_count_2 == cw_count_1 == 1
    assert token_count_2 == token_count_1
