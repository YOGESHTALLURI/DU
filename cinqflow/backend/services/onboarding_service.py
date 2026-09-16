"""
Onboarding Service — Wave 1 Slice 2

Manages the 5-step Business Analyst Feed Onboarding Wizard:
1. Feed Setup (Metadata)
2. Sample & Profiling (Fact)
3. Schema Contract (Decision & Publishing)
4. Mapping Studio (Slice 3 Preview / Placeholder)
5. Review & Activation (Server-side Governed Activation)
"""
import uuid
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from fastapi import HTTPException, status

from backend.models.feed import Feed, FeedStatusEnum
from backend.models.schema import (
    OnboardingSession,
    OnboardingStatusEnum,
    SampleFile,
    ProfilingRun,
    ProfilingRunStatusEnum,
    Schema,
    SchemaVersion,
    SchemaVersionStatusEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.schemas.feed import OnboardingStepUpdateRequest


class OnboardingService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def get_or_create_session(
        self, feed_id: uuid.UUID, actor_id: str = "system", actor_email: Optional[str] = None
    ) -> OnboardingSession:
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {feed_id} not found",
            )

        session = (
            self.db.query(OnboardingSession)
            .filter(OnboardingSession.feed_id == feed_id)
            .first()
        )

        # Look up existing artifacts to link
        sample_file = (
            self.db.query(SampleFile)
            .filter(SampleFile.feed_id == feed_id)
            .order_by(SampleFile.created_at.desc())
            .first()
        )
        completed_run = (
            self.db.query(ProfilingRun)
            .filter(
                ProfilingRun.feed_id == feed_id,
                ProfilingRun.status == ProfilingRunStatusEnum.COMPLETED,
            )
            .order_by(ProfilingRun.completed_at.desc())
            .first()
        )
        schema_obj = (
            self.db.query(Schema)
            .filter(Schema.feed_id == feed_id)
            .first()
        )
        published_schema = None
        if schema_obj:
            published_schema = (
                self.db.query(SchemaVersion)
                .filter(
                    SchemaVersion.schema_id == schema_obj.id,
                    SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
                )
                .first()
            )

        if not session:
            completed_steps: List[int] = []
            if feed.name and feed.domain and feed.landing_folder and feed.filename_pattern:
                completed_steps.append(1)
            if sample_file and completed_run:
                completed_steps.append(2)
            if schema_obj and published_schema:
                completed_steps.append(3)
            if feed.status == FeedStatusEnum.ACTIVE:
                completed_steps.extend([4, 5])

            session = OnboardingSession(
                id=uuid.uuid4(),
                feed_id=feed_id,
                current_step=1,
                completed_steps=sorted(list(set(completed_steps))),
                sample_file_id=sample_file.id if sample_file else None,
                profiling_run_id=completed_run.id if completed_run else None,
                schema_id=schema_obj.id if schema_obj else None,
                status=OnboardingStatusEnum.COMPLETED if feed.status == FeedStatusEnum.ACTIVE else OnboardingStatusEnum.IN_PROGRESS,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(session)
            self.db.flush()

            self.audit.emit(
                action=AuditActionEnum.ONBOARDING_STARTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="onboarding_sessions",
                object_id=str(session.id),
                after_state={
                    "feed_id": str(feed_id),
                    "current_step": session.current_step,
                    "completed_steps": session.completed_steps,
                },
                description=f"Started onboarding wizard for feed {feed.name}",
            )
            self.db.commit()
            self.db.refresh(session)
            return session

        # If session exists, keep linkages updated
        changed = False
        if sample_file and session.sample_file_id != sample_file.id:
            session.sample_file_id = sample_file.id
            changed = True
        if completed_run and session.profiling_run_id != completed_run.id:
            session.profiling_run_id = completed_run.id
            changed = True
        if schema_obj and session.schema_id != schema_obj.id:
            session.schema_id = schema_obj.id
            changed = True

        # Sync completed steps automatically if artifacts are ready
        if feed.name and feed.domain and feed.landing_folder and feed.filename_pattern:
            if 1 not in session.completed_steps:
                session.completed_steps.append(1)
                changed = True
        if sample_file and completed_run and (2 not in session.completed_steps):
            session.completed_steps.append(2)
            changed = True
        if schema_obj and published_schema and (3 not in session.completed_steps):
            session.completed_steps.append(3)
            changed = True

        if changed:
            session.completed_steps = sorted(list(set(session.completed_steps)))
            flag_modified(session, "completed_steps")
            session.updated_by = actor_id
            self.db.commit()
            self.db.refresh(session)

        return session

    def update_step(
        self,
        feed_id: uuid.UUID,
        data: OnboardingStepUpdateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> OnboardingSession:
        session = self.get_or_create_session(feed_id, actor_id=actor_id, actor_email=actor_email)
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()

        if data.mark_step_completed is not None:
            step_to_complete = data.mark_step_completed

            if step_to_complete == 1:
                if not (feed.name and feed.domain and feed.landing_folder and feed.filename_pattern):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Step 1 incomplete: Feed metadata (name, domain, landing folder, filename pattern) is required",
                    )
            elif step_to_complete == 2:
                # Must have sample file and completed profiling run
                completed_run = (
                    self.db.query(ProfilingRun)
                    .filter(
                        ProfilingRun.feed_id == feed_id,
                        ProfilingRun.status == ProfilingRunStatusEnum.COMPLETED,
                    )
                    .first()
                )
                if not completed_run:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Step 2 incomplete: A representative sample file must be uploaded and deterministic profiling completed",
                    )
                session.profiling_run_id = completed_run.id
                session.sample_file_id = completed_run.sample_file_id
            elif step_to_complete == 3:
                # Must have schema and published version
                schema_obj = self.db.query(Schema).filter(Schema.feed_id == feed_id).first()
                if not schema_obj:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Step 3 incomplete: Schema contract has not been created",
                    )
                published_ver = (
                    self.db.query(SchemaVersion)
                    .filter(
                        SchemaVersion.schema_id == schema_obj.id,
                        SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
                    )
                    .first()
                )
                if not published_ver:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Step 3 incomplete: Schema contract must have a PUBLISHED version before completing this step (found draft only)",
                    )
                session.schema_id = schema_obj.id
            elif step_to_complete == 4:
                from backend.models.mapping import Mapping, MappingVersion, MappingVersionStatusEnum
                mapping = self.db.query(Mapping).filter(Mapping.feed_id == feed_id).first()
                if data.current_step == 4 or mapping is not None:
                    if not mapping:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Step 4 incomplete: Canonical mapping contract has not been created",
                        )
                    published_mapping = (
                        self.db.query(MappingVersion)
                        .filter(
                            MappingVersion.mapping_id == mapping.id,
                            MappingVersion.status == MappingVersionStatusEnum.PUBLISHED,
                        )
                        .first()
                    )
                    if not published_mapping:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Step 4 incomplete: Canonical mapping contract must have a PUBLISHED version before completing this step (found draft only)",
                        )

                # Slice 4: Rule governance check — non-deleted rules must have at least one PUBLISHED version
                from backend.models.rule import DataQualityRule, RuleVersion, RuleVersionStatusEnum
                active_rules = (
                    self.db.query(DataQualityRule)
                    .filter(
                        DataQualityRule.feed_id == feed_id,
                        DataQualityRule.is_deleted.is_(False),
                    )
                    .all()
                )
                unpublished_rule_names = []
                for r in active_rules:
                    has_published = any(v.status == RuleVersionStatusEnum.PUBLISHED for v in r.versions)
                    if not has_published:
                        unpublished_rule_names.append(r.name)

                if unpublished_rule_names:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Step 4 incomplete: All defined data quality rules must have a PUBLISHED version before completing this step. Found unpublished draft-only rules: {', '.join(unpublished_rule_names)}",
                    )
            elif step_to_complete == 5:
                # Activation step
                if feed.status != FeedStatusEnum.ACTIVE:
                    from backend.models.mapping import Mapping
                    mapping_exists = self.db.query(Mapping).filter(Mapping.feed_id == feed_id).first() is not None
                    from backend.services.feed_service import FeedService
                    feed_svc = FeedService(self.db)
                    feed_svc.transition_feed_status(
                        feed_id=feed_id,
                        target_status=FeedStatusEnum.ACTIVE,
                        reason="Activated via Onboarding Wizard",
                        actor_id=actor_id,
                        actor_email=actor_email,
                        require_mapping=mapping_exists,
                    )

            current_completed = list(session.completed_steps or [])
            if step_to_complete not in current_completed:
                current_completed.append(step_to_complete)
            session.completed_steps = sorted(list(set(current_completed)))
            flag_modified(session, "completed_steps")

            self.audit.emit(
                action=AuditActionEnum.ONBOARDING_STEP_COMPLETED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="onboarding_sessions",
                object_id=str(session.id),
                after_state={
                    "completed_step": step_to_complete,
                    "completed_steps": session.completed_steps,
                },
                description=f"Completed step {step_to_complete} in onboarding wizard for feed {feed.name}",
            )

            if set(session.completed_steps) >= {1, 2, 3, 4, 5}:
                session.status = OnboardingStatusEnum.COMPLETED
                self.audit.emit(
                    action=AuditActionEnum.ONBOARDING_COMPLETED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="onboarding_sessions",
                    object_id=str(session.id),
                    after_state={"status": session.status.value},
                    description=f"Completed onboarding wizard for feed {feed.name}",
                )

        session.current_step = data.current_step
        session.updated_by = actor_id
        self.db.commit()
        self.db.refresh(session)
        return session
