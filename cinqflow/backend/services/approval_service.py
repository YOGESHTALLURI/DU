"""
Approval Service — Wave 1 Slice 5 (CF-V1-E4-03, CF-V1-E11-01, CF-V1-E11-02)

Provides:
- Review Packet Aggregator: aggregates metadata, profiling facts, schema, mapping, rules, and sandbox evidence
- Sandbox Test Triggering: invokes isolated sandbox pipeline execution and logs audit events
- Approval Submission: validates all prerequisites before entering PENDING_APPROVAL
- Governed Activation & Four-Eyes Principle: verifies author != approver, locks version bundle, and activates feed
- Activation Rejection: records mandatory rejection reason and reverts to DRAFT
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from fastapi import HTTPException, status

from backend.models.feed import Feed, FeedStatusEnum, FeedVersion
from backend.models.schema import (
    SampleFile,
    ProfilingRun,
    ProfilingRunStatusEnum,
    Schema,
    SchemaVersion,
    SchemaVersionStatusEnum,
    OnboardingSession,
    OnboardingStatusEnum,
)
from backend.models.mapping import (
    Mapping,
    MappingVersion,
    MappingVersionStatusEnum,
)
from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleVersionStatusEnum,
)
from backend.models.approval import (
    SandboxTestRun,
    SandboxRunStatusEnum,
    ApprovalRequest,
    ApprovalRequestStatusEnum,
    FeedActivationRecord,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.engine.sandbox_executor import SandboxExecutor
from backend.core.security import CurrentUser
from backend.schemas.approval import (
    ReviewPacketResponse,
    FeedMetadataSummary,
    ProfilingSummary,
    SchemaSummary,
    MappingSummary,
    RulesSummary,
    ReadinessChecklist,
    UserCapabilities,
    SandboxTestRunResponse,
    ApprovalRequestResponse,
    FeedActivationResponse,
)


class ApprovalService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def run_sandbox_test(
        self,
        feed_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str] = None,
        max_rows: int = 10000,
    ) -> SandboxTestRun:
        """Trigger in-memory sandbox execution test and record audit events."""
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        self.audit.emit(
            action=AuditActionEnum.SANDBOX_TEST_STARTED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="feeds",
            object_id=str(feed_id),
            description=f"Started sandbox test execution for feed {feed.name}",
        )

        executor = SandboxExecutor(self.db)
        test_run = executor.run_sandbox_test(feed_id=feed_id, actor_id=actor_id, max_rows=max_rows)

        if test_run.status == SandboxRunStatusEnum.SUCCESS:
            self.audit.emit(
                action=AuditActionEnum.SANDBOX_TEST_COMPLETED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="sandbox_test_runs",
                object_id=str(test_run.id),
                after_state={
                    "total_rows": test_run.total_rows,
                    "passed_rows": test_run.passed_rows,
                    "quarantined_rows": test_run.quarantined_rows,
                    "reconciliation_status": test_run.reconciliation_status,
                    "duration_ms": test_run.execution_duration_ms,
                    "has_reject_file_violation": test_run.has_reject_file_violation,
                },
                description=f"Completed sandbox test run {test_run.id} for feed {feed.name} ({test_run.pass_rate}% passed)",
            )
        else:
            self.audit.emit(
                action=AuditActionEnum.SANDBOX_TEST_FAILED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="sandbox_test_runs",
                object_id=str(test_run.id),
                after_state={"error_message": test_run.error_message},
                description=f"Sandbox test run {test_run.id} failed: {test_run.error_message}",
            )

        self.db.commit()
        return test_run

    def get_review_packet(self, feed_id: uuid.UUID, current_user: CurrentUser) -> ReviewPacketResponse:
        """Aggregates all 5 domains into a unified review & impact packet."""
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        # 1. Feed Metadata
        feed_summary = FeedMetadataSummary(
            id=feed.id,
            name=feed.name,
            domain=feed.domain,
            source_system=feed.source_system,
            data_owner=feed.data_owner,
            sla_expectation=feed.sla_expectation,
            landing_folder=feed.landing_folder,
            filename_pattern=feed.filename_pattern,
            schedule_expression=feed.schedule_expression,
            status=feed.status.value,
        )

        # 2. Profiling Facts
        sample_file = (
            self.db.query(SampleFile)
            .filter(SampleFile.feed_id == feed_id)
            .order_by(SampleFile.created_at.desc())
            .first()
        )
        completed_prof_run = (
            self.db.query(ProfilingRun)
            .filter(
                ProfilingRun.feed_id == feed_id,
                ProfilingRun.status == ProfilingRunStatusEnum.COMPLETED,
            )
            .order_by(ProfilingRun.completed_at.desc())
            .first()
        )
        profiling_summary = ProfilingSummary(
            sample_file_id=sample_file.id if sample_file else None,
            sample_file_name=sample_file.filename if sample_file else None,
            total_columns=completed_prof_run.column_count if completed_prof_run else 0,
            total_rows=completed_prof_run.row_count if completed_prof_run else 0,
            profiled_at=completed_prof_run.completed_at if completed_prof_run else None,
        )

        # 3. Schema Summary
        schema_obj = self.db.query(Schema).filter(Schema.feed_id == feed_id).first()
        active_schema_ver = None
        if schema_obj:
            active_schema_ver = (
                self.db.query(SchemaVersion)
                .filter(
                    SchemaVersion.schema_id == schema_obj.id,
                    SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
                )
                .order_by(SchemaVersion.version_number.desc())
                .first()
            )
        schema_summary = SchemaSummary(
            schema_id=schema_obj.id if schema_obj else None,
            schema_version_id=active_schema_ver.id if active_schema_ver else None,
            version_number=active_schema_ver.version_number if active_schema_ver else None,
            status=active_schema_ver.status.value if active_schema_ver else ("DRAFT" if schema_obj else None),
            total_fields=len(active_schema_ver.fields) if active_schema_ver else 0,
            required_fields_count=len([f for f in active_schema_ver.fields if f.is_required]) if active_schema_ver else 0,
        )

        # 4. Mapping Summary
        mapping_obj = self.db.query(Mapping).filter(Mapping.feed_id == feed_id).first()
        active_mapping_ver = None
        if mapping_obj:
            active_mapping_ver = (
                self.db.query(MappingVersion)
                .filter(
                    MappingVersion.mapping_id == mapping_obj.id,
                    MappingVersion.status == MappingVersionStatusEnum.PUBLISHED,
                )
                .order_by(MappingVersion.version_number.desc())
                .first()
            )

        transform_counts: Dict[str, int] = {}
        mapped_count = 0
        unmapped_count = 0
        canonical_name = None
        canonical_id = None

        if mapping_obj and mapping_obj.canonical_model:
            canonical_name = mapping_obj.canonical_model.name
            canonical_id = mapping_obj.canonical_model.id
            all_canonical_fields = mapping_obj.canonical_model.fields
            mapped_canonical_field_ids = {l.canonical_field_id for l in (active_mapping_ver.lines if active_mapping_ver else [])}
            mapped_count = len(mapped_canonical_field_ids)
            unmapped_count = max(0, len(all_canonical_fields) - mapped_count)

            if active_mapping_ver:
                for l in active_mapping_ver.lines:
                    t = l.transform_type.value
                    transform_counts[t] = transform_counts.get(t, 0) + 1

        mapping_summary = MappingSummary(
            mapping_id=mapping_obj.id if mapping_obj else None,
            mapping_version_id=active_mapping_ver.id if active_mapping_ver else None,
            version_number=active_mapping_ver.version_number if active_mapping_ver else None,
            status=active_mapping_ver.status.value if active_mapping_ver else ("DRAFT" if mapping_obj else None),
            canonical_model_id=canonical_id,
            canonical_model_name=canonical_name,
            mapped_fields_count=mapped_count,
            unmapped_fields_count=unmapped_count,
            transform_counts=transform_counts,
        )

        # 5. Rules Summary
        active_rules = (
            self.db.query(DataQualityRule)
            .filter(
                DataQualityRule.feed_id == feed_id,
                DataQualityRule.is_deleted.is_(False),
            )
            .all()
        )
        published_rules_count = 0
        draft_rules_count = 0
        rule_severities: Dict[str, int] = {}
        rule_types_count: Dict[str, int] = {}
        needs_review_count = 0

        for r in active_rules:
            # Check latest version
            latest_v = r.versions[-1] if r.versions else None
            if latest_v:
                if latest_v.status == RuleVersionStatusEnum.PUBLISHED:
                    published_rules_count += 1
                else:
                    draft_rules_count += 1
                sev = latest_v.severity.value
                rule_severities[sev] = rule_severities.get(sev, 0) + 1
                rtype = latest_v.rule_type.value
                rule_types_count[rtype] = rule_types_count.get(rtype, 0) + 1
                if latest_v.needs_review:
                    needs_review_count += 1

        rules_summary = RulesSummary(
            active_rules_count=len(active_rules),
            published_rules_count=published_rules_count,
            draft_rules_count=draft_rules_count,
            severities=rule_severities,
            rule_types=rule_types_count,
            needs_review_count=needs_review_count,
        )

        # 6. Latest Sandbox Run
        latest_sandbox_run = (
            self.db.query(SandboxTestRun)
            .filter(SandboxTestRun.feed_id == feed_id)
            .order_by(SandboxTestRun.created_at.desc())
            .first()
        )
        sandbox_resp = None
        if latest_sandbox_run:
            sandbox_resp = SandboxTestRunResponse.model_validate(latest_sandbox_run)

        # 7. Readiness Checklist
        s1_valid = bool(feed.name and feed.domain and feed.landing_folder and feed.filename_pattern)
        s2_complete = bool(sample_file and completed_prof_run)
        s3_pub = bool(active_schema_ver is not None)
        s4_map_pub = bool(active_mapping_ver is not None and active_schema_ver is not None and active_mapping_ver.schema_version_id == active_schema_ver.id)

        # Step 4 rules published: every active rule must have at least one published version
        s4_rules_pub = True
        for r in active_rules:
            has_pub = any(v.status == RuleVersionStatusEnum.PUBLISHED for v in r.versions)
            if not has_pub:
                s4_rules_pub = False
                break

        # Step 5 sandbox passed: latest run exists, status SUCCESS, on active schema and mapping
        s5_passed = False
        if latest_sandbox_run and latest_sandbox_run.status == SandboxRunStatusEnum.SUCCESS:
            if active_schema_ver and active_mapping_ver:
                if (
                    latest_sandbox_run.schema_version_id == active_schema_ver.id
                    and latest_sandbox_run.mapping_version_id == active_mapping_ver.id
                ):
                    s5_passed = True

        all_prereqs = (
            s1_valid
            and s2_complete
            and s3_pub
            and s4_map_pub
            and s4_rules_pub
            and s5_passed
        )

        checklist = ReadinessChecklist(
            step1_metadata_valid=s1_valid,
            step2_profiling_complete=s2_complete,
            step3_schema_published=s3_pub,
            step4_mapping_published=s4_map_pub,
            step4_rules_published=s4_rules_pub,
            step5_sandbox_passed=s5_passed,
            all_prerequisites_met=all_prereqs,
        )

        # 8. Active Approval Request
        active_approval = (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.feed_id == feed_id,
                ApprovalRequest.status.in_([
                    ApprovalRequestStatusEnum.PENDING_APPROVAL,
                    ApprovalRequestStatusEnum.APPROVED,
                    ApprovalRequestStatusEnum.REJECTED,
                ])
            )
            .order_by(ApprovalRequest.created_at.desc())
            .first()
        )
        approval_resp = None
        if active_approval:
            approval_resp = ApprovalRequestResponse.model_validate(active_approval)

        # 9. User Capabilities
        is_ba = current_user.is_business_analyst()
        is_eng = current_user.is_engineer()
        is_ro = current_user.is_read_only()

        is_author = (active_approval is not None and current_user.user_id == active_approval.submitted_by)
        is_pending = (active_approval is not None and active_approval.status == ApprovalRequestStatusEnum.PENDING_APPROVAL)

        can_run = not is_ro and (is_ba or is_eng)
        can_sub = not is_ro and (is_ba or is_eng) and all_prereqs and feed.status == FeedStatusEnum.DRAFT and not is_pending
        # Four-Eyes Principle: only Engineer who is NOT the author can approve/reject
        can_app = is_eng and is_pending and not is_author
        can_rej = is_eng and is_pending and not is_author

        role_name = "ENGINEER" if is_eng else ("BUSINESS_ANALYST" if is_ba else "READ_ONLY")

        user_caps = UserCapabilities(
            can_run_test=can_run,
            can_submit=can_sub,
            can_approve=can_app,
            can_reject=can_rej,
            is_author=is_author,
            role_name=role_name,
        )

        return ReviewPacketResponse(
            feed_metadata=feed_summary,
            profiling_summary=profiling_summary,
            schema_summary=schema_summary,
            mapping_summary=mapping_summary,
            rules_summary=rules_summary,
            latest_sandbox_run=sandbox_resp,
            readiness_checklist=checklist,
            approval_status=approval_resp,
            user_capabilities=user_caps,
        )

    def submit_for_approval(
        self,
        feed_id: uuid.UUID,
        notes: Optional[str],
        current_user: CurrentUser,
    ) -> ApprovalRequest:
        """Formal submission of feed for activation review."""
        packet = self.get_review_packet(feed_id, current_user)
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()

        if feed.status != FeedStatusEnum.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot submit feed for approval: Feed is currently in {feed.status.value} status (only DRAFT feeds can be submitted)",
            )

        if not packet.readiness_checklist.all_prerequisites_met:
            reasons = []
            if not packet.readiness_checklist.step1_metadata_valid:
                reasons.append("Feed metadata incomplete")
            if not packet.readiness_checklist.step2_profiling_complete:
                reasons.append("Representative sample profiling incomplete")
            if not packet.readiness_checklist.step3_schema_published:
                reasons.append("Schema contract not published")
            if not packet.readiness_checklist.step4_mapping_published:
                reasons.append("Canonical mapping contract not published or unaligned with schema")
            if not packet.readiness_checklist.step4_rules_published:
                reasons.append("One or more active data quality rules have no published version")
            if not packet.readiness_checklist.step5_sandbox_passed:
                reasons.append("Successful end-to-end sandbox test run has not been executed on active published versions")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot submit feed for approval: Prerequisites not met ({', '.join(reasons)})",
            )

        # Check existing pending request
        existing_pending = (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.feed_id == feed_id,
                ApprovalRequest.status == ApprovalRequestStatusEnum.PENDING_APPROVAL,
            )
            .first()
        )
        if existing_pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An activation approval request is already pending for feed {feed.name} (submitted by {existing_pending.submitted_by})",
            )

        # Retrieve active feed version
        feed_version = (
            self.db.query(FeedVersion)
            .filter(FeedVersion.feed_id == feed.id)
            .order_by(FeedVersion.version_number.desc())
            .first()
        )
        if not feed_version:
            # Create v1 feed version if missing
            feed_version = FeedVersion(
                id=uuid.uuid4(),
                feed_id=feed.id,
                version_number=1,
                status=FeedVersion.status,
                config_snapshot={},
                created_by=current_user.user_id,
                updated_by=current_user.user_id,
            )
            self.db.add(feed_version)
            self.db.flush()

        approval_req = ApprovalRequest(
            id=uuid.uuid4(),
            feed_id=feed.id,
            feed_version_id=feed_version.id,
            schema_version_id=packet.schema_summary.schema_version_id,
            mapping_version_id=packet.mapping_summary.mapping_version_id,
            sandbox_test_run_id=packet.latest_sandbox_run.id,
            status=ApprovalRequestStatusEnum.PENDING_APPROVAL,
            submitted_by=current_user.user_id,
            submitted_by_email=current_user.email,
            submitted_at=datetime.now(timezone.utc),
            submission_notes=notes,
            created_by=current_user.user_id,
            updated_by=current_user.user_id,
        )
        self.db.add(approval_req)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.APPROVAL_SUBMITTED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="approval_requests",
            object_id=str(approval_req.id),
            after_state={
                "feed_id": str(feed.id),
                "feed_name": feed.name,
                "sandbox_test_run_id": str(packet.latest_sandbox_run.id),
                "submission_notes": notes,
            },
            description=f"Submitted activation approval request for feed {feed.name}",
        )
        self.db.commit()
        self.db.refresh(approval_req)
        return approval_req

    def approve_activation(
        self,
        feed_id: uuid.UUID,
        decision_notes: Optional[str],
        current_user: CurrentUser,
    ) -> FeedActivationResponse:
        """
        Approves feed activation under the Four-Eyes Principle:
        The author/submitter cannot approve their own feed.
        """
        if not current_user.is_engineer():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ENGINEER role required to approve feed activation into production",
            )

        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        approval_req = (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.feed_id == feed_id,
                ApprovalRequest.status == ApprovalRequestStatusEnum.PENDING_APPROVAL,
            )
            .order_by(ApprovalRequest.created_at.desc())
            .first()
        )
        if not approval_req:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve activation: No pending approval request found for feed {feed.name}",
            )

        # FOUR-EYES PRINCIPLE CHECK
        if current_user.user_id == approval_req.submitted_by:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Four-Eyes Principle Violation: Author/submitter cannot approve their own activation request. An independent Engineer must review and approve.",
            )

        # Collect active published rule version IDs
        active_rules = (
            self.db.query(DataQualityRule)
            .filter(
                DataQualityRule.feed_id == feed_id,
                DataQualityRule.is_deleted.is_(False),
            )
            .all()
        )
        rule_version_ids = []
        for r in active_rules:
            for v in r.versions:
                if v.status == RuleVersionStatusEnum.PUBLISHED and v.schema_version_id == approval_req.schema_version_id:
                    rule_version_ids.append(str(v.id))

        now_utc = datetime.now(timezone.utc)

        # Update ApprovalRequest
        approval_req.status = ApprovalRequestStatusEnum.APPROVED
        approval_req.reviewed_by = current_user.user_id
        approval_req.reviewed_by_email = current_user.email
        approval_req.reviewed_at = now_utc
        approval_req.decision_notes = decision_notes
        approval_req.updated_by = current_user.user_id

        # Insert immutable FeedActivationRecord
        activation_record = FeedActivationRecord(
            id=uuid.uuid4(),
            feed_id=feed.id,
            approval_request_id=approval_req.id,
            feed_version_id=approval_req.feed_version_id,
            schema_version_id=approval_req.schema_version_id,
            mapping_version_id=approval_req.mapping_version_id,
            rule_version_ids=rule_version_ids,
            sandbox_test_run_id=approval_req.sandbox_test_run_id,
            activated_by=current_user.user_id,
            activated_by_email=current_user.email,
            activated_at=now_utc,
            activation_notes=decision_notes,
            created_by=current_user.user_id,
            updated_by=current_user.user_id,
        )
        self.db.add(activation_record)

        # Transition Feed status to ACTIVE
        before_status = feed.status.value
        feed.status = FeedStatusEnum.ACTIVE
        feed.updated_by = current_user.user_id
        feed.version += 1

        # Complete OnboardingSession if present
        session = self.db.query(OnboardingSession).filter(OnboardingSession.feed_id == feed.id).first()
        if session:
            completed_set = set(session.completed_steps or [])
            completed_set.update([1, 2, 3, 4, 5])
            session.completed_steps = sorted(list(completed_set))
            flag_modified(session, "completed_steps")
            session.current_step = 5
            session.status = OnboardingStatusEnum.COMPLETED
            session.updated_by = current_user.user_id

        self.db.flush()

        # Emit audit events
        self.audit.emit(
            action=AuditActionEnum.APPROVAL_APPROVED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="approval_requests",
            object_id=str(approval_req.id),
            after_state={
                "feed_id": str(feed.id),
                "activation_record_id": str(activation_record.id),
                "schema_version_id": str(approval_req.schema_version_id),
                "mapping_version_id": str(approval_req.mapping_version_id),
                "rule_version_ids": rule_version_ids,
                "decision_notes": decision_notes,
            },
            description=f"Approved feed {feed.name} activation into ACTIVE status",
        )

        self.audit.emit(
            action=AuditActionEnum.FEED_STATUS_CHANGED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feeds",
            object_id=str(feed.id),
            before_state={"status": before_status},
            after_state={"status": FeedStatusEnum.ACTIVE.value, "reason": "Governed activation approved"},
            description=f"Changed feed {feed.name} status from {before_status} to ACTIVE via governed approval",
        )

        self.db.commit()
        self.db.refresh(feed)
        self.db.refresh(activation_record)

        return FeedActivationResponse(
            feed_id=feed.id,
            status=feed.status.value,
            activation_record_id=activation_record.id,
            activated_by=current_user.user_id,
            activated_at=activation_record.activated_at,
            decision_notes=decision_notes,
        )

    def reject_activation(
        self,
        feed_id: uuid.UUID,
        decision_notes: str,
        current_user: CurrentUser,
    ) -> ApprovalRequest:
        """Rejects feed activation request with mandatory reason."""
        if not current_user.is_engineer():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ENGINEER role required to review and reject activation requests",
            )

        if not decision_notes or len(decision_notes.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A non-empty rejection reason (at least 3 characters) is mandatory to reject activation",
            )

        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        approval_req = (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.feed_id == feed_id,
                ApprovalRequest.status == ApprovalRequestStatusEnum.PENDING_APPROVAL,
            )
            .order_by(ApprovalRequest.created_at.desc())
            .first()
        )
        if not approval_req:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject activation: No pending approval request found for feed {feed.name}",
            )

        # Submitter cannot reject their own submission
        if current_user.user_id == approval_req.submitted_by:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Four-Eyes Principle Violation: Author/submitter cannot reject their own activation request.",
            )

        approval_req.status = ApprovalRequestStatusEnum.REJECTED
        approval_req.reviewed_by = current_user.user_id
        approval_req.reviewed_by_email = current_user.email
        approval_req.reviewed_at = datetime.now(timezone.utc)
        approval_req.decision_notes = decision_notes.strip()
        approval_req.updated_by = current_user.user_id
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.APPROVAL_REJECTED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="approval_requests",
            object_id=str(approval_req.id),
            after_state={
                "feed_id": str(feed.id),
                "rejection_reason": decision_notes.strip(),
            },
            description=f"Rejected activation request for feed {feed.name}: {decision_notes.strip()}",
        )

        self.db.commit()
        self.db.refresh(approval_req)
        return approval_req
