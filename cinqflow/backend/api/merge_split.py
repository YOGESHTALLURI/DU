"""
API Router for Identity Merge and Split Proposals (CF-V3-E9-03)
"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    require_steward_or_engineer,
    require_steward,
    require_any_role,
    CurrentUser,
)
from backend.models.merge_split import IdentityMergeSplitProposal
from backend.schemas.merge_split import (
    MergeProposalCreateRequest,
    SplitProposalCreateRequest,
    ProposalRejectRequest,
    ProposalResponse,
    EventResponse,
)
from backend.services.merge_split_service import MergeSplitService

router = APIRouter()


@router.post("/merge", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
def propose_merge(
    request: MergeProposalCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    return MergeSplitService.create_merge_proposal(db, request, proposer_email=current_user.email)


@router.post("/split", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
def propose_split(
    request: SplitProposalCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    return MergeSplitService.create_split_proposal(db, request, proposer_email=current_user.email)


@router.get("", response_model=List[ProposalResponse])
def list_proposals(
    state: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    query = db.query(IdentityMergeSplitProposal)
    if state:
        query = query.filter(IdentityMergeSplitProposal.state == state)
    return query.order_by(IdentityMergeSplitProposal.created_at.desc()).all()


@router.get("/{proposal_id}", response_model=ProposalResponse)
def get_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    prop = db.query(IdentityMergeSplitProposal).filter(IdentityMergeSplitProposal.proposal_id == proposal_id).first()
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return prop


@router.post("/{proposal_id}/approve", response_model=ProposalResponse)
def approve_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward),
):
    return MergeSplitService.approve_proposal(db, proposal_id, approver_email=current_user.email)


@router.post("/{proposal_id}/reject", response_model=ProposalResponse)
def reject_proposal(
    proposal_id: uuid.UUID,
    request: ProposalRejectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward),
):
    return MergeSplitService.reject_proposal(db, proposal_id, rejector_email=current_user.email, reason=request.reason)


@router.post("/{proposal_id}/execute", response_model=ProposalResponse)
def execute_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward),
):
    prop, _ = MergeSplitService.execute_proposal(db, proposal_id, executor_email=current_user.email)
    return prop
