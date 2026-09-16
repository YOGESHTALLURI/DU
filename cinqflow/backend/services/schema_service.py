"""
Schema Service — Wave 1 Slice 1

Manages Schema contracts, draft authoring, immutability of published versions,
and strict lineage back to source profiling runs.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.feed import Feed
from backend.models.schema import (
    Schema,
    SchemaVersion,
    SchemaField,
    ProfilingRun,
    SchemaVersionStatusEnum,
    SchemaDataTypeEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.schemas.schema import SchemaFieldCreate, SchemaCreateRequest, SchemaDraftUpdateRequest


class SchemaService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def create_schema(
        self,
        request: SchemaCreateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> Schema:
        """
        Create a new schema contract for a feed.
        Creates version 1 as DRAFT.
        If source_profiling_run_id is provided, verifies lineage and populates initial fields
        from profiling facts if initial_fields was omitted.
        """
        feed = self.db.query(Feed).filter(Feed.id == request.feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {request.feed_id} not found",
            )

        source_run = None
        source_sample_id = None
        if request.source_profiling_run_id:
            source_run = (
                self.db.query(ProfilingRun)
                .filter(
                    ProfilingRun.id == request.source_profiling_run_id,
                    ProfilingRun.feed_id == feed.id,
                )
                .first()
            )
            if not source_run:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Profiling run {request.source_profiling_run_id} not found for feed {feed.id}",
                )
            source_sample_id = source_run.sample_file_id

        schema = Schema(
            id=uuid.uuid4(),
            feed_id=feed.id,
            name=request.name,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(schema)
        self.db.flush()

        # Create Version 1 as DRAFT
        version = SchemaVersion(
            id=uuid.uuid4(),
            schema_id=schema.id,
            version_number=1,
            status=SchemaVersionStatusEnum.DRAFT,
            change_notes="Initial draft version",
            source_profiling_run_id=source_run.id if source_run else None,
            source_sample_file_id=source_sample_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(version)
        self.db.flush()

        # Seed fields
        fields_to_add: List[SchemaField] = []
        if request.initial_fields:
            for f in request.initial_fields:
                fields_to_add.append(
                    SchemaField(
                        id=uuid.uuid4(),
                        schema_version_id=version.id,
                        field_name=f.field_name,
                        ordinal_position=f.ordinal_position,
                        data_type=f.data_type,
                        is_nullable=f.is_nullable,
                        is_required=f.is_required,
                        format_pattern=f.format_pattern,
                        description=f.description,
                        source_metadata=f.source_metadata,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
        elif source_run and source_run.column_stats:
            # Seed decisions from profiling observational facts
            for stat in source_run.column_stats:
                # Inferred date format hint if available
                detected_fmt = None
                if stat.detected_date_patterns and len(stat.detected_date_patterns) > 0:
                    detected_fmt = stat.detected_date_patterns[0].get("pattern")

                fields_to_add.append(
                    SchemaField(
                        id=uuid.uuid4(),
                        schema_version_id=version.id,
                        field_name=stat.column_name,
                        ordinal_position=stat.ordinal_position,
                        data_type=stat.inferred_type,
                        is_nullable=(stat.null_count > 0),
                        is_required=(stat.null_count == 0),
                        format_pattern=detected_fmt,
                        description=f"Auto-seeded from profiling run {source_run.id}",
                        source_metadata={
                            "profiling_inferred_type": stat.inferred_type.value,
                            "profiling_null_pct": stat.null_percentage,
                            "profiling_distinct_pct": stat.distinct_percentage,
                        },
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )

        for sf in fields_to_add:
            self.db.add(sf)

        self.audit.emit(
            action=AuditActionEnum.SCHEMA_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="schemas",
            object_id=str(schema.id),
            after_state={
                "name": schema.name,
                "feed_id": str(feed.id),
                "version_id": str(version.id),
                "field_count": len(fields_to_add),
                "lineage_run_id": str(source_run.id) if source_run else None,
            },
            description=f"Created schema contract '{schema.name}' for feed {feed.name} (v1 Draft)",
        )
        self.db.commit()
        return self.get_schema(schema.id)

    def get_schema(self, schema_id: uuid.UUID) -> Schema:
        schema = self.db.query(Schema).filter(Schema.id == schema_id).first()
        if not schema:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema {schema_id} not found",
            )
        return schema

    def list_schemas_for_feed(self, feed_id: uuid.UUID) -> List[Schema]:
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {feed_id} not found",
            )
        return (
            self.db.query(Schema)
            .filter(Schema.feed_id == feed_id)
            .order_by(Schema.created_at.desc())
            .all()
        )

    def get_schema_version(self, schema_id: uuid.UUID, version_id: uuid.UUID) -> SchemaVersion:
        version = (
            self.db.query(SchemaVersion)
            .filter(
                SchemaVersion.id == version_id,
                SchemaVersion.schema_id == schema_id,
            )
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema version {version_id} not found for schema {schema_id}",
            )
        return version

    def update_draft_version(
        self,
        schema_id: uuid.UUID,
        version_id: uuid.UUID,
        request: SchemaDraftUpdateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> SchemaVersion:
        """
        Update fields and change notes in a DRAFT version.
        STRICT IMMUTABILITY RULE: Cannot modify a PUBLISHED version.
        """
        version = self.get_schema_version(schema_id, version_id)
        if version.status != SchemaVersionStatusEnum.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot modify version with status '{version.status.value}'. Published versions are strictly immutable.",
            )

        # Update metadata
        if request.change_notes is not None:
            version.change_notes = request.change_notes
        version.updated_by = actor_id
        version.updated_at = datetime.now(timezone.utc)

        # Replace fields
        self.db.query(SchemaField).filter(SchemaField.schema_version_id == version.id).delete()
        for f in request.fields:
            sf = SchemaField(
                id=uuid.uuid4(),
                schema_version_id=version.id,
                field_name=f.field_name,
                ordinal_position=f.ordinal_position,
                data_type=f.data_type,
                is_nullable=f.is_nullable,
                is_required=f.is_required,
                format_pattern=f.format_pattern,
                description=f.description,
                source_metadata=f.source_metadata,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(sf)

        self.audit.emit(
            action=AuditActionEnum.SCHEMA_DRAFT_UPDATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="schema_versions",
            object_id=str(version.id),
            after_state={
                "version_number": version.version_number,
                "field_count": len(request.fields),
            },
            description=f"Updated draft schema version {version.version_number} with {len(request.fields)} fields",
        )
        self.db.commit()
        return self.get_schema_version(schema_id, version_id)

    def publish_schema_version(
        self,
        schema_id: uuid.UUID,
        version_id: uuid.UUID,
        change_notes: Optional[str],
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> SchemaVersion:
        """
        Publish a schema version.
        Locks the version permanently.
        Supersedes previous published versions of the same schema.
        """
        version = self.get_schema_version(schema_id, version_id)
        if version.status == SchemaVersionStatusEnum.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Version is already published",
            )

        if not version.fields or len(version.fields) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot publish a schema version with no fields",
            )

        # Supersede any currently published version
        existing_published = (
            self.db.query(SchemaVersion)
            .filter(
                SchemaVersion.schema_id == schema_id,
                SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
            )
            .all()
        )
        for ep in existing_published:
            ep.status = SchemaVersionStatusEnum.SUPERSEDED
            ep.updated_by = actor_id
            ep.updated_at = datetime.now(timezone.utc)

        version.status = SchemaVersionStatusEnum.PUBLISHED
        if change_notes:
            version.change_notes = change_notes
        version.published_by = actor_id
        version.published_at = datetime.now(timezone.utc)
        version.updated_by = actor_id
        version.updated_at = datetime.now(timezone.utc)

        self.audit.emit(
            action=AuditActionEnum.SCHEMA_PUBLISHED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="schema_versions",
            object_id=str(version.id),
            after_state={
                "version_number": version.version_number,
                "status": version.status.value,
                "published_by": actor_id,
            },
            description=f"Published schema version v{version.version_number} (now immutable)",
        )
        self.db.commit()
        return self.get_schema_version(schema_id, version_id)

    def create_new_draft_version(
        self,
        schema_id: uuid.UUID,
        source_version_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> SchemaVersion:
        """
        Create a new draft version by cloning an existing version's fields.
        Increments version_number.
        """
        schema = self.get_schema(schema_id)
        source_ver = self.get_schema_version(schema_id, source_version_id)

        max_ver = max((v.version_number for v in schema.versions), default=1)
        new_ver_number = max_ver + 1

        new_version = SchemaVersion(
            id=uuid.uuid4(),
            schema_id=schema.id,
            version_number=new_ver_number,
            status=SchemaVersionStatusEnum.DRAFT,
            change_notes=f"Draft created from v{source_ver.version_number}",
            source_profiling_run_id=source_ver.source_profiling_run_id,
            source_sample_file_id=source_ver.source_sample_file_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(new_version)
        self.db.flush()

        for f in source_ver.fields:
            sf = SchemaField(
                id=uuid.uuid4(),
                schema_version_id=new_version.id,
                field_name=f.field_name,
                ordinal_position=f.ordinal_position,
                data_type=f.data_type,
                is_nullable=f.is_nullable,
                is_required=f.is_required,
                format_pattern=f.format_pattern,
                description=f.description,
                source_metadata=f.source_metadata,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(sf)

        self.audit.emit(
            action=AuditActionEnum.SCHEMA_VERSION_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="schema_versions",
            object_id=str(new_version.id),
            after_state={
                "version_number": new_version.version_number,
                "cloned_from": source_ver.version_number,
            },
            description=f"Created schema version v{new_version.version_number} draft from v{source_ver.version_number}",
        )
        self.db.commit()
        return self.get_schema_version(schema_id, new_version.id)
