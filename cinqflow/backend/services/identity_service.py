"""
Deterministic Identity Scoring Engine, Crosswalk Management & Exception Lifecycle
Wave 3 Slice 3 (CF-V3-E9-01, CF-V3-E9-02)
"""
import uuid
import hmac
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple, List, Dict, Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc

from backend.core.config import settings
from backend.models.identity import (
    MasterIdentity,
    IdentityToken,
    IdentityCrosswalk,
    IdentityException,
    IdentityDecision,
    MasterIdentityStatusEnum,
    CrosswalkMatchTypeEnum,
    IdentityExceptionTypeEnum,
    IdentityExceptionStatusEnum,
    StewardResolutionTypeEnum,
)
from backend.models.feed import Feed, FeedVersion, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.schemas.identity import (
    IdentityTokens,
    MatchRecordRequest,
    MatchRecordResponse,
    CandidateMatchSummary,
    CandidateMatchEntry,
    PreResolutionState,
    PostResolutionState,
    compute_canonical_source_hash,
    compute_evidence_hash,
    validate_no_raw_phi_in_dict,
    validate_decision_notes_non_phi,
)

# Deterministic Attribute Scoring Weights
WEIGHT_SSN = Decimal("40.00")
WEIGHT_DOB = Decimal("25.00")
WEIGHT_LAST_NAME = Decimal("15.00")
WEIGHT_FIRST_NAME = Decimal("10.00")
WEIGHT_GENDER = Decimal("5.00")
WEIGHT_POSTAL_CODE = Decimal("5.00")

# Negative Conflict Penalties
PENALTY_SSN_CONFLICT = Decimal("25.00")
PENALTY_DOB_CONFLICT = Decimal("15.00")
PENALTY_LAST_NAME_CONFLICT = Decimal("10.00")
PENALTY_FIRST_NAME_CONFLICT = Decimal("5.00")
PENALTY_GENDER_CONFLICT = Decimal("10.00")

# Authoritative Score Decision Boundaries
THRESHOLD_HIGH_CONFIDENCE = Decimal("85.00")
THRESHOLD_AMBIGUOUS_MIN = Decimal("65.00")


def normalize_string(val: Optional[str]) -> Optional[str]:
    """Trims and upper-cases string, collapsing multiple whitespaces."""
    if not val:
        return None
    cleaned = re.sub(r"\s+", " ", val.strip().upper())
    return cleaned if cleaned else None


PEPPER_KEY_REGISTRY: Dict[int, str] = {
    1: getattr(settings, "IDENTITY_HASH_PEPPER_V1", getattr(settings, "IDENTITY_HASH_PEPPER", "TEST_PEPPER_KEY_V1")),
}


def compute_hmac_token(raw_value: Optional[str], pepper_version: int = 1, pepper: Optional[str] = None) -> Optional[str]:
    """
    Computes a cryptographic HMAC-SHA256 digest of normalized token.
    Never stores or returns the raw input value.
    pepper_version = 1 <-> IDENTITY_HASH_PEPPER_V1
    """
    if raw_value is None:
        return None
    norm = normalize_string(raw_value)
    if not norm:
        return None
    if pepper:
        p = pepper
    else:
        p = PEPPER_KEY_REGISTRY.get(pepper_version)
        if not p:
            raise ValueError(f"Unconfigured pepper version: {pepper_version}")
    return hmac.new(p.encode("utf-8"), norm.encode("utf-8"), hashlib.sha256).hexdigest()


class IdentityService:
    """Authoritative Identity Engine service implementation."""

    @staticmethod
    def calculate_score(
        input_tokens: IdentityTokens,
        candidate_tokens: Dict[str, Any],
    ) -> Tuple[Decimal, List[str], List[str]]:
        """
        Calculates deterministic match score between incoming record and an identity candidate.
        Returns: (score, matched_attributes, conflicting_attributes)
        """
        score = Decimal("0.00")
        matched: List[str] = []
        conflicts: List[str] = []

        # 1. Social Security Number (40 pts, conflict penalty -25 pts)
        if input_tokens.ssn_hash and candidate_tokens.get("ssn_hash"):
            if input_tokens.ssn_hash == candidate_tokens.get("ssn_hash"):
                score += WEIGHT_SSN
                matched.append("ssn_hash")
            else:
                score -= PENALTY_SSN_CONFLICT
                conflicts.append("ssn_hash")

        # 2. Date of Birth (25 pts, conflict penalty -15 pts)
        if input_tokens.dob_hash and candidate_tokens.get("dob_hash"):
            if input_tokens.dob_hash == candidate_tokens.get("dob_hash"):
                score += WEIGHT_DOB
                matched.append("dob_hash")
            else:
                score -= PENALTY_DOB_CONFLICT
                conflicts.append("dob_hash")

        # 3. Last Name (15 pts, conflict penalty -10 pts)
        if input_tokens.last_name_hash and candidate_tokens.get("last_name_hash"):
            if input_tokens.last_name_hash == candidate_tokens.get("last_name_hash"):
                score += WEIGHT_LAST_NAME
                matched.append("last_name_hash")
            else:
                score -= PENALTY_LAST_NAME_CONFLICT
                conflicts.append("last_name_hash")

        # 4. First Name (10 pts, conflict penalty -5 pts)
        if input_tokens.first_name_hash and candidate_tokens.get("first_name_hash"):
            if input_tokens.first_name_hash == candidate_tokens.get("first_name_hash"):
                score += WEIGHT_FIRST_NAME
                matched.append("first_name_hash")
            else:
                score -= PENALTY_FIRST_NAME_CONFLICT
                conflicts.append("first_name_hash")

        # 5. Gender Hash (5 pts, conflict penalty -10 pts)
        if input_tokens.gender_hash and candidate_tokens.get("gender_hash"):
            if input_tokens.gender_hash == candidate_tokens.get("gender_hash"):
                score += WEIGHT_GENDER
                matched.append("gender_hash")
            else:
                score -= PENALTY_GENDER_CONFLICT
                conflicts.append("gender_hash")

        # 6. Postal Code (5 pts)
        if input_tokens.postal_code_hash and candidate_tokens.get("postal_code_hash"):
            if input_tokens.postal_code_hash == candidate_tokens.get("postal_code_hash"):
                score += WEIGHT_POSTAL_CODE
                matched.append("postal_code_hash")
            else:
                conflicts.append("postal_code_hash")

        # Bound score between 0.00 and 100.00
        if score < Decimal("0.00"):
            score = Decimal("0.00")
        if score > Decimal("100.00"):
            score = Decimal("100.00")

        return score, matched, conflicts

    @classmethod
    def match_record(
        cls,
        db: Session,
        request: MatchRecordRequest,
        actor: str = "identity_engine",
    ) -> MatchRecordResponse:
        """
        Executes deterministic identity matching for an incoming record:
        1. Checks active crosswalk mapping.
        2. Retrieves candidate identities from indexed identity_tokens table.
        3. Evaluates candidates using deterministic scoring matrix.
        4. High confidence (> 85.00 without tie) auto-links and inserts crosswalk.
        5. Ambiguous, tied, or no viable candidate creates identity_exception (PENDING).
        """
        pepper = getattr(settings, "IDENTITY_HASH_PEPPER", "cinqflow-dev-identity-pepper-2026")
        
        # Step 1: Check active crosswalk for this source system + identifier hash
        existing_cw = (
            db.query(IdentityCrosswalk)
            .filter(
                IdentityCrosswalk.source_system == request.source_system,
                IdentityCrosswalk.source_identifier_hash == request.source_identifier_hash,
                IdentityCrosswalk.is_active == True,
            )
            .first()
        )
        if existing_cw:
            # Active mapping exists -> Direct authoritative resolution
            return MatchRecordResponse(
                disposition="HIGH_CONFIDENCE",
                cinq_id=existing_cw.cinq_id,
                match_score=Decimal("100.00"),
                winning_candidate=CandidateMatchSummary(
                    cinq_id=existing_cw.cinq_id,
                    score=Decimal("100.00"),
                    matched_attributes=["active_crosswalk_mapping"],
                    conflicting_attributes=[],
                ),
                exception_id=None,
                candidates_evaluated=1,
            )

        # Step 2: Retrieve candidate identities from identity_tokens table
        blocking_clauses = []
        if request.tokens.ssn_hash:
            blocking_clauses.append(IdentityToken.ssn_hash == request.tokens.ssn_hash)
        if request.tokens.last_name_hash and request.tokens.dob_hash:
            blocking_clauses.append(
                and_(
                    IdentityToken.last_name_hash == request.tokens.last_name_hash,
                    IdentityToken.dob_hash == request.tokens.dob_hash,
                )
            )

        candidate_tokens_records: List[IdentityToken] = []
        if blocking_clauses:
            candidate_tokens_records = (
                db.query(IdentityToken)
                .filter(
                    IdentityToken.is_current == True,
                    or_(*blocking_clauses),
                )
                .limit(50)
                .all()
            )

        # Fallback: if no blocking candidates found but active master identities exist, evaluate up to 10
        if not candidate_tokens_records:
            candidate_tokens_records = (
                db.query(IdentityToken)
                .filter(IdentityToken.is_current == True)
                .limit(10)
                .all()
            )

        # Step 3: Deterministic Scoring across candidate tokens
        evaluated_candidates: List[Tuple[uuid.UUID, Decimal, List[str], List[str], Dict[str, Any]]] = []
        for cand in candidate_tokens_records:
            cand_dict = {
                "ssn_hash": cand.ssn_hash,
                "dob_hash": cand.dob_hash,
                "last_name_hash": cand.last_name_hash,
                "first_name_hash": cand.first_name_hash,
                "gender_hash": cand.gender_hash,
                "postal_code_hash": cand.postal_code_hash,
            }
            cand_score, matched_attrs, conflict_attrs = cls.calculate_score(request.tokens, cand_dict)
            evaluated_candidates.append(
                (cand.cinq_id, cand_score, matched_attrs, conflict_attrs, cand_dict)
            )

        evaluated_candidates.sort(key=lambda x: x[1], reverse=True)
        highest_score = evaluated_candidates[0][1] if evaluated_candidates else Decimal("0.00")
        num_candidates = len(evaluated_candidates)

        # Tie or close match detection in high confidence range
        is_score_tie = False
        if (
            len(evaluated_candidates) >= 2
            and evaluated_candidates[0][1] > THRESHOLD_HIGH_CONFIDENCE
            and (evaluated_candidates[0][1] - evaluated_candidates[1][1]) < Decimal("5.00")
        ):
            is_score_tie = True

        # Allowlisted candidates JSON structure (zero raw PHI!)
        candidates_json = [
            {
                "cinq_id": str(c[0]),
                "score": float(c[1]),
                "matched_attributes": c[2],
                "conflicting_attributes": c[3],
                "tokens": {
                    k: v for k, v in c[4].items()
                    if k in ("ssn_hash", "dob_hash", "last_name_hash", "first_name_hash", "gender_hash", "postal_code_hash")
                }
            }
            for c in evaluated_candidates[:10]
        ]
        validate_no_raw_phi_in_dict({"candidates": candidates_json})

        # Resolve valid foreign keys for batch_id and feed_id
        target_feed_id = request.feed_id
        target_batch_id = request.batch_id
        if not target_feed_id:
            feed = db.query(Feed).first()
            if not feed:
                feed = Feed(
                    name="System Identity Eval Feed",
                    domain="clinical",
                    description="System feed for standalone evaluations",
                    format="CSV",
                    landing_folder="./data/landing/system_identity",
                    filename_pattern=r"^IDENTITY_.*\.csv$",
                    schedule_expression="0 0 * * *",
                    status="ACTIVE",
                    created_by=actor,
                    updated_by=actor,
                )
                db.add(feed)
                db.flush()
            target_feed_id = feed.id

        if not target_batch_id:
            batch = db.query(Batch).filter(Batch.feed_id == target_feed_id).first()
            if not batch:
                ver = db.query(FeedVersion).filter(FeedVersion.feed_id == target_feed_id).first()
                if not ver:
                    ver = FeedVersion(
                        feed_id=target_feed_id,
                        version_number=1,
                        status=FeedVersionStatusEnum.PUBLISHED.value,
                        created_by=actor,
                        updated_by=actor,
                    )
                    db.add(ver)
                    db.flush()
                batch = Batch(
                    feed_id=target_feed_id,
                    feed_version_id=ver.id,
                    status=BatchStatusEnum.RUNNING.value,
                    triggered_by=actor,
                    created_by=actor,
                    updated_by=actor,
                )
                db.add(batch)
                db.flush()
            target_batch_id = batch.id

        # Case A: Score Tie in High Confidence
        if is_score_tie:
            exc = IdentityException(
                batch_id=target_batch_id,
                feed_id=target_feed_id,
                source_system=request.source_system,
                source_identifier_hash=request.source_identifier_hash,
                record_fingerprint=request.record_fingerprint or hashlib.sha256(request.source_identifier_hash.encode()).hexdigest(),
                candidate_matches_json=candidates_json,
                highest_score=highest_score,
                exception_type=IdentityExceptionTypeEnum.SCORE_TIE.value,
                status=IdentityExceptionStatusEnum.PENDING.value,
                created_by=actor,
                updated_by=actor,
            )
            db.add(exc)
            db.commit()
            db.refresh(exc)

            db.add(
                AuditEvent(
                    action=AuditActionEnum.IDENTITY_EXCEPTION_CREATED,
                    actor_id=actor,
                    object_type="identity_exception",
                    object_id=str(exc.id),
                    description="Identity exception created for score tie",
                    after_state={
                        "exception_id": str(exc.id),
                        "exception_type": exc.exception_type,
                        "highest_score": float(highest_score),
                        "tied_candidates": [str(c[0]) for c in evaluated_candidates[:2]],
                    },
                    created_by=actor,
                    updated_by=actor,
                )
            )
            db.commit()

            return MatchRecordResponse(
                disposition="SCORE_TIE",
                cinq_id=None,
                match_score=highest_score,
                winning_candidate=None,
                exception_id=exc.id,
                candidates_evaluated=num_candidates,
            )

        # Case B: High Confidence Unique Match (S > 85.00)
        if highest_score > THRESHOLD_HIGH_CONFIDENCE:
            winning_cid = evaluated_candidates[0][0]
            winning_cand = CandidateMatchSummary(
                cinq_id=winning_cid,
                score=highest_score,
                matched_attributes=evaluated_candidates[0][2],
                conflicting_attributes=evaluated_candidates[0][3],
            )

            # Insert authoritative active crosswalk entry
            new_cw = IdentityCrosswalk(
                cinq_id=winning_cid,
                source_system=request.source_system,
                source_identifier_hash=request.source_identifier_hash,
                is_active=True,
                valid_from=datetime.now(timezone.utc),
                valid_to=None,
                match_score=highest_score,
                match_type=CrosswalkMatchTypeEnum.DETERMINISTIC_HIGH_CONFIDENCE.value,
                source_feed_id=target_feed_id,
                source_batch_id=target_batch_id,
                created_by=actor,
                updated_by=actor,
            )
            db.add(new_cw)
            db.commit()

            db.add(
                AuditEvent(
                    action=AuditActionEnum.IDENTITY_MATCHED,
                    actor_id=actor,
                    object_type="master_identity",
                    object_id=str(winning_cid),
                    description=f"Deterministic high confidence match to {winning_cid}",
                    after_state={
                        "cinq_id": str(winning_cid),
                        "source_system": request.source_system,
                        "source_identifier_hash": request.source_identifier_hash,
                        "score": float(highest_score),
                    },
                    created_by=actor,
                    updated_by=actor,
                )
            )
            db.commit()

            return MatchRecordResponse(
                disposition="HIGH_CONFIDENCE",
                cinq_id=winning_cid,
                match_score=highest_score,
                winning_candidate=winning_cand,
                exception_id=None,
                candidates_evaluated=num_candidates,
            )

        # Case C: Ambiguous Match (65.00 <= S <= 85.00)
        if highest_score >= THRESHOLD_AMBIGUOUS_MIN:
            exc = IdentityException(
                batch_id=target_batch_id,
                feed_id=target_feed_id,
                source_system=request.source_system,
                source_identifier_hash=request.source_identifier_hash,
                record_fingerprint=request.record_fingerprint or hashlib.sha256(request.source_identifier_hash.encode()).hexdigest(),
                candidate_matches_json=candidates_json,
                highest_score=highest_score,
                exception_type=IdentityExceptionTypeEnum.AMBIGUOUS_MATCH.value,
                status=IdentityExceptionStatusEnum.PENDING.value,
                created_by=actor,
                updated_by=actor,
            )
            db.add(exc)
            db.commit()
            db.refresh(exc)

            db.add(
                AuditEvent(
                    action=AuditActionEnum.IDENTITY_EXCEPTION_CREATED,
                    actor_id=actor,
                    object_type="identity_exception",
                    object_id=str(exc.id),
                    description="Identity exception created for ambiguous match",
                    after_state={
                        "exception_id": str(exc.id),
                        "exception_type": exc.exception_type,
                        "highest_score": float(highest_score),
                    },
                    created_by=actor,
                    updated_by=actor,
                )
            )
            db.commit()

            return MatchRecordResponse(
                disposition="AMBIGUOUS_MATCH",
                cinq_id=None,
                match_score=highest_score,
                winning_candidate=None,
                exception_id=exc.id,
                candidates_evaluated=num_candidates,
            )

        # Case D: No Viable Candidate (S < 65.00)
        exc = IdentityException(
            batch_id=target_batch_id,
            feed_id=target_feed_id,
            source_system=request.source_system,
            source_identifier_hash=request.source_identifier_hash,
            record_fingerprint=request.record_fingerprint or hashlib.sha256(request.source_identifier_hash.encode()).hexdigest(),
            candidate_matches_json=candidates_json,
            highest_score=highest_score,
            exception_type=IdentityExceptionTypeEnum.NO_VIABLE_CANDIDATE.value,
            status=IdentityExceptionStatusEnum.PENDING.value,
            created_by=actor,
            updated_by=actor,
        )
        db.add(exc)
        db.commit()
        db.refresh(exc)

        db.add(
            AuditEvent(
                action=AuditActionEnum.IDENTITY_EXCEPTION_CREATED,
                actor_id=actor,
                object_type="identity_exception",
                object_id=str(exc.id),
                description="Identity exception created for no viable candidate",
                after_state={
                    "exception_id": str(exc.id),
                    "exception_type": exc.exception_type,
                    "highest_score": float(highest_score),
                },
                created_by=actor,
                updated_by=actor,
            )
        )
        db.commit()

        return MatchRecordResponse(
            disposition="NO_VIABLE_CANDIDATE",
            cinq_id=None,
            match_score=highest_score,
            winning_candidate=None,
            exception_id=exc.id,
            candidates_evaluated=num_candidates,
        )

    @classmethod
    def claim_exception(
        cls,
        db: Session,
        exception_id: uuid.UUID,
        steward_email: str,
    ) -> IdentityException:
        """
        Claims an exception, transitioning from PENDING to UNDER_REVIEW.
        """
        exc = db.query(IdentityException).filter(IdentityException.id == exception_id).first()
        if not exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Identity exception {exception_id} not found",
            )

        if exc.status != IdentityExceptionStatusEnum.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Exception cannot be claimed: status is '{exc.status}' (must be PENDING)",
            )

        exc.assigned_steward = steward_email
        exc.assigned_at = datetime.now(timezone.utc)
        exc.status = IdentityExceptionStatusEnum.UNDER_REVIEW.value
        exc.updated_by = steward_email
        exc.version += 1

        db.add(
            AuditEvent(
                action=AuditActionEnum.IDENTITY_EXCEPTION_CLAIMED,
                actor_id=steward_email,
                actor_email=steward_email,
                object_type="identity_exception",
                object_id=str(exc.id),
                description=f"Exception claimed by steward {steward_email}",
                after_state={
                    "exception_id": str(exc.id),
                    "assigned_steward": steward_email,
                },
                created_by=steward_email,
                updated_by=steward_email,
            )
        )
        db.commit()
        db.refresh(exc)
        return exc

    @classmethod
    def resolve_exception(
        cls,
        db: Session,
        exception_id: uuid.UUID,
        resolution_type: str,
        target_cinq_id: Optional[uuid.UUID],
        notes: str,
        steward_email: str,
        expected_version: int,
    ) -> Tuple[IdentityException, IdentityDecision]:
        """
        Authoritatively resolves an identity exception:
        - Enforces Four-Eyes segregation (Feed author != Resolver).
        - Enforces Steward custody (Assigned steward == Resolver).
        - Enforces optimistic concurrency (expected_version == version).
        - Records immutable decision with SHA-256 evidence_hash.
        - Persists IdentityToken on CREATE_NEW for future deterministic candidate matching.
        """
        exc = db.query(IdentityException).filter(IdentityException.id == exception_id).first()
        if not exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Identity exception {exception_id} not found",
            )

        # 1. Four-Eyes segregation check
        feed = db.query(Feed).filter(Feed.id == exc.feed_id).first()
        if feed and feed.created_by == steward_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Four-Eyes Principle Violation: Feed author '{feed.created_by}' cannot resolve exceptions originating from their own feed.",
            )

        # 2. Steward custody check
        if exc.assigned_steward and exc.assigned_steward != steward_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Steward Custody Violation: Assigned steward '{exc.assigned_steward}' does not match resolver '{steward_email}'.",
            )

        # 3. Optimistic concurrency check
        if expected_version != exc.version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Optimistic Concurrency Conflict: Expected version {expected_version} does not match current version {exc.version}.",
            )

        # 4. Immutability check
        if exc.status == IdentityExceptionStatusEnum.RESOLVED.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Identity exception is already RESOLVED and immutable.",
            )

        # 5. Non-PHI decision_notes check
        try:
            validate_decision_notes_non_phi(notes)
        except ValueError:
            import logging
            logging.getLogger("cinqflow.audit").warning(
                "Audit security: Steward decision notes rejected due to PHI pattern match. Content suppressed."
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="decision_notes contains prohibited PHI/PII patterns. Notes must contain only non-PHI procedural justifications.",
            )

        # Capture pre-resolution snapshot
        pre_state = {
            "exception_id": str(exc.id),
            "status": exc.status,
            "assigned_steward": exc.assigned_steward,
            "resolution_type": exc.resolution_type,
            "resolved_cinq_id": str(exc.resolved_cinq_id) if exc.resolved_cinq_id else None,
            "version": exc.version,
            "highest_score": float(exc.highest_score),
        }

        resolved_cinq_id: Optional[uuid.UUID] = None
        new_status = IdentityExceptionStatusEnum.RESOLVED.value
        now_dt = datetime.now(timezone.utc)

        if resolution_type == StewardResolutionTypeEnum.LINK_EXISTING.value:
            if not target_cinq_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="target_cinq_id is required for LINK_EXISTING resolution.",
                )
            master = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == target_cinq_id).first()
            if not master:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target MasterIdentity '{target_cinq_id}' not found.",
                )
            if master.status != MasterIdentityStatusEnum.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Target MasterIdentity is not ACTIVE (status: {master.status}).",
                )
            resolved_cinq_id = master.cinq_id

            # Insert active crosswalk mapping
            cw = IdentityCrosswalk(
                cinq_id=resolved_cinq_id,
                source_system=exc.source_system,
                source_identifier_hash=exc.source_identifier_hash,
                is_active=True,
                valid_from=now_dt,
                valid_to=None,
                match_score=Decimal("100.00"),
                match_type=CrosswalkMatchTypeEnum.STEWARD_LINK.value,
                source_feed_id=exc.feed_id,
                source_batch_id=exc.batch_id,
                created_by=steward_email,
                updated_by=steward_email,
            )
            db.add(cw)

        elif resolution_type == StewardResolutionTypeEnum.CREATE_NEW.value:
            # Use canonical lock utility for advisory locking and creation logic
            from backend.services.lock_utils import acquire_identity_operation_lock, generate_lock_keys

            # Build lock keys (SSN anchors or fallback source identifier)
            lock_keys = generate_lock_keys(exc)
            # Acquire locks within a transaction‑level advisory lock context
            with acquire_identity_operation_lock(db, *lock_keys):
                # Re‑evaluate active candidates under exclusive lock to prevent race conditions
                active_tokens = db.query(IdentityToken).filter(IdentityToken.is_current == True).limit(50).all()
                if exc.candidate_matches_json:
                    for cand in exc.candidate_matches_json:
                        if isinstance(cand, dict) and "tokens" in cand and isinstance(cand["tokens"], dict):
                            inc_tokens = IdentityTokens(
                                ssn_hash=cand["tokens"].get("ssn_hash"),
                                dob_hash=cand["tokens"].get("dob_hash"),
                                last_name_hash=cand["tokens"].get("last_name_hash"),
                                first_name_hash=cand["tokens"].get("first_name_hash"),
                                gender_hash=cand["tokens"].get("gender_hash"),
                                postal_code_hash=cand["tokens"].get("postal_code_hash"),
                            )
                            for tok_row in active_tokens:
                                cand_dict = {
                                    "ssn_hash": tok_row.ssn_hash,
                                    "dob_hash": tok_row.dob_hash,
                                    "last_name_hash": tok_row.last_name_hash,
                                    "first_name_hash": tok_row.first_name_hash,
                                    "gender_hash": tok_row.gender_hash,
                                    "postal_code_hash": tok_row.postal_code_hash,
                                }
                                re_score, _, _ = cls.calculate_score(inc_tokens, cand_dict)
                                if re_score >= Decimal("50.00"):
                                    raise HTTPException(
                                        status_code=status.HTTP_409_CONFLICT,
                                        detail=f"Concurrent MasterIdentity Candidate Detected: Re-scoring identified candidate match '{tok_row.cinq_id}' (Score: {re_score}). Resolution blocked to prevent duplicate identity creation. Steward must review newly available candidate."
                                    )
                # Create new MasterIdentity record
                new_master = MasterIdentity(
                    status=MasterIdentityStatusEnum.ACTIVE.value,
                    created_by=steward_email,
                    updated_by=steward_email,
                )
                db.add(new_master)
                db.flush()
                resolved_cinq_id = new_master.cinq_id

                # Persist deterministic tokens for future matching (first non‑null per attribute)
                tok_ssn = tok_dob = tok_ln = tok_fn = tok_gender = tok_postal = None
                if exc.candidate_matches_json:
                    for cand in exc.candidate_matches_json:
                        if isinstance(cand, dict) and "tokens" in cand and isinstance(cand["tokens"], dict):
                            t = cand["tokens"]
                            tok_ssn = tok_ssn or t.get("ssn_hash")
                            tok_dob = tok_dob or t.get("dob_hash")
                            tok_ln = tok_ln or t.get("last_name_hash")
                            tok_fn = tok_fn or t.get("first_name_hash")
                            tok_gender = tok_gender or t.get("gender_hash")
                            tok_postal = tok_postal or t.get("postal_code_hash")
                new_token = IdentityToken(
                    cinq_id=resolved_cinq_id,
                    pepper_version=1,
                    ssn_hash=tok_ssn,
                    dob_hash=tok_dob,
                    last_name_hash=tok_ln,
                    first_name_hash=tok_fn,
                    gender_hash=tok_gender,
                    postal_code_hash=tok_postal,
                    is_current=True,
                    effective_from=now_dt,
                    source_feed_id=exc.feed_id,
                    source_batch_id=exc.batch_id,
                    created_by=steward_email,
                    updated_by=steward_email,
                )
                db.add(new_token)

            # Insert active crosswalk mapping
            cw = IdentityCrosswalk(
                cinq_id=resolved_cinq_id,
                source_system=exc.source_system,
                source_identifier_hash=exc.source_identifier_hash,
                is_active=True,
                valid_from=now_dt,
                valid_to=None,
                match_score=Decimal("100.00"),
                match_type=CrosswalkMatchTypeEnum.STEWARD_CREATE.value,
                source_feed_id=exc.feed_id,
                source_batch_id=exc.batch_id,
                created_by=steward_email,
                updated_by=steward_email,
            )
            db.add(cw)

        elif resolution_type == StewardResolutionTypeEnum.DEFER.value:
            if target_cinq_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="cinq_id must be null for DEFER decision",
                )
            new_status = IdentityExceptionStatusEnum.DEFERRED.value
            resolved_cinq_id = None

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown resolution type '{resolution_type}'. Must be LINK_EXISTING, CREATE_NEW, or DEFER.",
            )

        # Update exception
        exc.status = new_status
        exc.resolution_type = resolution_type
        exc.resolved_cinq_id = resolved_cinq_id
        exc.resolution_notes = notes
        exc.resolved_by = steward_email
        exc.resolved_at = now_dt
        exc.version += 1
        exc.updated_by = steward_email

        post_state = {
            "exception_id": str(exc.id),
            "status": new_status,
            "assigned_steward": exc.assigned_steward,
            "resolution_type": resolution_type,
            "resolved_cinq_id": str(resolved_cinq_id) if resolved_cinq_id else None,
            "version": exc.version,
            "highest_score": float(exc.highest_score),
            "resolved_at": now_dt.isoformat(),
            "resolved_by": steward_email,
        }

        # Calculate cryptographic evidence hash
        ev_hash = compute_evidence_hash(pre_state, post_state, resolution_type, steward_email)

        # Append to immutable identity_decisions
        decision = IdentityDecision(
            exception_id=exc.id,
            decision_type=resolution_type,
            cinq_id=resolved_cinq_id,
            decided_by=steward_email,
            decided_at=now_dt,
            decision_notes=notes,
            pre_resolution_state=pre_state,
            post_resolution_state=post_state,
            evidence_hash=ev_hash,
            created_by=steward_email,
            updated_by=steward_email,
        )
        db.add(decision)

        # Audit events
        db.add(
            AuditEvent(
                action=AuditActionEnum.IDENTITY_EXCEPTION_RESOLVED,
                actor_id=steward_email,
                actor_email=steward_email,
                object_type="identity_exception",
                object_id=str(exc.id),
                description=f"Exception resolved as {resolution_type}",
                after_state={
                    "exception_id": str(exc.id),
                    "resolution_type": resolution_type,
                    "resolved_cinq_id": str(resolved_cinq_id) if resolved_cinq_id else None,
                },
                created_by=steward_email,
                updated_by=steward_email,
            )
        )
        db.add(
            AuditEvent(
                action=AuditActionEnum.IDENTITY_DECISION_RECORDED,
                actor_id=steward_email,
                actor_email=steward_email,
                object_type="identity_decision",
                object_id=str(decision.id),
                description=f"Decision recorded for exception {exc.id}",
                after_state={
                    "decision_id": str(decision.id),
                    "exception_id": str(exc.id),
                    "decision_type": resolution_type,
                    "evidence_hash": ev_hash,
                },
                created_by=steward_email,
                updated_by=steward_email,
            )
        )

        db.commit()
        db.refresh(exc)
        db.refresh(decision)

        return exc, decision

    @classmethod
    def lookup_crosswalk_point_in_time(
        cls,
        db: Session,
        source_system: str,
        source_identifier_hash: str,
        as_of: Optional[datetime] = None,
    ) -> Optional[IdentityCrosswalk]:
        """
        Point-in-time lookup of active crosswalk mapping.
        """
        target_ts = as_of or datetime.now(timezone.utc)
        return (
            db.query(IdentityCrosswalk)
            .filter(
                IdentityCrosswalk.source_system == source_system,
                IdentityCrosswalk.source_identifier_hash == source_identifier_hash,
                IdentityCrosswalk.valid_from <= target_ts,
                or_(
                    IdentityCrosswalk.valid_to == None,
                    IdentityCrosswalk.valid_to > target_ts,
                ),
            )
            .order_by(desc(IdentityCrosswalk.valid_from))
            .first()
        )
