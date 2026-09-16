"""
Profiling Service — Wave 1 Slice 1

Manages sample file uploads, verifies server-side access,
and executes deterministic profiling runs.
"""
import uuid
import hashlib
import io
from datetime import datetime, timezone
from typing import Tuple, List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.feed import Feed
from backend.models.schema import (
    SampleFile,
    ProfilingRun,
    ProfilingColumnStat,
    ProfilingRunStatusEnum,
    SchemaDataTypeEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.adapters.storage import get_storage_adapter
from backend.engine.profiler import DeterministicProfiler
from backend.core.config import settings


class ProfilingService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.storage = get_storage_adapter()

    def upload_sample_file(
        self,
        feed_id: uuid.UUID,
        filename: str,
        content: bytes,
        mime_type: str,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> SampleFile:
        """
        Server-side validated sample upload:
        1. Verify feed exists.
        2. Compute SHA-256 fingerprint.
        3. Persist file bytes via StorageAdapter.
        4. Record in database with audit event.
        """
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {feed_id} not found",
            )

        if not content or len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded sample file is empty (0 bytes)",
            )

        fingerprint = hashlib.sha256(content).hexdigest()
        dest_filename = f"{feed.id}_{int(datetime.now(timezone.utc).timestamp())}_{filename}"
        dest_path = f"{settings.SAMPLE_PATH}/{dest_filename}"

        saved_path = self.storage.write_file(dest_path, content)

        sample = SampleFile(
            id=uuid.uuid4(),
            feed_id=feed.id,
            filename=filename,
            storage_path=saved_path,
            file_size_bytes=len(content),
            file_fingerprint=fingerprint,
            mime_type=mime_type or "text/csv",
            uploaded_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(sample)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.SAMPLE_UPLOADED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="sample_files",
            object_id=str(sample.id),
            after_state={
                "feed_id": str(feed.id),
                "filename": filename,
                "file_size": len(content),
                "fingerprint": fingerprint,
            },
            description=f"Sample file '{filename}' uploaded for feed {feed.name}",
        )
        self.db.commit()
        return sample

    def list_sample_files(self, feed_id: uuid.UUID) -> List[SampleFile]:
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {feed_id} not found",
            )
        return (
            self.db.query(SampleFile)
            .filter(SampleFile.feed_id == feed_id)
            .order_by(SampleFile.created_at.desc())
            .all()
        )

    def run_profiling(
        self,
        feed_id: uuid.UUID,
        sample_file_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> ProfilingRun:
        """
        Execute deterministic profiling run on a feed's sample file.
        Strict server-side validation: sample MUST belong to feed.
        """
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed {feed_id} not found",
            )

        sample = (
            self.db.query(SampleFile)
            .filter(SampleFile.id == sample_file_id, SampleFile.feed_id == feed_id)
            .first()
        )
        if not sample:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sample file {sample_file_id} not found for feed {feed_id}",
            )

        if not self.storage.file_exists(sample.storage_path):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Sample file payload missing from storage: {sample.storage_path}",
            )

        run = ProfilingRun(
            id=uuid.uuid4(),
            feed_id=feed.id,
            sample_file_id=sample.id,
            status=ProfilingRunStatusEnum.RUNNING,
            started_at=datetime.now(timezone.utc),
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(run)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.PROFILING_STARTED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="profiling_runs",
            object_id=str(run.id),
            description=f"Profiling run started on sample '{sample.filename}'",
        )
        self.db.commit()

        # Read and profile
        try:
            file_bytes = self.storage.read_file(sample.storage_path)
            text_content = file_bytes.decode("utf-8-sig", errors="replace")

            profile_result = DeterministicProfiler.profile_auto(text_content)

            run.status = ProfilingRunStatusEnum.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.row_count = profile_result["row_count"]
            run.column_count = profile_result["column_count"]
            summary = profile_result["summary"]
            if "hierarchical_paths" in profile_result:
                summary["hierarchical_paths"] = profile_result["hierarchical_paths"]
            run.profiling_summary = summary

            # Persist observational facts per column / path
            for col in profile_result["columns"]:
                stat = ProfilingColumnStat(
                    id=uuid.uuid4(),
                    profiling_run_id=run.id,
                    column_name=col["column_name"],
                    ordinal_position=col["ordinal_position"],
                    inferred_type=col["inferred_type"],
                    null_count=col["null_count"],
                    null_percentage=col["null_percentage"],
                    distinct_count=col["distinct_count"],
                    distinct_percentage=col["distinct_percentage"],
                    min_value=col["min_value"],
                    max_value=col["max_value"],
                    sample_values=col["sample_values"],
                    detected_date_patterns=col["detected_date_patterns"],
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                self.db.add(stat)

            self.audit.emit(
                action=AuditActionEnum.PROFILING_COMPLETED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="profiling_runs",
                object_id=str(run.id),
                after_state={
                    "row_count": run.row_count,
                    "column_count": run.column_count,
                    "format": profile_result.get("format", "CSV"),
                    "status": run.status.value,
                },
                description=f"Profiling run completed on sample '{sample.filename}' ({profile_result.get('format', 'CSV')}): {run.row_count} rows, {run.column_count} columns/paths",
            )
            self.db.commit()
            return run

        except Exception as e:
            self.db.rollback()
            # Fetch fresh run object to record failure
            run = self.db.query(ProfilingRun).filter(ProfilingRun.id == run.id).first()
            if run:
                run.status = ProfilingRunStatusEnum.FAILED
                run.completed_at = datetime.now(timezone.utc)
                run.error_message = str(e)
                self.audit.emit(
                    action=AuditActionEnum.PROFILING_FAILED,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    object_type="profiling_runs",
                    object_id=str(run.id),
                    description=f"Profiling failed: {str(e)}",
                )
                self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Deterministic profiling failed: {str(e)}",
            )

    def get_profiling_run(self, run_id: uuid.UUID) -> ProfilingRun:
        run = self.db.query(ProfilingRun).filter(ProfilingRun.id == run_id).first()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profiling run {run_id} not found",
            )
        return run

    def get_hierarchical_paths(self, run_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Retrieves discovered hierarchical paths for complex formats."""
        run = self.get_profiling_run(run_id)
        if run.profiling_summary and "hierarchical_paths" in run.profiling_summary:
            return run.profiling_summary["hierarchical_paths"]
        # Fallback: construct from column stats
        return [
            {
                "path": stat.column_name,
                "ordinal_position": stat.ordinal_position,
                "depth": stat.column_name.count(".") + 1,
                "is_array": "[*]" in stat.column_name,
                "inferred_type": stat.inferred_type.value,
                "null_count": stat.null_count,
                "null_percentage": stat.null_percentage,
                "distinct_count": stat.distinct_count,
                "sample_values": stat.sample_values or [],
            }
            for stat in run.column_stats
        ]

