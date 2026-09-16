"""
Pydantic Schemas for Wave 3 Slice 3: Identity Foundation & Identity Exceptions
"""
import uuid
import hmac
import hashlib
import json
from decimal import Decimal
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator


PROHIBITED_DEMOGRAPHIC_SUBSTRINGS = {
    "name", "first_name", "last_name", "dob", "date_of_birth", "birth_date",
    "ssn", "social_security_number", "mrn", "member_id", "phone", "email",
    "address", "street", "raw_record", "source_record_raw"
}


def validate_no_raw_phi_in_dict(data: dict) -> None:
    """Recursively validates that dictionary keys do not contain raw PHI tokens."""
    for k, v in data.items():
        k_lower = k.lower()
        for forbidden in PROHIBITED_DEMOGRAPHIC_SUBSTRINGS:
            if forbidden == k_lower or f"_{forbidden}" in k_lower or f"{forbidden}_" in k_lower:
                # Allowed hash fields
                if k_lower in {"ssn_hash", "dob_hash", "last_name_hash", "first_name_hash", "gender_hash", "postal_code_hash"}:
                    continue
                raise ValueError(f"Prohibited demographic field '{k}' detected in zero-PHI payload.")
        if isinstance(v, dict):
            validate_no_raw_phi_in_dict(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    validate_no_raw_phi_in_dict(item)


import unicodedata
import re

PROHIBITED_NOTE_PHI_PATTERNS = [
    # SSN patterns (xxx-xx-xxxx, xxx xx xxxx, or 9 contiguous digits)
    (re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b"), "SSN"),
    (re.compile(r"\b\d{9}\b"), "SSN_DIGITS"),
    # DOB patterns with explicit indicator or YYYY-MM-DD
    (re.compile(r"\b(dob|birth|born)[:\s]+(0[1-9]|1[0-2]|[1-9])[-/.](0[1-9]|[12]\d|3[01]|[1-9])[-/.](19\d{2}|20\d{2})\b", re.IGNORECASE), "DOB"),
    (re.compile(r"\b(19\d{2}|20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b"), "DATE_YYYYMMDD"),
    # US Phone number pattern
    (re.compile(r"\b(?:\+?1[-. ]?)?\(?([2-9]\d{2})\)?[-. ]?([2-9]\d{2})[-. ]?(\d{4})\b"), "PHONE"),
    # External email pattern
    (re.compile(r"\b[A-Za-z0-9._%+-]+@(?!cinqflow\.local\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.IGNORECASE), "EMAIL"),
    # MRN / SSN tags
    (re.compile(r"\b(mrn|ssn)[:\s]*[A-Za-z0-9-]{4,}\b", re.IGNORECASE), "MRN_TAG"),
]


def validate_decision_notes_non_phi(notes: str) -> str:
    """
    Validates that steward decision notes contain strictly non-PHI procedural justifications.
    Rejects any detectable raw PHI patterns (SSN, DOB, Phone, External Email, MRN tags).
    Never prints or logs the violating text to maintain Zero-PHI invariants.
    """
    if not notes:
        return notes
    for pattern, category in PROHIBITED_NOTE_PHI_PATTERNS:
        if pattern.search(notes):
            raise ValueError(
                "decision_notes contains prohibited PHI/PII patterns. Notes must contain only non-PHI procedural justifications."
            )
    return notes



def compute_canonical_source_hash(source_system: str, raw_source_identifier: str, pepper: str) -> str:
    """
    Computes canonical source_identifier_hash using source_system namespace:
    - Unicode NFKC normalization
    - source_system: stripped, collapsed internal whitespace, uppercase. Disallows colons ':'.
    - raw_source_identifier: stripped, uppercase, strictly preserving leading zeros (string-preserved). Disallows '::'.
    - Rejects null or empty values with ValueError
    - HMAC-SHA256 with pepper
    """
    if source_system is None or not str(source_system).strip():
        raise ValueError("source_system cannot be empty")
    if raw_source_identifier is None or not str(raw_source_identifier).strip():
        raise ValueError("raw_source_identifier cannot be empty")

    norm_system = unicodedata.normalize("NFKC", str(source_system)).strip()
    norm_system = re.sub(r"\s+", " ", norm_system).upper()
    if ":" in norm_system:
        raise ValueError("source_system contains illegal character ':' - colons are prohibited")

    norm_raw = unicodedata.normalize("NFKC", str(raw_source_identifier)).strip().upper()
    if "::" in norm_raw:
        raise ValueError("raw_source_identifier cannot contain delimiter sequence '::'")

    canonical_input = f"{norm_system}::{norm_raw}"
    return hmac.new(pepper.encode("utf-8"), canonical_input.encode("utf-8"), hashlib.sha256).hexdigest().lower()


def compute_evidence_hash(pre_state: dict, post_state: dict, resolution_type: str, steward_email: str) -> str:
    """Computes SHA-256 tamper-evident hash across canonical JSON resolution snapshots."""
    def canonical_json(d: dict) -> str:
        return json.dumps(d, sort_keys=True, separators=(",", ":"))
    content = f"{canonical_json(pre_state)}::{canonical_json(post_state)}::{resolution_type}::{steward_email}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class IdentityTokens(BaseModel):
    """
    Cryptographic HMAC-SHA256 token digests.
    Zero raw patient PHI.
    """
    ssn_hash: Optional[str] = Field(None, description="HMAC digest of SSN/National ID")
    dob_hash: Optional[str] = Field(None, description="HMAC digest of ISO Date of Birth")
    last_name_hash: Optional[str] = Field(None, description="HMAC digest of normalized last name")
    first_name_hash: Optional[str] = Field(None, description="HMAC digest of normalized first name")
    gender_hash: Optional[str] = Field(None, description="HMAC digest of normalized gender (M/F/U/X)")
    postal_code_hash: Optional[str] = Field(None, description="HMAC digest of postal code")


class CandidateMatchEntry(BaseModel):
    """Allowlisted schema for elements of candidate_matches_json."""
    model_config = ConfigDict(extra="forbid")
    cinq_id: str
    score: float
    matched_attributes: List[str]
    conflicting_attributes: List[str]
    tokens: Dict[str, Optional[str]]

    @field_validator("tokens")
    @classmethod
    def check_tokens_allowlist(cls, v: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        allowed = {"ssn_hash", "dob_hash", "last_name_hash", "first_name_hash", "gender", "postal_code_hash"}
        for k in v.keys():
            if k not in allowed:
                raise ValueError(f"Disallowed token key '{k}' in CandidateMatchEntry")
        return v


class PreResolutionState(BaseModel):
    """Allowlisted snapshot of exception prior to Data Steward resolution."""
    model_config = ConfigDict(extra="forbid")
    exception_id: str
    status: str
    assigned_steward: Optional[str] = None
    resolution_type: Optional[str] = None
    resolved_cinq_id: Optional[str] = None
    version: int
    highest_score: float


class PostResolutionState(BaseModel):
    """Allowlisted snapshot of exception post Data Steward resolution."""
    model_config = ConfigDict(extra="forbid")
    exception_id: str
    status: str
    assigned_steward: Optional[str] = None
    resolution_type: str
    resolved_cinq_id: Optional[str] = None
    version: int
    highest_score: float
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


class MatchRecordRequest(BaseModel):
    source_system: str
    source_identifier_hash: str
    tokens: IdentityTokens
    batch_id: Optional[uuid.UUID] = None
    feed_id: Optional[uuid.UUID] = None
    record_fingerprint: Optional[str] = None


class CandidateMatchSummary(BaseModel):
    cinq_id: uuid.UUID
    score: Decimal
    matched_attributes: List[str]
    conflicting_attributes: List[str]


class MatchRecordResponse(BaseModel):
    disposition: str
    cinq_id: Optional[uuid.UUID] = None
    match_score: Decimal
    winning_candidate: Optional[CandidateMatchSummary] = None
    exception_id: Optional[uuid.UUID] = None
    candidates_evaluated: int


class IdentityExceptionOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    feed_id: uuid.UUID
    source_system: str
    source_identifier_hash: str
    record_fingerprint: str
    candidate_matches_json: List[Dict[str, Any]]
    highest_score: Decimal
    exception_type: str
    status: str
    assigned_steward: Optional[str] = None
    assigned_at: Optional[datetime] = None
    resolution_type: Optional[str] = None
    resolved_cinq_id: Optional[uuid.UUID] = None
    resolution_notes: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    version: int

    model_config = {"from_attributes": True}


class ClaimExceptionResponse(BaseModel):
    exception_id: uuid.UUID
    assigned_steward: str
    assigned_at: datetime
    status: str


class ResolveExceptionRequest(BaseModel):
    resolution_type: str = Field(..., description="LINK_EXISTING, CREATE_NEW, or DEFER")
    target_cinq_id: Optional[uuid.UUID] = Field(None, description="Required if LINK_EXISTING")
    notes: str = Field(..., min_length=3, description="Mandatory audit rationale")
    expected_version: int = Field(..., ge=1, description="Optimistic locking version")


class ResolveExceptionResponse(BaseModel):
    exception_id: uuid.UUID
    status: str
    resolution_type: str
    resolved_cinq_id: Optional[uuid.UUID] = None
    decision_id: uuid.UUID
    evidence_hash: str
    resolved_by: str
    resolved_at: datetime


class CrosswalkEntryOut(BaseModel):
    id: uuid.UUID
    cinq_id: uuid.UUID
    source_system: str
    source_identifier_hash: str
    is_active: bool
    valid_from: datetime
    valid_to: Optional[datetime] = None
    match_score: Decimal
    match_type: str

    model_config = {"from_attributes": True}
