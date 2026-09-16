"""
Wave 2 Slice 3 Recovery Operations Service (CF-V2-E8-04)

Handles safe, idempotent operational recovery:
- Resuming failed batches from the exact point of failure (preserving successful upstream stages)
- Atomic cleanup of partial artifacts before stage re-run
- Governed batch re-triggering for completed batches
- Governed quarantine record reprocessing with recovery batches and lineage tracing
- Quarantine record discard
"""
import uuid
import io
import csv
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.pipeline import (
    Batch,
    BatchStage,
    BatchStatusEnum,
    StageStatusEnum,
    StageNameEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.input_registry import (
    QuarantineRecord,
    QuarantineStatusEnum,
    QuarantineReasonEnum,
)
from backend.models.dq_result import DQResult
from backend.models.reconciliation import BatchReconciliation, ReconciliationLedgerEntry, ReconciliationStatusEnum
from backend.models.audit import AuditActionEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.services.audit_service import AuditService
from backend.engine.arrival_engine import ArrivalEngine
from backend.engine.executor import PipelineExecutor
from backend.engine.compiler import PipelineCompiler
from backend.engine.production_rules import ProductionRulesEngine
from backend.adapters.storage import get_storage_adapter


class OpsRecoveryService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.storage = get_storage_adapter()

    def restart_failed_batch(
        self,
        batch_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Batch:
        """
        Restart a failed batch from the first non-completed stage.
        Completed stages (status=SUCCESS) are preserved and NOT re-run.
        Atomic cleanup: partial artifacts, previous dq_results, and previous quarantine_records
        for the restarting stage are purged before execution resumes.
        """
        # Acquire row lock
        batch = (
            self.db.query(Batch)
            .filter(Batch.id == batch_id)
            .with_for_update()
            .first()
        )
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found",
            )

        if batch.status == BatchStatusEnum.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Batch {batch_id} is already RUNNING",
            )

        if batch.status == BatchStatusEnum.SUCCESS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot restart successful batch {batch_id}; use RETRIGGER_BATCH instead",
            )

        if batch.status not in [BatchStatusEnum.FAILED, BatchStatusEnum.FAILED_RECONCILIATION]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot restart batch in status {batch.status.value}",
            )

        # Increment restart counter
        batch.restart_count += 1
        batch.status = BatchStatusEnum.RUNNING
        batch.error_message = None

        # Pre-execution cleanup of failed or pending stages
        found_first_incomplete = False
        for stage_name in WAVE0_STAGE_ORDER:
            stage_rec = batch.get_stage(stage_name)
            if not stage_rec:
                continue

            if stage_rec.status != StageStatusEnum.SUCCESS:
                found_first_incomplete = True

            if found_first_incomplete:
                stage_rec.status = StageStatusEnum.PENDING
                stage_rec.error_message = None

                # Clean up output files for incomplete stages
                if stage_rec.output_path:
                    try:
                        import os
                        if os.path.exists(stage_rec.output_path):
                            os.remove(stage_rec.output_path)
                    except Exception:
                        pass
                    stage_rec.output_path = None

                # Reset row counters for incomplete stage
                stage_rec.rows_in = 0
                stage_rec.rows_out = 0
                stage_rec.rows_quarantined = 0
                stage_rec.rows_dropped = 0

                # Clean up DQResults and QuarantineRecords for incomplete stage
                self.db.query(DQResult).filter(
                    DQResult.batch_id == batch.id,
                    DQResult.stage_id == stage_rec.id,
                ).delete()

                self.db.query(QuarantineRecord).filter(
                    QuarantineRecord.batch_id == batch.id,
                    QuarantineRecord.stage_name == stage_name.value,
                ).delete()

                # Reset reconciliation records if present
                recon = (
                    self.db.query(BatchReconciliation)
                    .filter(BatchReconciliation.batch_id == batch.id)
                    .first()
                )
                if recon:
                    self.db.query(ReconciliationLedgerEntry).filter(
                        ReconciliationLedgerEntry.reconciliation_id == recon.id
                    ).delete()
                    recon.status = ReconciliationStatusEnum.PENDING
                    recon.balance_check_passed = False
                    recon.rows_in = 0
                    recon.rows_silver_raw = 0
                    recon.rows_quarantined = 0
                    recon.rows_dropped = 0

        self.db.flush()

        sanitized_reason = ArrivalEngine.sanitize_operational_error(reason) if reason else None

        self.audit.emit(
            action=AuditActionEnum.BATCH_RESTART_REQUESTED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="batches",
            object_id=str(batch.id),
            after_state={
                "restart_count": batch.restart_count,
                "status": "RUNNING",
                "reason": sanitized_reason,
            },
            description=f"Batch {batch.id} restart #{batch.restart_count} requested. Rationale: {sanitized_reason or 'None'}",
        )

        # Run pipeline
        executor = PipelineExecutor(self.db)
        return executor.execute_batch(
            batch_id=batch.id,
            actor_id=actor_id,
            actor_email=actor_email,
            is_restart=True,
        )

    def retrigger_successful_batch(
        self,
        batch_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Batch:
        """
        Retrigger execution of an already completed (SUCCESS) batch.
        Evaluates downstream pre-flight dependency gates, creates a new Batch record,
        and re-runs the pipeline.
        """
        original_batch = (
            self.db.query(Batch)
            .filter(Batch.id == batch_id)
            .with_for_update()
            .first()
        )
        if not original_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found",
            )

        if original_batch.status != BatchStatusEnum.SUCCESS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"RETRIGGER_BATCH can only be performed on SUCCESS batches (current: {original_batch.status.value})",
            )

        # Pre-flight Downstream Gate Check
        from backend.services.dependency_service import DependencyService
        dep_service = DependencyService(self.db)
        gate_result = dep_service.evaluate_execution_gate(
            feed_id=original_batch.feed_id,
            audit_on_block=True,
            actor_id=actor_id,
            actor_email=actor_email,
        )
        if not gate_result.is_allowed:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail=f"Downstream protection gate blocked retrigger: {'; '.join(gate_result.blocking_reasons)}",
            )

        # Create new Batch record linked to the same input and parent batch
        new_batch = Batch(
            id=uuid.uuid4(),
            parent_batch_id=original_batch.id,
            feed_id=original_batch.feed_id,
            feed_version_id=original_batch.feed_version_id,
            input_registry_id=original_batch.input_registry_id,
            status=BatchStatusEnum.PENDING,
            triggered_by="manual_retrigger",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(new_batch)
        self.db.flush()

        sanitized_reason = ArrivalEngine.sanitize_operational_error(reason) if reason else None

        self.audit.emit(
            action=AuditActionEnum.BATCH_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="batches",
            object_id=str(new_batch.id),
            after_state={
                "feed_id": str(new_batch.feed_id),
                "retriggered_from": str(original_batch.id),
                "reason": sanitized_reason,
            },
            description=f"Batch {new_batch.id} retriggered from original batch {original_batch.id}. Rationale: {sanitized_reason or 'None'}",
        )

        executor = PipelineExecutor(self.db)
        return executor.execute_batch(
            batch_id=new_batch.id,
            actor_id=actor_id,
            actor_email=actor_email,
        )

    def reprocess_quarantine_records(
        self,
        record_ids: List[uuid.UUID],
        actor_id: str,
        actor_email: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Reprocess quarantined records against the active schema version and rules.
        Creates an isolated Recovery Batch ('quarantine_recovery').
        Valid records are appended to Silver Raw, and resolved quarantine records
        are updated with status=REPROCESSED and resolution_batch_id.
        """
        records = (
            self.db.query(QuarantineRecord)
            .filter(QuarantineRecord.id.in_(record_ids))
            .with_for_update()
            .all()
        )
        if not records:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No quarantine records found matching the provided IDs",
            )

        # Reject already resolved records to prevent duplicate reprocessing or double-write
        already_resolved = [r for r in records if r.status != QuarantineStatusEnum.QUARANTINED]
        if already_resolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Quarantine record {already_resolved[0].id} is already in status '{already_resolved[0].status.value}' and cannot be reprocessed again",
            )

        # All records must belong to the same feed
        feed_ids = {r.batch.feed_id for r in records}
        if len(feed_ids) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All quarantine records in a reprocess batch must belong to the same feed",
            )

        feed_id = records[0].batch.feed_id
        feed = records[0].batch.feed

        # Create Recovery Batch
        recovery_batch = Batch(
            id=uuid.uuid4(),
            feed_id=feed_id,
            feed_version_id=records[0].batch.feed_version_id,
            input_registry_id=records[0].batch.input_registry_id,
            status=BatchStatusEnum.RUNNING,
            started_at=datetime.now(timezone.utc),
            triggered_by="quarantine_recovery",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(recovery_batch)
        self.db.flush()

        # Load compiler plan and active published rules
        from backend.models.feed import FeedVersion
        feed_ver = None
        if feed.active_version_id:
            feed_ver = self.db.query(FeedVersion).filter(FeedVersion.id == feed.active_version_id).first()
        if not feed_ver:
            feed_ver = self.db.query(FeedVersion).filter(FeedVersion.id == records[0].batch.feed_version_id).first()

        plan = PipelineCompiler.compile(feed=feed, version=feed_ver)
        stage_plan = plan.get_stage_plan(StageNameEnum.SILVER_RAW)
        delimiter = stage_plan.config.get("delimiter", ",")
        fields_config = stage_plan.config.get("fields", [])

        schema_obj = self.db.query(Schema).filter(Schema.feed_id == feed_id).first()
        rules_to_run = []
        if schema_obj:
            pub_schema_ver = (
                self.db.query(SchemaVersion)
                .filter(
                    SchemaVersion.schema_id == schema_obj.id,
                    SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
                )
                .order_by(SchemaVersion.version_number.desc())
                .first()
            )
            if pub_schema_ver:
                rules_to_run = ProductionRulesEngine.load_active_rules(self.db, feed_id, pub_schema_ver.id)

        executor = PipelineExecutor(self.db)

        # Evaluate records
        reprocessed_count = 0
        still_quarantined_count = 0
        valid_silver_rows: List[Dict[str, Any]] = []

        now_utc = datetime.now(timezone.utc)
        sanitized_reason = ArrivalEngine.sanitize_operational_error(reason) if reason else None

        for rec in records:
            if rec.status != QuarantineStatusEnum.QUARANTINED:
                continue

            raw_str = rec.source_record_raw or ""
            row = [val.strip() for val in raw_str.split(delimiter)]
            header = [f["name"].strip().lower() for f in fields_config]
            header_indices = {col: idx for idx, col in enumerate(header)}

            is_valid, fail_field, fail_val, fail_reason, fail_detail = executor._validate_row(
                row, header_indices, fields_config
            )

            # Evaluate production rules if basic validation passed
            if is_valid and rules_to_run:
                row_dict = {
                    col_name: row[idx].strip() if idx < len(row) else ""
                    for col_name, idx in header_indices.items()
                }
                for rule, rule_ver in rules_to_run:
                    eval_res = ProductionRulesEngine.evaluate_record(rule_ver, row_dict)
                    if not eval_res.passed:
                        is_valid = False
                        break

            if is_valid:
                reprocessed_count += 1
                rec.status = QuarantineStatusEnum.REPROCESSED
                rec.resolution_batch_id = recovery_batch.id
                rec.resolved_at = now_utc
                rec.resolved_by = actor_id
                rec.resolution_notes = sanitized_reason

                # Lineage columns in Silver Raw output
                transformed = {
                    "_recovery_batch_id": str(recovery_batch.id),
                    "_quarantine_source_id": str(rec.id),
                    "_batch_id": str(rec.batch_id),
                    "_feed_id": str(feed_id),
                    "_source_row_num": rec.source_row_number,
                    "_ingested_at": now_utc.isoformat(),
                }
                for fld in fields_config:
                    fname = fld["name"].strip().lower()
                    idx = header_indices.get(fname)
                    val = row[idx].strip() if idx is not None and idx < len(row) else None
                    transformed[fld["name"]] = val
                valid_silver_rows.append(transformed)
            else:
                # Still invalid: DO NOT mark REPROCESSED! Leave original record QUARANTINED!
                still_quarantined_count += 1
                rec.resolution_notes = f"Recovery attempt {recovery_batch.id}: record remains invalid"

        # Write Silver Raw file to storage if valid records exist
        silver_dest = None
        if valid_silver_rows:
            feed_name = feed.name
            batch_id_str = str(recovery_batch.id)
            silver_dest = f"./data/silver_raw/{feed_name}/{batch_id_str}/silver_raw_recovery.csv"
            output_buffer = io.StringIO()
            fieldnames = list(valid_silver_rows[0].keys())
            writer = csv.DictWriter(output_buffer, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(valid_silver_rows)
            output_bytes = output_buffer.getvalue().encode("utf-8")
            self.storage.write_file(silver_dest, output_bytes)

        # BatchStage record on recovery_batch
        stage_rec = BatchStage(
            id=uuid.uuid4(),
            batch_id=recovery_batch.id,
            stage_name=StageNameEnum.SILVER_RAW,
            stage_order=3,
            status=StageStatusEnum.SUCCESS,
            output_path=silver_dest,
            rows_in=len(records),
            rows_out=len(valid_silver_rows),
            rows_quarantined=still_quarantined_count,
            rows_dropped=0,
            started_at=now_utc,
            completed_at=datetime.now(timezone.utc),
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(stage_rec)

        # BatchReconciliation on recovery_batch
        recon = BatchReconciliation(
            id=uuid.uuid4(),
            batch_id=recovery_batch.id,
            rows_in=len(records),
            rows_silver_raw=len(valid_silver_rows),
            rows_quarantined=still_quarantined_count,
            rows_dropped=0,
            balance_check_passed=(len(records) == len(valid_silver_rows) + still_quarantined_count),
            status=ReconciliationStatusEnum.PASS,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(recon)

        # Complete recovery batch
        recovery_batch.status = BatchStatusEnum.SUCCESS
        recovery_batch.completed_at = datetime.now(timezone.utc)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.OPS_QUARANTINE_REPROCESSED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="quarantine_records",
            object_id=str(recovery_batch.id),
            after_state={
                "total_records": len(records),
                "reprocessed_count": reprocessed_count,
                "still_quarantined": still_quarantined_count,
                "recovery_batch_id": str(recovery_batch.id),
                "silver_raw_path": silver_dest,
            },
            description=f"Quarantine recovery batch {recovery_batch.id}: {reprocessed_count} reprocessed to Silver Raw, {still_quarantined_count} retained as quarantined",
        )

        return {
            "recovery_batch_id": str(recovery_batch.id),
            "total_evaluated": len(records),
            "reprocessed_count": reprocessed_count,
            "still_quarantined_count": still_quarantined_count,
            "silver_raw_path": silver_dest,
        }

    def discard_quarantine_records(
        self,
        record_ids: List[uuid.UUID],
        actor_id: str,
        actor_email: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Mark quarantine records as permanently discarded.
        """
        records = (
            self.db.query(QuarantineRecord)
            .filter(QuarantineRecord.id.in_(record_ids))
            .with_for_update()
            .all()
        )
        if not records:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No quarantine records found matching the provided IDs",
            )

        now_utc = datetime.now(timezone.utc)
        sanitized_reason = ArrivalEngine.sanitize_operational_error(reason) if reason else None

        for rec in records:
            rec.status = QuarantineStatusEnum.DISCARDED
            rec.resolved_at = now_utc
            rec.resolved_by = actor_id
            rec.resolution_notes = sanitized_reason

        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.OPS_QUARANTINE_DISCARDED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="quarantine_records",
            object_id=str(records[0].id) if len(records) == 1 else "bulk",
            after_state={
                "discarded_count": len(records),
                "reason": sanitized_reason,
            },
            description=f"Discarded {len(records)} quarantine records. Rationale: {sanitized_reason or 'None'}",
        )

        return {
            "discarded_count": len(records),
            "record_ids": [str(r.id) for r in records],
        }
