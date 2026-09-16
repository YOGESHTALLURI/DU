"""
Unit tests for FingerprintService (CF-V2-E12-04)
Deterministic failure signature hashing, input normalization, zero-PHI guarantees.
"""
import uuid
from backend.services.fingerprint_service import FingerprintService
from backend.models.incident import FailureCategoryEnum, FailureFingerprint


def test_fingerprint_deterministic_hashing():
    """Identical errors across different calls must yield the exact same SHA-256 hash."""
    sig1, hash1 = FingerprintService.compute_signature(
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Value out of range for date_of_birth",
        error_class="DQRuleViolation.DATE_RANGE",
    )
    sig2, hash2 = FingerprintService.compute_signature(
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Value out of range for date_of_birth",
        error_class="DQRuleViolation.DATE_RANGE",
    )
    assert hash1 == hash2
    assert sig1 == sig2
    assert len(hash1) == 64


def test_fingerprint_normalization_uuids():
    """Volatile batch UUIDs must be normalized to <UUID> so two runs with different batch IDs produce identical hashes."""
    u1 = str(uuid.uuid4())
    u2 = str(uuid.uuid4())
    text1 = f"Failed processing batch {u1} in stage BRONZE"
    text2 = f"Failed processing batch {u2} in stage BRONZE"

    norm1 = FingerprintService.sanitize_and_normalize(text1)
    norm2 = FingerprintService.sanitize_and_normalize(text2)

    assert norm1 == norm2
    assert "<UUID>" in norm1
    assert u1 not in norm1

    _, h1 = FingerprintService.compute_signature(FailureCategoryEnum.STAGE_EXECUTION, "BRONZE", text1)
    _, h2 = FingerprintService.compute_signature(FailureCategoryEnum.STAGE_EXECUTION, "BRONZE", text2)
    assert h1 == h2


def test_fingerprint_normalization_timestamps():
    """Timestamps must be normalized to <TS> so identical errors on different days share the same fingerprint."""
    text1 = "Connection lost at 2026-09-06T12:00:00Z to database"
    text2 = "Connection lost at 2026-09-07T15:30:22.123456+00:00 to database"

    norm1 = FingerprintService.sanitize_and_normalize(text1)
    norm2 = FingerprintService.sanitize_and_normalize(text2)

    assert norm1 == norm2
    assert "<TS>" in norm1


def test_fingerprint_normalization_hex_pointers():
    """Memory addresses (0x...) in stack traces must be normalized to <HEX_ADDR>."""
    text1 = "Null pointer reference at 0x7ffd18b29c00"
    text2 = "Null pointer reference at 0x7ffd99a41b20"

    norm1 = FingerprintService.sanitize_and_normalize(text1)
    norm2 = FingerprintService.sanitize_and_normalize(text2)

    assert norm1 == norm2
    assert "<HEX_ADDR>" in norm1


def test_fingerprint_normalization_row_numbers():
    """Row or line number variations must be normalized to row <NUM>."""
    text1 = "CSV parsing failed at row #102: expected 15 fields"
    text2 = "CSV parsing failed at row #4059: expected 15 fields"

    norm1 = FingerprintService.sanitize_and_normalize(text1)
    norm2 = FingerprintService.sanitize_and_normalize(text2)

    assert norm1 == norm2
    assert "row <NUM>" in norm1


def test_fingerprint_zero_phi_ssn_redaction():
    """Social Security Numbers (SSN) must be scrubbed completely before signature creation."""
    text = "Invalid national id provided: 123-45-6789 in column ssn"
    norm = FingerprintService.sanitize_and_normalize(text)

    assert "123-45-6789" not in norm
    assert "[REDACTED_SSN]" in norm


def test_fingerprint_zero_phi_email_phone_redaction():
    """Patient emails and phone numbers must be redacted."""
    text = "Member contact patient.doe@hospital.org / 555-123-4567 failed regex verification"
    norm = FingerprintService.sanitize_and_normalize(text)

    assert "patient.doe@hospital.org" not in norm
    assert "555-123-4567" not in norm
    assert "[REDACTED_EMAIL]" in norm
    assert "[REDACTED_PHONE]" in norm


def test_get_or_create_fingerprint_increments_occurrence(db):
    """Calling get_or_create_fingerprint repeatedly must return the existing record and increment total_occurrences."""
    fp1 = FingerprintService.get_or_create_fingerprint(
        db=db,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Missing mandatory member_id field",
        user_id="test-operator",
    )
    assert fp1.total_occurrences == 1
    fp1_id = fp1.id

    fp2 = FingerprintService.get_or_create_fingerprint(
        db=db,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Missing mandatory member_id field",
        user_id="test-operator",
    )
    assert fp2.id == fp1_id
    assert fp2.total_occurrences == 2
