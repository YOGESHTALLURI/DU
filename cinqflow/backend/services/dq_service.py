"""
Wave 2 Slice 1 Service — Data Quality Service (CF-V2-E7-05)
"""
import uuid
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.pipeline import Batch, BatchStage
from backend.models.rule import DataQualityRule, RuleVersion
from backend.schemas.dq_result import (
    DQResultResponse,
    DQBatchRuleItem,
    DQBatchSummaryResponse,
)


class DQService:
    def __init__(self, db: Session):
        self.db = db

    def list_executions(
        self,
        batch_id: Optional[uuid.UUID] = None,
        rule_version_id: Optional[uuid.UUID] = None,
        action_taken: Optional[DQActionTakenEnum] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        query = (
            self.db.query(DQResult, RuleVersion, DataQualityRule)
            .join(RuleVersion, DQResult.rule_version_id == RuleVersion.id)
            .join(DataQualityRule, RuleVersion.rule_id == DataQualityRule.id)
        )

        if batch_id:
            query = query.filter(DQResult.batch_id == batch_id)
        if rule_version_id:
            query = query.filter(DQResult.rule_version_id == rule_version_id)
        if action_taken:
            query = query.filter(DQResult.action_taken == action_taken)

        total = query.count()
        rows = (
            query.order_by(DQResult.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = []
        for dq_res, r_ver, rule in rows:
            items.append({
                "id": dq_res.id,
                "batch_id": dq_res.batch_id,
                "stage_id": dq_res.stage_id,
                "rule_version_id": dq_res.rule_version_id,
                "rule_name": rule.name,
                "rule_type": r_ver.rule_type,
                "severity": r_ver.severity,
                "total_rows_evaluated": dq_res.total_rows_evaluated,
                "passed_rows": dq_res.passed_rows,
                "failed_rows": dq_res.failed_rows,
                "pass_rate": float(dq_res.pass_rate),
                "action_taken": dq_res.action_taken,
                "execution_duration_ms": dq_res.execution_duration_ms,
                "created_at": dq_res.created_at,
            })
        return items, total

    def get_batch_summary(self, batch_id: uuid.UUID) -> DQBatchSummaryResponse:
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found",
            )

        rows = (
            self.db.query(DQResult, RuleVersion, DataQualityRule)
            .join(RuleVersion, DQResult.rule_version_id == RuleVersion.id)
            .join(DataQualityRule, RuleVersion.rule_id == DataQualityRule.id)
            .filter(DQResult.batch_id == batch_id)
            .order_by(RuleVersion.target_field.asc())
            .all()
        )

        total_rules = len(rows)
        total_evaluated = 0
        total_violations = 0
        has_quarantine = False
        has_reject = False

        rules_list: List[DQBatchRuleItem] = []
        for dq_res, r_ver, rule in rows:
            total_evaluated = max(total_evaluated, dq_res.total_rows_evaluated)
            total_violations += dq_res.failed_rows
            if dq_res.action_taken == DQActionTakenEnum.QUARANTINED_ROWS:
                has_quarantine = True
            elif dq_res.action_taken == DQActionTakenEnum.BATCH_ABORTED:
                has_reject = True

            rules_list.append(DQBatchRuleItem(
                rule_id=rule.id,
                rule_version_id=r_ver.id,
                rule_name=rule.name,
                rule_type=r_ver.rule_type,
                severity=r_ver.severity,
                total_rows_evaluated=dq_res.total_rows_evaluated,
                passed_rows=dq_res.passed_rows,
                failed_rows=dq_res.failed_rows,
                pass_rate=float(dq_res.pass_rate),
                action_taken=dq_res.action_taken,
                execution_duration_ms=dq_res.execution_duration_ms,
            ))

        batch_action = "PASSED"
        if has_reject:
            batch_action = "BATCH_ABORTED"
        elif has_quarantine:
            batch_action = "QUARANTINED_ROWS"
        elif total_violations > 0:
            batch_action = "LOGGED_WARNING"

        return DQBatchSummaryResponse(
            batch_id=batch_id,
            total_rules_executed=total_rules,
            total_rows_evaluated=total_evaluated,
            total_violations=total_violations,
            has_quarantined_rows=has_quarantine,
            has_reject_file_violation=has_reject,
            batch_action=batch_action,
            rules=rules_list,
        )
