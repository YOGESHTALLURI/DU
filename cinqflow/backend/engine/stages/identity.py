"""
Wave 3 Identity Pipeline Stage Runner (CF-V3-E8-05)
Executes deterministic identity matching, records crosswalk linkages,
creates exceptions for ambiguous/no-match cases, and records identity_run_status.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from backend.models.pipeline import Batch, BatchStage, StageStatusEnum
from backend.models.identity_run_status import IdentityRunStatus
from backend.models.identity import IdentityToken
from backend.schemas.identity import (
    MatchRecordRequest,
    IdentityTokens,
    compute_canonical_source_hash,
)
from backend.services.identity_service import (
    IdentityService,
    compute_hmac_token,
)
from backend.core.config import settings


class IdentityStageRunner:
    @classmethod
    def execute(
        cls,
        db: Session,
        batch: Batch,
        stage_rec: BatchStage,
        context: Dict[str, Any],
        actor_id: str,
    ) -> Dict[str, Any]:
        identity_run_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        # 1. Initialize identity_run_status as RUNNING (or insert on completion)
        # 2. Extract records to match from the authoritative batch-bound Silver Raw storage
        import csv
        import io
        from backend.models.pipeline import StageNameEnum
        from backend.adapters.storage import get_storage_adapter

        raw_records = []
        silver_stage = (
            db.query(BatchStage)
            .filter(
                BatchStage.batch_id == batch.id,
                BatchStage.stage_name == StageNameEnum.SILVER_RAW.value,
            )
            .first()
        )
        storage = get_storage_adapter()
        feed_name = batch.feed.name if batch.feed else "default"
        default_silver_path = f"./data/silver_raw/{feed_name}/{batch.id}/silver_raw.csv"
        candidate_paths = []
        if silver_stage and silver_stage.output_path:
            candidate_paths.append(silver_stage.output_path)
        if context.get("silver_raw_path"):
            candidate_paths.append(context["silver_raw_path"])
        candidate_paths.append(default_silver_path)

        for path in candidate_paths:
            if storage.file_exists(path):
                file_bytes = storage.read_file(path)
                text_stream = io.StringIO(file_bytes.decode("utf-8", errors="replace"))
                reader = csv.DictReader(text_stream)
                raw_records = list(reader)
                break

        # Fallback to in-memory silver_raw_records if written during same execution session
        if not raw_records:
            raw_records = context.get("silver_raw_records", [])

        # Strictly reject missing or uncompleted Silver Raw output - no raw_bytes fallback
        if not raw_records:
            raise RuntimeError(
                f"Identity Stage execution blocked: Durable SILVER_RAW output missing or incomplete for batch {batch.id}"
            )

        # Sort deterministically by source row number if available
        def _get_row_sort_key(row: dict) -> int:
            try:
                return int(row.get("_source_row_num", 0))
            except (ValueError, TypeError):
                return 0

        raw_records.sort(key=_get_row_sort_key)

        total_processed = 0
        linked_count = 0
        exception_count = 0

        pepper = getattr(settings, "IDENTITY_HASH_PEPPER", "cinqflow-dev-identity-pepper-2026")

        for r in raw_records:
            total_processed += 1
            source_sys = batch.feed.domain or "clinical"
            member_id = r.get("member_id") or r.get("id") or str(uuid.uuid4())
            src_hash = compute_canonical_source_hash(source_sys, member_id, pepper=pepper)

            # Compute HMAC demographic tokens
            tokens = IdentityTokens(
                ssn_hash=compute_hmac_token(r.get("ssn")),
                dob_hash=compute_hmac_token(r.get("date_of_birth") or r.get("dob")),
                last_name_hash=compute_hmac_token(r.get("last_name")),
                first_name_hash=compute_hmac_token(r.get("first_name")),
                gender_hash=compute_hmac_token(r.get("gender")),
                postal_code_hash=compute_hmac_token(r.get("postal_code") or r.get("zip")),
            )

            req = MatchRecordRequest(
                source_system=source_sys,
                source_identifier_hash=src_hash,
                tokens=tokens,
                feed_id=batch.feed_id,
                batch_id=batch.id,
            )

            res = IdentityService.match_record(db, req, actor=actor_id)
            if res.disposition == "HIGH_CONFIDENCE":
                linked_count += 1
            else:
                exception_count += 1

        # Record IdentityRunStatus with SUCCESS
        run_status_rec = IdentityRunStatus(
            batch_id=batch.id,
            identity_run_id=identity_run_id,
            run_status="SUCCESS",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run_status_rec)
        db.flush()

        stage_rec.rows_in = total_processed
        stage_rec.rows_out = linked_count
        stage_rec.rows_quarantined = exception_count
        stage_rec.status = StageStatusEnum.SUCCESS
        stage_rec.completed_at = datetime.now(timezone.utc)

        context["identity_run_id"] = str(identity_run_id)
        context["identity_linked_count"] = linked_count
        context["identity_exception_count"] = exception_count

        return {
            "identity_run_id": str(identity_run_id),
            "total_processed": total_processed,
            "linked_count": linked_count,
            "exception_count": exception_count,
        }
