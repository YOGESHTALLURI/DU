"""
Sandbox Pipeline Execution Engine — Wave 1 Slice 5 (CF-V1-E4-02)

Executes feed pipeline deterministically in isolated Sandbox Mode:
1. Reads sample file bytes via StorageAdapter (representative sample from Step 2)
2. Validates records against published Schema Contract
3. Evaluates all active published Data Quality Rules (all 7 rule types)
4. Applies Canonical Model field transformations (all 7 transform types)
5. Computes row reconciliation balance (total_rows = canonical_rows + quarantined_rows)
6. Produces privacy-safe Evidence Pack with masked preview

STRICT GUARANTEE:
Zero writes to production tables (`batches`, `batch_stages`, `quarantine_records`, `input_registry`).
"""
import io
import csv
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.feed import Feed
from backend.models.schema import (
    SampleFile,
    Schema,
    SchemaVersion,
    SchemaVersionStatusEnum,
    SchemaDataTypeEnum,
)
from backend.models.mapping import (
    Mapping,
    MappingVersion,
    MappingVersionStatusEnum,
    TransformTypeEnum,
)
from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
)
from backend.models.approval import (
    SandboxTestRun,
    SandboxRunStatusEnum,
)
from backend.adapters.storage import get_storage_adapter


class SandboxExecutor:
    """
    Executes in-memory sandbox pipeline on sample data without contaminating production.
    """

    def __init__(self, db: Session):
        self.db = db
        self.storage = get_storage_adapter()

    def run_sandbox_test(
        self,
        feed_id: uuid.UUID,
        actor_id: str,
        max_rows: int = 10000,
    ) -> SandboxTestRun:
        start_time = time.time()

        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {feed_id} not found",
            )

        # 1. Retrieve representative sample file
        sample_file = (
            self.db.query(SampleFile)
            .filter(SampleFile.feed_id == feed_id)
            .order_by(SampleFile.created_at.desc())
            .first()
        )
        if not sample_file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sandbox test cannot run: No sample file uploaded for this feed (Step 2 prerequisite missing)",
            )

        # 2. Retrieve published schema version
        schema_obj = self.db.query(Schema).filter(Schema.feed_id == feed_id).first()
        if not schema_obj:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sandbox test cannot run: No schema contract found for this feed (Step 3 prerequisite missing)",
            )

        published_schema_ver = (
            self.db.query(SchemaVersion)
            .filter(
                SchemaVersion.schema_id == schema_obj.id,
                SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
            )
            .order_by(SchemaVersion.version_number.desc())
            .first()
        )
        if not published_schema_ver:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sandbox test cannot run: Schema contract does not have a PUBLISHED version (found draft only)",
            )

        # 3. Retrieve published mapping version
        mapping_obj = self.db.query(Mapping).filter(Mapping.feed_id == feed_id).first()
        if not mapping_obj:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sandbox test cannot run: No canonical mapping contract found for this feed (Step 4 prerequisite missing)",
            )

        published_mapping_ver = (
            self.db.query(MappingVersion)
            .filter(
                MappingVersion.mapping_id == mapping_obj.id,
                MappingVersion.status == MappingVersionStatusEnum.PUBLISHED,
            )
            .order_by(MappingVersion.version_number.desc())
            .first()
        )
        if not published_mapping_ver:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sandbox test cannot run: Canonical mapping contract does not have a PUBLISHED version (found draft only)",
            )

        # Verify mapping is pinned to active schema version
        if published_mapping_ver.schema_version_id != published_schema_ver.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sandbox test cannot run: Published mapping version v{published_mapping_ver.version_number} is pinned to schema version {published_mapping_ver.schema_version_id}, but active schema version is {published_schema_ver.id}. Version alignment required.",
            )

        # 4. Retrieve active published DQ rules pinned to this schema version
        active_rules = (
            self.db.query(DataQualityRule)
            .filter(
                DataQualityRule.feed_id == feed_id,
                DataQualityRule.is_deleted.is_(False),
            )
            .all()
        )

        published_rules_to_run: List[Tuple[DataQualityRule, RuleVersion]] = []
        for r in active_rules:
            # Find published version pinned to active schema
            pub_ver = (
                self.db.query(RuleVersion)
                .filter(
                    RuleVersion.rule_id == r.id,
                    RuleVersion.status == RuleVersionStatusEnum.PUBLISHED,
                    RuleVersion.schema_version_id == published_schema_ver.id,
                )
                .order_by(RuleVersion.version_number.desc())
                .first()
            )
            if pub_ver:
                published_rules_to_run.append((r, pub_ver))

        # 5. Read sample file bytes
        try:
            raw_bytes = self.storage.read_file(sample_file.storage_path)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read sample file from storage: {str(e)}",
            )

        # Parse CSV
        try:
            text_stream = io.StringIO(raw_bytes.decode("utf-8-sig"))
            reader = csv.reader(text_stream)
            header = next(reader, None)
            if not header:
                raise ValueError("Sample file contains no header row")
            rows = list(reader)
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            failed_run = SandboxTestRun(
                id=uuid.uuid4(),
                feed_id=feed_id,
                sample_file_id=sample_file.id,
                schema_version_id=published_schema_ver.id,
                mapping_version_id=published_mapping_ver.id,
                status=SandboxRunStatusEnum.FAILED,
                total_rows=0,
                passed_rows=0,
                quarantined_rows=0,
                dropped_rows=0,
                pass_rate=0.0,
                reconciliation_status="FAILED",
                error_message=f"Failed to parse CSV: {str(e)}",
                execution_duration_ms=duration_ms,
                executed_by=actor_id,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(failed_run)
            self.db.commit()
            self.db.refresh(failed_run)
            return failed_run

        header_indices = {col.strip().lower(): idx for idx, col in enumerate(header)}
        total_rows = min(len(rows), max_rows)
        sample_slice = rows[:total_rows]

        # Initialize tracking metrics
        passed_rows_count = 0
        quarantined_rows_count = 0
        has_reject_file_violation = False

        # Per-rule breakdown metrics: {rule_name: {type, severity, evaluated, failed}}
        rule_metrics: Dict[str, Dict[str, Any]] = {}
        for rule, r_ver in published_rules_to_run:
            rule_metrics[rule.name] = {
                "rule_id": str(rule.id),
                "version_id": str(r_ver.id),
                "rule_type": r_ver.rule_type.value,
                "severity": r_ver.severity.value,
                "target_field": r_ver.target_field,
                "evaluated_count": 0,
                "failed_count": 0,
            }

        canonical_records_preview: List[Dict[str, Any]] = []

        # 6. Stream and evaluate each row
        for row in sample_slice:
            row_dict = {}
            for col_name, idx in header_indices.items():
                row_dict[col_name] = row[idx].strip() if idx < len(row) else None

            # A. Evaluate Schema Contract Constraints
            schema_invalid, schema_reason = self._evaluate_schema_row(row_dict, published_schema_ver)

            # B. Evaluate DQ Rules
            row_quarantined = False
            if schema_invalid:
                row_quarantined = True
            else:
                for rule, r_ver in published_rules_to_run:
                    rule_metric = rule_metrics[rule.name]
                    rule_metric["evaluated_count"] += 1

                    violated, reason = self._evaluate_rule_row(row_dict, r_ver)
                    if violated:
                        rule_metric["failed_count"] += 1
                        if r_ver.severity in [RuleSeverityEnum.QUARANTINE, RuleSeverityEnum.REJECT_FILE]:
                            row_quarantined = True
                        if r_ver.severity == RuleSeverityEnum.REJECT_FILE:
                            has_reject_file_violation = True

            # C. Transform Valid Rows to Canonical Model
            if not row_quarantined:
                passed_rows_count += 1
                if len(canonical_records_preview) < 5:
                    canonical_row = self._transform_canonical_row(row_dict, published_mapping_ver)
                    masked_row = self._mask_sensitive_fields(canonical_row)
                    canonical_records_preview.append(masked_row)
            else:
                quarantined_rows_count += 1

        # 7. Check Reconciliation
        is_balanced = (total_rows == passed_rows_count + quarantined_rows_count)
        reconciliation_status = "BALANCED" if is_balanced else "UNBALANCED"
        pass_rate = round((passed_rows_count / total_rows * 100), 2) if total_rows > 0 else 100.0

        duration_ms = int((time.time() - start_time) * 1000)

        # 8. Record in sandbox_test_runs table
        run_record = SandboxTestRun(
            id=uuid.uuid4(),
            feed_id=feed_id,
            sample_file_id=sample_file.id,
            schema_version_id=published_schema_ver.id,
            mapping_version_id=published_mapping_ver.id,
            status=SandboxRunStatusEnum.SUCCESS,
            total_rows=total_rows,
            passed_rows=passed_rows_count,
            quarantined_rows=quarantined_rows_count,
            dropped_rows=0,
            pass_rate=pass_rate,
            reconciliation_status=reconciliation_status,
            rule_metrics=rule_metrics,
            canonical_sample_preview=canonical_records_preview,
            has_reject_file_violation=has_reject_file_violation,
            execution_duration_ms=duration_ms,
            executed_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(run_record)
        self.db.commit()
        self.db.refresh(run_record)
        return run_record

    def _evaluate_schema_row(self, row_dict: Dict[str, Optional[str]], schema_ver: SchemaVersion) -> Tuple[bool, Optional[str]]:
        """Validate row against published schema field requirements."""
        for field in schema_ver.fields:
            val = row_dict.get(field.field_name.lower())
            if field.is_required and (val is None or val == ""):
                return True, f"Required field '{field.field_name}' is missing or empty"
        return False, None

    def _evaluate_rule_row(self, row_dict: Dict[str, Optional[str]], r_ver: RuleVersion) -> Tuple[bool, Optional[str]]:
        """Evaluate a single rule on a row dictionary using deterministic logic."""
        target_val = row_dict.get(r_ver.target_field.lower())
        rtype = r_ver.rule_type
        config = r_ver.rule_config or {}

        # 1. NOT_NULL
        if rtype == RuleTypeEnum.NOT_NULL:
            if target_val is None or target_val == "":
                return True, f"{r_ver.target_field} is null or empty"
            return False, None

        # For remaining rules, if value is null/empty and NOT_NULL is not explicitly set, null is typically skipped
        if target_val is None or target_val == "":
            return False, None

        # 2. RANGE
        if rtype == RuleTypeEnum.RANGE:
            try:
                num = Decimal(str(target_val))
            except (InvalidOperation, ValueError):
                return True, f"{r_ver.target_field} value '{target_val}' is not numeric"

            min_val = config.get("min")
            max_val = config.get("max")
            inc_min = config.get("inclusive_min", True)
            inc_max = config.get("inclusive_max", True)

            if min_val is not None:
                min_dec = Decimal(str(min_val))
                if inc_min and num < min_dec:
                    return True, f"{num} < min {min_dec}"
                if not inc_min and num <= min_dec:
                    return True, f"{num} <= min {min_dec}"

            if max_val is not None:
                max_dec = Decimal(str(max_val))
                if inc_max and num > max_dec:
                    return True, f"{num} > max {max_dec}"
                if not inc_max and num >= max_dec:
                    return True, f"{num} >= max {max_dec}"
            return False, None

        # 3. REGEX
        if rtype == RuleTypeEnum.REGEX:
            pat_str = config.get("pattern", "")
            if pat_str:
                try:
                    if not re.search(pat_str, str(target_val)):
                        return True, f"Value does not match regex pattern {pat_str}"
                except re.error:
                    pass
            return False, None

        # 4. ENUM
        if rtype == RuleTypeEnum.ENUM:
            allowed = config.get("allowed_values", [])
            case_sens = config.get("case_sensitive", True)
            val_cmp = str(target_val) if case_sens else str(target_val).lower()
            allowed_cmp = [str(x) if case_sens else str(x).lower() for x in allowed]
            if val_cmp not in allowed_cmp:
                return True, f"Value not in allowed values"
            return False, None

        # 5. LENGTH
        if rtype == RuleTypeEnum.LENGTH:
            s_len = len(str(target_val))
            min_l = config.get("min_length")
            max_l = config.get("max_length")
            exact_l = config.get("exact_length")

            if exact_l is not None and s_len != exact_l:
                return True, f"Length {s_len} != exact {exact_l}"
            if min_l is not None and s_len < min_l:
                return True, f"Length {s_len} < min {min_l}"
            if max_l is not None and s_len > max_l:
                return True, f"Length {s_len} > max {max_l}"
            return False, None

        # 6. DATE_RANGE
        if rtype == RuleTypeEnum.DATE_RANGE:
            fmt = config.get("format", "%Y-%m-%d")
            # Python strptime format translation if needed
            py_fmt = fmt.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
            try:
                dt_val = datetime.strptime(str(target_val), py_fmt).date()
            except ValueError:
                return True, f"Date '{target_val}' does not match format {fmt}"

            min_d_str = config.get("min_date")
            max_d_str = config.get("max_date")
            if min_d_str:
                try:
                    min_d = datetime.strptime(min_d_str, "%Y-%m-%d").date()
                    if dt_val < min_d:
                        return True, f"Date {dt_val} < min {min_d}"
                except ValueError:
                    pass
            if max_d_str:
                try:
                    max_d = datetime.strptime(max_d_str, "%Y-%m-%d").date()
                    if dt_val > max_d:
                        return True, f"Date {dt_val} > max {max_d}"
                except ValueError:
                    pass
            return False, None

        # 7. CROSS_FIELD
        if rtype == RuleTypeEnum.CROSS_FIELD:
            sec_field = config.get("secondary_field", "")
            operator = config.get("operator", "EQUALS")
            sec_val = row_dict.get(sec_field.lower())

            if operator == "EQUALS":
                if str(target_val) != str(sec_val):
                    return True, f"{target_val} != {sec_val}"
            elif operator == "NOT_EQUALS":
                if str(target_val) == str(sec_val):
                    return True, f"{target_val} == {sec_val}"
            elif operator in ["GREATER_THAN", "LESS_THAN"]:
                try:
                    d1 = Decimal(str(target_val))
                    d2 = Decimal(str(sec_val))
                    if operator == "GREATER_THAN" and not (d1 > d2):
                        return True, f"{d1} not > {d2}"
                    if operator == "LESS_THAN" and not (d1 < d2):
                        return True, f"{d1} not < {d2}"
                except (InvalidOperation, ValueError, TypeError):
                    return True, "Non-numeric values in cross-field comparison"
            return False, None

        return False, None

    def _transform_canonical_row(self, row_dict: Dict[str, Optional[str]], mapping_ver: MappingVersion) -> Dict[str, Any]:
        """Applies mapping lines to generate canonical model record."""
        canonical_record = {}
        from backend.engine.structural_transforms import StructuralTransformEngine
        for line in mapping_ver.lines:
            target_name = line.canonical_field.field_name if line.canonical_field else "unknown_field"
            ttype = line.transform_type
            params = line.transform_params or {}
            src_names = line.source_field_names or []

            if ttype in [
                TransformTypeEnum.EXPLODE,
                TransformTypeEnum.FLATTEN,
                TransformTypeEnum.PATH_EXTRACT,
                TransformTypeEnum.ARRAY_MAP,
                TransformTypeEnum.UNNEST,
            ]:
                canonical_record[target_name] = StructuralTransformEngine.evaluate(
                    transform_type=ttype,
                    transform_params=params,
                    source_fields=src_names,
                    row_or_obj=row_dict,
                )

            elif ttype == TransformTypeEnum.DIRECT:
                src = src_names[0] if src_names else None
                canonical_record[target_name] = row_dict.get(src.lower()) if src else None

            elif ttype == TransformTypeEnum.CONSTANT:
                canonical_record[target_name] = params.get("value")

            elif ttype == TransformTypeEnum.VALUE_MAP:
                src = src_names[0] if src_names else None
                src_val = row_dict.get(src.lower()) if src else None
                dictionary = params.get("dictionary", {})
                on_unmapped = params.get("on_unmapped", "DEFAULT")
                fallback = params.get("default")
                if src_val in dictionary:
                    canonical_record[target_name] = dictionary[src_val]
                elif on_unmapped == "NULL":
                    canonical_record[target_name] = None
                else:
                    canonical_record[target_name] = fallback

            elif ttype == TransformTypeEnum.DATE_FORMAT:
                src = src_names[0] if src_names else None
                src_val = row_dict.get(src.lower()) if src else None
                src_fmt = params.get("source_format", "%Y-%m-%d").replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
                tgt_fmt = params.get("target_format", "%Y-%m-%d").replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
                if src_val:
                    try:
                        d = datetime.strptime(src_val, src_fmt)
                        canonical_record[target_name] = d.strftime(tgt_fmt)
                    except ValueError:
                        canonical_record[target_name] = src_val
                else:
                    canonical_record[target_name] = None

            elif ttype == TransformTypeEnum.CONCAT:
                delimiter = params.get("delimiter", " ")
                parts = [row_dict.get(s.lower(), "") or "" for s in src_names]
                canonical_record[target_name] = delimiter.join(parts)

            elif ttype == TransformTypeEnum.COALESCE:
                found = None
                for s in src_names:
                    v = row_dict.get(s.lower())
                    if v is not None and v != "":
                        found = v
                        break
                canonical_record[target_name] = found

            elif ttype == TransformTypeEnum.STRING_CLEAN:
                src = src_names[0] if src_names else None
                val = row_dict.get(src.lower()) if src else ""
                if val is not None:
                    if params.get("trim", True):
                        val = val.strip()
                    casing = params.get("casing", "NONE")
                    if casing == "UPPER":
                        val = val.upper()
                    elif casing == "LOWER":
                        val = val.lower()
                    canonical_record[target_name] = val
                else:
                    canonical_record[target_name] = None

        return canonical_record

    def _mask_sensitive_fields(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive patient identifiable fields for safe UI preview."""
        masked = {}
        sensitive_keywords = ["name", "dob", "birth", "ssn", "identifier", "phone", "email", "address", "zip"]
        for k, v in record.items():
            k_lower = k.lower()
            if any(kw in k_lower for kw in sensitive_keywords) and isinstance(v, str) and len(v) > 0:
                if len(v) <= 2:
                    masked[k] = "**"
                else:
                    masked[k] = f"{v[0]}***{v[-1]}"
            else:
                masked[k] = v
        return masked
