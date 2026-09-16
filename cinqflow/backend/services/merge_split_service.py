"""
Deterministic Service for Identity Merge & Split Decisions (CF-V3-E9-03)
Enforces Four-Eyes segregation, atomic transactional transitions, advisory locking,
temporal crosswalk invalidation, and audit ledger persistence.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, text

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
from backend.schemas.identity import validate_decision_notes_non_phi
from backend.services.lock_utils import acquire_identity_operation_lock


class MergeSplitService:
    """Authoritative service for Identity Merge and Split proposals & executions."""

    @classmethod
    def create_merge_proposal(
        cls,
        db: Session,
        request: MergeProposalCreateRequest,
        proposer_email: str,
    ) -> IdentityMergeSplitProposal:
        if request.source_cinq_id == request.target_cinq_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot merge an identity into itself (source_cinq_id == target_cinq_id)",
            )

        # Check existing active proposal for idempotency
        existing = (
            db.query(IdentityMergeSplitProposal)
            .filter(
                IdentityMergeSplitProposal.client_key == request.client_key,
                IdentityMergeSplitProposal.operation_type == OperationTypeEnum.MERGE.value,
                IdentityMergeSplitProposal.state == ProposalStateEnum.PENDING_APPROVAL.value,
            )
            .first()
        )
        if existing:
            return existing

        # Validate non-PHI notes
        try:
            validate_decision_notes_non_phi(request.reason)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Proposal reason contains prohibited PHI/PII patterns",
            )

        # Validate identities exist and are ACTIVE
        src = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == request.source_cinq_id).first()
        tgt = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == request.target_cinq_id).first()
        if not src or not tgt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or both MasterIdentities not found",
            )
        if src.status != MasterIdentityStatusEnum.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source MasterIdentity is not ACTIVE (status: {src.status})",
            )
        if tgt.status != MasterIdentityStatusEnum.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Target MasterIdentity is not ACTIVE (status: {tgt.status})",
            )

        proposal = IdentityMergeSplitProposal(
            source_cinq_id=request.source_cinq_id,
            target_cinq_id=request.target_cinq_id,
            operation_type=OperationTypeEnum.MERGE.value,
            client_key=request.client_key,
            state=ProposalStateEnum.PENDING_APPROVAL.value,
            proposer_id=proposer_email,
            expected_version=src.version,
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        return proposal

    @classmethod
    def create_split_proposal(
        cls,
        db: Session,
        request: SplitProposalCreateRequest,
        proposer_email: str,
    ) -> IdentityMergeSplitProposal:
        existing = (
            db.query(IdentityMergeSplitProposal)
            .filter(
                IdentityMergeSplitProposal.client_key == request.client_key,
                IdentityMergeSplitProposal.operation_type == OperationTypeEnum.SPLIT.value,
                IdentityMergeSplitProposal.state == ProposalStateEnum.PENDING_APPROVAL.value,
            )
            .first()
        )
        if existing:
            return existing

        try:
            validate_decision_notes_non_phi(request.reason)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Proposal reason contains prohibited PHI/PII patterns",
            )

        src = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == request.source_cinq_id).first()
        if not src:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source MasterIdentity {request.source_cinq_id} not found",
            )
        if src.status != MasterIdentityStatusEnum.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source MasterIdentity is not ACTIVE (status: {src.status})",
            )

        # Verify that the identifier is currently active under this source identity
        matching_cws = (
            db.query(IdentityCrosswalk)
            .filter(
                IdentityCrosswalk.cinq_id == request.source_cinq_id,
                IdentityCrosswalk.source_system == request.source_system,
                IdentityCrosswalk.source_identifier_hash == request.source_identifier_hash,
                IdentityCrosswalk.is_active == True,
            )
            .all()
        )
        if len(matching_cws) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identifier is not actively associated with the specified source identity",
            )
        elif len(matching_cws) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ambiguity conflict: Multiple active crosswalks found for coordinates under source identity",
            )
        cw = matching_cws[0]

        if request.target_cinq_id:
            tgt = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == request.target_cinq_id).first()
            if not tgt or tgt.status != MasterIdentityStatusEnum.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Specified target MasterIdentity is not active or not found",
                )

        proposal = IdentityMergeSplitProposal(
            source_cinq_id=request.source_cinq_id,
            target_cinq_id=request.target_cinq_id,
            operation_type=OperationTypeEnum.SPLIT.value,
            source_system=request.source_system,
            source_identifier_hash=request.source_identifier_hash,
            client_key=request.client_key,
            state=ProposalStateEnum.PENDING_APPROVAL.value,
            proposer_id=proposer_email,
            expected_version=src.version,
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        return proposal

    @classmethod
    def approve_proposal(
        cls,
        db: Session,
        proposal_id: uuid.UUID,
        approver_email: str,
    ) -> IdentityMergeSplitProposal:
        prop = db.query(IdentityMergeSplitProposal).filter(IdentityMergeSplitProposal.proposal_id == proposal_id).first()
        if not prop:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

        if prop.state != ProposalStateEnum.PENDING_APPROVAL.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Proposal cannot be approved in state '{prop.state}'",
            )

        # Four-Eyes Principle Enforcement
        if prop.proposer_id == approver_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Four-Eyes Principle Violation: Proposer cannot approve their own proposal",
            )

        prop.state = ProposalStateEnum.APPROVED.value
        prop.approver_id = approver_email
        prop.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(prop)
        return prop

    @classmethod
    def reject_proposal(
        cls,
        db: Session,
        proposal_id: uuid.UUID,
        rejector_email: str,
        reason: str,
    ) -> IdentityMergeSplitProposal:
        prop = db.query(IdentityMergeSplitProposal).filter(IdentityMergeSplitProposal.proposal_id == proposal_id).first()
        if not prop:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

        if prop.state != ProposalStateEnum.PENDING_APPROVAL.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Proposal cannot be rejected in state '{prop.state}'",
            )

        prop.state = ProposalStateEnum.REJECTED.value
        prop.approver_id = rejector_email
        prop.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(prop)
        return prop

    @classmethod
    def execute_proposal(
        cls,
        db: Session,
        proposal_id: uuid.UUID,
        executor_email: str,
    ) -> Tuple[IdentityMergeSplitProposal, IdentityMergeSplitEvent]:
        prop = db.query(IdentityMergeSplitProposal).filter(IdentityMergeSplitProposal.proposal_id == proposal_id).first()
        if not prop:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

        if prop.state == ProposalStateEnum.EXECUTED.value:
            # Idempotent execution: return already executed proposal and associated event without re-executing
            existing_event = (
                db.query(IdentityMergeSplitEvent)
                .filter(IdentityMergeSplitEvent.proposal_id == proposal_id)
                .order_by(IdentityMergeSplitEvent.created_at.desc())
                .first()
            )
            return prop, existing_event

        if prop.state != ProposalStateEnum.APPROVED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Proposal must be APPROVED before execution (current state: {prop.state})",
            )

        now_dt = datetime.now(timezone.utc)
        actor_uuid = uuid.uuid4()

        # Deterministic locking keys: hash of source and target UUIDs
        lock_keys = [
            int(prop.source_cinq_id.int % (2**31 - 1)),
        ]
        if prop.target_cinq_id:
            lock_keys.append(int(prop.target_cinq_id.int % (2**31 - 1)))

        with acquire_identity_operation_lock(db, *lock_keys):
            if prop.operation_type == OperationTypeEnum.MERGE.value:
                # MERGE EXECUTION
                src = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == prop.source_cinq_id).first()
                tgt = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == prop.target_cinq_id).first()
                if not src or not tgt:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identities not found")
                if src.status != MasterIdentityStatusEnum.ACTIVE.value:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Source identity is no longer ACTIVE")

                # 1. Update source MasterIdentity
                src.status = MasterIdentityStatusEnum.MERGED.value
                src.merged_into_cinq_id = tgt.cinq_id
                src.updated_by = executor_email
                src.updated_at = now_dt
                src.version += 1

                # 2. Deactivate source current token
                db.query(IdentityToken).filter(
                    IdentityToken.cinq_id == src.cinq_id,
                    IdentityToken.is_current == True,
                ).update({
                    "is_current": False,
                    "effective_to": now_dt,
                    "updated_by": executor_email,
                    "updated_at": now_dt,
                }, synchronize_session=False)

                # 3. Re-point crosswalks: close source active, insert target active
                active_cws = (
                    db.query(IdentityCrosswalk)
                    .filter(
                        IdentityCrosswalk.cinq_id == src.cinq_id,
                        IdentityCrosswalk.is_active == True,
                    )
                    .all()
                )
                for cw in active_cws:
                    cw.is_active = False
                    cw.valid_to = now_dt
                    cw.updated_by = executor_email
                    cw.updated_at = now_dt

                    # Insert new active crosswalk pointing to target
                    new_cw = IdentityCrosswalk(
                        cinq_id=tgt.cinq_id,
                        source_system=cw.source_system,
                        source_identifier_hash=cw.source_identifier_hash,
                        is_active=True,
                        valid_from=now_dt,
                        valid_to=None,
                        match_score=cw.match_score,
                        match_type="MERGE_OVERRIDE",
                        source_feed_id=cw.source_feed_id,
                        source_batch_id=cw.source_batch_id,
                        created_by=executor_email,
                        updated_by=executor_email,
                    )
                    db.add(new_cw)

                # 4. Insert append-only event
                event = IdentityMergeSplitEvent(
                    proposal_id=prop.proposal_id,
                    event_type=OperationTypeEnum.MERGE.value,
                    source_cinq_id=src.cinq_id,
                    target_cinq_id=tgt.cinq_id,
                    effective_from=now_dt,
                    effective_to=None,
                    actor_uuid=actor_uuid,
                )
                db.add(event)

            elif prop.operation_type == OperationTypeEnum.SPLIT.value:
                # SPLIT EXECUTION
                src = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == prop.source_cinq_id).first()
                if not src or src.status != MasterIdentityStatusEnum.ACTIVE.value:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Source identity is not ACTIVE")

                target_cinq_id = prop.target_cinq_id
                if not target_cinq_id:
                    new_tgt = MasterIdentity(
                        status=MasterIdentityStatusEnum.ACTIVE.value,
                        created_by=executor_email,
                        updated_by=executor_email,
                    )
                    db.add(new_tgt)
                    db.flush()
                    target_cinq_id = new_tgt.cinq_id
                    prop.target_cinq_id = target_cinq_id

                # Resolve EXACT crosswalk specified by proposal coordinates
                cw_query = (
                    db.query(IdentityCrosswalk)
                    .filter(
                        IdentityCrosswalk.cinq_id == src.cinq_id,
                        IdentityCrosswalk.is_active == True,
                    )
                )
                if prop.source_system and prop.source_identifier_hash:
                    cw_query = cw_query.filter(
                        IdentityCrosswalk.source_system == prop.source_system,
                        IdentityCrosswalk.source_identifier_hash == prop.source_identifier_hash,
                    )
                matching_target_cws = cw_query.all()
                if len(matching_target_cws) == 0:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Exact active crosswalk matching requested split identifier not found under source identity",
                    )
                elif len(matching_target_cws) > 1:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Ambiguity conflict: Multiple active crosswalks match the requested coordinates under source identity",
                    )
                target_cw = matching_target_cws[0]

                target_cw.is_active = False
                target_cw.valid_to = now_dt
                target_cw.updated_by = executor_email
                target_cw.updated_at = now_dt

                new_cw = IdentityCrosswalk(
                    cinq_id=target_cinq_id,
                    source_system=target_cw.source_system,
                    source_identifier_hash=target_cw.source_identifier_hash,
                    is_active=True,
                    valid_from=now_dt,
                    valid_to=None,
                    match_score=target_cw.match_score,
                    match_type="SPLIT_OVERRIDE",
                    source_feed_id=target_cw.source_feed_id,
                    source_batch_id=target_cw.source_batch_id,
                    created_by=executor_email,
                    updated_by=executor_email,
                )
                db.add(new_cw)

                # Token semantics:
                # Source identity keeps its current tokens representing its surviving demographic anchor.
                # If splitting to an existing target identity with active tokens, verify they don't conflict.
                tgt_token = db.query(IdentityToken).filter(
                    IdentityToken.cinq_id == target_cinq_id,
                    IdentityToken.is_current == True,
                ).first()
                src_token = db.query(IdentityToken).filter(
                    IdentityToken.cinq_id == src.cinq_id,
                    IdentityToken.is_current == True,
                ).first()

                if tgt_token and src_token:
                    # If target already has distinct demographic token anchor, verify non-conflict
                    if tgt_token.ssn_hash and src_token.ssn_hash and tgt_token.ssn_hash != src_token.ssn_hash:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Target identity has conflicting demographic token anchor (conflicting SSN hash)",
                        )
                elif not tgt_token and src_token:
                    # Seed target identity token anchor from surviving record anchor
                    new_token = IdentityToken(
                        cinq_id=target_cinq_id,
                        ssn_hash=src_token.ssn_hash,
                        dob_hash=src_token.dob_hash,
                        last_name_hash=src_token.last_name_hash,
                        first_name_hash=src_token.first_name_hash,
                        gender_hash=src_token.gender_hash,
                        postal_code_hash=src_token.postal_code_hash,
                        pepper_version=src_token.pepper_version,
                        is_current=True,
                        effective_from=now_dt,
                        effective_to=None,
                        source_feed_id=target_cw.source_feed_id,
                        source_batch_id=target_cw.source_batch_id,
                        created_by=executor_email,
                        updated_by=executor_email,
                    )
                    db.add(new_token)

                event = IdentityMergeSplitEvent(
                    proposal_id=prop.proposal_id,
                    event_type=OperationTypeEnum.SPLIT.value,
                    source_cinq_id=src.cinq_id,
                    target_cinq_id=target_cinq_id,
                    effective_from=now_dt,
                    effective_to=None,
                    actor_uuid=actor_uuid,
                )
                db.add(event)

            # Update proposal state to EXECUTED
            prop.state = ProposalStateEnum.EXECUTED.value
            prop.updated_at = now_dt

            db.commit()
            db.refresh(prop)
            db.refresh(event)
            return prop, event
