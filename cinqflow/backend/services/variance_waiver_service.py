"""
Wave 2 Slice 5 Service — Operational Variances & Waivers (CF-V2-E13-03)
Enforces four-eyes dual-control governance, bounded expirations, zero-PHI sanitization,
concurrency locking, and immutable audit trails.
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.governance import (
    OperationalVariance,
    OperationalWaiver,
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
)
from backend.models.audit import AuditActionEnum
from backend.models.feed import Feed
from backend.models.pipeline import Batch
from backend.core.security import CurrentUser
from backend.services.audit_service import AuditService
from backend.services.fingerprint_service import FingerprintService
from backend.schemas.governance import WaiverSubmitRequest


class VarianceWaiverService:
    @staticmethod
    def record_variance(
        db: Session,
        feed_id: uuid.UUID,
        batch_id: uuid.UUID,
        control_type: str,
        control_id: str,
        title: str,
        description: str,
        severity: str = "WARNING",
        telemetry_snapshot: Optional[Dict[str, Any]] = None,
        user_id: str = "system",
        user_email: Optional[str] = None,
    ) -> OperationalVariance:
        """
        Record a factual non-compliance deviation from an operational or data quality control.
        Scrubs all PHI before storage and logs an audit event.
        """
        clean_title = FingerprintService.sanitize_zero_phi(title)
        clean_description = FingerprintService.sanitize_zero_phi(description)
        clean_snapshot = FingerprintService.sanitize_zero_phi_dict(telemetry_snapshot or {})

        variance = OperationalVariance(
            id=uuid.uuid4(),
            feed_id=feed_id,
            batch_id=batch_id,
            control_type=control_type,
            control_id=control_id,
            severity=severity,
            title=clean_title,
            description=clean_description,
            telemetry_snapshot=clean_snapshot,
            status=VarianceStatusEnum.OPEN,
            detected_at=datetime.now(timezone.utc),
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(variance)
        db.flush()

        AuditService.log(
            db=db,
            action=AuditActionEnum.OPS_VARIANCE_CREATED,
            actor_id=user_id,
            actor_email=user_email,
            object_type="operational_variance",
            object_id=str(variance.id),
            after_state={
                "variance_id": str(variance.id),
                "feed_id": str(feed_id),
                "batch_id": str(batch_id),
                "control_type": control_type,
                "control_id": control_id,
                "severity": severity,
                "title": clean_title,
                "status": variance.status.value,
            },
            description=f"Operational variance recorded on batch {batch_id} for control {control_type}:{control_id}",
        )
        return variance

    @staticmethod
    def list_variances(
        db: Session,
        feed_id: Optional[uuid.UUID] = None,
        batch_id: Optional[uuid.UUID] = None,
        status_filter: Optional[VarianceStatusEnum] = None,
        control_type: Optional[str] = None,
    ) -> List[OperationalVariance]:
        query = db.query(OperationalVariance)
        if feed_id:
            query = query.filter(OperationalVariance.feed_id == feed_id)
        if batch_id:
            query = query.filter(OperationalVariance.batch_id == batch_id)
        if status_filter:
            query = query.filter(OperationalVariance.status == status_filter)
        if control_type:
            query = query.filter(OperationalVariance.control_type == control_type)
        return query.order_by(OperationalVariance.detected_at.desc()).all()

    @staticmethod
    def get_variance(db: Session, variance_id: uuid.UUID) -> OperationalVariance:
        variance = db.query(OperationalVariance).filter(OperationalVariance.id == variance_id).first()
        if not variance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operational variance '{variance_id}' not found",
            )
        return variance

    @staticmethod
    def request_waiver(
        db: Session,
        req: WaiverSubmitRequest,
        current_user: CurrentUser,
    ) -> OperationalWaiver:
        """
        Formally submit a waiver request for an active variance.
        Enforces:
        - Variance existence and OPEN status
        - Expiration in the future and strictly within 30 days
        - Zero-PHI text sanitization
        - Prevention of duplicate active waivers per variance
        """
        variance = db.query(OperationalVariance).filter(OperationalVariance.id == req.variance_id).first()
        if not variance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Variance '{req.variance_id}' not found",
            )

        if variance.status == VarianceStatusEnum.RESOLVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot request a waiver for an already RESOLVED variance",
            )

        # Check for existing active/pending waiver
        existing_waivers = (
            db.query(OperationalWaiver)
            .filter(
                OperationalWaiver.variance_id == req.variance_id,
                OperationalWaiver.status.in_([WaiverStatusEnum.PENDING_APPROVAL, WaiverStatusEnum.APPROVED]),
            )
            .all()
        )
        now = datetime.now(timezone.utc)
        for existing_waiver in existing_waivers:
            if existing_waiver.status == WaiverStatusEnum.PENDING_APPROVAL:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"A waiver request ({existing_waiver.id}) is already pending review for this variance",
                )
            elif existing_waiver.status == WaiverStatusEnum.APPROVED:
                if VarianceWaiverService.is_waiver_active(existing_waiver):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"An active approved waiver ({existing_waiver.id}) already exists for this variance",
                    )
                else:
                    # It has expired or exhausted max_batches; transition to EXPIRED to free index and record history
                    existing_waiver.status = WaiverStatusEnum.EXPIRED
                    existing_waiver.updated_at = now
                    existing_waiver.updated_by = current_user.user_id
                    db.flush()

        if req.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Waiver expiration must be strictly in the future",
            )

        max_expiry = now + timedelta(days=30)
        if req.expires_at > max_expiry:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Waiver expiration exceeds the maximum allowable policy window (30 days)",
            )

        # Validate Scope Parameters
        valid_from = req.valid_from or now
        if valid_from > req.expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Waiver valid_from cannot be after expires_at",
            )

        range_start_batch_id = req.range_start_batch_id
        range_end_batch_id = req.range_end_batch_id
        target_batch_ids = None

        if req.scope == WaiverScopeEnum.SINGLE_BATCH:
            # Single batch waiver targets variance.batch_id
            target_batch_ids = [str(variance.batch_id)]
        elif req.scope == WaiverScopeEnum.BATCH_RANGE:
            if req.target_batch_ids:
                target_batch_ids = [str(bid) for bid in req.target_batch_ids]
            elif req.range_start_batch_id and req.range_end_batch_id:
                start_b = db.query(Batch).filter(Batch.id == req.range_start_batch_id).first()
                end_b = db.query(Batch).filter(Batch.id == req.range_end_batch_id).first()
                if not start_b or not end_b:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="BATCH_RANGE start and end batches must exist in the database",
                    )
                range_start_batch_id = start_b.id
                range_end_batch_id = end_b.id
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="BATCH_RANGE scope requires either target_batch_ids or both range_start_batch_id and range_end_batch_id",
                )
        elif req.scope == WaiverScopeEnum.TIME_BOUNDED:
            # Time-bounded requires valid window
            if req.target_batch_ids:
                target_batch_ids = [str(bid) for bid in req.target_batch_ids]

        clean_justification = FingerprintService.sanitize_zero_phi(req.business_justification)
        clean_risk = FingerprintService.sanitize_zero_phi(req.risk_assessment)
        clean_mitigation = FingerprintService.sanitize_zero_phi(req.mitigation_notes)

        waiver = OperationalWaiver(
            id=uuid.uuid4(),
            variance_id=variance.id,
            feed_id=variance.feed_id,
            batch_id=variance.batch_id,
            scope=req.scope,
            affected_control_type=variance.control_type,
            affected_control_id=variance.control_id,
            valid_from=valid_from,
            range_start_batch_id=range_start_batch_id,
            range_end_batch_id=range_end_batch_id,
            target_batch_ids=target_batch_ids,
            business_justification=clean_justification,
            risk_assessment=clean_risk,
            mitigation_notes=clean_mitigation,
            expires_at=req.expires_at,
            max_batches=req.max_batches,
            batches_applied_count=0,
            status=WaiverStatusEnum.PENDING_APPROVAL,
            requested_by=current_user.user_id,
            requested_by_email=current_user.email,
            requested_at=now,
            created_by=current_user.user_id,
            updated_by=current_user.user_id,
        )
        db.add(waiver)
        try:
            db.flush()
        except Exception as e:
            from sqlalchemy.exc import IntegrityError
            if isinstance(e, IntegrityError):
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A waiver is already pending approval or actively approved for this variance",
                )
            raise e

        AuditService.log(
            db=db,
            action=AuditActionEnum.OPS_WAIVER_REQUESTED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="operational_waiver",
            object_id=str(waiver.id),
            after_state={
                "waiver_id": str(waiver.id),
                "variance_id": str(variance.id),
                "batch_id": str(variance.batch_id),
                "control_type": variance.control_type,
                "control_id": variance.control_id,
                "scope": waiver.scope.value,
                "expires_at": waiver.expires_at.isoformat(),
                "requested_by": current_user.user_id,
            },
            description=f"Waiver requested for variance {variance.id} on batch {variance.batch_id}",
        )
        return waiver

    @staticmethod
    def review_waiver(
        db: Session,
        waiver_id: uuid.UUID,
        decision: str,
        decision_notes: str,
        current_user: CurrentUser,
    ) -> OperationalWaiver:
        """
        Approve or reject a waiver.
        Strictly enforces:
        - Four-eyes separation of duties (requester != reviewer)
        - Pessimistic locking (with_for_update) to prevent concurrent review collisions
        - Deterministic transition of parent variance status
        """
        decision_upper = decision.strip().upper()
        if decision_upper not in ["APPROVE", "REJECT"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Decision must be either 'APPROVE' or 'REJECT'",
            )

        waiver = (
            db.query(OperationalWaiver)
            .filter(OperationalWaiver.id == waiver_id)
            .with_for_update()
            .first()
        )
        if not waiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operational waiver '{waiver_id}' not found",
            )

        if waiver.status != WaiverStatusEnum.PENDING_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Waiver '{waiver_id}' is not in PENDING_APPROVAL status (currently {waiver.status.value})",
            )

        # Four-Eyes Governance Enforcement
        req_user_id = (waiver.requested_by or "").strip().lower()
        rev_user_id = (current_user.user_id or "").strip().lower()
        req_email = (waiver.requested_by_email or "").strip().lower()
        rev_email = (current_user.email or "").strip().lower()

        if rev_user_id == req_user_id or (req_email and rev_email and req_email == rev_email):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Four-eyes violation: Requester cannot review or approve their own waiver request",
            )

        clean_notes = FingerprintService.sanitize_zero_phi(decision_notes)
        now = datetime.now(timezone.utc)

        variance = db.query(OperationalVariance).filter(OperationalVariance.id == waiver.variance_id).first()

        if decision_upper == "APPROVE":
            waiver.status = WaiverStatusEnum.APPROVED
            if variance and variance.status == VarianceStatusEnum.OPEN:
                variance.status = VarianceStatusEnum.WAIVED
                variance.updated_at = now
                variance.updated_by = current_user.user_id
            audit_action = AuditActionEnum.OPS_WAIVER_APPROVED
        else:
            waiver.status = WaiverStatusEnum.REJECTED
            audit_action = AuditActionEnum.OPS_WAIVER_REJECTED

        waiver.reviewed_by = current_user.user_id
        waiver.reviewed_by_email = current_user.email
        waiver.reviewed_at = now
        waiver.decision_notes = clean_notes
        waiver.updated_at = now
        waiver.updated_by = current_user.user_id
        db.flush()

        AuditService.log(
            db=db,
            action=audit_action,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="operational_waiver",
            object_id=str(waiver.id),
            after_state={
                "waiver_id": str(waiver.id),
                "status": waiver.status.value,
                "reviewed_by": current_user.user_id,
                "reviewed_at": now.isoformat(),
                "decision": decision_upper,
                "decision_notes": clean_notes,
            },
            description=f"Waiver {waiver.id} reviewed with decision {decision_upper}",
        )
        return waiver

    @staticmethod
    def revoke_waiver(
        db: Session,
        waiver_id: uuid.UUID,
        revocation_reason: str,
        current_user: CurrentUser,
    ) -> OperationalWaiver:
        """
        Revoke an active approved waiver.
        Reverts the underlying variance status back to OPEN.
        """
        waiver = (
            db.query(OperationalWaiver)
            .filter(OperationalWaiver.id == waiver_id)
            .with_for_update()
            .first()
        )
        if not waiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operational waiver '{waiver_id}' not found",
            )

        if waiver.status != WaiverStatusEnum.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only APPROVED waivers can be revoked (currently {waiver.status.value})",
            )

        clean_reason = FingerprintService.sanitize_zero_phi(revocation_reason)
        now = datetime.now(timezone.utc)

        waiver.status = WaiverStatusEnum.REVOKED
        waiver.revoked_by = current_user.user_id
        waiver.revoked_at = now
        waiver.revocation_reason = clean_reason
        waiver.updated_at = now
        waiver.updated_by = current_user.user_id

        # Revert variance status if still WAIVED
        variance = db.query(OperationalVariance).filter(OperationalVariance.id == waiver.variance_id).first()
        if variance and variance.status == VarianceStatusEnum.WAIVED:
            variance.status = VarianceStatusEnum.OPEN
            variance.updated_at = now
            variance.updated_by = current_user.user_id

        db.flush()

        AuditService.log(
            db=db,
            action=AuditActionEnum.OPS_WAIVER_REVOKED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="operational_waiver",
            object_id=str(waiver.id),
            after_state={
                "waiver_id": str(waiver.id),
                "status": waiver.status.value,
                "revoked_by": current_user.user_id,
                "revocation_reason": clean_reason,
            },
            description=f"Waiver {waiver.id} revoked by {current_user.user_id}",
        )
        return waiver

    @staticmethod
    def is_waiver_active(waiver: OperationalWaiver) -> bool:
        """
        Evaluate if a waiver is currently active and non-expired.
        Evaluates dynamic expiration conditions.
        """
        if waiver.status != WaiverStatusEnum.APPROVED:
            return False

        now = datetime.now(timezone.utc)
        if now > waiver.expires_at:
            return False

        if waiver.max_batches is not None and waiver.batches_applied_count >= waiver.max_batches:
            return False

        return True

    @staticmethod
    def does_waiver_apply_to_batch(
        waiver: OperationalWaiver,
        batch: Batch,
        db: Session,
        reference_time: Optional[datetime] = None,
    ) -> bool:
        """
        Authoritative evaluation of waiver applicability to a specific batch.
        Enforces:
        - Feed alignment (waiver.feed_id == batch.feed_id)
        - Waiver approval status (status == APPROVED)
        - Dynamic time bounds: valid_from <= reference_time <= expires_at
        - Max batch quota: batches_applied_count < max_batches
        - Scope-specific matching:
            * SINGLE_BATCH: matches waiver.batch_id == batch.id
            * BATCH_RANGE: matches explicit target_batch_ids or chronological window between start and end batch
            * TIME_BOUNDED: matches batch.created_at within [valid_from, expires_at]
        """
        if waiver.feed_id != batch.feed_id:
            return False

        if waiver.status != WaiverStatusEnum.APPROVED:
            return False

        ref_time = reference_time or datetime.now(timezone.utc)

        # Time bounds
        if waiver.valid_from and ref_time < waiver.valid_from:
            return False
        if ref_time > waiver.expires_at:
            return False

        # Max batches quota
        if waiver.max_batches is not None and waiver.batches_applied_count >= waiver.max_batches:
            return False

        # Scope evaluations
        if waiver.scope == WaiverScopeEnum.SINGLE_BATCH:
            return waiver.batch_id == batch.id

        elif waiver.scope == WaiverScopeEnum.BATCH_RANGE:
            # Check target_batch_ids
            if waiver.target_batch_ids:
                return str(batch.id) in [str(b) for b in waiver.target_batch_ids]
            # Check range boundaries
            if waiver.range_start_batch_id and waiver.range_end_batch_id:
                start_b = db.query(Batch).filter(Batch.id == waiver.range_start_batch_id).first()
                end_b = db.query(Batch).filter(Batch.id == waiver.range_end_batch_id).first()
                if start_b and end_b:
                    t_min = min(start_b.created_at, end_b.created_at)
                    t_max = max(start_b.created_at, end_b.created_at)
                    return t_min <= batch.created_at <= t_max
            return False

        elif waiver.scope == WaiverScopeEnum.TIME_BOUNDED:
            # Batch creation time must fall within waiver period
            t_start = waiver.valid_from or waiver.created_at
            t_end = waiver.expires_at
            if t_start and batch.created_at < t_start:
                return False
            if batch.created_at > t_end:
                return False
            return True

        return False

    @staticmethod
    def list_waivers(
        db: Session,
        feed_id: Optional[uuid.UUID] = None,
        batch_id: Optional[uuid.UUID] = None,
        status_filter: Optional[WaiverStatusEnum] = None,
    ) -> List[OperationalWaiver]:
        query = db.query(OperationalWaiver)
        if feed_id:
            query = query.filter(OperationalWaiver.feed_id == feed_id)
        if batch_id:
            query = query.filter(OperationalWaiver.batch_id == batch_id)
        if status_filter:
            query = query.filter(OperationalWaiver.status == status_filter)
        return query.order_by(OperationalWaiver.requested_at.desc()).all()
