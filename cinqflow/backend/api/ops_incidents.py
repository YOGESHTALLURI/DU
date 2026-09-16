"""
Wave 2 Slice 4 REST API Router — Incidents, Failure Fingerprints, Playbooks & Operational Alerts
(CF-V2-E12-04, CF-V2-E12-05)
"""
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    CurrentUser,
    get_current_user,
    require_engineer,
    require_steward_or_engineer,
)
from backend.models.incident import (
    OperationalAlert,
    AlertOccurrence,
    FailureFingerprint,
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
    PlaybookStatusEnum,
)
from backend.schemas.incident import (
    FailureFingerprintResponse,
    RecoveryPlaybookResponse,
    RecoveryPlaybookVersionResponse,
    RecoveryPlaybookCreateRequest,
    RecoveryPlaybookUpdateRequest,
    OperationalAlertResponse,
    AlertOccurrenceResponse,
    AlertAcknowledgeRequest,
    AlertResolveRequest,
    AlertReopenRequest,
    PlaybookActionProposalResponse,
    PlaybookExecuteResponse,
)
from backend.schemas.ops_action import OpsActionSubmitRequest
from backend.services.alert_service import AlertService
from backend.services.playbook_service import PlaybookService
from backend.services.ops_action_service import OpsActionService

router = APIRouter()


def _format_occurrence_response(occ: AlertOccurrence) -> AlertOccurrenceResponse:
    return AlertOccurrenceResponse(
        id=occ.id,
        alert_id=occ.alert_id,
        batch_id=occ.batch_id,
        stage=occ.stage,
        error_context=occ.error_context or {},
        occurred_at=occ.occurred_at,
    )


def _format_version_response(ver: RecoveryPlaybookVersion) -> RecoveryPlaybookVersionResponse:
    return RecoveryPlaybookVersionResponse(
        id=ver.id,
        playbook_id=ver.playbook_id,
        version_number=ver.version_number,
        explanation_template=ver.explanation_template,
        suggested_action_type=ver.suggested_action_type,
        action_parameters_template=ver.action_parameters_template or {},
        manual_steps_markdown=ver.manual_steps_markdown or "",
        prerequisites=ver.prerequisites or [],
        risk_assessment=ver.risk_assessment or "",
        approved_by=ver.approved_by,
        approved_at=ver.approved_at,
        status=ver.status,
        created_at=ver.created_at,
    )


def _format_playbook_response(pb: RecoveryPlaybook) -> RecoveryPlaybookResponse:
    curr_ver = None
    if pb.current_version:
        curr_ver = _format_version_response(pb.current_version)
    elif pb.versions:
        # fallback to newest version
        curr_ver = _format_version_response(pb.versions[0])

    return RecoveryPlaybookResponse(
        id=pb.id,
        title=pb.title,
        category=pb.category,
        playbook_code=pb.playbook_code,
        current_version_id=pb.current_version_id,
        status=pb.status,
        current_version=curr_ver,
        created_at=pb.created_at,
        updated_at=pb.updated_at,
    )


def _format_fingerprint_response(fp: FailureFingerprint) -> FailureFingerprintResponse:
    return FailureFingerprintResponse(
        id=fp.id,
        category=fp.category,
        failure_stage=fp.failure_stage,
        root_cause_pattern=fp.root_cause_pattern,
        canonical_signature=fp.canonical_signature,
        fingerprint_hash=fp.fingerprint_hash,
        total_occurrences=fp.total_occurrences,
        first_seen_at=fp.first_seen_at,
        last_seen_at=fp.last_seen_at,
        created_at=fp.created_at,
    )


def _format_alert_response(alert: OperationalAlert, db: Optional[Session] = None) -> OperationalAlertResponse:
    feed_name = alert.feed.name if (alert.feed and hasattr(alert.feed, "name")) else None
    fp_resp = _format_fingerprint_response(alert.fingerprint) if alert.fingerprint else None
    pb_resp = _format_version_response(alert.recommended_playbook_version) if alert.recommended_playbook_version else None
    occurrences_resp = [_format_occurrence_response(o) for o in (alert.occurrences or [])]

    proposal_resp = None
    if db and alert.recommended_playbook_version:
        try:
            prop = PlaybookService.evaluate_playbook_preconditions(
                db=db,
                playbook_version=alert.recommended_playbook_version,
                alert=alert,
            )
            proposal_resp = PlaybookActionProposalResponse(
                action_type=prop.get("action_type"),
                target_type=prop.get("target_type"),
                target_id=prop.get("target_id"),
                parameters=prop.get("parameters") or {},
                is_executable=prop.get("is_executable", False),
                blocking_reason=prop.get("blocking_reason"),
                risk_level=prop.get("risk_level"),
            )
        except Exception:
            pass

    return OperationalAlertResponse(
        id=alert.id,
        feed_id=alert.feed_id,
        feed_name=feed_name,
        batch_id=alert.batch_id,
        failure_fingerprint_id=alert.failure_fingerprint_id,
        recommended_playbook_version_id=alert.recommended_playbook_version_id,
        title=alert.title,
        description=alert.description,
        severity=alert.severity,
        status=alert.status,
        occurrence_count=alert.occurrence_count,
        first_occurred_at=alert.first_occurred_at,
        last_occurred_at=alert.last_occurred_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        resolved_at=alert.resolved_at,
        resolved_by=alert.resolved_by,
        resolution_notes=alert.resolution_notes,
        fingerprint=fp_resp,
        recommended_playbook_version=pb_resp,
        occurrences=occurrences_resp,
        action_proposal=proposal_resp,
    )


# =====================================================================
# 1. ALERTS ENDPOINTS
# =====================================================================

@router.get("/alerts", response_model=List[OperationalAlertResponse])
def list_operational_alerts(
    status: Optional[AlertStatusEnum] = Query(None),
    severity: Optional[AlertSeverityEnum] = Query(None),
    feed_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lists operational alerts with preloaded relationships and filters."""
    alerts = AlertService.list_alerts(
        db=db,
        status_filter=status,
        severity_filter=severity,
        feed_id=feed_id,
        limit=limit,
        offset=offset,
    )
    return [_format_alert_response(a, db) for a in alerts]


@router.get("/alerts/{id}", response_model=OperationalAlertResponse)
def get_operational_alert(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves full details of a specific operational alert including occurrence timeline."""
    alert = AlertService.get_alert_detail(db=db, alert_id=id)
    return _format_alert_response(alert, db)


@router.post("/alerts/{id}/acknowledge", response_model=OperationalAlertResponse)
def acknowledge_operational_alert(
    id: uuid.UUID,
    data: Optional[AlertAcknowledgeRequest] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """Acknowledges an active operational alert."""
    alert = AlertService.acknowledge_alert(
        db=db,
        alert_id=id,
        user_id=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_alert_response(AlertService.get_alert_detail(db=db, alert_id=alert.id), db)


@router.post("/alerts/{id}/start-recovery", response_model=OperationalAlertResponse)
def start_alert_recovery(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """Transitions an active alert to RECOVERY_IN_PROGRESS."""
    alert = AlertService.start_recovery(
        db=db,
        alert_id=id,
        user_id=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_alert_response(AlertService.get_alert_detail(db=db, alert_id=alert.id), db)


@router.get("/alerts/{id}/action-proposal", response_model=PlaybookActionProposalResponse)
def get_alert_action_proposal(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Evaluates safety preconditions against live system state and returns a concrete
    governed-action proposal derived from the alert's recommended playbook.
    (Wave 2 Slice 4 Blockers 1, 2, 6)
    """
    alert = AlertService.get_alert_detail(db=db, alert_id=id)
    if not alert.recommended_playbook_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recommended recovery playbook attached to this alert.",
        )

    prop = PlaybookService.evaluate_playbook_preconditions(
        db=db,
        playbook_version=alert.recommended_playbook_version,
        alert=alert,
    )
    return PlaybookActionProposalResponse(
        action_type=prop.get("action_type"),
        target_type=prop.get("target_type"),
        target_id=prop.get("target_id"),
        parameters=prop.get("parameters") or {},
        is_executable=prop.get("is_executable", False),
        blocking_reason=prop.get("blocking_reason"),
        risk_level=prop.get("risk_level"),
    )


@router.post("/alerts/{id}/execute-playbook", response_model=PlaybookExecuteResponse)
def execute_alert_playbook(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """
    Executes the recommended playbook action for an operational alert:
    1. Evaluates safety preconditions against live system state.
    2. Rejects with deterministic 400 if preconditions are unmet.
    3. Transitions alert to RECOVERY_IN_PROGRESS.
    4. Routes through Slice 3 Governed Action Surface.
    5. On execution completion, auto-resolves the alert.
    (Wave 2 Slice 4 Blockers 1, 2, 5, 6)
    """
    alert = AlertService.get_alert_detail(db=db, alert_id=id)
    if not alert.recommended_playbook_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alert does not have a recommended recovery playbook.",
        )

    prop = PlaybookService.evaluate_playbook_preconditions(
        db=db,
        playbook_version=alert.recommended_playbook_version,
        alert=alert,
    )

    if not prop["is_executable"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Precondition failed: {prop['blocking_reason']}",
        )

    # Transition alert to RECOVERY_IN_PROGRESS
    AlertService.start_recovery(db=db, alert_id=alert.id, user_id=current_user.email or current_user.user_id)

    # Submit action through governed action surface
    action_service = OpsActionService(db)
    req_data = OpsActionSubmitRequest(
        action_type=prop["action_type"],
        target_type=prop["target_type"],
        target_id=str(prop["target_id"]),
        parameters=prop["parameters"],
        reason=f"Playbook execution for alert '{alert.title}'",
    )

    from backend.models.user import User
    acting_user = None
    try:
        user_uuid = uuid.UUID(str(current_user.user_id))
        acting_user = db.query(User).filter(User.id == user_uuid).first()
    except (ValueError, TypeError):
        pass
    if not acting_user:
        acting_user = db.query(User).filter(User.auth_provider_id == str(current_user.user_id)).first()
    acting_user = acting_user or current_user

    try:
        action = action_service.submit_action(request_data=req_data, current_user=acting_user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Recovery action execution failed: {str(e)}",
        )

    msg = (
        f"Standard recovery action executed successfully and alert resolved."
        if action.status.value == "COMPLETED"
        else f"High-risk action queued for dual-control approval."
    )

    return PlaybookExecuteResponse(
        alert_id=alert.id,
        action_id=action.id,
        action_type=action.action_type,
        target_type=action.target_type,
        target_id=str(action.target_id),
        risk_level=action.risk_level.value,
        status=action.status.value,
        message=msg,
    )


@router.post("/alerts/{id}/resolve", response_model=OperationalAlertResponse)
def resolve_operational_alert(
    id: uuid.UUID,
    data: AlertResolveRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """Resolves an operational alert with explanation notes."""
    alert = AlertService.resolve_alert(
        db=db,
        alert_id=id,
        resolution_notes=data.resolution_notes,
        user_id=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_alert_response(AlertService.get_alert_detail(db=db, alert_id=alert.id), db)


@router.post("/alerts/{id}/reopen", response_model=OperationalAlertResponse)
def reopen_operational_alert(
    id: uuid.UUID,
    data: AlertReopenRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """Reopens a resolved operational alert."""
    alert = AlertService.reopen_alert(
        db=db,
        alert_id=id,
        reason=data.reason,
        user_id=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_alert_response(AlertService.get_alert_detail(db=db, alert_id=alert.id), db)


# =====================================================================
# 2. FINGERPRINTS ENDPOINTS
# =====================================================================

@router.get("/fingerprints", response_model=List[FailureFingerprintResponse])
def list_failure_fingerprints(
    category: Optional[FailureCategoryEnum] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lists deterministic failure fingerprints."""
    q = db.query(FailureFingerprint).order_by(FailureFingerprint.total_occurrences.desc())
    if category:
        q = q.filter(FailureFingerprint.category == category)
    items = q.offset(offset).limit(limit).all()
    return [_format_fingerprint_response(f) for f in items]


@router.get("/fingerprints/{id}", response_model=FailureFingerprintResponse)
def get_failure_fingerprint(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves a specific failure fingerprint."""
    fp = db.query(FailureFingerprint).filter(FailureFingerprint.id == id).first()
    if not fp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fingerprint not found")
    return _format_fingerprint_response(fp)


# =====================================================================
# 3. PLAYBOOKS ENDPOINTS
# =====================================================================

@router.get("/playbooks", response_model=List[RecoveryPlaybookResponse])
def list_recovery_playbooks(
    category: Optional[FailureCategoryEnum] = Query(None),
    status: Optional[PlaybookStatusEnum] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lists recovery playbooks."""
    q = db.query(RecoveryPlaybook).order_by(RecoveryPlaybook.title.asc())
    if category:
        q = q.filter(RecoveryPlaybook.category == category)
    if status:
        q = q.filter(RecoveryPlaybook.status == status)
    playbooks = q.all()
    return [_format_playbook_response(p) for p in playbooks]


@router.get("/playbooks/{id}", response_model=RecoveryPlaybookResponse)
def get_recovery_playbook(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves a recovery playbook and its active version."""
    pb = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.id == id).first()
    if not pb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")
    return _format_playbook_response(pb)


@router.post("/playbooks", response_model=RecoveryPlaybookResponse, status_code=status.HTTP_201_CREATED)
def create_recovery_playbook(
    data: RecoveryPlaybookCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Creates a new recovery playbook (starts in DRAFT status)."""
    pb = PlaybookService.create_playbook(
        db=db,
        title=data.title,
        category=data.category,
        playbook_code=data.playbook_code,
        explanation_template=data.explanation_template,
        suggested_action_type=data.suggested_action_type,
        action_parameters_template=data.action_parameters_template,
        manual_steps_markdown=data.manual_steps_markdown,
        prerequisites=data.prerequisites,
        risk_assessment=data.risk_assessment,
        user_id=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_playbook_response(pb)


@router.put("/playbooks/{id}", response_model=RecoveryPlaybookVersionResponse)
def update_recovery_playbook(
    id: uuid.UUID,
    data: RecoveryPlaybookUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Creates a new version under the playbook (immutable history)."""
    new_ver = PlaybookService.update_playbook(
        db=db,
        playbook_id=id,
        explanation_template=data.explanation_template,
        suggested_action_type=data.suggested_action_type,
        action_parameters_template=data.action_parameters_template,
        manual_steps_markdown=data.manual_steps_markdown,
        prerequisites=data.prerequisites,
        risk_assessment=data.risk_assessment,
        user_id=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_version_response(new_ver)


@router.post("/playbooks/{id}/approve", response_model=RecoveryPlaybookResponse)
def approve_recovery_playbook(
    id: uuid.UUID,
    version_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """Approves a playbook version and sets it as the active version."""
    pb = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.id == id).first()
    if not pb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")

    target_ver_id = version_id or pb.current_version_id
    if not target_ver_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No version to approve")

    updated_pb = PlaybookService.approve_playbook_version(
        db=db,
        version_id=target_ver_id,
        approved_by=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_playbook_response(updated_pb)


@router.post("/playbooks/{id}/deprecate", response_model=RecoveryPlaybookResponse)
def deprecate_recovery_playbook(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Deprecates a recovery playbook."""
    pb = PlaybookService.deprecate_playbook(
        db=db,
        playbook_id=id,
        user_id=current_user.email or current_user.user_id,
    )
    db.commit()
    return _format_playbook_response(pb)


@router.post("/playbooks/seed-defaults", status_code=status.HTTP_200_OK)
def seed_default_playbooks_endpoint(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Seeds standard operational recovery playbooks."""
    PlaybookService.seed_default_playbooks(db=db, user_id=current_user.email or current_user.user_id)
    db.commit()
    return {"status": "ok", "message": "Default recovery playbooks seeded successfully"}
