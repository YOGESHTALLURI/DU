"""
Feed Registry Service — Wave 0

Metadata-driven feed management and immutable configuration versioning.
Strictly GENERIC — no feed-specific logic or branching.
All configuration state changes emit immutable audit events.
"""
import uuid
import fnmatch
import copy
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from fastapi import HTTPException, status
from backend.models.feed import (
    Feed,
    FeedVersion,
    FeedFormatEnum,
    FeedStatusEnum,
    FeedVersionStatusEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.schemas.feed import (
    FeedCreateRequest,
    FeedUpdateRequest,
    FeedCloneRequest,
    FeedStatusUpdateRequest,
    FeedVersionCreateRequest,
    FeedVersionPublishRequest,
)


class FeedService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def create_feed(
        self, data: FeedCreateRequest, actor_id: str, actor_email: Optional[str] = None
    ) -> Feed:
        # Check uniqueness of name
        existing = self.db.query(Feed).filter(Feed.name == data.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Feed with name '{data.name}' already exists",
            )

        feed = Feed(
            id=uuid.uuid4(),
            name=data.name,
            domain=data.domain,
            description=data.description,
            format=data.format,
            landing_folder=data.landing_folder,
            filename_pattern=data.filename_pattern,
            schedule_expression=data.schedule_expression,
            source_system=data.source_system,
            data_owner=data.data_owner,
            sla_expectation=data.sla_expectation,
            status=FeedStatusEnum.DRAFT,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(feed)
        self.db.flush()

        # Create initial Version 1 in DRAFT
        initial_snapshot = data.initial_config or {
            "fields": [],
            "delimiter": ",",
            "has_header": True,
        }
        v1 = FeedVersion(
            id=uuid.uuid4(),
            feed_id=feed.id,
            version_number=1,
            status=FeedVersionStatusEnum.DRAFT,
            config_snapshot=initial_snapshot,
            change_notes="Initial draft configuration",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(v1)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.FEED_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="feeds",
            object_id=str(feed.id),
            after_state={
                "name": feed.name,
                "domain": feed.domain,
                "format": feed.format.value,
                "source_system": feed.source_system,
                "data_owner": feed.data_owner,
            },
            description=f"Created feed {feed.name}",
        )
        self.db.commit()
        self.db.refresh(feed)
        return feed

    def update_feed(
        self,
        feed_id: uuid.UUID,
        data: FeedUpdateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> Feed:
        feed = self.get_feed_or_404(feed_id)

        if feed.status == FeedStatusEnum.RETIRED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify a retired feed",
            )

        before_state = {
            "description": feed.description,
            "format": feed.format.value,
            "landing_folder": feed.landing_folder,
            "filename_pattern": feed.filename_pattern,
            "source_system": feed.source_system,
            "data_owner": feed.data_owner,
            "sla_expectation": feed.sla_expectation,
            "status": feed.status.value,
        }

        if data.description is not None:
            feed.description = data.description
        if data.format is not None:
            feed.format = data.format
        if data.landing_folder is not None:
            feed.landing_folder = data.landing_folder
        if data.filename_pattern is not None:
            feed.filename_pattern = data.filename_pattern
        if data.schedule_expression is not None:
            feed.schedule_expression = data.schedule_expression
        if data.source_system is not None:
            feed.source_system = data.source_system
        if data.data_owner is not None:
            feed.data_owner = data.data_owner
        if data.sla_expectation is not None:
            feed.sla_expectation = data.sla_expectation
        if data.status is not None:
            feed.status = data.status

        feed.updated_by = actor_id
        feed.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.FEED_UPDATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="feeds",
            object_id=str(feed.id),
            before_state=before_state,
            after_state={
                "description": feed.description,
                "format": feed.format.value,
                "landing_folder": feed.landing_folder,
                "filename_pattern": feed.filename_pattern,
                "source_system": feed.source_system,
                "data_owner": feed.data_owner,
                "sla_expectation": feed.sla_expectation,
                "status": feed.status.value,
            },
            description=f"Updated feed {feed.name}",
        )
        self.db.commit()
        self.db.refresh(feed)
        return feed

    def get_feed_or_404(self, feed_id: uuid.UUID) -> Feed:
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {feed_id} not found",
            )
        return feed

    def list_feeds(
        self,
        domain: Optional[str] = None,
        status_filter: Optional[FeedStatusEnum] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Feed], int]:
        query = self.db.query(Feed)
        if domain:
            query = query.filter(Feed.domain == domain)
        if status_filter:
            query = query.filter(Feed.status == status_filter)

        total = query.count()
        items = query.order_by(Feed.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

    def create_feed_version(
        self,
        feed_id: uuid.UUID,
        data: FeedVersionCreateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> FeedVersion:
        feed = self.get_feed_or_404(feed_id)

        # Get highest version number
        highest_v = (
            self.db.query(FeedVersion.version_number)
            .filter(FeedVersion.feed_id == feed.id)
            .order_by(FeedVersion.version_number.desc())
            .first()
        )
        next_ver = (highest_v[0] + 1) if highest_v else 1

        new_version = FeedVersion(
            id=uuid.uuid4(),
            feed_id=feed.id,
            version_number=next_ver,
            status=FeedVersionStatusEnum.DRAFT,
            config_snapshot=data.config_snapshot,
            change_notes=data.change_notes,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(new_version)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.FEED_VERSION_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="feed_versions",
            object_id=str(new_version.id),
            after_state={"version_number": next_ver, "status": "DRAFT"},
            description=f"Created version {next_ver} for feed {feed.name}",
        )
        self.db.commit()
        self.db.refresh(new_version)
        return new_version

    def publish_feed_version(
        self,
        feed_id: uuid.UUID,
        version_id: uuid.UUID,
        data: FeedVersionPublishRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> FeedVersion:
        feed = self.get_feed_or_404(feed_id)
        version = (
            self.db.query(FeedVersion)
            .filter(FeedVersion.id == version_id, FeedVersion.feed_id == feed.id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed version {version_id} not found for feed {feed.name}",
            )

        if version.status == FeedVersionStatusEnum.PUBLISHED:
            return version  # already published

        # Supersede previously published versions
        currently_published = (
            self.db.query(FeedVersion)
            .filter(
                FeedVersion.feed_id == feed.id,
                FeedVersion.status == FeedVersionStatusEnum.PUBLISHED,
            )
            .all()
        )
        for pub in currently_published:
            pub.status = FeedVersionStatusEnum.SUPERSEDED
            pub.updated_by = actor_id

        version.status = FeedVersionStatusEnum.PUBLISHED
        version.published_by = actor_email or actor_id
        if data.change_notes:
            version.change_notes = data.change_notes
        version.updated_by = actor_id

        # Also activate the feed if it was DRAFT
        if feed.status == FeedStatusEnum.DRAFT:
            feed.status = FeedStatusEnum.ACTIVE
            feed.updated_by = actor_id

        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.FEED_VERSION_PUBLISHED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="feed_versions",
            object_id=str(version.id),
            after_state={"version_number": version.version_number, "status": "PUBLISHED"},
            description=f"Published version {version.version_number} for feed {feed.name}",
        )
        self.db.commit()
        self.db.refresh(version)
        return version

    def validate_pattern(self, feed_id: uuid.UUID, sample_filename: str) -> bool:
        """
        Generic pattern matching without feed-specific code.
        Uses glob pattern matching from the feed's stored metadata.
        """
        feed = self.get_feed_or_404(feed_id)
        return fnmatch.fnmatch(sample_filename, feed.filename_pattern)

    def clone_feed(
        self,
        feed_id: uuid.UUID,
        data: FeedCloneRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> Feed:
        """
        Clones an existing feed into an independent new feed with strict isolation.
        The clone has an independent UUID, independent version UUID, and deep-copied configuration.
        """
        source_feed = self.get_feed_or_404(feed_id)

        # Check name uniqueness
        existing = self.db.query(Feed).filter(Feed.name == data.new_name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Feed with name '{data.new_name}' already exists",
            )

        # Get latest configuration snapshot from source feed
        source_version = (
            self.db.query(FeedVersion)
            .filter(FeedVersion.feed_id == source_feed.id)
            .order_by(FeedVersion.version_number.desc())
            .first()
        )
        cloned_config = copy.deepcopy(source_version.config_snapshot) if source_version and source_version.config_snapshot else {
            "fields": [],
            "delimiter": ",",
            "has_header": True,
        }

        # Create new feed record with strict isolation
        new_feed = Feed(
            id=uuid.uuid4(),
            name=data.new_name,
            domain=source_feed.domain,
            description=data.description if data.description is not None else (
                f"Cloned from {source_feed.name}" if not source_feed.description else f"{source_feed.description} (Cloned from {source_feed.name})"
            ),
            format=source_feed.format,
            landing_folder=source_feed.landing_folder,
            filename_pattern=data.new_filename_pattern or source_feed.filename_pattern,
            schedule_expression=source_feed.schedule_expression,
            source_system=source_feed.source_system,
            data_owner=source_feed.data_owner,
            sla_expectation=source_feed.sla_expectation,
            cloned_from_feed_id=source_feed.id,
            status=FeedStatusEnum.DRAFT,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(new_feed)
        self.db.flush()

        # Create initial Version 1 in DRAFT for cloned feed
        new_version = FeedVersion(
            id=uuid.uuid4(),
            feed_id=new_feed.id,
            version_number=1,
            status=FeedVersionStatusEnum.DRAFT,
            config_snapshot=cloned_config,
            change_notes=f"Initial draft configuration cloned from {source_feed.name}",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(new_version)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.FEED_CLONED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="feeds",
            object_id=str(new_feed.id),
            before_state={"source_feed_id": str(source_feed.id), "source_feed_name": source_feed.name},
            after_state={
                "id": str(new_feed.id),
                "name": new_feed.name,
                "domain": new_feed.domain,
                "status": new_feed.status.value,
                "cloned_from_feed_id": str(source_feed.id),
            },
            description=f"Cloned feed {source_feed.name} ({source_feed.id}) to {new_feed.name} ({new_feed.id})",
        )
        self.db.commit()
        self.db.refresh(new_feed)
        return new_feed

    def validate_feed_for_activation(self, feed: Feed, require_mapping: bool = False) -> None:
        """
        Validates whether a feed meets all requirements to transition to ACTIVE.
        Enforces:
        - required metadata present (name, domain, landing_folder, filename_pattern)
        - at least one valid FeedVersion exists
        - associated Schema contract exists
        - associated Schema has a PUBLISHED version (fails if only DRAFT or no published version)
        - if an OnboardingSession exists, onboarding prerequisites (sample & profiling) must be satisfied
        """
        if not feed.name or not feed.domain or not feed.landing_folder or not feed.filename_pattern:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot activate feed: Missing required metadata (name, domain, landing_folder, filename_pattern)",
            )

        # Check feed version exists
        feed_version = self.db.query(FeedVersion).filter(FeedVersion.feed_id == feed.id).first()
        if not feed_version:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot activate feed: Feed must have at least one configuration version",
            )

        # Check associated schema exists and is published
        from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
        schema = self.db.query(Schema).filter(Schema.feed_id == feed.id).first()
        if not schema:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot activate feed: Feed requires an associated schema contract before activation",
            )

        published_schema_version = (
            self.db.query(SchemaVersion)
            .filter(
                SchemaVersion.schema_id == schema.id,
                SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
            )
            .first()
        )
        if not published_schema_version:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot activate feed: Associated schema contract does not have a PUBLISHED version (schema is merely DRAFT or unpublished)",
            )

        # Check onboarding prerequisites if session exists
        from backend.models.schema import OnboardingSession, ProfilingRun, ProfilingRunStatusEnum
        session = self.db.query(OnboardingSession).filter(OnboardingSession.feed_id == feed.id).first()
        if session:
            completed_run = (
                self.db.query(ProfilingRun)
                .filter(
                    ProfilingRun.feed_id == feed.id,
                    ProfilingRun.status == ProfilingRunStatusEnum.COMPLETED,
                )
                .first()
            )
            if not completed_run:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot activate feed: Feed sample profiling prerequisite is not completed",
                )

        # Check canonical mapping requirement
        from backend.models.mapping import Mapping, MappingVersion, MappingVersionStatusEnum
        mapping = self.db.query(Mapping).filter(Mapping.feed_id == feed.id).first()

        if require_mapping and not mapping:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot activate feed: Feed requires an associated canonical mapping contract before activation",
            )

        if mapping:
            published_mapping_version = (
                self.db.query(MappingVersion)
                .filter(
                    MappingVersion.mapping_id == mapping.id,
                    MappingVersion.status == MappingVersionStatusEnum.PUBLISHED,
                )
                .first()
            )
            if not published_mapping_version:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot activate feed: Associated canonical mapping contract does not have a PUBLISHED version (mapping is merely DRAFT or unpublished)",
                )

            if published_mapping_version.schema_version_id != published_schema_version.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot activate feed: Published mapping version v{published_mapping_version.version_number} is pinned to schema version {published_mapping_version.schema_version_id}, but the active schema version is {published_schema_version.id}. Mapping must be aligned with the published schema.",
                )

    def transition_feed_status(
        self,
        feed_id: uuid.UUID,
        target_status: FeedStatusEnum,
        reason: Optional[str] = None,
        actor_id: str = "system",
        actor_email: Optional[str] = None,
        require_mapping: bool = False,
    ) -> Feed:
        """
        Transitions feed lifecycle status (DRAFT -> ACTIVE -> INACTIVE -> ACTIVE, or * -> RETIRED).
        Enforces strict server-side validation when activating.
        """
        feed = self.get_feed_or_404(feed_id)

        if feed.status == FeedStatusEnum.RETIRED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify status of a retired feed",
            )

        if feed.status == target_status:
            return feed

        # Validate allowed transitions
        valid_transitions = {
            FeedStatusEnum.DRAFT: [FeedStatusEnum.ACTIVE, FeedStatusEnum.RETIRED],
            FeedStatusEnum.ACTIVE: [FeedStatusEnum.INACTIVE, FeedStatusEnum.RETIRED],
            FeedStatusEnum.INACTIVE: [FeedStatusEnum.ACTIVE, FeedStatusEnum.RETIRED],
        }

        allowed = valid_transitions.get(feed.status, [])
        if target_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status transition from {feed.status.value} to {target_status.value}",
            )

        if target_status == FeedStatusEnum.ACTIVE:
            self.validate_feed_for_activation(feed, require_mapping=require_mapping)

        before_status = feed.status.value
        feed.status = target_status
        feed.updated_by = actor_id
        feed.version += 1

        # If transitioning to ACTIVE, also complete OnboardingSession if present
        if target_status == FeedStatusEnum.ACTIVE:
            from backend.models.schema import OnboardingSession, OnboardingStatusEnum
            session = self.db.query(OnboardingSession).filter(OnboardingSession.feed_id == feed.id).first()
            if session:
                cur_steps = list(session.completed_steps or [])
                for step in [1, 2, 3, 4, 5]:
                    if step not in cur_steps:
                        cur_steps.append(step)
                session.completed_steps = sorted(list(set(cur_steps)))
                flag_modified(session, "completed_steps")
                session.current_step = 5
                session.status = OnboardingStatusEnum.COMPLETED
                session.updated_by = actor_id

        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.FEED_STATUS_CHANGED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="feeds",
            object_id=str(feed.id),
            before_state={"status": before_status},
            after_state={"status": feed.status.value, "reason": reason},
            description=f"Changed feed {feed.name} status from {before_status} to {feed.status.value}" + (f": {reason}" if reason else ""),
        )
        self.db.commit()
        self.db.refresh(feed)
        return feed
