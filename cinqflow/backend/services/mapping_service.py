"""
Mapping Service — Wave 1 Slice 3: Mapping Studio Foundation

Handles:
- Mapping entity CRUD with uniqueness rule: ONE mapping per (feed_id, canonical_model_id)
- Explicit schema version pinning
- Field-level mapping lines management (DRAFT only)
- Authoritative server-side validation for all 7 transforms & edge cases
- Strict version immutability upon publishing
- Explicit POST /mappings/{id}/versions endpoint for independent new DRAFT versions
- Audit event logging (no sample values in mapping tables or audit logs)
"""
import uuid
import copy
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.feed import Feed
from backend.models.schema import (
    Schema,
    SchemaVersion,
    SchemaVersionStatusEnum,
    SchemaDataTypeEnum,
    OnboardingSession,
    OnboardingStatusEnum,
)
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.mapping import (
    Mapping,
    MappingVersion,
    MappingLine,
    MappingVersionStatusEnum,
    TransformTypeEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.schemas.mapping import (
    MappingCreateRequest,
    MappingUpdateLinesRequest,
    MappingPublishRequest,
    MappingNewVersionRequest,
    MappingValidationReport,
    MappingResponse,
    MappingVersionSummary,
    MappingVersionDetail,
    MappingLineResponse,
)


class MappingService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def get_mapping_by_id(self, mapping_id: uuid.UUID) -> Mapping:
        mapping = self.db.query(Mapping).filter(Mapping.id == mapping_id).first()
        if not mapping:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mapping {mapping_id} not found",
            )
        return mapping

    def get_mappings_for_feed(self, feed_id: uuid.UUID) -> List[MappingResponse]:
        mappings = self.db.query(Mapping).filter(Mapping.feed_id == feed_id).all()
        return [self._serialize_mapping(m) for m in mappings]

    def create_mapping(
        self, data: MappingCreateRequest, actor_id: str, actor_email: Optional[str] = None
    ) -> MappingResponse:
        feed = self.db.query(Feed).filter(Feed.id == data.feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {data.feed_id} not found",
            )

        canonical_model = (
            self.db.query(CanonicalModel)
            .filter(CanonicalModel.id == data.canonical_model_id)
            .first()
        )
        if not canonical_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Canonical model {data.canonical_model_id} not found",
            )

        # Feed must have a published schema version
        schema = self.db.query(Schema).filter(Schema.feed_id == data.feed_id).first()
        if not schema:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Feed does not have an associated schema contract",
            )

        published_schema_ver = (
            self.db.query(SchemaVersion)
            .filter(
                SchemaVersion.schema_id == schema.id,
                SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
            )
            .order_by(SchemaVersion.version_number.desc())
            .first()
        )
        if not published_schema_ver:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Feed must have a PUBLISHED schema version before creating a mapping contract",
            )

        # Rule 8: Unique (feed_id, canonical_model_id)
        existing = (
            self.db.query(Mapping)
            .filter(
                Mapping.feed_id == data.feed_id,
                Mapping.canonical_model_id == data.canonical_model_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A mapping already exists for feed '{feed.name}' and canonical model '{canonical_model.name}'. Edit the existing mapping or spawn a new version.",
            )

        mapping_name = data.name or f"{feed.name} to {canonical_model.name}"
        mapping = Mapping(
            id=uuid.uuid4(),
            feed_id=feed.id,
            schema_id=schema.id,
            canonical_model_id=canonical_model.id,
            name=mapping_name,
            description=data.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(mapping)
        self.db.flush()

        # Create Version 1 in DRAFT, explicitly pinned to published schema version
        v1 = MappingVersion(
            id=uuid.uuid4(),
            mapping_id=mapping.id,
            version_number=1,
            schema_version_id=published_schema_ver.id,
            status=MappingVersionStatusEnum.DRAFT,
            change_notes="Initial draft mapping version",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(v1)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.MAPPING_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="mappings",
            object_id=str(mapping.id),
            after_state={
                "feed_id": str(feed.id),
                "canonical_model_id": str(canonical_model.id),
                "mapping_name": mapping.name,
                "version_1_id": str(v1.id),
                "pinned_schema_version_id": str(published_schema_ver.id),
            },
            description=f"Created mapping contract '{mapping.name}' for feed {feed.name}",
        )
        self.db.commit()
        self.db.refresh(mapping)
        return self._serialize_mapping(mapping)

    def get_version_detail(
        self, mapping_id: uuid.UUID, version_id: uuid.UUID
    ) -> MappingVersionDetail:
        mapping = self.get_mapping_by_id(mapping_id)
        version = (
            self.db.query(MappingVersion)
            .filter(
                MappingVersion.id == version_id,
                MappingVersion.mapping_id == mapping.id,
            )
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mapping version {version_id} not found for mapping {mapping_id}",
            )
        return self._serialize_version_detail(version)

    def update_draft_lines(
        self,
        mapping_id: uuid.UUID,
        version_id: uuid.UUID,
        data: MappingUpdateLinesRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> MappingVersionDetail:
        mapping = self.get_mapping_by_id(mapping_id)
        version = (
            self.db.query(MappingVersion)
            .filter(
                MappingVersion.id == version_id,
                MappingVersion.mapping_id == mapping.id,
            )
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mapping version {version_id} not found",
            )

        if version.status == MappingVersionStatusEnum.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify a published mapping version; version is strictly immutable",
            )

        if version.status != MappingVersionStatusEnum.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot modify mapping version with status '{version.status.value}'. Only DRAFT versions can be edited.",
            )

        # Validate canonical field IDs belong to the canonical model
        valid_canonical_ids = {
            f.id: f
            for f in self.db.query(CanonicalField)
            .filter(CanonicalField.canonical_model_id == mapping.canonical_model_id)
            .all()
        }

        # Check for duplicate target fields in request
        seen_targets = set()
        for line in data.lines:
            if line.canonical_field_id not in valid_canonical_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Canonical field {line.canonical_field_id} does not belong to canonical model {mapping.canonical_model.name}",
                )
            if line.canonical_field_id in seen_targets:
                target_field = valid_canonical_ids[line.canonical_field_id]
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Duplicate mapping line for target canonical attribute '{target_field.field_name}'",
                )
            seen_targets.add(line.canonical_field_id)

        # Clear existing lines for this version
        self.db.query(MappingLine).filter(MappingLine.mapping_version_id == version.id).delete()
        self.db.flush()

        # Insert new lines (Notice: NEVER storing sample values, only clean metadata)
        new_lines = []
        for line in data.lines:
            ml = MappingLine(
                id=uuid.uuid4(),
                mapping_version_id=version.id,
                canonical_field_id=line.canonical_field_id,
                source_field_names=line.source_field_names or [],
                transform_type=line.transform_type,
                transform_params=line.transform_params or {},
                notes=line.notes,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(ml)
            new_lines.append(ml)

        version.updated_by = actor_id
        version.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.MAPPING_DRAFT_UPDATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="mapping_versions",
            object_id=str(version.id),
            after_state={
                "mapping_id": str(mapping.id),
                "version_number": version.version_number,
                "lines_count": len(new_lines),
            },
            description=f"Updated mapping draft v{version.version_number} lines for mapping '{mapping.name}'",
        )
        self.db.commit()
        self.db.refresh(version)
        return self._serialize_version_detail(version)

    def validate_mapping_version(
        self, mapping_id: uuid.UUID, version_id: uuid.UUID
    ) -> MappingValidationReport:
        mapping = self.get_mapping_by_id(mapping_id)
        version = (
            self.db.query(MappingVersion)
            .filter(
                MappingVersion.id == version_id,
                MappingVersion.mapping_id == mapping.id,
            )
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mapping version {version_id} not found",
            )

        errors: List[str] = []
        warnings: List[str] = []

        # Target Canonical Attributes
        canonical_fields = (
            self.db.query(CanonicalField)
            .filter(CanonicalField.canonical_model_id == mapping.canonical_model_id)
            .order_by(CanonicalField.ordinal_position)
            .all()
        )
        canonical_by_id = {f.id: f for f in canonical_fields}
        canonical_by_name = {f.field_name: f for f in canonical_fields}

        # Source Schema Fields from pinned schema version
        schema_version = (
            self.db.query(SchemaVersion)
            .filter(SchemaVersion.id == version.schema_version_id)
            .first()
        )
        if not schema_version:
            errors.append(f"Pinned schema version {version.schema_version_id} does not exist")
            return MappingValidationReport(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                unmapped_required_canonical_fields=[],
                unmapped_optional_canonical_fields=[],
                unmapped_source_fields=[],
            )

        source_fields = {f.field_name: f for f in schema_version.fields}
        source_field_names_set = set(source_fields.keys())

        # Mapped lines
        lines = (
            self.db.query(MappingLine)
            .filter(MappingLine.mapping_version_id == version.id)
            .all()
        )
        mapped_target_ids = {l.canonical_field_id: l for l in lines}
        used_source_field_names = set()

        # 1. Target Completeness Check
        unmapped_required: List[str] = []
        unmapped_optional: List[str] = []
        for cf in canonical_fields:
            if cf.id not in mapped_target_ids:
                if cf.is_required:
                    unmapped_required.append(cf.field_name)
                    errors.append(f"Required canonical field '{cf.field_name}' is unmapped")
                else:
                    unmapped_optional.append(cf.field_name)

        # 2. Line Validation & Transform Edge Cases
        for line in lines:
            cf = canonical_by_id.get(line.canonical_field_id)
            if not cf:
                errors.append(f"Mapping line references unknown canonical field ID {line.canonical_field_id}")
                continue

            # Verify all source fields exist in pinned schema
            for sf_name in line.source_field_names:
                used_source_field_names.add(sf_name)
                root_part = sf_name.split(".")[0].split("[")[0]
                if sf_name not in source_field_names_set and root_part not in source_field_names_set:
                    errors.append(
                        f"Source field '{sf_name}' mapped to '{cf.field_name}' does not exist in pinned schema v{schema_version.version_number}"
                    )

            # Transform-specific validations
            ttype = line.transform_type
            params = line.transform_params or {}

            if ttype == TransformTypeEnum.DIRECT:
                if len(line.source_field_names) != 1:
                    errors.append(f"DIRECT transform for '{cf.field_name}' requires exactly 1 source field")
                else:
                    sf_name = line.source_field_names[0]
                    sf = source_fields.get(sf_name)
                    if sf:
                        # Type compatibility check
                        if sf.data_type == SchemaDataTypeEnum.STRING and cf.data_type in (
                            SchemaDataTypeEnum.DECIMAL,
                            SchemaDataTypeEnum.INTEGER,
                            SchemaDataTypeEnum.DATE,
                            SchemaDataTypeEnum.TIMESTAMP,
                        ):
                            warnings.append(
                                f"DIRECT mapping from STRING '{sf_name}' to {cf.data_type.value} '{cf.field_name}' will require runtime casting"
                            )
                        elif sf.data_type == SchemaDataTypeEnum.DATE and cf.data_type in (
                            SchemaDataTypeEnum.INTEGER,
                            SchemaDataTypeEnum.DECIMAL,
                        ):
                            errors.append(
                                f"Incompatible DIRECT type mapping: cannot cast DATE '{sf_name}' to {cf.data_type.value} '{cf.field_name}'"
                            )

            elif ttype == TransformTypeEnum.CONSTANT:
                if "value" not in params:
                    errors.append(f"CONSTANT transform for '{cf.field_name}' requires 'value' parameter")
                else:
                    val = params["value"]
                    # Test constant conversion against target canonical data type
                    if cf.data_type == SchemaDataTypeEnum.INTEGER:
                        try:
                            int(str(val))
                        except (ValueError, TypeError):
                            errors.append(f"Constant value '{val}' cannot be converted to INTEGER for '{cf.field_name}'")
                    elif cf.data_type == SchemaDataTypeEnum.DECIMAL:
                        try:
                            float(str(val))
                        except (ValueError, TypeError):
                            errors.append(f"Constant value '{val}' cannot be converted to DECIMAL for '{cf.field_name}'")
                    elif cf.data_type == SchemaDataTypeEnum.BOOLEAN:
                        if not isinstance(val, bool) and str(val).lower() not in ("true", "false", "1", "0"):
                            errors.append(f"Constant value '{val}' cannot be converted to BOOLEAN for '{cf.field_name}'")
                    elif cf.data_type in (SchemaDataTypeEnum.DATE, SchemaDataTypeEnum.TIMESTAMP):
                        if not isinstance(val, str) or len(val.strip()) == 0:
                            errors.append(f"Constant value '{val}' is not a valid date string for '{cf.field_name}'")

            elif ttype == TransformTypeEnum.VALUE_MAP:
                if len(line.source_field_names) < 1:
                    errors.append(f"VALUE_MAP transform for '{cf.field_name}' requires at least 1 source field")

                dictionary = params.get("dictionary")
                if not isinstance(dictionary, dict) or len(dictionary) == 0:
                    errors.append(f"VALUE_MAP transform for '{cf.field_name}' requires a non-empty 'dictionary'")

                on_unmapped = params.get("on_unmapped", "DEFAULT")
                if on_unmapped not in ("DEFAULT", "NULL", "ERROR"):
                    errors.append(f"Invalid on_unmapped '{on_unmapped}' for VALUE_MAP on '{cf.field_name}'. Must be DEFAULT, NULL, or ERROR")
                elif on_unmapped == "DEFAULT" and "default" not in params:
                    errors.append(f"VALUE_MAP transform for '{cf.field_name}' with on_unmapped='DEFAULT' requires a 'default' parameter")

            elif ttype == TransformTypeEnum.DATE_FORMAT:
                if len(line.source_field_names) != 1:
                    errors.append(f"DATE_FORMAT transform for '{cf.field_name}' requires exactly 1 source field")
                if cf.data_type not in (SchemaDataTypeEnum.DATE, SchemaDataTypeEnum.TIMESTAMP):
                    errors.append(f"DATE_FORMAT transform can only target DATE or TIMESTAMP fields (got {cf.data_type.value} for '{cf.field_name}')")

                src_fmt = params.get("source_format")
                tgt_fmt = params.get("target_format", "YYYY-MM-DD")
                if not src_fmt or not isinstance(src_fmt, str) or len(src_fmt.strip()) == 0:
                    errors.append(f"DATE_FORMAT transform for '{cf.field_name}' requires non-empty 'source_format'")
                if not tgt_fmt or not isinstance(tgt_fmt, str) or len(tgt_fmt.strip()) == 0:
                    errors.append(f"DATE_FORMAT transform for '{cf.field_name}' requires non-empty 'target_format'")

            elif ttype == TransformTypeEnum.CONCAT:
                if len(line.source_field_names) < 2:
                    errors.append(f"CONCAT transform for '{cf.field_name}' requires at least 2 source fields (got {len(line.source_field_names)})")
                if "delimiter" not in params or not isinstance(params.get("delimiter"), str):
                    errors.append(f"CONCAT transform for '{cf.field_name}' requires a string 'delimiter' parameter")

            elif ttype == TransformTypeEnum.COALESCE:
                if len(line.source_field_names) < 2:
                    errors.append(f"COALESCE transform for '{cf.field_name}' requires at least 2 source fields (got {len(line.source_field_names)})")

            elif ttype == TransformTypeEnum.STRING_CLEAN:
                if len(line.source_field_names) != 1:
                    errors.append(f"STRING_CLEAN transform for '{cf.field_name}' requires exactly 1 source field")
                casing = params.get("casing", "NONE")
                if casing not in ("UPPER", "LOWER", "TRIM", "NONE"):
                    errors.append(f"Invalid casing '{casing}' for STRING_CLEAN on '{cf.field_name}'. Must be UPPER, LOWER, TRIM, or NONE")

            elif ttype == TransformTypeEnum.EXPLODE:
                array_path = params.get("array_path") or (line.source_field_names[0] if line.source_field_names else None)
                if not array_path:
                    errors.append(f"EXPLODE transform for '{cf.field_name}' requires 'array_path' parameter or 1 source field")
                if "outer_join" in params and not isinstance(params["outer_join"], bool):
                    errors.append(f"EXPLODE transform for '{cf.field_name}' parameter 'outer_join' must be a boolean")

            elif ttype == TransformTypeEnum.FLATTEN:
                if "max_depth" in params:
                    try:
                        md = int(params["max_depth"])
                        if md < 1 or md > 20:
                            errors.append(f"FLATTEN transform for '{cf.field_name}' parameter 'max_depth' must be between 1 and 20")
                    except (ValueError, TypeError):
                        errors.append(f"FLATTEN transform for '{cf.field_name}' parameter 'max_depth' must be an integer")
                if "separator" in params and not isinstance(params["separator"], str):
                    errors.append(f"FLATTEN transform for '{cf.field_name}' parameter 'separator' must be a string")

            elif ttype == TransformTypeEnum.PATH_EXTRACT:
                path = params.get("path") or (line.source_field_names[0] if line.source_field_names else None)
                if not path or not isinstance(path, str) or not path.strip():
                    errors.append(f"PATH_EXTRACT transform for '{cf.field_name}' requires 'path' parameter or 1 source field")

            elif ttype == TransformTypeEnum.ARRAY_MAP:
                array_path = params.get("array_path") or (line.source_field_names[0] if line.source_field_names else None)
                if not array_path:
                    errors.append(f"ARRAY_MAP transform for '{cf.field_name}' requires 'array_path' parameter or 1 source field")
                if "delimiter" in params and params["delimiter"] is not None and not isinstance(params["delimiter"], str):
                    errors.append(f"ARRAY_MAP transform for '{cf.field_name}' parameter 'delimiter' must be a string or null")

            elif ttype == TransformTypeEnum.UNNEST:
                path = params.get("path") or (line.source_field_names[0] if line.source_field_names else None)
                if not path:
                    errors.append(f"UNNEST transform for '{cf.field_name}' requires 'path' parameter or 1 source field")
                if "properties" in params and not isinstance(params["properties"], list):
                    errors.append(f"UNNEST transform for '{cf.field_name}' parameter 'properties' must be a list of strings")

        # 3. Unmapped Source Attributes
        unmapped_sources = sorted(list(source_field_names_set - used_source_field_names))

        return MappingValidationReport(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            unmapped_required_canonical_fields=unmapped_required,
            unmapped_optional_canonical_fields=unmapped_optional,
            unmapped_source_fields=unmapped_sources,
        )

    def publish_mapping_version(
        self,
        mapping_id: uuid.UUID,
        version_id: uuid.UUID,
        data: MappingPublishRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> MappingVersionDetail:
        mapping = self.get_mapping_by_id(mapping_id)
        version = (
            self.db.query(MappingVersion)
            .filter(
                MappingVersion.id == version_id,
                MappingVersion.mapping_id == mapping.id,
            )
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mapping version {version_id} not found",
            )

        if version.status == MappingVersionStatusEnum.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Version is already published and immutable",
            )

        # Authoritative backend validation before publish
        report = self.validate_mapping_version(mapping_id, version_id)
        if not report.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot publish mapping: {'; '.join(report.errors)}",
            )

        # Supersede any previous published version
        prev_published = (
            self.db.query(MappingVersion)
            .filter(
                MappingVersion.mapping_id == mapping.id,
                MappingVersion.status == MappingVersionStatusEnum.PUBLISHED,
            )
            .all()
        )
        for prev in prev_published:
            prev.status = MappingVersionStatusEnum.SUPERSEDED
            prev.updated_by = actor_id

        # Compile deterministic execution spec
        compiled_spec = self._compile_spec(mapping, version)

        now = datetime.now(timezone.utc)
        version.status = MappingVersionStatusEnum.PUBLISHED
        version.compiled_spec = compiled_spec
        version.change_notes = data.change_notes or "Published via Mapping Studio"
        version.published_by = actor_id
        version.published_at = now
        version.updated_by = actor_id
        version.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.MAPPING_PUBLISHED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="mapping_versions",
            object_id=str(version.id),
            after_state={
                "mapping_id": str(mapping.id),
                "version_number": version.version_number,
                "schema_version_id": str(version.schema_version_id),
                "published_at": now.isoformat(),
            },
            description=f"Published mapping version v{version.version_number} for mapping '{mapping.name}'",
        )

        # Update onboarding session step completion if in progress
        session = (
            self.db.query(OnboardingSession)
            .filter(OnboardingSession.feed_id == mapping.feed_id)
            .first()
        )
        if session:
            completed_steps = list(session.completed_steps or [])
            if 4 not in completed_steps:
                completed_steps.append(4)
                session.completed_steps = sorted(list(set(completed_steps)))
                session.updated_by = actor_id
                self.audit.emit(
                    action=AuditActionEnum.ONBOARDING_STEP_COMPLETED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="onboarding_sessions",
                    object_id=str(session.id),
                    after_state={"completed_step": 4, "completed_steps": session.completed_steps},
                    description=f"Completed Step 4 (Mapping Studio) for feed {mapping.feed.name}",
                )

        self.db.commit()
        self.db.refresh(version)
        return self._serialize_version_detail(version)

    def spawn_new_version(
        self,
        mapping_id: uuid.UUID,
        data: MappingNewVersionRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> MappingVersionDetail:
        """
        Creates an independent new DRAFT mapping version (e.g. v2) inheriting lines from the latest version.
        Leaves the existing version (e.g. v1) strictly immutable and unmutated.
        """
        mapping = self.get_mapping_by_id(mapping_id)

        # Determine new version number
        latest_version = (
            self.db.query(MappingVersion)
            .filter(MappingVersion.mapping_id == mapping.id)
            .order_by(MappingVersion.version_number.desc())
            .first()
        )
        new_version_num = (latest_version.version_number + 1) if latest_version else 1

        # Determine pinned schema version
        schema_version_id = data.schema_version_id
        if not schema_version_id:
            # Default to mapping's schema active published version or previous version's pinned schema
            if latest_version:
                schema_version_id = latest_version.schema_version_id
            else:
                schema = self.db.query(Schema).filter(Schema.feed_id == mapping.feed_id).first()
                if not schema or not schema.active_version:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Feed has no published schema version to pin",
                    )
                schema_version_id = schema.active_version.id

        # Verify schema_version exists
        schema_ver = self.db.query(SchemaVersion).filter(SchemaVersion.id == schema_version_id).first()
        if not schema_ver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema version {schema_version_id} not found",
            )

        new_version = MappingVersion(
            id=uuid.uuid4(),
            mapping_id=mapping.id,
            version_number=new_version_num,
            schema_version_id=schema_version_id,
            status=MappingVersionStatusEnum.DRAFT,
            change_notes=data.change_notes or f"Draft version {new_version_num}",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(new_version)
        self.db.flush()

        # Deep-copy lines from previous version
        if latest_version:
            for old_line in latest_version.lines:
                new_line = MappingLine(
                    id=uuid.uuid4(),
                    mapping_version_id=new_version.id,
                    canonical_field_id=old_line.canonical_field_id,
                    source_field_names=list(old_line.source_field_names or []),
                    transform_type=old_line.transform_type,
                    transform_params=copy.deepcopy(old_line.transform_params or {}),
                    notes=old_line.notes,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                self.db.add(new_line)
            self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.MAPPING_VERSION_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="mapping_versions",
            object_id=str(new_version.id),
            after_state={
                "mapping_id": str(mapping.id),
                "version_number": new_version.version_number,
                "schema_version_id": str(schema_version_id),
                "cloned_from_version": latest_version.version_number if latest_version else None,
            },
            description=f"Created new draft mapping version v{new_version.version_number} for '{mapping.name}'",
        )
        self.db.commit()
        self.db.refresh(new_version)
        return self._serialize_version_detail(new_version)

    def _compile_spec(self, mapping: Mapping, version: MappingVersion) -> Dict[str, Any]:
        """Compiles the deterministic execution specification for the mapping."""
        lines = (
            self.db.query(MappingLine)
            .filter(MappingLine.mapping_version_id == version.id)
            .all()
        )
        fields_spec = []
        for line in lines:
            cf = line.canonical_field
            fields_spec.append({
                "target_field": cf.field_name,
                "target_data_type": cf.data_type.value,
                "is_required": cf.is_required,
                "source_fields": line.source_field_names,
                "transform_type": line.transform_type.value,
                "transform_params": line.transform_params,
            })

        return {
            "feed_id": str(mapping.feed_id),
            "feed_name": mapping.feed.name,
            "canonical_model": mapping.canonical_model.name,
            "mapping_version_number": version.version_number,
            "schema_version_id": str(version.schema_version_id),
            "schema_version_number": version.schema_version.version_number if version.schema_version else None,
            "compiled_at": datetime.now(timezone.utc).isoformat(),
            "field_count": len(fields_spec),
            "fields": fields_spec,
        }

    def _serialize_mapping(self, m: Mapping) -> MappingResponse:
        versions_summary = [
            MappingVersionSummary(
                id=v.id,
                mapping_id=v.mapping_id,
                version_number=v.version_number,
                schema_version_id=v.schema_version_id,
                schema_version_number=v.schema_version.version_number if v.schema_version else None,
                status=v.status,
                change_notes=v.change_notes,
                published_by=v.published_by,
                published_at=v.published_at,
            )
            for v in m.versions
        ]
        active_ver = next((v for v in versions_summary if v.status == MappingVersionStatusEnum.PUBLISHED), None)
        draft_ver = next((v for v in versions_summary if v.status == MappingVersionStatusEnum.DRAFT), None)

        return MappingResponse(
            id=m.id,
            feed_id=m.feed_id,
            feed_name=m.feed.name,
            schema_id=m.schema_id,
            canonical_model_id=m.canonical_model_id,
            canonical_model_name=m.canonical_model.name,
            name=m.name,
            description=m.description,
            active_version=active_ver,
            draft_version=draft_ver,
            versions=versions_summary,
        )

    def _serialize_version_detail(self, v: MappingVersion) -> MappingVersionDetail:
        lines_resp = [
            MappingLineResponse(
                id=l.id,
                mapping_version_id=l.mapping_version_id,
                canonical_field_id=l.canonical_field_id,
                canonical_field_name=l.canonical_field.field_name,
                canonical_data_type=l.canonical_field.data_type.value,
                canonical_is_required=l.canonical_field.is_required,
                canonical_ordinal_position=l.canonical_field.ordinal_position,
                source_field_names=l.source_field_names,
                transform_type=l.transform_type,
                transform_params=l.transform_params,
                notes=l.notes,
            )
            for l in sorted(v.lines, key=lambda x: x.canonical_field.ordinal_position if x.canonical_field else 0)
        ]

        return MappingVersionDetail(
            id=v.id,
            mapping_id=v.mapping_id,
            version_number=v.version_number,
            schema_version_id=v.schema_version_id,
            schema_version_number=v.schema_version.version_number if v.schema_version else None,
            status=v.status,
            compiled_spec=v.compiled_spec,
            change_notes=v.change_notes,
            published_by=v.published_by,
            published_at=v.published_at,
            lines=lines_resp,
        )

    def test_structural_transform(
        self,
        transform_type: TransformTypeEnum,
        transform_params: Dict[str, Any],
        source_fields: List[str],
        sample_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Executes an isolated structural transform against sample JSON/dict input.
        Returns extracted result, output type, and diagnostics.
        """
        from backend.engine.structural_transforms import StructuralTransformEngine
        try:
            result = StructuralTransformEngine.evaluate(
                transform_type=transform_type,
                transform_params=transform_params,
                source_fields=source_fields,
                row_or_obj=sample_input,
            )
            return {
                "success": True,
                "transform_type": transform_type.value,
                "result": result,
                "result_type": type(result).__name__,
            }
        except Exception as e:
            return {
                "success": False,
                "transform_type": transform_type.value,
                "error": str(e),
            }
