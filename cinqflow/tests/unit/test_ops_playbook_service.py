"""
Unit tests for PlaybookService (CF-V2-E12-04)
Playbook version immutability, approval governance, matching, and lifecycle.
"""
import uuid
from backend.services.playbook_service import PlaybookService
from backend.services.fingerprint_service import FingerprintService
from backend.models.incident import (
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    FailureCategoryEnum,
    PlaybookStatusEnum,
)
from backend.models.ops_action import ActionTypeEnum


def test_create_playbook_draft_v1(db):
    """Creating a playbook initializes it in DRAFT state with version 1."""
    pb = PlaybookService.create_playbook(
        db=db,
        title="Handle Corrupted Header",
        category=FailureCategoryEnum.STAGE_EXECUTION,
        playbook_code=f"PB-TEST-{uuid.uuid4().hex[:6]}",
        explanation_template="Check file encoding and header delimiters",
        suggested_action_type=ActionTypeEnum.RESTART_BATCH,
        user_id="engineer@cinqflow.local",
    )
    assert pb.status == PlaybookStatusEnum.DRAFT
    assert pb.current_version_id is not None

    ver = db.query(RecoveryPlaybookVersion).filter(RecoveryPlaybookVersion.id == pb.current_version_id).first()
    assert ver.version_number == 1
    assert ver.status == PlaybookStatusEnum.DRAFT
    assert ver.suggested_action_type == ActionTypeEnum.RESTART_BATCH


def test_update_playbook_creates_new_immutable_version(db):
    """Updating a playbook creates a new version record while preserving version 1."""
    pb = PlaybookService.create_playbook(
        db=db,
        title="Handle Schema Drift",
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        playbook_code=f"PB-TEST-{uuid.uuid4().hex[:6]}",
        explanation_template="Version 1 explanation",
        user_id="engineer",
    )
    v1_id = pb.current_version_id

    v2 = PlaybookService.update_playbook(
        db=db,
        playbook_id=pb.id,
        explanation_template="Version 2 updated SOP explanation",
        user_id="engineer2",
    )
    assert v2.version_number == 2
    assert v2.id != v1_id

    # Verify version 1 is still intact in DB
    v1 = db.query(RecoveryPlaybookVersion).filter(RecoveryPlaybookVersion.id == v1_id).first()
    assert v1.version_number == 1
    assert v1.explanation_template == "Version 1 explanation"


def test_approve_playbook_sets_current_version(db):
    """Approving a version activates it as the playbook's current active version."""
    pb = PlaybookService.create_playbook(
        db=db,
        title="Quarantine Remediation SOP",
        category=FailureCategoryEnum.DATA_QUALITY,
        playbook_code=f"PB-TEST-{uuid.uuid4().hex[:6]}",
        explanation_template="Remediate invalid fields in quarantine",
        user_id="engineer",
    )
    v2 = PlaybookService.update_playbook(db=db, playbook_id=pb.id, explanation_template="V2 steps", user_id="engineer")

    approved_pb = PlaybookService.approve_playbook_version(
        db=db,
        version_id=v2.id,
        approved_by="steward@cinqflow.local",
    )
    assert approved_pb.status == PlaybookStatusEnum.APPROVED
    assert approved_pb.current_version_id == v2.id

    db.refresh(v2)
    assert v2.status == PlaybookStatusEnum.APPROVED
    assert v2.approved_by == "steward@cinqflow.local"


def test_deprecate_playbook(db):
    """Deprecating a playbook marks the playbook and active version as DEPRECATED."""
    pb = PlaybookService.create_playbook(
        db=db,
        title="Old SOP",
        category=FailureCategoryEnum.STAGE_EXECUTION,
        playbook_code=f"PB-TEST-{uuid.uuid4().hex[:6]}",
        explanation_template="Old instructions",
    )
    PlaybookService.approve_playbook_version(db=db, version_id=pb.current_version_id, approved_by="admin")

    dep_pb = PlaybookService.deprecate_playbook(db=db, playbook_id=pb.id, user_id="lead-engineer")
    assert dep_pb.status == PlaybookStatusEnum.DEPRECATED

    ver = db.query(RecoveryPlaybookVersion).filter(RecoveryPlaybookVersion.id == dep_pb.current_version_id).first()
    assert ver.status == PlaybookStatusEnum.DEPRECATED


def test_find_matching_playbook_explicit_binding(db):
    """Explicit fingerprint-playbook binding takes precedence over category defaults."""
    fp = FingerprintService.get_or_create_fingerprint(
        db=db,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Specific rule DOB_RANGE failure",
    )

    # Generic playbook
    generic_pb = PlaybookService.create_playbook(
        db=db,
        title="Generic DQ SOP",
        category=FailureCategoryEnum.DATA_QUALITY,
        playbook_code=f"PB-GEN-{uuid.uuid4().hex[:6]}",
        explanation_template="Generic explanation",
    )
    PlaybookService.approve_playbook_version(db=db, version_id=generic_pb.current_version_id, approved_by="admin")

    # Specific playbook bound explicitly
    specific_pb = PlaybookService.create_playbook(
        db=db,
        title="DOB Specific SOP",
        category=FailureCategoryEnum.DATA_QUALITY,
        playbook_code=f"PB-SPEC-{uuid.uuid4().hex[:6]}",
        explanation_template="DOB specific remediation",
    )
    PlaybookService.approve_playbook_version(db=db, version_id=specific_pb.current_version_id, approved_by="admin")
    PlaybookService.bind_fingerprint(db=db, fingerprint_id=fp.id, playbook_id=specific_pb.id, priority=10)

    matched = PlaybookService.find_matching_playbook_version(db=db, fingerprint=fp)
    assert matched is not None
    assert matched.playbook_id == specific_pb.id
    assert "DOB specific" in matched.explanation_template


def test_find_matching_playbook_category_fallback(db):
    """When no explicit binding exists, falls back to approved category playbook."""
    cat_pb = PlaybookService.create_playbook(
        db=db,
        title="Default Stage Execution SOP",
        category=FailureCategoryEnum.STAGE_EXECUTION,
        playbook_code=f"PB-STAGE-DEF-{uuid.uuid4().hex[:6]}",
        explanation_template="Default execution recovery steps",
    )
    PlaybookService.approve_playbook_version(db=db, version_id=cat_pb.current_version_id, approved_by="admin")

    fp = FingerprintService.get_or_create_fingerprint(
        db=db,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Unbound stage crash",
    )

    matched = PlaybookService.find_matching_playbook_version(db=db, fingerprint=fp)
    assert matched is not None
    assert matched.playbook_id == cat_pb.id
