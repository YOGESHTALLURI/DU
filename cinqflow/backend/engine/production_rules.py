"""
Production Data Quality Rules Engine — Wave 2 Slice 1 (CF-V2-E7-05)

Executes active published Data Quality Rules in the production pipeline (Bronze -> Silver Raw):
- Evaluates all 7 rule types: NOT_NULL, RANGE, REGEX, ENUM, LENGTH, DATE_RANGE, CROSS_FIELD
- Enforces 4 severities:
  - INFO: logs telemetry, passes row
  - WARNING: logs telemetry, passes row
  - QUARANTINE: drops row, creates quarantine_record, logs telemetry
  - REJECT_FILE: aborts batch execution, cleans partial stage output, marks batch FAILED
- Aggregates per-rule execution telemetry for persistence in dq_results table
"""
import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
)
from backend.models.dq_result import DQActionTakenEnum


@dataclass
class RuleTelemetry:
    rule: DataQualityRule
    rule_version: RuleVersion
    total_rows: int = 0
    passed_rows: int = 0
    failed_rows: int = 0
    action_taken: DQActionTakenEnum = DQActionTakenEnum.PASSED
    duration_ms: int = 0


@dataclass
class RowEvaluationResult:
    is_valid: bool
    quarantined: bool
    reject_file: bool
    failing_rule_name: Optional[str] = None
    failing_field: Optional[str] = None
    failing_val: Optional[str] = None
    failing_severity: Optional[RuleSeverityEnum] = None
    reason_detail: Optional[str] = None


class ProductionRulesEngine:
    """
    Production rules evaluator for batch ingestion.
    """

    @classmethod
    def load_active_rules(
        cls,
        db: Session,
        feed_id: uuid.UUID,
        schema_version_id: uuid.UUID,
    ) -> List[Tuple[DataQualityRule, RuleVersion]]:
        """
        Loads all active (non-deleted) rules that have a PUBLISHED version
        pinned to the specified schema_version_id.
        """
        active_rules = (
            db.query(DataQualityRule)
            .filter(
                DataQualityRule.feed_id == feed_id,
                DataQualityRule.is_deleted.is_(False),
            )
            .all()
        )

        published_rules: List[Tuple[DataQualityRule, RuleVersion]] = []
        for rule in active_rules:
            pub_ver = (
                db.query(RuleVersion)
                .filter(
                    RuleVersion.rule_id == rule.id,
                    RuleVersion.status == RuleVersionStatusEnum.PUBLISHED,
                    RuleVersion.schema_version_id == schema_version_id,
                )
                .order_by(RuleVersion.version_number.desc())
                .first()
            )
            if pub_ver:
                published_rules.append((rule, pub_ver))

        return published_rules

    @classmethod
    def evaluate_rule_on_value(
        cls,
        row_dict: Dict[str, Optional[str]],
        r_ver: RuleVersion,
    ) -> Tuple[bool, Optional[str]]:
        """
        Deterministic evaluation of a single rule on a row dictionary.
        Returns: (violated: bool, reason_detail: Optional[str])
        """
        target_val = row_dict.get(r_ver.target_field.lower())
        rtype = r_ver.rule_type
        config = r_ver.rule_config or {}

        # 1. NOT_NULL
        if rtype == RuleTypeEnum.NOT_NULL:
            if target_val is None or target_val == "":
                return True, f"Field '{r_ver.target_field}' is null or empty"
            return False, None

        # For remaining rules, if value is null/empty and NOT_NULL is not explicitly set, skip
        if target_val is None or target_val == "":
            return False, None

        # 2. RANGE
        if rtype == RuleTypeEnum.RANGE:
            try:
                num = Decimal(str(target_val))
            except (InvalidOperation, ValueError):
                return True, f"Field '{r_ver.target_field}' value '{target_val}' is not numeric"

            min_val = config.get("min")
            max_val = config.get("max")
            inc_min = config.get("inclusive_min", True)
            inc_max = config.get("inclusive_max", True)

            if min_val is not None:
                min_dec = Decimal(str(min_val))
                if inc_min and num < min_dec:
                    return True, f"Value {num} is below minimum allowed {min_dec}"
                if not inc_min and num <= min_dec:
                    return True, f"Value {num} is less than or equal to minimum {min_dec}"

            if max_val is not None:
                max_dec = Decimal(str(max_val))
                if inc_max and num > max_dec:
                    return True, f"Value {num} exceeds maximum allowed {max_dec}"
                if not inc_max and num >= max_dec:
                    return True, f"Value {num} is greater than or equal to maximum {max_dec}"
            return False, None

        # 3. REGEX
        if rtype == RuleTypeEnum.REGEX:
            pat_str = config.get("pattern", "")
            if pat_str:
                try:
                    if not re.search(pat_str, str(target_val)):
                        return True, f"Value '{target_val}' does not match pattern '{pat_str}'"
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
                return True, f"Value '{target_val}' is not in allowed set {allowed}"
            return False, None

        # 5. LENGTH
        if rtype == RuleTypeEnum.LENGTH:
            s_len = len(str(target_val))
            min_l = config.get("min_length")
            max_l = config.get("max_length")
            exact_l = config.get("exact_length")

            if exact_l is not None and s_len != exact_l:
                return True, f"Length {s_len} does not match required exact length {exact_l}"
            if min_l is not None and s_len < min_l:
                return True, f"Length {s_len} is below minimum required {min_l}"
            if max_l is not None and s_len > max_l:
                return True, f"Length {s_len} exceeds maximum allowed {max_l}"
            return False, None

        # 6. DATE_RANGE
        if rtype == RuleTypeEnum.DATE_RANGE:
            fmt = config.get("format", "%Y-%m-%d")
            py_fmt = fmt.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
            try:
                dt_val = datetime.strptime(str(target_val), py_fmt).date()
            except ValueError:
                return True, f"Date value '{target_val}' does not match format '{fmt}'"

            min_d_str = config.get("min_date")
            max_d_str = config.get("max_date")
            if min_d_str:
                try:
                    min_d = datetime.strptime(min_d_str, "%Y-%m-%d").date()
                    if dt_val < min_d:
                        return True, f"Date {dt_val} is prior to minimum date {min_d}"
                except ValueError:
                    pass
            if max_d_str:
                try:
                    max_d = datetime.strptime(max_d_str, "%Y-%m-%d").date()
                    if dt_val > max_d:
                        return True, f"Date {dt_val} is after maximum date {max_d}"
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
                    return True, f"Field '{r_ver.target_field}' ({target_val}) does not equal '{sec_field}' ({sec_val})"
            elif operator == "NOT_EQUALS":
                if str(target_val) == str(sec_val):
                    return True, f"Field '{r_ver.target_field}' ({target_val}) equals '{sec_field}' ({sec_val}) but must not"
            elif operator in ["GREATER_THAN", "LESS_THAN"]:
                try:
                    d1 = Decimal(str(target_val))
                    d2 = Decimal(str(sec_val))
                    if operator == "GREATER_THAN" and not (d1 > d2):
                        return True, f"Field '{r_ver.target_field}' ({d1}) is not greater than '{sec_field}' ({d2})"
                    if operator == "LESS_THAN" and not (d1 < d2):
                        return True, f"Field '{r_ver.target_field}' ({d1}) is not less than '{sec_field}' ({d2})"
                except (InvalidOperation, ValueError, TypeError):
                    return True, "Non-numeric values in cross-field numeric comparison"
            return False, None

        return False, None
