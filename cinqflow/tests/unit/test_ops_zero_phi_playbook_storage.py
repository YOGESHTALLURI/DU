"""
Unit tests for Zero-PHI Enforcement Across Persisted Playbook Fields
Wave 2 Slice 4 Blocker 4
"""
import uuid
import pytest
from sqlalchemy import text
from backend.services.playbook_service import PlaybookService
from backend.models.incident import (
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    FailureCategoryEnum,
    PlaybookStatusEnum,
)
from backend.models.ops_action import ActionTypeEnum


def test_create_playbook_zero_phi_scrubbing(db):
    """Blocker 4: create_playbook must scrub all PHI across title, templates, steps, risk, parameters, prerequisites."""
    raw_title = "Remediation for Patient with SSN 123-45-6789"
    raw_explanation = "Contact patient at 555-123-4567 or email john.doe@healthsystem.org immediately"
    raw_steps = "1. Look up patient: John Doe in records\n2. Verify MRN: 987654321"
    raw_risk = "Physical site inspection needed at 123 Main Street for patient records"
    raw_params = {
        "member_dob": "DOB: 1980-05-12",
        "nested": {"contact_phone": "(555) 987-6543"},
    }
    raw_prereqs = ["Check patient zipcode: 90210 before dispatch"]

    code = f"PB-TEST-PHI-{uuid.uuid4().hex[:6]}"

    pb = PlaybookService.create_playbook(
        db=db,
        title=raw_title,
        category=FailureCategoryEnum.DATA_QUALITY,
        playbook_code=code,
        explanation_template=raw_explanation,
        suggested_action_type=ActionTypeEnum.REPROCESS_QUARANTINE,
        action_parameters_template=raw_params,
        manual_steps_markdown=raw_steps,
        prerequisites=raw_prereqs,
        risk_assessment=raw_risk,
        user_id="test-operator",
    )
    db.commit()

    # Query DB directly to verify persisted records in PostgreSQL
    persisted_pb = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.id == pb.id).first()
    assert "123-45-6789" not in persisted_pb.title
    assert "[REDACTED_SSN]" in persisted_pb.title

    persisted_ver = (
        db.query(RecoveryPlaybookVersion)
        .filter(RecoveryPlaybookVersion.id == pb.current_version_id)
        .first()
    )

    # Explanation scrubbing
    assert "555-123-4567" not in persisted_ver.explanation_template
    assert "john.doe@healthsystem.org" not in persisted_ver.explanation_template
    assert "[REDACTED_PHONE]" in persisted_ver.explanation_template
    assert "[REDACTED_EMAIL]" in persisted_ver.explanation_template

    # Steps scrubbing
    assert "John Doe" not in persisted_ver.manual_steps_markdown
    assert "987654321" not in persisted_ver.manual_steps_markdown
    assert "[REDACTED_NAME]" in persisted_ver.manual_steps_markdown
    assert "[REDACTED_MRN]" in persisted_ver.manual_steps_markdown

    # Risk assessment scrubbing
    assert "123 Main Street" not in persisted_ver.risk_assessment
    assert "[REDACTED_ADDRESS]" in persisted_ver.risk_assessment

    # Parameters dict scrubbing
    assert "1980-05-12" not in str(persisted_ver.action_parameters_template)
    assert "(555) 987-6543" not in str(persisted_ver.action_parameters_template)
    assert "[REDACTED_DOB]" in persisted_ver.action_parameters_template["member_dob"]
    assert "[REDACTED_PHONE]" in persisted_ver.action_parameters_template["nested"]["contact_phone"]

    # Prerequisites scrubbing
    assert "90210" not in str(persisted_ver.prerequisites)
    assert "[REDACTED_ZIP]" in str(persisted_ver.prerequisites)


def test_update_playbook_zero_phi_scrubbing(db):
    """Blocker 4: update_playbook must scrub all PHI when creating new version snapshots."""
    code = f"PB-TEST-UPDATE-{uuid.uuid4().hex[:6]}"
    pb = PlaybookService.create_playbook(
        db=db,
        title="Initial Clean Title",
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        playbook_code=code,
        explanation_template="Clean explanation",
    )
    db.commit()

    # Update with PHI in explanation and parameters
    new_ver = PlaybookService.update_playbook(
        db=db,
        playbook_id=pb.id,
        explanation_template="Contact patient via email jane.smith@clinic.com or 555-456-7890",
        action_parameters_template={"patient_ssn": "987-65-4321"},
        manual_steps_markdown="patient: Bob Builder requires verification at 456 Oak Avenue",
        user_id="test-operator",
    )
    db.commit()

    assert new_ver.version_number == 2
    assert "jane.smith@clinic.com" not in new_ver.explanation_template
    assert "[REDACTED_EMAIL]" in new_ver.explanation_template
    assert "987-65-4321" not in str(new_ver.action_parameters_template)
    assert "[REDACTED_SSN]" in str(new_ver.action_parameters_template)
    assert "Bob Builder" not in new_ver.manual_steps_markdown
    assert "456 Oak Avenue" not in new_ver.manual_steps_markdown
    assert "[REDACTED_NAME]" in new_ver.manual_steps_markdown
    assert "[REDACTED_ADDRESS]" in new_ver.manual_steps_markdown
