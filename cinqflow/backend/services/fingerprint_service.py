"""
Wave 2 Slice 4 Service — Deterministic Failure Fingerprinting (CF-V2-E12-04)

Normalizes raw operational failure contexts, strips PHI and runtime variability
(UUIDs, timestamps, line numbers, memory pointers, file paths), and generates
deterministic SHA-256 signatures.
"""
import re
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from backend.models.incident import FailureFingerprint, FailureCategoryEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.engine.arrival_engine import ArrivalEngine

# Normalization regular expressions
_RE_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_RE_HEX_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_RE_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_RE_ROW_NUM = re.compile(r"(?:row|line|record)\s*#?\d+", re.IGNORECASE)
_RE_FILE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:home|var|tmp|app|etc|usr)/)[^\s'\"\)\]\}]+", re.IGNORECASE)
_RE_WHITESPACE = re.compile(r"\s+")

# Zero-PHI regular expressions
_RE_SSN_HYPHEN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_RE_SSN_DIGITS = re.compile(r"(?:(?<=[\W_])|^)\d{9}(?:(?=[\W_])|$)")
_RE_PHONE = re.compile(r"(?:(?<=[\s,;:()\[\]\-])|^)(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}(?:(?=[\s,;:()\[\].\-])|$)")
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_MRN = re.compile(r"\b(?:MRN|mrn|MEDREC|PatientID)[:\s#-]*[A-Za-z0-9]{4,15}\b", re.IGNORECASE)
_RE_DOB = re.compile(r"\b(?:DOB|dob|Date of Birth|birth date)[:\s#-]*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b", re.IGNORECASE)
_RE_NAME = re.compile(r"\b(?:patient(?:\s+name)?|member(?:\s+name)?|patient_name|member_name)[:\s]+[A-Za-z]+(?:\s+[A-Za-z]+)+\b", re.IGNORECASE)
_RE_ADDRESS = re.compile(r"\b\d{1,5}\s+[A-Za-z0-9\s,.'-]{3,35}\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Circle|Cir|Terrace|Ter|Place|Pl|Trail|Trl|Parkway|Pkwy|Highway|Hwy)\b", re.IGNORECASE)
_RE_ZIP = re.compile(r"\b(?:ZIP(?:code)?|postal(?:\s*code)?)[:\s#-]*\d{5}(?:-\d{4})?\b|\b\d{5}-\d{4}\b", re.IGNORECASE)


class FingerprintService:
    """Core logic for deterministic failure fingerprinting and normalization."""

    @classmethod
    def sanitize_zero_phi(cls, text: Optional[str]) -> str:
        """
        Scrubs potential patient/member identifying strings (PHI/PII) from any text.
        Redacts SSN, MRN, Email, Phone, DOB, Patient Names, Street Addresses, and ZIPs.
        """
        if not text:
            return ""
        s = _RE_MRN.sub("[REDACTED_MRN]", str(text))
        s = _RE_DOB.sub("[REDACTED_DOB]", s)
        s = _RE_NAME.sub("[REDACTED_NAME]", s)
        s = _RE_ADDRESS.sub("[REDACTED_ADDRESS]", s)
        s = _RE_ZIP.sub("[REDACTED_ZIP]", s)
        s = _RE_EMAIL.sub("[REDACTED_EMAIL]", s)
        s = _RE_PHONE.sub("[REDACTED_PHONE]", s)
        s = _RE_SSN_HYPHEN.sub("[REDACTED_SSN]", s)
        s = _RE_SSN_DIGITS.sub("[REDACTED_SSN]", s)
        return s

    @classmethod
    def sanitize_zero_phi_dict(cls, data: Any) -> Any:
        """Recursively sanitizes dict, list, or string values to guarantee zero PHI."""
        if isinstance(data, dict):
            return {cls.sanitize_zero_phi(str(k)): cls.sanitize_zero_phi_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls.sanitize_zero_phi_dict(item) for item in data]
        elif isinstance(data, str):
            return cls.sanitize_zero_phi(data)
        return data

    @classmethod
    def sanitize_and_normalize(cls, raw_text: Optional[str]) -> str:
        """
        Applies strict zero-PHI sanitization followed by runtime artifact normalization.
        Removes UUIDs, hex pointers, timestamps, row numbers, and file paths.
        """
        if not raw_text:
            return "UnknownError"

        # 1. Normalize volatile runtime tokens first so hex strings/UUIDs don't trigger PHI regexes
        normalized = _RE_UUID.sub("<UUID>", raw_text)
        normalized = _RE_HEX_ADDR.sub("<HEX_ADDR>", normalized)
        normalized = _RE_TIMESTAMP.sub("<TS>", normalized)
        normalized = _RE_ROW_NUM.sub("row <NUM>", normalized)
        normalized = _RE_FILE_PATH.sub("<PATH>", normalized)

        # 2. Comprehensive PHI Scrubbing
        sanitized = cls.sanitize_zero_phi(normalized)

        # 3. Collapse whitespace
        result = _RE_WHITESPACE.sub(" ", sanitized).strip()
        return result

    @classmethod
    def compute_signature(
        cls,
        category: FailureCategoryEnum,
        failure_stage: Optional[str],
        root_cause_pattern: str,
        error_class: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Generates canonical JSON signature and deterministic SHA-256 hash.
        Returns: (canonical_signature, fingerprint_hash)
        """
        norm_pattern = cls.sanitize_and_normalize(root_cause_pattern)
        norm_class = cls.sanitize_and_normalize(error_class) if error_class else "OperationalFailure"
        norm_stage = (failure_stage.strip().upper()) if failure_stage else "UNKNOWN"
        cat_str = category.value if hasattr(category, "value") else str(category)

        payload = {
            "v": 1,
            "cat": cat_str,
            "cls": norm_class,
            "sig": norm_pattern[:255],
            "stg": norm_stage,
        }
        canonical_signature = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fingerprint_hash = hashlib.sha256(canonical_signature.encode("utf-8")).hexdigest()
        return canonical_signature, fingerprint_hash

    @classmethod
    def get_or_create_fingerprint(
        cls,
        db: Session,
        category: FailureCategoryEnum,
        failure_stage: Optional[str],
        root_cause_pattern: str,
        error_class: Optional[str] = None,
        user_id: str = "system",
    ) -> FailureFingerprint:
        """
        Resolves or creates a deterministic failure fingerprint in the database.
        Increments total_occurrences and updates last_seen_at if already seen.
        """
        canonical_sig, fp_hash = cls.compute_signature(
            category=category,
            failure_stage=failure_stage,
            root_cause_pattern=root_cause_pattern,
            error_class=error_class,
        )

        now_utc = datetime.now(timezone.utc)
        fingerprint = (
            db.query(FailureFingerprint)
            .filter(FailureFingerprint.fingerprint_hash == fp_hash)
            .with_for_update()
            .first()
        )

        if fingerprint:
            fingerprint.total_occurrences += 1
            fingerprint.last_seen_at = now_utc
            fingerprint.updated_at = now_utc
            fingerprint.updated_by = user_id
            db.flush()
            return fingerprint

        # Create new fingerprint with savepoint concurrency protection
        norm_pattern = cls.sanitize_and_normalize(root_cause_pattern)[:255]
        norm_stage = (failure_stage.strip().upper()) if failure_stage else None

        from sqlalchemy.exc import IntegrityError
        try:
            with db.begin_nested():
                fingerprint = FailureFingerprint(
                    category=category,
                    failure_stage=norm_stage,
                    root_cause_pattern=norm_pattern,
                    canonical_signature=canonical_sig,
                    fingerprint_hash=fp_hash,
                    total_occurrences=1,
                    first_seen_at=now_utc,
                    last_seen_at=now_utc,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(fingerprint)
                db.flush()

                # Audit event
                db.add(
                    AuditEvent(
                        action=AuditActionEnum.OPS_FINGERPRINT_CREATED,
                        object_type="failure_fingerprint",
                        object_id=str(fingerprint.id),
                        actor_id=user_id,
                        description=f"Failure fingerprint created: {fp_hash[:8]}",
                        after_state={
                            "fingerprint_hash": fp_hash,
                            "category": category.value if hasattr(category, "value") else str(category),
                            "stage": norm_stage,
                            "pattern": norm_pattern,
                        },
                        created_by=user_id,
                        updated_by=user_id,
                    )
                )
                db.flush()
                return fingerprint
        except IntegrityError:
            # Concurrent worker created it simultaneously — reload existing fingerprint
            fingerprint = (
                db.query(FailureFingerprint)
                .filter(FailureFingerprint.fingerprint_hash == fp_hash)
                .with_for_update()
                .first()
            )
            if fingerprint:
                fingerprint.total_occurrences += 1
                fingerprint.last_seen_at = now_utc
                fingerprint.updated_at = now_utc
                fingerprint.updated_by = user_id
                db.flush()
                return fingerprint
            raise
