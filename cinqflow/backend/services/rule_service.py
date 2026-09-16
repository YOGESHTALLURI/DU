"""
Rule Service — Wave 1 Slice 4: Deterministic Data Quality Rules Engine

Handles:
- Rule CRUD with UNIQUE(feed_id, name) where is_deleted=FALSE
- Soft delete (is_deleted=TRUE, deleted_at, deleted_by) only allowed when all versions are DRAFT
- Immutable schema version pinning (rule versions pinned to schema_version_id, never silently float)
- Versioning: spawn new independent DRAFT version (e.g. v2) with new UUID, leaving previous version untouched
- Exhaustive deterministic backend validation for all 7 rule types (CUSTOM_SQL strictly excluded)
- Strict version immutability upon publishing
- Deterministic sample data execution engine against CSV bytes (up to 10,000 rows)
- Strict sample data isolation: failed_row_details persists ONLY row_number, field_name, reason (ZERO sample/cell values persisted)
- Audit event logging with ZERO sample/data values
"""
import uuid
import copy
import re
import io
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import HTTPException, status

from backend.models.feed import Feed
from backend.models.schema import (
    Schema,
    SchemaVersion,
    SchemaVersionStatusEnum,
    SchemaDataTypeEnum,
    SampleFile,
)
from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleTestRun,
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
    TestRunStatusEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.adapters.storage import get_storage_adapter
from backend.schemas.rule import (
    RuleCreateRequest,
    RuleVersionUpdateRequest,
    RulePublishRequest,
    RuleNewVersionRequest,
    RuleValidationReport,
    RuleResponse,
    RuleVersionSummary,
    RuleVersionDetail,
    RuleTestRunResponse,
    FailedRowDetail,
)


class RuleService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.storage = get_storage_adapter()

    def get_rule_by_id(self, rule_id: uuid.UUID) -> DataQualityRule:
        rule = self.db.query(DataQualityRule).filter(DataQualityRule.id == rule_id).first()
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Data quality rule {rule_id} not found",
            )
        return rule

    def get_rules_for_feed(self, feed_id: uuid.UUID, include_deleted: bool = False) -> List[RuleResponse]:
        query = self.db.query(DataQualityRule).filter(DataQualityRule.feed_id == feed_id)
        if not include_deleted:
            query = query.filter(DataQualityRule.is_deleted.is_(False))
        rules = query.all()
        return [self._serialize_rule(r) for r in rules]

    def get_rule_detail(self, rule_id: uuid.UUID) -> RuleResponse:
        rule = self.get_rule_by_id(rule_id)
        return self._serialize_rule(rule)

    def get_version_detail(self, rule_id: uuid.UUID, version_id: uuid.UUID) -> RuleVersionDetail:
        rule = self.get_rule_by_id(rule_id)
        version = (
            self.db.query(RuleVersion)
            .filter(RuleVersion.id == version_id, RuleVersion.rule_id == rule.id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rule version {version_id} not found for rule {rule_id}",
            )
        return self._serialize_version_detail(version)

    def create_rule(
        self, data: RuleCreateRequest, actor_id: str, actor_email: Optional[str] = None
    ) -> RuleResponse:
        feed = self.db.query(Feed).filter(Feed.id == data.feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {data.feed_id} not found",
            )

        schema = self.db.query(Schema).filter(Schema.feed_id == data.feed_id).first()
        if not schema:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Feed does not have an associated schema contract",
            )

        # Check published schema version exists
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
                detail="Feed must have a PUBLISHED schema version before creating a data quality rule",
            )

        pinned_schema_ver_id = data.schema_version_id or published_schema_ver.id

        # Verify pinned schema version exists
        schema_ver = self.db.query(SchemaVersion).filter(SchemaVersion.id == pinned_schema_ver_id).first()
        if not schema_ver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema version {pinned_schema_ver_id} not found",
            )

        # Enforce unique rule name per feed among non-deleted rules
        existing = (
            self.db.query(DataQualityRule)
            .filter(
                DataQualityRule.feed_id == data.feed_id,
                DataQualityRule.name == data.name,
                DataQualityRule.is_deleted.is_(False),
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A rule named '{data.name}' already exists for feed '{feed.name}'. Choose a unique name or edit the existing rule.",
            )

        rule = DataQualityRule(
            id=uuid.uuid4(),
            feed_id=feed.id,
            schema_id=schema.id,
            name=data.name,
            description=data.description,
            is_deleted=False,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(rule)
        self.db.flush()

        v1 = RuleVersion(
            id=uuid.uuid4(),
            rule_id=rule.id,
            version_number=1,
            schema_version_id=pinned_schema_ver_id,
            status=RuleVersionStatusEnum.DRAFT,
            rule_type=data.rule_type,
            target_field=data.target_field,
            severity=data.severity,
            rule_config=data.rule_config or {},
            error_message_template=data.error_message_template,
            change_notes="Initial draft rule version",
            needs_review=data.needs_review,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(v1)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.RULE_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="data_quality_rules",
            object_id=str(rule.id),
            after_state={
                "feed_id": str(feed.id),
                "name": rule.name,
                "target_field": v1.target_field,
                "rule_type": v1.rule_type.value,
                "schema_version_id": str(pinned_schema_ver_id),
                "version_number": 1,
            },
            description=f"Created data quality rule '{rule.name}' for feed {feed.name}",
        )
        self.db.commit()
        self.db.refresh(rule)
        return self._serialize_rule(rule)

    def update_draft_version(
        self,
        rule_id: uuid.UUID,
        version_id: uuid.UUID,
        data: RuleVersionUpdateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> RuleVersionDetail:
        rule = self.get_rule_by_id(rule_id)
        if rule.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify a deleted rule",
            )

        version = (
            self.db.query(RuleVersion)
            .filter(RuleVersion.id == version_id, RuleVersion.rule_id == rule.id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rule version {version_id} not found",
            )

        if version.status == RuleVersionStatusEnum.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify a published rule version; version is strictly immutable",
            )
        if version.status != RuleVersionStatusEnum.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot modify rule version with status '{version.status.value}'. Only DRAFT versions can be edited.",
            )

        changed_fields = []
        if data.rule_type is not None:
            version.rule_type = data.rule_type
            changed_fields.append("rule_type")
        if data.target_field is not None:
            version.target_field = data.target_field
            changed_fields.append("target_field")
        if data.severity is not None:
            version.severity = data.severity
            changed_fields.append("severity")
        if data.rule_config is not None:
            version.rule_config = data.rule_config
            changed_fields.append("rule_config")
        if data.error_message_template is not None:
            version.error_message_template = data.error_message_template
            changed_fields.append("error_message_template")
        if data.change_notes is not None:
            version.change_notes = data.change_notes
            changed_fields.append("change_notes")
        if data.needs_review is not None:
            version.needs_review = data.needs_review
            changed_fields.append("needs_review")

        version.updated_by = actor_id
        version.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.RULE_DRAFT_UPDATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="rule_versions",
            object_id=str(version.id),
            after_state={
                "rule_id": str(rule.id),
                "version_number": version.version_number,
                "changed_fields": changed_fields,
            },
            description=f"Updated draft rule version v{version.version_number} for rule '{rule.name}'",
        )
        self.db.commit()
        self.db.refresh(version)
        return self._serialize_version_detail(version)

    def validate_rule_version(
        self, rule_id: uuid.UUID, version_id: uuid.UUID
    ) -> RuleValidationReport:
        rule = self.get_rule_by_id(rule_id)
        version = (
            self.db.query(RuleVersion)
            .filter(RuleVersion.id == version_id, RuleVersion.rule_id == rule.id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rule version {version_id} not found",
            )

        errors: List[str] = []
        warnings: List[str] = []

        if rule.is_deleted:
            errors.append("Rule is deleted and cannot be validated")

        # Pinned schema version check
        schema_version = (
            self.db.query(SchemaVersion)
            .filter(SchemaVersion.id == version.schema_version_id)
            .first()
        )
        if not schema_version:
            errors.append(f"Pinned schema version {version.schema_version_id} does not exist")
            return RuleValidationReport(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                rule_id=rule.id,
                version_id=version.id,
                rule_type=version.rule_type,
                target_field=version.target_field,
            )

        schema_fields = {f.field_name: f for f in schema_version.fields}

        # 1. Target field existence
        target_f = schema_fields.get(version.target_field)
        if not target_f:
            errors.append(
                f"Target field '{version.target_field}' does not exist in pinned schema version v{schema_version.version_number}"
            )

        # 2. Template length check
        if version.error_message_template and len(version.error_message_template) > 500:
            errors.append("Error message template exceeds 500 characters limit")

        # 3. Rule type specific validation
        rtype = version.rule_type
        cfg = version.rule_config or {}

        if rtype == RuleTypeEnum.NOT_NULL:
            # Accepts empty or {}; warn on unknown keys
            if cfg and any(k not in () for k in cfg.keys()):
                warnings.append("NOT_NULL rule does not require configuration parameters; extra parameters ignored")

        elif rtype == RuleTypeEnum.RANGE:
            if target_f and target_f.data_type not in (SchemaDataTypeEnum.INTEGER, SchemaDataTypeEnum.DECIMAL):
                errors.append(
                    f"RANGE rule requires numeric target field (INTEGER or DECIMAL), got {target_f.data_type.value}"
                )
            has_min = "min" in cfg and cfg["min"] is not None
            has_max = "max" in cfg and cfg["max"] is not None
            if not has_min and not has_max:
                errors.append("RANGE rule requires at least one of 'min' or 'max' boundary")
            else:
                min_val = None
                max_val = None
                if has_min:
                    try:
                        min_val = float(cfg["min"])
                    except (ValueError, TypeError):
                        errors.append(f"RANGE 'min' value '{cfg['min']}' is not a valid number")
                if has_max:
                    try:
                        max_val = float(cfg["max"])
                    except (ValueError, TypeError):
                        errors.append(f"RANGE 'max' value '{cfg['max']}' is not a valid number")
                if min_val is not None and max_val is not None and min_val > max_val:
                    errors.append(f"RANGE 'min' ({min_val}) cannot be greater than 'max' ({max_val})")

        elif rtype == RuleTypeEnum.REGEX:
            pattern = cfg.get("pattern")
            if not pattern or not isinstance(pattern, str) or len(pattern.strip()) == 0:
                errors.append("REGEX rule requires a non-empty 'pattern' string")
            else:
                try:
                    re.compile(pattern)
                except re.error as e:
                    errors.append(f"Invalid regex pattern '{pattern}': {str(e)}")
            if target_f and target_f.data_type != SchemaDataTypeEnum.STRING:
                warnings.append(
                    f"REGEX rule on non-STRING field '{target_f.field_name}' ({target_f.data_type.value}) will evaluate string representation"
                )

        elif rtype == RuleTypeEnum.ENUM:
            allowed = cfg.get("allowed_values")
            if not isinstance(allowed, list) or len(allowed) == 0:
                errors.append("ENUM rule requires a non-empty 'allowed_values' list")
            else:
                non_strings = [v for v in allowed if not isinstance(v, str)]
                if non_strings:
                    errors.append(f"All elements in ENUM 'allowed_values' must be strings (found: {non_strings[:3]})")
                # Check duplicates
                seen = set()
                dups = set()
                for v in allowed:
                    if v in seen:
                        dups.add(v)
                    seen.add(v)
                if dups:
                    errors.append(f"ENUM 'allowed_values' contains duplicate values: {list(dups)}")

        elif rtype == RuleTypeEnum.LENGTH:
            if target_f and target_f.data_type != SchemaDataTypeEnum.STRING:
                warnings.append(
                    f"LENGTH rule on non-STRING field '{target_f.field_name}' ({target_f.data_type.value}) will evaluate string length"
                )
            has_min_len = "min_length" in cfg and cfg["min_length"] is not None
            has_max_len = "max_length" in cfg and cfg["max_length"] is not None
            if not has_min_len and not has_max_len:
                errors.append("LENGTH rule requires at least one of 'min_length' or 'max_length'")
            else:
                min_l = None
                max_l = None
                if has_min_len:
                    try:
                        min_l = int(cfg["min_length"])
                        if min_l < 0:
                            errors.append(f"LENGTH 'min_length' must be non-negative (got {min_l})")
                    except (ValueError, TypeError):
                        errors.append(f"LENGTH 'min_length' '{cfg['min_length']}' is not a valid integer")
                if has_max_len:
                    try:
                        max_l = int(cfg["max_length"])
                        if max_l < 0:
                            errors.append(f"LENGTH 'max_length' must be non-negative (got {max_l})")
                    except (ValueError, TypeError):
                        errors.append(f"LENGTH 'max_length' '{cfg['max_length']}' is not a valid integer")
                if min_l is not None and max_l is not None and min_l > max_l:
                    errors.append(f"LENGTH 'min_length' ({min_l}) cannot be greater than 'max_length' ({max_l})")

        elif rtype == RuleTypeEnum.DATE_RANGE:
            if target_f and target_f.data_type not in (SchemaDataTypeEnum.DATE, SchemaDataTypeEnum.TIMESTAMP):
                errors.append(
                    f"DATE_RANGE rule requires DATE or TIMESTAMP target field, got {target_f.data_type.value}"
                )
            fmt = cfg.get("format")
            if not fmt or not isinstance(fmt, str) or len(fmt.strip()) == 0:
                errors.append("DATE_RANGE rule requires a non-empty 'format' string")
            else:
                recognized_fmts = ["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "DD-MM-YYYY", "MM-DD-YYYY"]
                if fmt.upper() not in recognized_fmts:
                    errors.append(
                        f"Unrecognized date format '{fmt}'. Supported: {', '.join(recognized_fmts)}"
                    )

            has_min_d = "min_date" in cfg and cfg["min_date"] is not None
            has_max_d = "max_date" in cfg and cfg["max_date"] is not None
            if not has_min_d and not has_max_d:
                errors.append("DATE_RANGE rule requires at least one of 'min_date' or 'max_date'")
            else:
                parsed_min = None
                parsed_max = None
                if has_min_d:
                    parsed_min = self._parse_date_string(str(cfg["min_date"]), fmt)
                    if parsed_min is None:
                        errors.append(f"DATE_RANGE 'min_date' '{cfg['min_date']}' does not match format '{fmt}'")
                if has_max_d:
                    parsed_max = self._parse_date_string(str(cfg["max_date"]), fmt)
                    if parsed_max is None:
                        errors.append(f"DATE_RANGE 'max_date' '{cfg['max_date']}' does not match format '{fmt}'")
                if parsed_min and parsed_max and parsed_min > parsed_max:
                    errors.append(f"DATE_RANGE 'min_date' ({cfg['min_date']}) cannot be after 'max_date' ({cfg['max_date']})")

        elif rtype == RuleTypeEnum.CROSS_FIELD:
            cmp_field = cfg.get("compare_field")
            if not cmp_field or not isinstance(cmp_field, str) or len(cmp_field.strip()) == 0:
                errors.append("CROSS_FIELD rule requires a non-empty 'compare_field' string")
            else:
                if cmp_field == version.target_field:
                    errors.append("CROSS_FIELD rule cannot compare a field to itself")
                cmp_f = schema_fields.get(cmp_field)
                if not cmp_f:
                    errors.append(
                        f"Comparison field '{cmp_field}' does not exist in pinned schema version v{schema_version.version_number}"
                    )
                op = cfg.get("operator")
                valid_ops = ["EQ", "NE", "GT", "LT", "GTE", "LTE"]
                if not op or op not in valid_ops:
                    errors.append(f"CROSS_FIELD rule requires 'operator' to be one of: {', '.join(valid_ops)}")
                elif op in ["GT", "LT", "GTE", "LTE"] and target_f and cmp_f:
                    # Both numeric or both date
                    target_numeric = target_f.data_type in (SchemaDataTypeEnum.INTEGER, SchemaDataTypeEnum.DECIMAL)
                    cmp_numeric = cmp_f.data_type in (SchemaDataTypeEnum.INTEGER, SchemaDataTypeEnum.DECIMAL)
                    target_date = target_f.data_type in (SchemaDataTypeEnum.DATE, SchemaDataTypeEnum.TIMESTAMP)
                    cmp_date = cmp_f.data_type in (SchemaDataTypeEnum.DATE, SchemaDataTypeEnum.TIMESTAMP)

                    if not ((target_numeric and cmp_numeric) or (target_date and cmp_date)):
                        errors.append(
                            f"Ordering operator '{op}' requires both fields to be numeric or both date/timestamp (got {target_f.field_name}: {target_f.data_type.value}, {cmp_f.field_name}: {cmp_f.data_type.value})"
                        )

        return RuleValidationReport(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            rule_id=rule.id,
            version_id=version.id,
            rule_type=version.rule_type,
            target_field=version.target_field,
        )

    def test_rule_version(
        self,
        rule_id: uuid.UUID,
        version_id: uuid.UUID,
        sample_id: Optional[uuid.UUID],
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> RuleTestRunResponse:
        rule = self.get_rule_by_id(rule_id)
        if rule.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot test a deleted rule",
            )

        version = (
            self.db.query(RuleVersion)
            .filter(RuleVersion.id == version_id, RuleVersion.rule_id == rule.id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rule version {version_id} not found",
            )

        # 1. Fetch sample file
        if sample_id:
            sample = self.db.query(SampleFile).filter(SampleFile.id == sample_id, SampleFile.feed_id == rule.feed_id).first()
        else:
            sample = (
                self.db.query(SampleFile)
                .filter(SampleFile.feed_id == rule.feed_id)
                .order_by(SampleFile.created_at.desc())
                .first()
            )

        if not sample:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No sample file found for this feed to test against. Please upload a sample file in Step 2 first.",
            )

        # 2. Read sample CSV bytes
        try:
            raw_bytes = self.storage.read_file(sample.storage_path)
            # Read first 10,000 rows
            df = pd.read_csv(io.BytesIO(raw_bytes), nrows=10000)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to read or parse sample file: {str(e)}",
            )

        # 3. Check target column existence in sample
        target_col = version.target_field
        if target_col not in df.columns:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target field '{target_col}' not found in sample file columns: {list(df.columns)}",
            )

        total_rows = len(df)
        passed_rows = 0
        failed_rows = 0
        persisted_failures: List[Dict[str, Any]] = []
        transient_failures: List[Dict[str, Any]] = []

        cfg = version.rule_config or {}
        rtype = version.rule_type
        fmt = cfg.get("format", "YYYY-MM-DD")

        for idx, row in df.iterrows():
            row_num = idx + 1
            val = row[target_col]
            is_pass, reason = self._evaluate_row_rule(val, row, rtype, cfg, target_col, fmt)

            if is_pass:
                passed_rows += 1
            else:
                failed_rows += 1
                if len(persisted_failures) < 10:
                    # PERSISTED: ZERO actual values/sample cells
                    persisted_failures.append({
                        "row_number": row_num,
                        "field_name": target_col,
                        "reason": reason,
                    })
                    # TRANSIENT (for this HTTP response only): includes cell value preview
                    transient_val_str = "null" if pd.isna(val) else str(val)
                    transient_failures.append({
                        "row_number": row_num,
                        "field_name": target_col,
                        "reason": reason,
                        "value": transient_val_str,
                    })

        pass_rate = round((passed_rows / total_rows * 100.0), 2) if total_rows > 0 else 0.0

        test_run = RuleTestRun(
            id=uuid.uuid4(),
            rule_version_id=version.id,
            sample_id=sample.id,
            total_rows=total_rows,
            passed_rows=passed_rows,
            failed_rows=failed_rows,
            pass_rate=pass_rate,
            status=TestRunStatusEnum.COMPLETED,
            failed_row_details=persisted_failures,
            executed_by=actor_id,
            executed_at=datetime.now(timezone.utc),
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(test_run)
        self.db.flush()

        # Audit event logs ONLY aggregate statistics, ZERO sample data values
        self.audit.emit(
            action=AuditActionEnum.RULE_TEST_EXECUTED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="rule_test_runs",
            object_id=str(test_run.id),
            after_state={
                "rule_id": str(rule.id),
                "version_id": str(version.id),
                "sample_id": str(sample.id),
                "total_rows": total_rows,
                "passed_rows": passed_rows,
                "failed_rows": failed_rows,
                "pass_rate": pass_rate,
            },
            description=f"Executed test for rule '{rule.name}' v{version.version_number} against sample data: {pass_rate}% passed",
        )
        self.db.commit()
        self.db.refresh(test_run)

        resp = RuleTestRunResponse.model_validate(test_run)
        resp.transient_sample_failures = transient_failures
        return resp

    def publish_rule_version(
        self,
        rule_id: uuid.UUID,
        version_id: uuid.UUID,
        data: RulePublishRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> RuleVersionDetail:
        rule = self.get_rule_by_id(rule_id)
        if rule.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot publish a version of a deleted rule",
            )

        version = (
            self.db.query(RuleVersion)
            .filter(RuleVersion.id == version_id, RuleVersion.rule_id == rule.id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rule version {version_id} not found",
            )

        if version.status == RuleVersionStatusEnum.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Version is already published and immutable",
            )

        # Authoritative validation check before publish
        rep = self.validate_rule_version(rule_id, version_id)
        if not rep.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot publish rule: {'; '.join(rep.errors)}",
            )

        # Supersede any previous published versions
        prev_published = (
            self.db.query(RuleVersion)
            .filter(
                RuleVersion.rule_id == rule.id,
                RuleVersion.status == RuleVersionStatusEnum.PUBLISHED,
            )
            .all()
        )
        for prev in prev_published:
            prev.status = RuleVersionStatusEnum.SUPERSEDED
            prev.updated_by = actor_id

        # Compile deterministic execution spec
        compiled_spec = {
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "feed_id": str(rule.feed_id),
            "version_number": version.version_number,
            "schema_version_id": str(version.schema_version_id),
            "rule_type": version.rule_type.value,
            "target_field": version.target_field,
            "severity": version.severity.value,
            "rule_config": version.rule_config,
            "error_message_template": version.error_message_template,
            "needs_review": version.needs_review,
            "compiled_at": datetime.now(timezone.utc).isoformat(),
        }

        now = datetime.now(timezone.utc)
        version.status = RuleVersionStatusEnum.PUBLISHED
        version.compiled_spec = compiled_spec
        version.change_notes = data.change_notes or "Published via Rule Builder"
        version.published_by = actor_id
        version.published_at = now
        version.updated_by = actor_id
        version.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.RULE_PUBLISHED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="rule_versions",
            object_id=str(version.id),
            after_state={
                "rule_id": str(rule.id),
                "version_number": version.version_number,
                "schema_version_id": str(version.schema_version_id),
                "published_at": now.isoformat(),
                "rule_type": version.rule_type.value,
                "target_field": version.target_field,
            },
            description=f"Published rule '{rule.name}' version v{version.version_number}",
        )
        self.db.commit()
        self.db.refresh(version)
        return self._serialize_version_detail(version)

    def spawn_new_version(
        self,
        rule_id: uuid.UUID,
        data: RuleNewVersionRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> RuleVersionDetail:
        rule = self.get_rule_by_id(rule_id)
        if rule.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create versions for a deleted rule",
            )

        latest_ver = (
            self.db.query(RuleVersion)
            .filter(RuleVersion.rule_id == rule.id)
            .order_by(RuleVersion.version_number.desc())
            .first()
        )
        new_version_num = (latest_ver.version_number + 1) if latest_ver else 1

        # Determine pinned schema version
        schema_version_id = data.schema_version_id
        if not schema_version_id:
            # Default to feed's active published schema version
            schema = self.db.query(Schema).filter(Schema.feed_id == rule.feed_id).first()
            if schema and schema.active_version:
                schema_version_id = schema.active_version.id
            elif latest_ver:
                schema_version_id = latest_ver.schema_version_id
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Feed has no published schema version to pin",
                )

        schema_ver = self.db.query(SchemaVersion).filter(SchemaVersion.id == schema_version_id).first()
        if not schema_ver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema version {schema_version_id} not found",
            )

        new_version = RuleVersion(
            id=uuid.uuid4(),
            rule_id=rule.id,
            version_number=new_version_num,
            schema_version_id=schema_version_id,
            status=RuleVersionStatusEnum.DRAFT,
            rule_type=latest_ver.rule_type if latest_ver else RuleTypeEnum.NOT_NULL,
            target_field=latest_ver.target_field if latest_ver else "",
            severity=latest_ver.severity if latest_ver else RuleSeverityEnum.QUARANTINE,
            rule_config=copy.deepcopy(latest_ver.rule_config or {}) if latest_ver else {},
            error_message_template=latest_ver.error_message_template if latest_ver else None,
            change_notes=data.change_notes or f"Draft version {new_version_num}",
            needs_review=latest_ver.needs_review if latest_ver else False,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(new_version)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.RULE_VERSION_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="rule_versions",
            object_id=str(new_version.id),
            after_state={
                "rule_id": str(rule.id),
                "version_number": new_version.version_number,
                "schema_version_id": str(schema_version_id),
                "cloned_from_version": latest_ver.version_number if latest_ver else None,
            },
            description=f"Created new draft rule version v{new_version.version_number} for rule '{rule.name}'",
        )
        self.db.commit()
        self.db.refresh(new_version)
        return self._serialize_version_detail(new_version)

    def soft_delete_rule(
        self, rule_id: uuid.UUID, actor_id: str, actor_email: Optional[str] = None
    ) -> RuleResponse:
        rule = self.get_rule_by_id(rule_id)
        if rule.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rule is already deleted",
            )

        # Only allow soft-delete if all versions are DRAFT
        has_published_or_superseded = any(
            v.status in (RuleVersionStatusEnum.PUBLISHED, RuleVersionStatusEnum.SUPERSEDED)
            for v in rule.versions
        )
        if has_published_or_superseded:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete rule: rule has published or superseded versions. Published rules are immutable and cannot be deleted.",
            )

        rule.is_deleted = True
        rule.deleted_at = datetime.now(timezone.utc)
        rule.deleted_by = actor_id
        rule.updated_by = actor_id
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.RULE_DELETED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="data_quality_rules",
            object_id=str(rule.id),
            after_state={
                "rule_id": str(rule.id),
                "name": rule.name,
                "deleted_by": actor_id,
            },
            description=f"Soft-deleted data quality rule '{rule.name}'",
        )
        self.db.commit()
        self.db.refresh(rule)
        return self._serialize_rule(rule)

    # -------------------------------------------------------------
    # Evaluation helper for row-level rule testing
    # -------------------------------------------------------------
    def _evaluate_row_rule(
        self,
        val: Any,
        row: pd.Series,
        rtype: RuleTypeEnum,
        cfg: Dict[str, Any],
        target_col: str,
        fmt: str,
    ) -> Tuple[bool, str]:
        is_null = pd.isna(val) or val is None or str(val).strip() == ""

        if rtype == RuleTypeEnum.NOT_NULL:
            if is_null:
                return False, f"Field '{target_col}' is null or whitespace-only; NOT_NULL rule failed"
            return True, ""

        if is_null:
            # All other rules fail on null
            return False, f"Field '{target_col}' is null; rule requires a valid non-null value"

        if rtype == RuleTypeEnum.RANGE:
            try:
                num = float(str(val))
            except (ValueError, TypeError):
                return False, f"Field '{target_col}' value cannot be parsed as numeric"
            inclusive = cfg.get("inclusive", True)
            min_v = cfg.get("min")
            max_v = cfg.get("max")
            if min_v is not None:
                min_f = float(min_v)
                if inclusive and num < min_f:
                    return False, f"Field '{target_col}' numeric value is below minimum {min_f}"
                elif not inclusive and num <= min_f:
                    return False, f"Field '{target_col}' numeric value is not strictly greater than minimum {min_f}"
            if max_v is not None:
                max_f = float(max_v)
                if inclusive and num > max_f:
                    return False, f"Field '{target_col}' numeric value exceeds maximum {max_f}"
                elif not inclusive and num >= max_f:
                    return False, f"Field '{target_col}' numeric value is not strictly less than maximum {max_f}"
            return True, ""

        if rtype == RuleTypeEnum.REGEX:
            pat = cfg.get("pattern", "")
            try:
                if re.fullmatch(pat, str(val)):
                    return True, ""
                return False, f"Field '{target_col}' does not match regex pattern '{pat}'"
            except Exception as e:
                return False, f"Regex evaluation error: {str(e)}"

        if rtype == RuleTypeEnum.ENUM:
            allowed = cfg.get("allowed_values", [])
            case_sens = cfg.get("case_sensitive", True)
            s_val = str(val)
            if case_sens:
                if s_val in allowed:
                    return True, ""
            else:
                allowed_lower = [str(x).lower() for x in allowed]
                if s_val.lower() in allowed_lower:
                    return True, ""
            return False, f"Field '{target_col}' value is not in allowed ENUM set"

        if rtype == RuleTypeEnum.LENGTH:
            s_len = len(str(val))
            min_l = cfg.get("min_length")
            max_l = cfg.get("max_length")
            if min_l is not None and s_len < int(min_l):
                return False, f"Field '{target_col}' string length {s_len} is below minimum {min_l}"
            if max_l is not None and s_len > int(max_l):
                return False, f"Field '{target_col}' string length {s_len} exceeds maximum {max_l}"
            return True, ""

        if rtype == RuleTypeEnum.DATE_RANGE:
            parsed_d = self._parse_date_string(str(val), fmt)
            if parsed_d is None:
                return False, f"Field '{target_col}' cannot be parsed as date using format '{fmt}'"
            min_d_str = cfg.get("min_date")
            max_d_str = cfg.get("max_date")
            if min_d_str:
                min_d = self._parse_date_string(str(min_d_str), fmt)
                if min_d and parsed_d < min_d:
                    return False, f"Field '{target_col}' date is before minimum date {min_d_str}"
            if max_d_str:
                max_d = self._parse_date_string(str(max_d_str), fmt)
                if max_d and parsed_d > max_d:
                    return False, f"Field '{target_col}' date is after maximum date {max_d_str}"
            return True, ""

        if rtype == RuleTypeEnum.CROSS_FIELD:
            cmp_col = cfg.get("compare_field")
            if not cmp_col or cmp_col not in row:
                return False, f"Comparison column '{cmp_col}' not found in row data"
            cmp_val = row[cmp_col]
            if pd.isna(cmp_val) or cmp_val is None:
                return False, f"Comparison column '{cmp_col}' is null"
            op = cfg.get("operator", "EQ")

            # Try numeric comparison first if both castable, otherwise string/date
            try:
                n1, n2 = float(str(val)), float(str(cmp_val))
                v1, v2 = n1, n2
            except (ValueError, TypeError):
                # Try date comparison
                d1 = self._parse_date_string(str(val), fmt)
                d2 = self._parse_date_string(str(cmp_val), fmt)
                if d1 and d2:
                    v1, v2 = d1, d2
                else:
                    v1, v2 = str(val), str(cmp_val)

            if op == "EQ":
                passes = v1 == v2
            elif op == "NE":
                passes = v1 != v2
            elif op == "GT":
                passes = v1 > v2
            elif op == "LT":
                passes = v1 < v2
            elif op == "GTE":
                passes = v1 >= v2
            elif op == "LTE":
                passes = v1 <= v2
            else:
                passes = False

            if passes:
                return True, ""
            return False, f"Cross-field comparison failed: {target_col} {op} {cmp_col}"

        return False, "Unknown rule type"

    def _parse_date_string(self, val_str: str, fmt: str) -> Optional[datetime]:
        fmt_clean = fmt.strip().upper()
        patterns = {
            "YYYY-MM-DD": "%Y-%m-%d",
            "DD/MM/YYYY": "%d/%m/%Y",
            "MM/DD/YYYY": "%m/%d/%Y",
            "YYYY/MM/DD": "%Y/%m/%d",
            "DD-MM-YYYY": "%d-%m-%Y",
            "MM-DD-YYYY": "%m-%d-%Y",
        }
        py_fmt = patterns.get(fmt_clean, "%Y-%m-%d")
        try:
            return datetime.strptime(val_str.strip(), py_fmt)
        except (ValueError, TypeError):
            # Try dateutil parser fallback
            try:
                return pd.to_datetime(val_str, dayfirst=("DD" in fmt_clean)).to_pydatetime()
            except Exception:
                return None

    def _serialize_rule(self, r: DataQualityRule) -> RuleResponse:
        v_summaries = [
            RuleVersionSummary(
                id=v.id,
                rule_id=v.rule_id,
                version_number=v.version_number,
                schema_version_id=v.schema_version_id,
                schema_version_number=v.schema_version.version_number if v.schema_version else None,
                status=v.status,
                rule_type=v.rule_type,
                target_field=v.target_field,
                severity=v.severity,
                needs_review=v.needs_review,
                change_notes=v.change_notes,
                published_by=v.published_by,
                published_at=v.published_at,
            )
            for v in r.versions
        ]
        active_ver = next((v for v in v_summaries if v.status == RuleVersionStatusEnum.PUBLISHED), None)
        draft_ver = next((v for v in v_summaries if v.status == RuleVersionStatusEnum.DRAFT), None)

        return RuleResponse(
            id=r.id,
            feed_id=r.feed_id,
            feed_name=r.feed.name if r.feed else None,
            schema_id=r.schema_id,
            name=r.name,
            description=r.description,
            is_deleted=r.is_deleted,
            deleted_at=r.deleted_at,
            deleted_by=r.deleted_by,
            active_version=active_ver,
            draft_version=draft_ver,
            versions=v_summaries,
        )

    def _serialize_version_detail(self, v: RuleVersion) -> RuleVersionDetail:
        latest_run = v.test_runs[0] if v.test_runs else None
        run_resp = None
        if latest_run:
            run_resp = RuleTestRunResponse.model_validate(latest_run)

        return RuleVersionDetail(
            id=v.id,
            rule_id=v.rule_id,
            version_number=v.version_number,
            schema_version_id=v.schema_version_id,
            schema_version_number=v.schema_version.version_number if v.schema_version else None,
            status=v.status,
            rule_type=v.rule_type,
            target_field=v.target_field,
            severity=v.severity,
            rule_config=v.rule_config,
            error_message_template=v.error_message_template,
            change_notes=v.change_notes,
            compiled_spec=v.compiled_spec,
            published_by=v.published_by,
            published_at=v.published_at,
            needs_review=v.needs_review,
            latest_test_run=run_resp,
        )
