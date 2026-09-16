"""
Wave 2 Slice 3 Governed Action Surface Engine (CF-V2-E12-03)

Handles:
- Centralized operational action execution & routing
- Role-based authorization & permission validation
- Dual-control (four-eyes) governance: requester != approver
- Action risk classification (STANDARD vs HIGH_RISK)
- Concurrency locks & idempotency protection
- Zero-PHI sanitization across action rationale and audit entries
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.user import User, RoleEnum
from backend.models.ops_action import (
    OperationalActionRequest,
    ActionTypeEnum,
    ActionRiskLevelEnum,
    ActionStatusEnum,
)
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.input_registry import QuarantineRecord, QuarantineStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.services.ops_recovery_service import OpsRecoveryService
from backend.engine.arrival_engine import ArrivalEngine
from backend.schemas.ops_action import (
    OpsActionSubmitRequest,
    OpsActionResponse,
    OpsActionListResponse,
)

# Authoritative governed action target mapping (Wave 2 Slice 4 Blocker 1)
ACTION_TARGET_MAPPING: Dict[ActionTypeEnum, List[str]] = {
    ActionTypeEnum.RESTART_BATCH: ["BATCH"],
    ActionTypeEnum.RETRIGGER_BATCH: ["BATCH"],
    ActionTypeEnum.REPROCESS_QUARANTINE: ["QUARANTINE_RECORD"],
    ActionTypeEnum.BULK_REPROCESS_QUARANTINE: ["QUARANTINE_RECORD"],
    ActionTypeEnum.DISCARD_QUARANTINE: ["QUARANTINE_RECORD"],
    ActionTypeEnum.PAUSE_SCHEDULE: ["FEED_SCHEDULE"],
    ActionTypeEnum.RESUME_SCHEDULE: ["FEED_SCHEDULE"],
}


class OpsActionService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.recovery = OpsRecoveryService(db)

    @classmethod
    def _user_has_role(cls, user: Any, role_name: Any) -> bool:
        """Check if user has a specific role, supporting both CurrentUser and User models."""
        r_name = role_name.value if hasattr(role_name, "value") else str(role_name)
        if hasattr(user, "roles") and isinstance(user.roles, list):
            return r_name in user.roles or any(
                (r.value if hasattr(r, "value") else str(r)) == r_name for r in user.roles
            )
        if hasattr(user, "user_roles"):
            return any(
                (ur.role.name.value if hasattr(ur.role.name, "value") else str(ur.role.name)) == r_name
                for ur in user.user_roles if hasattr(ur, "role") and ur.role
            )
        return False

    @classmethod
    def _verify_permissions(cls, user: User, action_type: ActionTypeEnum) -> None:
        """
        Verify user has appropriate RBAC permissions for the requested action.
        - ENGINEER can perform all operational and batch recovery actions.
        - DATA_STEWARD can perform and approve quarantine operations.
        - READ_ONLY and ANALYST are forbidden from mutations.
        """
        is_engineer = cls._user_has_role(user, RoleEnum.ENGINEER)
        is_steward = cls._user_has_role(user, RoleEnum.DATA_STEWARD)

        if action_type in [
            ActionTypeEnum.RESTART_BATCH,
            ActionTypeEnum.RETRIGGER_BATCH,
            ActionTypeEnum.PAUSE_SCHEDULE,
            ActionTypeEnum.RESUME_SCHEDULE,
        ]:
            if not is_engineer:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Only ENGINEER role is authorized to perform {action_type.value}",
                )

        elif action_type in [
            ActionTypeEnum.REPROCESS_QUARANTINE,
            ActionTypeEnum.BULK_REPROCESS_QUARANTINE,
            ActionTypeEnum.DISCARD_QUARANTINE,
        ]:
            if not (is_engineer or is_steward):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Only ENGINEER or DATA_STEWARD role is authorized to perform {action_type.value}",
                )

    @classmethod
    def classify_risk(cls, action_type: ActionTypeEnum, parameters: Dict[str, Any]) -> ActionRiskLevelEnum:
        """
        Classifies risk tier according to approved governance matrix:
        - HIGH_RISK:
            * RETRIGGER_BATCH (re-running completed batches)
            * BULK_REPROCESS_QUARANTINE
            * DISCARD_QUARANTINE
            * REPROCESS_QUARANTINE when row count > 50
        - STANDARD:
            * RESTART_BATCH on failed batches
            * PAUSE_SCHEDULE / RESUME_SCHEDULE
            * REPROCESS_QUARANTINE <= 50 records
        """
        if action_type in [ActionTypeEnum.RETRIGGER_BATCH, ActionTypeEnum.BULK_REPROCESS_QUARANTINE, ActionTypeEnum.DISCARD_QUARANTINE]:
            return ActionRiskLevelEnum.HIGH_RISK

        if action_type == ActionTypeEnum.REPROCESS_QUARANTINE:
            rec_ids = parameters.get("record_ids", [])
            if len(rec_ids) > 50:
                return ActionRiskLevelEnum.HIGH_RISK

        return ActionRiskLevelEnum.STANDARD

    @classmethod
    def validate_action_target_mapping(cls, action_type: Any, target_type: str) -> None:
        """Enforces authoritative mapping between action type and target type."""
        # Normalize to ActionTypeEnum if string is passed
        act_enum = action_type
        if isinstance(action_type, str):
            try:
                act_enum = ActionTypeEnum(action_type)
            except ValueError:
                act_enum = action_type
        allowed = ACTION_TARGET_MAPPING.get(act_enum, [])
        if target_type not in allowed:
            act_name = act_enum.value if hasattr(act_enum, "value") else str(act_enum)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target_type '{target_type}' for action_type '{act_name}'. Allowed target types: {allowed}",
            )

    def validate_safety_preconditions(
        self,
        action_type: Any,
        target_type: str,
        target_id: str,
        parameters: Dict[str, Any],
    ) -> None:
        """
        Evaluates safety preconditions against the real database target before action creation.
        Prevents blind execution and halts invalid-state transitions with deterministic 400 errors.
        """
        if isinstance(action_type, str):
            try:
                action_type = ActionTypeEnum(action_type)
            except ValueError:
                pass

        # Validate UUID format
        try:
            target_uuid = uuid.UUID(target_id)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target_id '{target_id}'; must be a valid UUID string",
            )

        if action_type == ActionTypeEnum.RESTART_BATCH:
            batch = self.db.query(Batch).filter(Batch.id == target_uuid).first()
            if batch and batch.status not in [BatchStatusEnum.FAILED, BatchStatusEnum.FAILED_RECONCILIATION]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Precondition failed: Batch {target_id} is in status '{batch.status.value}'; RESTART_BATCH requires FAILED or FAILED_RECONCILIATION",
                )

        elif action_type == ActionTypeEnum.RETRIGGER_BATCH:
            batch = self.db.query(Batch).filter(Batch.id == target_uuid).first()
            if batch and batch.status != BatchStatusEnum.SUCCESS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Precondition failed: Batch {target_id} is in status '{batch.status.value}'; RETRIGGER_BATCH requires SUCCESS",
                )

        elif action_type == ActionTypeEnum.PAUSE_SCHEDULE:
            sched = self.db.query(FeedSchedule).filter(
                (FeedSchedule.id == target_uuid) | (FeedSchedule.feed_id == target_uuid)
            ).first()
            if sched and sched.status != ScheduleStatusEnum.ACTIVE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Precondition failed: Feed schedule for feed {sched.feed_id} is already PAUSED; PAUSE_SCHEDULE requires ACTIVE",
                )

        elif action_type == ActionTypeEnum.RESUME_SCHEDULE:
            sched = self.db.query(FeedSchedule).filter(
                (FeedSchedule.id == target_uuid) | (FeedSchedule.feed_id == target_uuid)
            ).first()
            if sched and sched.status != ScheduleStatusEnum.PAUSED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Precondition failed: Feed schedule for feed {sched.feed_id} is already ACTIVE; RESUME_SCHEDULE requires PAUSED",
                )

        elif action_type in [ActionTypeEnum.REPROCESS_QUARANTINE, ActionTypeEnum.BULK_REPROCESS_QUARANTINE, ActionTypeEnum.DISCARD_QUARANTINE]:
            record_id_strs = parameters.get("record_ids", [])
            if not record_id_strs:
                record_id_strs = [target_id]
            else:
                # Ensure target_id is present in record_ids
                if target_id not in record_id_strs:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Precondition failed: target_id '{target_id}' must match or be included in parameters.record_ids",
                    )
            try:
                rec_uuids = [uuid.UUID(r) for r in record_id_strs]
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid record_ids parameter; all items must be valid UUIDs",
                )
            records = self.db.query(QuarantineRecord).filter(QuarantineRecord.id.in_(rec_uuids)).all()
            if not records:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Precondition failed: Target quarantine record {target_id} not found in database",
                )
            if len(records) != len(set(rec_uuids)):
                missing = len(set(rec_uuids)) - len(records)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Precondition failed: {missing} quarantine record(s) not found in database",
                )
            invalid_records = [r for r in records if r.status != QuarantineStatusEnum.QUARANTINED]
            if invalid_records:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Precondition failed: {len(invalid_records)} quarantine record(s) are already resolved or not in QUARANTINED status",
                )

    def submit_action(
        self,
        request_data: OpsActionSubmitRequest,
        current_user: User,
    ) -> OperationalActionRequest:
        """
        Submits an operational action:
        - Verifies authorization.
        - Checks idempotency cache.
        - Validates authoritative target mapping.
        - Validates safety preconditions.
        - Classifies risk level.
        - Executes standard actions immediately with audit.
        - Queues HIGH_RISK actions for Four-Eyes approval.
        """
        # 1. Authorization
        self._verify_permissions(current_user, request_data.action_type)

        # 2. Idempotency Check (return cached result immediately on rapid replay)
        if request_data.idempotency_key:
            existing = (
                self.db.query(OperationalActionRequest)
                .filter(OperationalActionRequest.idempotency_key == request_data.idempotency_key)
                .first()
            )
            if existing:
                # Verify payload match to prevent silent re-use on conflicting action
                is_same = (
                    existing.action_type == request_data.action_type
                    and existing.target_type == request_data.target_type
                    and existing.target_id == str(request_data.target_id)
                )
                if not is_same:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key conflict: identical key reused with materially different request payload",
                    )
                # Return existing action (idempotent replay)
                return existing

        # 3. Authoritative Target Mapping Validation
        self.validate_action_target_mapping(request_data.action_type, request_data.target_type)

        # 4. Safety Preconditions Validation
        self.validate_safety_preconditions(
            request_data.action_type,
            request_data.target_type,
            str(request_data.target_id),
            request_data.parameters or {},
        )

        # Auto-promote REPROCESS_QUARANTINE with > 50 records to BULK_REPROCESS_QUARANTINE
        if request_data.action_type == ActionTypeEnum.REPROCESS_QUARANTINE:
            rec_ids = request_data.parameters.get("record_ids", [])
            if len(rec_ids) > 50:
                request_data.action_type = ActionTypeEnum.BULK_REPROCESS_QUARANTINE

        # 3. Classify Risk
        risk_level = self.classify_risk(request_data.action_type, request_data.parameters)

        # 4. Sanitize reason and notes
        sanitized_reason = ArrivalEngine.sanitize_operational_error(request_data.reason)

        # 5. Create action request record
        action_req = OperationalActionRequest(
            id=uuid.uuid4(),
            action_type=request_data.action_type,
            target_type=request_data.target_type,
            target_id=str(request_data.target_id),
            parameters=request_data.parameters,
            reason=sanitized_reason,
            idempotency_key=request_data.idempotency_key,
            risk_level=risk_level,
            status=ActionStatusEnum.PENDING_APPROVAL if risk_level == ActionRiskLevelEnum.HIGH_RISK else ActionStatusEnum.EXECUTING,
            requested_by=str(current_user.user_id),
            requested_by_email=current_user.email,
            requested_at=datetime.now(timezone.utc),
            created_by=str(current_user.user_id),
            updated_by=str(current_user.user_id),
        )
        self.db.add(action_req)
        self.db.flush()

        # 6. Execution Branch
        if risk_level == ActionRiskLevelEnum.STANDARD:
            # Immediate Execution
            try:
                exec_result = self._execute_underlying_action(action_req, current_user)
                action_req.status = ActionStatusEnum.COMPLETED
                action_req.execution_result = exec_result
                action_req.reviewed_by = str(current_user.user_id)
                action_req.reviewed_by_email = current_user.email
                action_req.reviewed_at = datetime.now(timezone.utc)
                action_req.decision_notes = "Auto-approved standard action"

                # Auto-resolve alert if alert_id is present in parameters and execution succeeded
                if action_req.parameters and "alert_id" in action_req.parameters:
                    try:
                        from backend.services.alert_service import AlertService
                        AlertService.resolve_alert(
                            db=self.db,
                            alert_id=uuid.UUID(str(action_req.parameters["alert_id"])),
                            resolution_notes=f"Resolved automatically by successful recovery action {action_req.id} ({action_req.action_type.value})",
                            user_id=str(current_user.user_id),
                        )
                    except Exception:
                        pass
            except Exception as e:
                action_req.status = ActionStatusEnum.FAILED
                action_req.error_message = ArrivalEngine.sanitize_operational_error(str(e))
                self.db.commit()
                raise e

            self.audit.emit(
                action=AuditActionEnum.OPS_ACTION_EXECUTED,
                actor_id=str(current_user.user_id),
                actor_email=current_user.email,
                object_type="operational_action_requests",
                object_id=str(action_req.id),
                after_state={
                    "action_type": action_req.action_type.value,
                    "target_id": action_req.target_id,
                    "status": action_req.status.value,
                },
                description=f"Executed standard action {action_req.action_type.value} on {action_req.target_id}",
            )
            self.db.commit()
        else:
            # High-Risk Queued for Review
            self.audit.emit(
                action=AuditActionEnum.OPS_ACTION_REQUESTED,
                actor_id=str(current_user.user_id),
                actor_email=current_user.email,
                object_type="operational_action_requests",
                object_id=str(action_req.id),
                after_state={
                    "action_type": action_req.action_type.value,
                    "target_id": action_req.target_id,
                    "risk_level": action_req.risk_level.value,
                    "status": "PENDING_APPROVAL",
                },
                description=f"Submitted high-risk action {action_req.action_type.value} on {action_req.target_id} for dual-control approval",
            )
            self.db.commit()

        return action_req

    def approve_action(
        self,
        action_id: uuid.UUID,
        decision_notes: Optional[str],
        current_user: User,
    ) -> OperationalActionRequest:
        """
        Approves a high-risk operational action:
        - Acquires row lock.
        - Enforces Four-Eyes: requester_id != approver_id.
        - Executes the underlying operation.
        - Emits ops.action_approved and ops.action_executed.
        """
        # Row lock
        action = (
            self.db.query(OperationalActionRequest)
            .filter(OperationalActionRequest.id == action_id)
            .with_for_update()
            .first()
        )
        if not action:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operational action request {action_id} not found",
            )

        if action.status != ActionStatusEnum.PENDING_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Action request {action_id} is in status '{action.status.value}'; only PENDING_APPROVAL can be approved",
            )

        # STRICT FOUR-EYES VERIFICATION
        if str(current_user.user_id) == action.requested_by:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Four-Eyes dual control violation: Requester cannot approve their own action",
            )

        # Permission check: Both ENGINEER and DATA_STEWARD can approve high-risk actions
        is_engineer = self._user_has_role(current_user, RoleEnum.ENGINEER)
        is_steward = self._user_has_role(current_user, RoleEnum.DATA_STEWARD)
        if not (is_engineer or is_steward):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only ENGINEER or DATA_STEWARD can approve operational actions",
            )

        action.status = ActionStatusEnum.EXECUTING
        action.reviewed_by = str(current_user.user_id)
        action.reviewed_by_email = current_user.email
        action.reviewed_at = datetime.now(timezone.utc)
        action.decision_notes = ArrivalEngine.sanitize_operational_error(decision_notes)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.OPS_ACTION_APPROVED,
            actor_id=str(current_user.user_id),
            actor_email=current_user.email,
            object_type="operational_action_requests",
            object_id=str(action.id),
            after_state={"status": "APPROVED", "reviewed_by": action.reviewed_by},
            description=f"Action {action.id} ({action.action_type.value}) approved by {current_user.email or current_user.user_id}",
        )

        try:
            exec_result = self._execute_underlying_action(action, current_user)
            action.status = ActionStatusEnum.COMPLETED
            action.execution_result = exec_result

            # Auto-resolve alert if alert_id is present in parameters and execution succeeded
            if action.parameters and "alert_id" in action.parameters:
                try:
                    from backend.services.alert_service import AlertService
                    AlertService.resolve_alert(
                        db=self.db,
                        alert_id=uuid.UUID(str(action.parameters["alert_id"])),
                        resolution_notes=f"Resolved automatically by approved recovery action {action.id} ({action.action_type.value})",
                        user_id=str(current_user.user_id),
                    )
                except Exception:
                    pass
        except Exception as e:
            action.status = ActionStatusEnum.FAILED
            action.error_message = ArrivalEngine.sanitize_operational_error(str(e))
            self.db.commit()
            raise e

        self.audit.emit(
            action=AuditActionEnum.OPS_ACTION_EXECUTED,
            actor_id=str(current_user.user_id),
            actor_email=current_user.email,
            object_type="operational_action_requests",
            object_id=str(action.id),
            after_state={"status": "COMPLETED", "execution_result": action.execution_result},
            description=f"Executed approved action {action.action_type.value} on {action.target_id}",
        )
        self.db.commit()
        return action

    def reject_action(
        self,
        action_id: uuid.UUID,
        decision_notes: Optional[str],
        current_user: User,
    ) -> OperationalActionRequest:
        """
        Rejects a pending operational action.
        """
        action = (
            self.db.query(OperationalActionRequest)
            .filter(OperationalActionRequest.id == action_id)
            .with_for_update()
            .first()
        )
        if not action:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operational action request {action_id} not found",
            )

        if action.status != ActionStatusEnum.PENDING_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Action request {action_id} is in status '{action.status.value}'; only PENDING_APPROVAL can be rejected",
            )

        is_engineer = self._user_has_role(current_user, RoleEnum.ENGINEER)
        is_steward = self._user_has_role(current_user, RoleEnum.DATA_STEWARD)
        if not (is_engineer or is_steward):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only ENGINEER or DATA_STEWARD can reject operational actions",
            )

        action.status = ActionStatusEnum.REJECTED
        action.reviewed_by = str(current_user.user_id)
        action.reviewed_by_email = current_user.email
        action.reviewed_at = datetime.now(timezone.utc)
        action.decision_notes = ArrivalEngine.sanitize_operational_error(decision_notes)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.OPS_ACTION_REJECTED,
            actor_id=str(current_user.user_id),
            actor_email=current_user.email,
            object_type="operational_action_requests",
            object_id=str(action.id),
            after_state={"status": "REJECTED", "decision_notes": action.decision_notes},
            description=f"Action {action.id} ({action.action_type.value}) rejected by {current_user.email or current_user.user_id}",
        )
        self.db.commit()
        return action

    def _execute_underlying_action(
        self,
        action: OperationalActionRequest,
        current_user: User,
    ) -> Dict[str, Any]:
        """Dispatches operational action execution to the respective recovery handler."""
        actor_id = str(current_user.user_id)
        actor_email = current_user.email

        if action.action_type == ActionTypeEnum.RESTART_BATCH:
            batch_uuid = uuid.UUID(action.target_id)
            res_batch = self.recovery.restart_failed_batch(
                batch_id=batch_uuid,
                actor_id=actor_id,
                actor_email=actor_email,
                reason=action.reason,
            )
            if res_batch.status != BatchStatusEnum.SUCCESS:
                raise RuntimeError(
                    f"Underlying batch restart failed with terminal status '{res_batch.status.value}': {res_batch.error_message or 'Pipeline execution failed'}"
                )
            return {
                "batch_id": str(res_batch.id),
                "batch_status": res_batch.status.value,
                "restart_count": res_batch.restart_count,
            }

        elif action.action_type == ActionTypeEnum.RETRIGGER_BATCH:
            batch_uuid = uuid.UUID(action.target_id)
            new_batch = self.recovery.retrigger_successful_batch(
                batch_id=batch_uuid,
                actor_id=actor_id,
                actor_email=actor_email,
                reason=action.reason,
            )
            if new_batch.status != BatchStatusEnum.SUCCESS:
                raise RuntimeError(
                    f"Underlying batch retrigger failed with terminal status '{new_batch.status.value}': {new_batch.error_message or 'Pipeline execution failed'}"
                )
            return {
                "new_batch_id": str(new_batch.id),
                "original_batch_id": str(batch_uuid),
                "batch_status": new_batch.status.value,
            }

        elif action.action_type in [ActionTypeEnum.REPROCESS_QUARANTINE, ActionTypeEnum.BULK_REPROCESS_QUARANTINE]:
            record_ids = [uuid.UUID(rid) for rid in action.parameters.get("record_ids", [])]
            if not record_ids and action.target_type == "QUARANTINE_RECORD":
                record_ids = [uuid.UUID(action.target_id)]
            q_res = self.recovery.reprocess_quarantine_records(
                record_ids=record_ids,
                actor_id=actor_id,
                actor_email=actor_email,
                reason=action.reason,
            )
            if q_res.get("reprocessed_count", 0) == 0 and q_res.get("still_quarantined_count", 0) > 0:
                raise RuntimeError(
                    f"Quarantine reprocessing failed: all {q_res.get('still_quarantined_count')} record(s) failed revalidation and remain quarantined"
                )
            return q_res

        elif action.action_type == ActionTypeEnum.DISCARD_QUARANTINE:
            record_ids = [uuid.UUID(rid) for rid in action.parameters.get("record_ids", [])]
            if not record_ids and action.target_type == "QUARANTINE_RECORD":
                record_ids = [uuid.UUID(action.target_id)]
            return self.recovery.discard_quarantine_records(
                record_ids=record_ids,
                actor_id=actor_id,
                actor_email=actor_email,
                reason=action.reason,
            )

        elif action.action_type == ActionTypeEnum.PAUSE_SCHEDULE:
            target_uuid = uuid.UUID(action.target_id)
            sched = self.db.query(FeedSchedule).filter(
                (FeedSchedule.id == target_uuid) | (FeedSchedule.feed_id == target_uuid)
            ).first()
            if not sched:
                raise HTTPException(status_code=404, detail=f"Feed schedule {action.target_id} not found")
            if sched.status == ScheduleStatusEnum.PAUSED:
                raise HTTPException(status_code=400, detail=f"Feed schedule for feed {sched.feed_id} is already PAUSED")
            from backend.services.scheduling_service import SchedulingService
            from backend.core.security import CurrentUser
            sched_service = SchedulingService(self.db)
            user_obj = CurrentUser(
                user_id=actor_id,
                email=actor_email or "system@cinqflow.local",
                roles=["ENGINEER"],
                auth_provider="mock",
            )
            sched_service.pause_schedule(sched.feed_id, user_obj)
            return {"feed_id": str(sched.feed_id), "schedule_id": str(sched.id), "schedule_status": "PAUSED"}

        elif action.action_type == ActionTypeEnum.RESUME_SCHEDULE:
            target_uuid = uuid.UUID(action.target_id)
            sched = self.db.query(FeedSchedule).filter(
                (FeedSchedule.id == target_uuid) | (FeedSchedule.feed_id == target_uuid)
            ).first()
            if not sched:
                raise HTTPException(status_code=404, detail=f"Feed schedule {action.target_id} not found")
            if sched.status == ScheduleStatusEnum.ACTIVE:
                raise HTTPException(status_code=400, detail=f"Feed schedule for feed {sched.feed_id} is already ACTIVE")
            from backend.services.scheduling_service import SchedulingService
            from backend.core.security import CurrentUser
            sched_service = SchedulingService(self.db)
            user_obj = CurrentUser(
                user_id=actor_id,
                email=actor_email or "system@cinqflow.local",
                roles=["ENGINEER"],
                auth_provider="mock",
            )
            sched_service.resume_schedule(sched.feed_id, user_obj)
            return {"feed_id": str(sched.feed_id), "schedule_id": str(sched.id), "schedule_status": "ACTIVE"}

        raise HTTPException(status_code=400, detail=f"Unsupported action type: {action.action_type.value}")

    def list_pending_actions(
        self,
        action_type: Optional[ActionTypeEnum] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[int, List[OperationalActionRequest]]:
        """Returns pending dual-control approval actions."""
        query = (
            self.db.query(OperationalActionRequest)
            .filter(OperationalActionRequest.status == ActionStatusEnum.PENDING_APPROVAL)
        )
        if action_type:
            query = query.filter(OperationalActionRequest.action_type == action_type)

        total = query.count()
        items = query.order_by(OperationalActionRequest.requested_at.desc()).offset(offset).limit(limit).all()
        return total, items
