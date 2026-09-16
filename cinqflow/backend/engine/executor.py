"""
Pipeline Execution Engine — Wave 0

Local execution adapter: runs deterministic pipelines without Databricks/Airflow.
Stages:
  1. LANDING: verify file, count raw rows
  2. BRONZE: bit-for-bit immutable copy into lake, verify checksum
  3. SILVER_RAW: generic parsing, validation, lineage injection, quarantine routing
  4. RECONCILIATION: measurable row balance (rows_in = rows_out + quarantined)

Restart Capability:
  When restarting a failed batch, completed stages (SUCCESS) are NOT rerun.
  Execution resumes from the first non-completed stage.

Idempotency:
  Repeated execution relies on input registry fingerprint. Duplicate files
  are rejected before batch creation.
"""
import uuid
import io
import csv
import hashlib
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from backend.models.pipeline import (
    Batch,
    BatchStage,
    BatchStatusEnum,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.input_registry import (
    InputRegistry,
    QuarantineRecord,
    QuarantineReasonEnum,
)
from backend.models.reconciliation import (
    BatchReconciliation,
    ReconciliationLedgerEntry,
    ReconciliationStatusEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.engine.compiler import PipelineCompiler
from backend.adapters.storage import get_storage_adapter
import time
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
)
from backend.engine.drift_detector import SchemaDriftDetector
from backend.engine.production_rules import ProductionRulesEngine, RuleTelemetry


class PipelineExecutor:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.storage = get_storage_adapter()

    def execute_batch(
        self,
        batch_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str] = None,
        simulate_failure_stage: Optional[StageNameEnum] = None,
        is_restart: bool = False,
    ) -> Batch:
        """
        Execute or resume a batch across Wave 0 stages.
        """
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found",
            )

        if batch.status in [BatchStatusEnum.SUCCESS, BatchStatusEnum.CANCELLED]:
            return batch

        if not is_restart and batch.status == BatchStatusEnum.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Batch {batch_id} is already RUNNING",
            )

        # Load feed & version plan
        plan = PipelineCompiler.compile(feed=batch.feed, version=batch.feed_version)

        batch.status = BatchStatusEnum.RUNNING
        if not batch.started_at:
            batch.started_at = datetime.now(timezone.utc)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.BATCH_STARTED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="batches",
            object_id=str(batch.id),
            after_state={"status": "RUNNING"},
            description=f"Batch {batch.id} execution started",
        )

        input_entry: Optional[InputRegistry] = batch.input_registry
        if not input_entry:
            batch.status = BatchStatusEnum.FAILED
            batch.error_message = "No input registry record associated with this batch"
            self.db.commit()
            return batch

        # Raw file content from landing zone
        raw_bytes = self.storage.read_file(input_entry.file_path)

        # Context passed across stages
        context: Dict[str, Any] = {
            "raw_bytes": raw_bytes,
            "filename": input_entry.filename,
            "fingerprint": input_entry.file_fingerprint,
            "total_rows": 0,
            "bronze_path": None,
            "silver_raw_path": None,
            "valid_rows_count": 0,
            "quarantined_count": 0,
            "quarantine_reasons": {},  # reason -> count
        }

        # Execute stages in order
        stages_to_run = [s.stage_name for s in plan.stages] if (plan and plan.stages) else WAVE0_STAGE_ORDER
        for stage_name in stages_to_run:
            stage_rec = batch.get_stage(stage_name)
            if not stage_rec:
                stage_rec = BatchStage(
                    id=uuid.uuid4(),
                    batch_id=batch.id,
                    stage_name=stage_name,
                    stage_order=stages_to_run.index(stage_name) + 1,
                    status=StageStatusEnum.PENDING,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                self.db.add(stage_rec)
                self.db.flush()

            # RESTART RECOVERY RULE: If already SUCCESS, DO NOT RERUN!
            if stage_rec.status == StageStatusEnum.SUCCESS:
                # Populate context from prior stage results for subsequent stages
                if stage_name == StageNameEnum.LANDING:
                    context["total_rows"] = stage_rec.rows_in or 0
                elif stage_name == StageNameEnum.BRONZE:
                    context["bronze_path"] = stage_rec.output_path
                continue

            # Check if simulation requested failure at this stage
            if simulate_failure_stage == stage_name:
                stage_rec.status = StageStatusEnum.FAILED
                stage_rec.started_at = datetime.now(timezone.utc)
                stage_rec.completed_at = datetime.now(timezone.utc)
                stage_rec.error_message = f"Simulated failure at stage {stage_name.value}"
                batch.status = BatchStatusEnum.FAILED
                batch.error_message = stage_rec.error_message
                self.db.flush()

                self.audit.emit(
                    action=AuditActionEnum.STAGE_FAILED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="batch_stages",
                    object_id=str(stage_rec.id),
                    description=f"Stage {stage_name.value} failed: {stage_rec.error_message}",
                )
                try:
                    from backend.services.alert_service import AlertService
                    from backend.models.incident import FailureCategoryEnum, AlertSeverityEnum

                    AlertService.record_failure(
                        db=self.db,
                        feed_id=batch.feed_id,
                        batch_id=batch.id,
                        category=FailureCategoryEnum.STAGE_EXECUTION,
                        failure_stage=stage_name.value,
                        root_cause_pattern=stage_rec.error_message,
                        error_context={"stage": stage_name.value, "error": stage_rec.error_message},
                        severity=AlertSeverityEnum.CRITICAL,
                        user_id=actor_id,
                    )
                except Exception:
                    pass

                self.db.commit()
                return batch

            # Execute Stage
            stage_rec.status = StageStatusEnum.RUNNING
            stage_rec.started_at = datetime.now(timezone.utc)
            self.db.flush()

            self.audit.emit(
                action=AuditActionEnum.STAGE_STARTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="batch_stages",
                object_id=str(stage_rec.id),
                description=f"Stage {stage_name.value} started",
            )

            try:
                if stage_name == StageNameEnum.LANDING:
                    self._execute_landing_stage(batch, stage_rec, context, plan, actor_id, actor_email)
                elif stage_name == StageNameEnum.BRONZE:
                    self._execute_bronze_stage(batch, stage_rec, context, plan)
                elif stage_name == StageNameEnum.SILVER_RAW:
                    self._execute_silver_raw_stage(batch, stage_rec, context, plan, actor_id, actor_email)
                elif stage_name == StageNameEnum.IDENTITY:
                    self._execute_identity_stage(batch, stage_rec, context, plan, actor_id, actor_email)
                elif stage_name == StageNameEnum.ODS:
                    self._execute_ods_stage(batch, stage_rec, context, plan, actor_id, actor_email)

                stage_rec.status = StageStatusEnum.SUCCESS
                stage_rec.completed_at = datetime.now(timezone.utc)
                self.db.flush()

                self.audit.emit(
                    action=AuditActionEnum.STAGE_COMPLETED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="batch_stages",
                    object_id=str(stage_rec.id),
                    description=f"Stage {stage_name.value} completed successfully",
                )

            except Exception as e:
                stage_rec.status = StageStatusEnum.FAILED
                stage_rec.completed_at = datetime.now(timezone.utc)
                stage_rec.error_message = str(e)
                batch.status = BatchStatusEnum.FAILED
                batch.error_message = f"Error in stage {stage_name.value}: {str(e)}"
                self.db.flush()

                self.audit.emit(
                    action=AuditActionEnum.STAGE_FAILED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="batch_stages",
                    object_id=str(stage_rec.id),
                    description=f"Stage {stage_name.value} failed with exception: {str(e)}",
                )
                self.audit.emit(
                    action=AuditActionEnum.BATCH_FAILED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="batches",
                    object_id=str(batch.id),
                    description=f"Batch {batch.id} failed: {stage_rec.error_message}",
                )

                try:
                    from backend.services.alert_service import AlertService
                    from backend.models.incident import FailureCategoryEnum, AlertSeverityEnum

                    err_str = str(e)
                    if "breaking schema drift" in err_str.lower():
                        cat = FailureCategoryEnum.SCHEMA_DRIFT
                    elif "batch rejected by rule" in err_str.lower() or "dq rule" in err_str.lower():
                        cat = FailureCategoryEnum.DATA_QUALITY
                    else:
                        cat = FailureCategoryEnum.STAGE_EXECUTION

                    AlertService.record_failure(
                        db=self.db,
                        feed_id=batch.feed_id,
                        batch_id=batch.id,
                        category=cat,
                        failure_stage=stage_name.value,
                        root_cause_pattern=err_str,
                        error_context={"stage": stage_name.value, "error": err_str},
                        severity=AlertSeverityEnum.CRITICAL,
                        user_id=actor_id,
                    )
                except Exception:
                    pass

                self.db.commit()
                return batch

        # All 3 stages succeeded — Compute Reconciliation
        self._compute_reconciliation(batch, context, actor_id, actor_email)

        self.db.commit()
        self.db.refresh(batch)
        return batch

    
    def _execute_identity_stage(
        self, batch: Batch, stage_rec: BatchStage, context: Dict[str, Any], plan: Any, actor_id: str, actor_email: Optional[str] = None
    ):
        from backend.engine.stages.identity import IdentityStageRunner
        IdentityStageRunner.execute(self.db, batch, stage_rec, context, actor_id)

    def _execute_ods_stage(
        self, batch: Batch, stage_rec: BatchStage, context: Dict[str, Any], plan: Any, actor_id: str, actor_email: Optional[str] = None
    ):
        from backend.models.identity_run_status import IdentityRunStatus
        id_run = (
            self.db.query(IdentityRunStatus)
            .filter(IdentityRunStatus.batch_id == batch.id)
            .order_by(IdentityRunStatus.created_at.desc())
            .first()
        )
        if not id_run or id_run.run_status != "SUCCESS":
            raise RuntimeError(f"ODS execution blocked: Identity stage has not completed successfully for batch {batch.id}")
        stage_rec.rows_in = context.get("identity_linked_count", 0)
        stage_rec.rows_out = stage_rec.rows_in
        stage_rec.status = StageStatusEnum.SUCCESS
        stage_rec.completed_at = datetime.now(timezone.utc)

    def _execute_landing_stage(
        self, batch: Batch, stage_rec: BatchStage, context: Dict[str, Any], plan, actor_id: str, actor_email: Optional[str]
    ):
        """Landing stage: parse header, detect schema drift against published contract, count total data rows."""
        raw_bytes = context["raw_bytes"]
        text_stream = io.StringIO(raw_bytes.decode("utf-8-sig"))
        reader = csv.reader(text_stream)
        header = next(reader, None)
        rows = list(reader)

        total_rows = len(rows)
        context["total_rows"] = total_rows
        stage_rec.rows_in = total_rows
        stage_rec.rows_out = total_rows
        stage_rec.rows_quarantined = 0
        stage_rec.rows_dropped = 0
        stage_rec.stage_metadata = {
            "columns": header,
            "raw_byte_count": len(raw_bytes),
        }

        # CF-V2-E5-04: Deterministic Pre-Ingestion Schema Drift Detection
        schema_obj = self.db.query(Schema).filter(Schema.feed_id == batch.feed_id).first()
        if schema_obj:
            pub_ver = (
                self.db.query(SchemaVersion)
                .filter(
                    SchemaVersion.schema_id == schema_obj.id,
                    SchemaVersion.status == SchemaVersionStatusEnum.PUBLISHED,
                )
                .order_by(SchemaVersion.version_number.desc())
                .first()
            )
            if pub_ver:
                stage_plan = plan.get_stage_plan(StageNameEnum.SILVER_RAW) if plan else None
                expected_delim = stage_plan.config.get("delimiter", ",") if stage_plan else ","

                drift_res = SchemaDriftDetector.detect_drift(
                    raw_bytes=raw_bytes,
                    schema_version=pub_ver,
                    expected_delimiter=expected_delim,
                )

                drift_report = SchemaDriftReport(
                    id=uuid.uuid4(),
                    batch_id=batch.id,
                    feed_id=batch.feed_id,
                    expected_schema_version_id=pub_ver.id,
                    drift_severity=drift_res.drift_severity,
                    missing_fields=drift_res.missing_fields,
                    unexpected_fields=drift_res.unexpected_fields,
                    type_mismatches=drift_res.type_mismatches,
                    detected_delimiter=drift_res.detected_delimiter,
                    status=DriftStatusEnum.DETECTED,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                self.db.add(drift_report)
                self.db.flush()

                if drift_res.drift_severity != DriftSeverityEnum.NONE:
                    self.audit.emit(
                        action=AuditActionEnum.SCHEMA_DRIFT_DETECTED,
                        actor_id=actor_id,
                        actor_email=actor_email,
                        object_type="schema_drift_reports",
                        object_id=str(drift_report.id),
                        after_state={
                            "drift_severity": drift_res.drift_severity.value,
                            "missing_fields": drift_res.missing_fields,
                            "unexpected_fields": drift_res.unexpected_fields,
                        },
                        description=f"Schema drift detected on batch {batch.id}: {drift_res.summary}",
                    )

                if drift_res.drift_severity == DriftSeverityEnum.BREAKING:
                    raise ValueError(f"Pre-ingestion breaking schema drift: {drift_res.summary}")

    def _execute_bronze_stage(self, batch: Batch, stage_rec: BatchStage, context: Dict[str, Any], plan):
        """
        Bronze stage:
        Write exact, unchanged source bytes into Bronze data lake.
        Verify checksum matches input fingerprint.
        """
        raw_bytes = context["raw_bytes"]
        filename = context["filename"]
        feed_name = batch.feed.name
        batch_id_str = str(batch.id)

        # Path: ./data/bronze/{feed_name}/{batch_id}/{filename}
        bronze_dest = f"./data/bronze/{feed_name}/{batch_id_str}/{filename}"
        saved_path = self.storage.write_file(bronze_dest, raw_bytes)

        # Checksum verification to guarantee bit-for-bit immutability
        written_bytes = self.storage.read_file(saved_path)
        bronze_hash = hashlib.sha256(written_bytes).hexdigest()
        if bronze_hash != context["fingerprint"]:
            raise ValueError(f"Bronze checksum mismatch! Expected {context['fingerprint']}, got {bronze_hash}")

        context["bronze_path"] = saved_path
        stage_rec.output_path = saved_path
        stage_rec.rows_in = context["total_rows"]
        stage_rec.rows_out = context["total_rows"]
        stage_rec.rows_quarantined = 0
        stage_rec.rows_dropped = 0
        stage_rec.stage_metadata = {
            "bronze_path": saved_path,
            "checksum_verified": True,
            "byte_size": len(written_bytes),
        }

    def _execute_silver_raw_stage(
        self, batch: Batch, stage_rec: BatchStage, context: Dict[str, Any], plan, actor_id: str, actor_email: Optional[str]
    ):
        """
        Silver Raw stage:
        1. Reads from Bronze file (repeatable reads)
        2. Validates records against generic metadata fields & active published DQ rules
        3. Routes invalid records to QuarantineRecord with named reasons
        4. Enforces REJECT_FILE by immediately failing the batch
        5. Records execution telemetry in dq_results
        6. Writes valid records with lineage columns (_batch_id, _source_row_num, _ingested_at)
        """
        # Idempotency: remove previous dq_results and quarantine_records for this batch/stage if re-running
        self.db.query(DQResult).filter(DQResult.batch_id == batch.id, DQResult.stage_id == stage_rec.id).delete()
        self.db.query(QuarantineRecord).filter(
            QuarantineRecord.batch_id == batch.id,
            QuarantineRecord.stage_name == StageNameEnum.SILVER_RAW.value
        ).delete()
        self.db.flush()

        bronze_path = context.get("bronze_path")
        if not bronze_path:
            bronze_path = batch.get_stage(StageNameEnum.BRONZE).output_path

        bronze_bytes = self.storage.read_file(bronze_path)
        stage_plan = plan.get_stage_plan(StageNameEnum.SILVER_RAW)
        delimiter = stage_plan.config.get("delimiter", ",")
        fields_config = stage_plan.config.get("fields", [])

        text_stream = io.StringIO(bronze_bytes.decode("utf-8-sig"))
        reader = csv.reader(text_stream, delimiter=delimiter)
        header = next(reader, None)
        if not header:
            raise ValueError("Bronze file contains no header row")

        header_indices = {col.strip().lower(): idx for idx, col in enumerate(header)}

        # CF-V2-E7-05: Load active published DQ rules pinned to active schema version
        schema_obj = self.db.query(Schema).filter(Schema.feed_id == batch.feed_id).first()
        pub_schema_ver = None
        rules_to_run: List[Tuple[DataQualityRule, RuleVersion]] = []
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
                rules_to_run = ProductionRulesEngine.load_active_rules(self.db, batch.feed_id, pub_schema_ver.id)

        # Initialize rule telemetry trackers
        rule_trackers: Dict[uuid.UUID, RuleTelemetry] = {
            r_ver.id: RuleTelemetry(rule=r, rule_version=r_ver)
            for r, r_ver in rules_to_run
        }

        valid_records: List[Dict[str, Any]] = []
        quarantined_count = 0
        quarantine_reasons: Dict[str, int] = {}
        batch_aborted_by_rule: Optional[Tuple[str, str, RuleTelemetry]] = None

        row_num = 1  # 1-indexed for data rows (header is 0)
        for row in reader:
            raw_row_str = delimiter.join(row)
            row_dict = {
                col_name: row[idx].strip() if idx < len(row) else ""
                for col_name, idx in header_indices.items()
            }

            # 1. Generic metadata row validation
            is_valid, fail_field, fail_val, fail_reason, fail_detail = self._validate_row(
                row, header_indices, fields_config
            )

            row_quarantined = False

            if not is_valid:
                row_quarantined = True
            else:
                # 2. CF-V2-E7-05: Evaluate active published Data Quality Rules
                for r, r_ver in rules_to_run:
                    tracker = rule_trackers[r_ver.id]
                    tracker.total_rows += 1

                    t0 = time.time()
                    violated, reason_detail = ProductionRulesEngine.evaluate_rule_on_value(row_dict, r_ver)
                    tracker.duration_ms += int((time.time() - t0) * 1000)

                    if violated:
                        tracker.failed_rows += 1
                        if r_ver.severity == RuleSeverityEnum.REJECT_FILE:
                            tracker.action_taken = DQActionTakenEnum.BATCH_ABORTED
                            batch_aborted_by_rule = (r.name, reason_detail, tracker)
                            break
                        elif r_ver.severity == RuleSeverityEnum.QUARANTINE:
                            row_quarantined = True
                            tracker.action_taken = DQActionTakenEnum.QUARANTINED_ROWS
                            if not fail_detail:
                                fail_field = r_ver.target_field
                                fail_val = row_dict.get(r_ver.target_field.lower())
                                fail_reason = self._map_rule_to_quarantine_reason(r_ver.rule_type)
                                fail_detail = f"DQ rule '{r.name}' failed: {reason_detail}"
                        elif r_ver.severity == RuleSeverityEnum.WARNING:
                            if tracker.action_taken not in [DQActionTakenEnum.QUARANTINED_ROWS, DQActionTakenEnum.BATCH_ABORTED]:
                                tracker.action_taken = DQActionTakenEnum.LOGGED_WARNING
                        elif r_ver.severity == RuleSeverityEnum.INFO:
                            if tracker.action_taken not in [DQActionTakenEnum.QUARANTINED_ROWS, DQActionTakenEnum.BATCH_ABORTED, DQActionTakenEnum.LOGGED_WARNING]:
                                tracker.action_taken = DQActionTakenEnum.LOGGED_INFO
                    else:
                        tracker.passed_rows += 1

            if batch_aborted_by_rule:
                # Halt row evaluation immediately
                break

            if not row_quarantined:
                # Build valid transformed record with record-level lineage
                transformed = {
                    "_batch_id": str(batch.id),
                    "_feed_id": str(batch.feed_id),
                    "_source_row_num": row_num,
                    "_ingested_at": datetime.now(timezone.utc).isoformat(),
                }
                for fld in fields_config:
                    fname = fld["name"].strip().lower()
                    idx = header_indices.get(fname)
                    val = row[idx].strip() if idx is not None and idx < len(row) else None
                    transformed[fld["name"]] = val
                valid_records.append(transformed)
            else:
                quarantined_count += 1
                reason_code = fail_reason.value if fail_reason else "DATA_QUALITY_RULE_VIOLATION"
                quarantine_reasons[reason_code] = quarantine_reasons.get(reason_code, 0) + 1

                # Create real QuarantineRecord in database
                qr = QuarantineRecord(
                    id=uuid.uuid4(),
                    batch_id=batch.id,
                    stage_name=StageNameEnum.SILVER_RAW.value,
                    source_row_number=row_num,
                    source_record_raw=raw_row_str,
                    field_name=fail_field,
                    field_value=fail_val,
                    reason=fail_reason or QuarantineReasonEnum.INVALID_FIELD_TYPE,
                    reason_detail=fail_detail or "Record failed validation",
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                self.db.add(qr)
                self.audit.emit(
                    action=AuditActionEnum.QUARANTINE_RECORD_ADDED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="quarantine_records",
                    object_id=str(qr.id),
                    description=f"Quarantined row {row_num}: {fail_detail}",
                )

            row_num += 1

        # Persist DQ Results for all evaluated rules
        for r_id, tracker in rule_trackers.items():
            pass_rate = round((tracker.passed_rows / tracker.total_rows * 100), 2) if tracker.total_rows > 0 else 100.0
            dq_res = DQResult(
                id=uuid.uuid4(),
                batch_id=batch.id,
                stage_id=stage_rec.id,
                rule_version_id=tracker.rule_version.id,
                total_rows_evaluated=tracker.total_rows,
                passed_rows=tracker.passed_rows,
                failed_rows=tracker.failed_rows,
                pass_rate=pass_rate,
                action_taken=tracker.action_taken,
                execution_duration_ms=tracker.duration_ms,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(dq_res)

        self.db.flush()

        if rules_to_run:
            self.audit.emit(
                action=AuditActionEnum.RULE_PRODUCTION_EXECUTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="dq_results",
                object_id=str(batch.id),
                after_state={
                    "total_rules": len(rules_to_run),
                    "total_rows_evaluated": context["total_rows"],
                },
                description=f"Evaluated {len(rules_to_run)} production DQ rules on batch {batch.id}",
            )

        if batch_aborted_by_rule:
            rule_name, reason_detail, tracker = batch_aborted_by_rule
            self.audit.emit(
                action=AuditActionEnum.RULE_BATCH_ABORTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="batches",
                object_id=str(batch.id),
                after_state={
                    "aborted_by_rule": rule_name,
                    "rule_version_id": str(tracker.rule_version.id),
                    "reason": reason_detail,
                },
                description=f"Batch {batch.id} aborted in Silver Raw by REJECT_FILE rule '{rule_name}': {reason_detail}",
            )
            raise ValueError(f"Batch rejected by rule '{rule_name}' at row {row_num}: {reason_detail}")

        # Save Silver Raw output
        feed_name = batch.feed.name
        batch_id_str = str(batch.id)
        silver_dest = f"./data/silver_raw/{feed_name}/{batch_id_str}/silver_raw.csv"

        # Serialize valid records to CSV
        output_buffer = io.StringIO()
        if valid_records:
            fieldnames = list(valid_records[0].keys())
            writer = csv.DictWriter(output_buffer, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(valid_records)
        output_bytes = output_buffer.getvalue().encode("utf-8")
        saved_silver_path = self.storage.write_file(silver_dest, output_bytes)

        context["silver_raw_path"] = saved_silver_path
        context["silver_raw_records"] = valid_records
        context["valid_rows_count"] = len(valid_records)
        context["quarantined_count"] = quarantined_count
        context["quarantine_reasons"] = quarantine_reasons

        stage_rec.output_path = saved_silver_path
        stage_rec.rows_in = context["total_rows"]
        stage_rec.rows_out = len(valid_records)
        stage_rec.rows_quarantined = quarantined_count
        stage_rec.rows_dropped = 0

    @classmethod
    def _map_rule_to_quarantine_reason(cls, rule_type: RuleTypeEnum) -> QuarantineReasonEnum:
        if rule_type == RuleTypeEnum.NOT_NULL:
            return QuarantineReasonEnum.MISSING_REQUIRED_FIELD
        elif rule_type == RuleTypeEnum.RANGE:
            return QuarantineReasonEnum.VALUE_OUT_OF_RANGE
        elif rule_type == RuleTypeEnum.REGEX:
            return QuarantineReasonEnum.REGEX_MISMATCH
        elif rule_type == RuleTypeEnum.ENUM:
            return QuarantineReasonEnum.INVALID_ENUM_VALUE
        elif rule_type == RuleTypeEnum.LENGTH:
            return QuarantineReasonEnum.RECORD_TOO_LONG
        elif rule_type == RuleTypeEnum.DATE_RANGE:
            return QuarantineReasonEnum.INVALID_DATE_FORMAT
        elif rule_type == RuleTypeEnum.CROSS_FIELD:
            return QuarantineReasonEnum.REFERENTIAL_INTEGRITY
        return QuarantineReasonEnum.INVALID_FIELD_TYPE

    def _validate_row(
        self, row: List[str], header_indices: Dict[str, int], fields_config: List[Dict[str, Any]]
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[QuarantineReasonEnum], Optional[str]]:
        """
        Generic row validator based purely on metadata:
        - Required field presence
        - Date format and future date restriction
        - Enum allowed values
        """
        for fld in fields_config:
            fname = fld["name"].strip().lower()
            ftype = fld.get("type", "STRING").upper()
            required = fld.get("required", False)

            idx = header_indices.get(fname)
            val = row[idx].strip() if idx is not None and idx < len(row) else ""

            # Check required
            if required and not val:
                return (
                    False,
                    fld["name"],
                    None,
                    QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
                    f"Required field '{fld['name']}' is empty or missing",
                )

            if not val:
                continue

            # Check DATE
            if ftype == "DATE":
                try:
                    parsed_date = datetime.strptime(val, "%Y-%m-%d").date()
                    # Rule: date_of_birth cannot be in future
                    if "birth" in fname or "dob" in fname:
                        if parsed_date > date.today():
                            return (
                                False,
                                fld["name"],
                                val,
                                QuarantineReasonEnum.FUTURE_DATE,
                                f"Date '{val}' in '{fld['name']}' is in the future",
                            )
                except ValueError:
                    return (
                        False,
                        fld["name"],
                        val,
                        QuarantineReasonEnum.INVALID_DATE_FORMAT,
                        f"Field '{fld['name']}' value '{val}' does not match YYYY-MM-DD format",
                    )

            # Check ENUM
            if ftype == "ENUM":
                allowed = fld.get("allowed_values", [])
                if allowed and val not in allowed:
                    return (
                        False,
                        fld["name"],
                        val,
                        QuarantineReasonEnum.INVALID_ENUM_VALUE,
                        f"Field '{fld['name']}' value '{val}' not in allowed set {allowed}",
                    )

        return True, None, None, None, None

    def _compute_reconciliation(
        self, batch: Batch, context: Dict[str, Any], actor_id: str, actor_email: Optional[str]
    ):
        """
        Compute and persist measurable reconciliation balance check:
        rows_in = rows_silver_raw + rows_quarantined + rows_dropped
        """
        rows_in = context["total_rows"]
        rows_silver = context["valid_rows_count"]
        rows_quarantine = context["quarantined_count"]
        rows_dropped = 0

        is_balanced = (rows_in == (rows_silver + rows_quarantine + rows_dropped))
        discrepancy = rows_in - (rows_silver + rows_quarantine + rows_dropped)

        recon = (
            self.db.query(BatchReconciliation)
            .filter(BatchReconciliation.batch_id == batch.id)
            .first()
        )
        if not recon:
            recon = BatchReconciliation(
                id=uuid.uuid4(),
                batch_id=batch.id,
                rows_in=rows_in,
                rows_silver_raw=rows_silver,
                rows_quarantined=rows_quarantine,
                rows_dropped=rows_dropped,
                balance_check_passed=is_balanced,
                status=ReconciliationStatusEnum.PASS if is_balanced else ReconciliationStatusEnum.FAIL,
                discrepancy=discrepancy,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(recon)
        else:
            recon.rows_in = rows_in
            recon.rows_silver_raw = rows_silver
            recon.rows_quarantined = rows_quarantine
            recon.rows_dropped = rows_dropped
            recon.balance_check_passed = is_balanced
            recon.status = ReconciliationStatusEnum.PASS if is_balanced else ReconciliationStatusEnum.FAIL
            recon.discrepancy = discrepancy
            recon.updated_by = actor_id
        self.db.flush()

        # Record Ledger Entries for each quarantine reason
        for reason_code, count in context.get("quarantine_reasons", {}).items():
            ledger = ReconciliationLedgerEntry(
                id=uuid.uuid4(),
                reconciliation_id=recon.id,
                reason_code=reason_code,
                reason_description=f"Quarantined {count} rows due to {reason_code}",
                row_count=count,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(ledger)

        if is_balanced:
            batch.status = BatchStatusEnum.SUCCESS
            batch.completed_at = datetime.now(timezone.utc)
            self.audit.emit(
                action=AuditActionEnum.RECONCILIATION_COMPUTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="batch_reconciliation",
                object_id=str(recon.id),
                after_state={
                    "rows_in": rows_in,
                    "rows_silver": rows_silver,
                    "rows_quarantine": rows_quarantine,
                    "balance_check": "PASS",
                },
                description=f"Reconciliation PASS for batch {batch.id}: {rows_in} in = {rows_silver} out + {rows_quarantine} quarantined",
            )
            self.audit.emit(
                action=AuditActionEnum.BATCH_COMPLETED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="batches",
                object_id=str(batch.id),
                after_state={"status": "SUCCESS"},
                description=f"Batch {batch.id} completed successfully",
            )
        else:
            batch.status = BatchStatusEnum.FAILED_RECONCILIATION
            batch.completed_at = datetime.now(timezone.utc)
            self.audit.emit(
                action=AuditActionEnum.RECONCILIATION_FAILED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="batch_reconciliation",
                object_id=str(recon.id),
                after_state={"discrepancy": discrepancy, "balance_check": "FAIL"},
                description=f"Reconciliation FAIL for batch {batch.id}: discrepancy of {discrepancy} rows",
            )
            try:
                from backend.services.alert_service import AlertService
                from backend.models.incident import FailureCategoryEnum, AlertSeverityEnum

                AlertService.record_failure(
                    db=self.db,
                    feed_id=batch.feed_id,
                    batch_id=batch.id,
                    category=FailureCategoryEnum.RECONCILIATION,
                    failure_stage="RECONCILIATION",
                    root_cause_pattern=f"Reconciliation balance mismatch: discrepancy of {discrepancy} rows (in={rows_in}, silver={rows_silver}, quarantine={rows_quarantine})",
                    error_context={"discrepancy": discrepancy, "rows_in": rows_in, "rows_silver": rows_silver, "rows_quarantine": rows_quarantine},
                    severity=AlertSeverityEnum.CRITICAL,
                    user_id=actor_id,
                )
            except Exception:
                pass

    def restart_batch(
        self,
        batch_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> Batch:
        """
        Restart a failed batch.
        Completed stages (status=SUCCESS) are preserved and NOT re-run.
        Failed and pending stages are re-executed.
        """
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found",
            )

        if batch.status not in [BatchStatusEnum.FAILED, BatchStatusEnum.FAILED_RECONCILIATION]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot restart batch in status {batch.status.value}",
            )

        batch.restart_count += 1
        batch.status = BatchStatusEnum.RUNNING
        batch.error_message = None

        # Find first non-SUCCESS stage and reset failed stages to PENDING
        for stage in batch.stages:
            if stage.status == StageStatusEnum.FAILED:
                stage.status = StageStatusEnum.PENDING
                stage.error_message = None

        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.BATCH_RESTART_REQUESTED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="batches",
            object_id=str(batch.id),
            after_state={"restart_count": batch.restart_count, "status": "RUNNING"},
            description=f"Batch {batch.id} restart #{batch.restart_count} requested",
        )

        # Run pipeline
        return self.execute_batch(batch_id=batch.id, actor_id=actor_id, actor_email=actor_email, is_restart=True)
