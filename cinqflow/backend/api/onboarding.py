"""
Onboarding API Endpoints — Wave 1 Slices 2 & 5

Provides endpoints for Business Analyst 5-step feed onboarding wizard:
- GET /api/v1/onboarding/feed/{feed_id} (Session state)
- PUT /api/v1/onboarding/feed/{feed_id}/step (Step transition & gating)

Wave 1 Slice 5 (Step 5: Review & Activate):
- GET /api/v1/onboarding/feed/{feed_id}/review-packet (Consolidated Review & Both-Sides Impact)
- POST /api/v1/onboarding/feed/{feed_id}/sandbox-test (End-to-End Sample Test & Evidence Pack)
- POST /api/v1/onboarding/feed/{feed_id}/submit-approval (Formal Submission for Activation Review)
- POST /api/v1/onboarding/feed/{feed_id}/approve (Governed Activation with Four-Eyes Principle)
- POST /api/v1/onboarding/feed/{feed_id}/reject (Rejection with Mandatory Reason)
"""
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    require_engineer,
    require_analyst_or_engineer,
    require_any_role,
    CurrentUser,
)
from backend.services.onboarding_service import OnboardingService
from backend.services.approval_service import ApprovalService
from backend.schemas.feed import OnboardingStepUpdateRequest, OnboardingSessionResponse
from backend.schemas.approval import (
    ReviewPacketResponse,
    SandboxTestRunResponse,
    ApprovalSubmitRequest,
    ApprovalDecisionRequest,
    ApprovalRejectRequest,
    ApprovalRequestResponse,
    FeedActivationResponse,
)

router = APIRouter()


@router.get("/feed/{feed_id}", response_model=OnboardingSessionResponse)
def get_onboarding_session(
    feed_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get or initialize onboarding session for a feed."""
    service = OnboardingService(db)
    session = service.get_or_create_session(
        feed_id, actor_id=current_user.user_id, actor_email=current_user.email
    )
    return session


@router.put("/feed/{feed_id}/step", response_model=OnboardingSessionResponse)
def update_onboarding_step(
    feed_id: UUID,
    data: OnboardingStepUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """Update current step or mark a step completed with prerequisite verification (Analyst or Engineer)."""
    service = OnboardingService(db)
    session = service.update_step(
        feed_id=feed_id,
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )
    return session


# =====================================================================
# Wave 1 Slice 5: Review & Activate (Sandbox Test, Review Packet, Approvals)
# =====================================================================

@router.get("/feed/{feed_id}/review-packet", response_model=ReviewPacketResponse)
def get_review_packet(
    feed_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Retrieve comprehensive unified review packet for a feed:
    Aggregates metadata, profiling facts, schema contract, canonical mapping,
    active data quality rules, latest sandbox test evidence, readiness checklist,
    and user governance capabilities.
    """
    service = ApprovalService(db)
    return service.get_review_packet(feed_id=feed_id, current_user=current_user)


@router.post("/feed/{feed_id}/sandbox-test", response_model=SandboxTestRunResponse)
def run_sandbox_test(
    feed_id: UUID,
    max_rows: int = 10000,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Executes in-memory deterministic sandbox pipeline on representative sample data:
    Evaluates published schema contract, published data quality rules (all 7 types),
    and published canonical mapping transforms.
    Produces reconciliation proof (In = Out + Quarantined).
    Guaranteed ZERO writes to production tables.
    """
    service = ApprovalService(db)
    return service.run_sandbox_test(
        feed_id=feed_id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        max_rows=max_rows,
    )


@router.post(
    "/feed/{feed_id}/submit-approval",
    response_model=ApprovalRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_for_approval(
    feed_id: UUID,
    data: ApprovalSubmitRequest = ApprovalSubmitRequest(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Submits feed for activation review:
    Validates that Steps 1 to 4 are complete and a successful Sandbox Test Run has been executed.
    Transitions request into PENDING_APPROVAL.
    """
    service = ApprovalService(db)
    return service.submit_for_approval(
        feed_id=feed_id,
        notes=data.notes,
        current_user=current_user,
    )


@router.post("/feed/{feed_id}/approve", response_model=FeedActivationResponse)
def approve_feed_activation(
    feed_id: UUID,
    data: ApprovalDecisionRequest = ApprovalDecisionRequest(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """
    Approves feed activation into production (ENGINEER role only):
    Enforces Four-Eyes Principle: Submitter/author CANNOT approve their own activation request.
    Permanently locks approved version bundle into FeedActivationRecord,
    transitions feed to ACTIVE, and marks OnboardingSession completed.
    """
    service = ApprovalService(db)
    return service.approve_activation(
        feed_id=feed_id,
        decision_notes=data.decision_notes,
        current_user=current_user,
    )


@router.post("/feed/{feed_id}/reject", response_model=ApprovalRequestResponse)
def reject_feed_activation(
    feed_id: UUID,
    data: ApprovalRejectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """
    Rejects feed activation request (ENGINEER role only):
    Enforces mandatory rejection reason.
    Transitions request to REJECTED and leaves feed in DRAFT status.
    """
    service = ApprovalService(db)
    return service.reject_activation(
        feed_id=feed_id,
        decision_notes=data.decision_notes,
        current_user=current_user,
    )
