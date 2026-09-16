"""
Landing Controls & Input Service — Wave 0

Implements real local file ingestion:
1. Discover/match feed by filename pattern
2. Validate filename pattern
3. Validate file size (non-empty, within limits)
4. Calculate SHA-256 fingerprint
5. Check for duplicate fingerprint (Idempotency enforcement)
6. Validate file structure (CSV header check)
7. Create InputRegistry record (ACCEPTED or REJECTED)
8. Create Batch & BatchStages for accepted input
9. Record immutable audit events
"""
import uuid
import hashlib
import csv
import io
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from backend.models.feed import Feed, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum, StageStatusEnum, WAVE0_STAGE_ORDER
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.adapters.storage import get_storage_adapter

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB max for Wave 0 local dev


class InputService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.storage = get_storage_adapter()

    def calculate_fingerprint(self, content: bytes) -> str:
        """Calculate SHA-256 hex digest of file bytes."""
        return hashlib.sha256(content).hexdigest()

    def discover_feed_for_filename(self, filename: str) -> Optional[Feed]:
        """Find an active feed whose filename_pattern matches the given filename."""
        feeds = self.db.query(Feed).filter(Feed.status.in_([FeedStatusEnum.ACTIVE, FeedStatusEnum.DRAFT])).all()
        for feed in feeds:
            if feed.matches_filename(filename):
                return feed
        return None

    def validate_structure(self, content: bytes, feed: Feed) -> Tuple[bool, Optional[str]]:
        """Validate structural compliance against feed's active version configuration."""
        active_version = feed.get_active_version()
        if not active_version or not active_version.config_snapshot:
            # If no published version, fall back to draft version 1
            active_version = feed.versions[-1] if feed.versions else None

        if not active_version or not active_version.config_snapshot:
            return True, None

        config = active_version.config_snapshot
        fields = config.get("fields", [])
        delimiter = config.get("delimiter", ",")

        try:
            text_stream = io.StringIO(content.decode("utf-8-sig"))
            reader = csv.reader(text_stream, delimiter=delimiter)
            header = next(reader, None)
            if not header:
                return False, "File is empty or contains no header row"

            # Check that required fields are present in the header
            header_clean = [h.strip().lower() for h in header]
            for field in fields:
                if field.get("required", False):
                    field_name = field.get("name", "").strip().lower()
                    if field_name not in header_clean:
                        return False, f"Missing required column in header: '{field.get('name')}'"

            return True, None
        except UnicodeDecodeError:
            return False, "File encoding is invalid (expected UTF-8)"
        except Exception as e:
            return False, f"Structural parse error: {str(e)}"

    def register_file(
        self,
        filename: str,
        content: bytes,
        actor_id: str,
        actor_email: Optional[str] = None,
        forced_feed_id: Optional[uuid.UUID] = None,
    ) -> Tuple[InputRegistry, Optional[Batch], bool]:
        """
        Process an incoming file with full landing controls.

        Returns:
            (InputRegistry, Optional[Batch], is_duplicate)
        """
        file_size = len(content)
        fingerprint = self.calculate_fingerprint(content)

        # 1. Match Feed
        if forced_feed_id:
            feed = self.db.query(Feed).filter(Feed.id == forced_feed_id).first()
        else:
            feed = self.discover_feed_for_filename(filename)

        if not feed:
            # Park/reject unexpected file
            rejected_entry = InputRegistry(
                id=uuid.uuid4(),
                feed_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                filename=filename,
                file_path="",
                file_size_bytes=file_size,
                file_fingerprint=fingerprint,
                status=InputStatusEnum.REJECTED,
                rejection_reason=f"No configured feed pattern matched filename '{filename}'",
                registered_by=actor_id,
                detected_at=datetime.now(timezone.utc),
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.audit.emit(
                action=AuditActionEnum.INPUT_REJECTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="input_registry",
                description=f"Rejected incoming file {filename}: no matching feed pattern",
            )
            return rejected_entry, None, False

        # 2. Check for Duplicate Fingerprint (IDEMPOTENCY)
        existing = (
            self.db.query(InputRegistry)
            .filter(InputRegistry.file_fingerprint == fingerprint)
            .first()
        )
        if existing:
            self.audit.emit(
                action=AuditActionEnum.INPUT_DUPLICATE_DETECTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="input_registry",
                object_id=str(existing.id),
                description=f"Duplicate file arrival detected for fingerprint {fingerprint}. Skipped duplicate processing.",
            )
            self.db.commit()
            # Find existing batch for this input if any
            existing_batch = self.db.query(Batch).filter(Batch.input_registry_id == existing.id).first()
            return existing, existing_batch, True

        # 3. Validate File Size
        if file_size == 0:
            reg = InputRegistry(
                id=uuid.uuid4(),
                feed_id=feed.id,
                filename=filename,
                file_path="",
                file_size_bytes=0,
                file_fingerprint=fingerprint,
                status=InputStatusEnum.REJECTED,
                rejection_reason="File is empty (0 bytes)",
                registered_by=actor_id,
                detected_at=datetime.now(timezone.utc),
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(reg)
            self.audit.emit(
                action=AuditActionEnum.INPUT_REJECTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="input_registry",
                object_id=str(reg.id),
                description=f"Rejected file {filename}: empty file",
            )
            self.db.commit()
            return reg, None, False

        if file_size > MAX_FILE_SIZE_BYTES:
            reg = InputRegistry(
                id=uuid.uuid4(),
                feed_id=feed.id,
                filename=filename,
                file_path="",
                file_size_bytes=file_size,
                file_fingerprint=fingerprint,
                status=InputStatusEnum.REJECTED,
                rejection_reason=f"File size {file_size} bytes exceeds max allowed {MAX_FILE_SIZE_BYTES} bytes",
                registered_by=actor_id,
                detected_at=datetime.now(timezone.utc),
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(reg)
            self.audit.emit(
                action=AuditActionEnum.INPUT_REJECTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="input_registry",
                object_id=str(reg.id),
                description=f"Rejected file {filename}: file size exceeded",
            )
            self.db.commit()
            return reg, None, False

        # 4. Validate Structure
        is_valid_structure, structure_err = self.validate_structure(content, feed)
        if not is_valid_structure:
            reg = InputRegistry(
                id=uuid.uuid4(),
                feed_id=feed.id,
                filename=filename,
                file_path="",
                file_size_bytes=file_size,
                file_fingerprint=fingerprint,
                status=InputStatusEnum.REJECTED,
                rejection_reason=structure_err,
                registered_by=actor_id,
                detected_at=datetime.now(timezone.utc),
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(reg)
            self.audit.emit(
                action=AuditActionEnum.INPUT_REJECTED,
                actor_id=actor_id,
                actor_email=actor_email,
                object_type="input_registry",
                object_id=str(reg.id),
                description=f"Rejected file {filename}: {structure_err}",
            )
            self.db.commit()
            return reg, None, False

        # 5. Store File in Landing Zone
        destination_path = f"{feed.landing_folder}/{filename}"
        saved_path = self.storage.write_file(destination_path, content)

        # 6. Create InputRegistry Record (ACCEPTED)
        input_entry = InputRegistry(
            id=uuid.uuid4(),
            feed_id=feed.id,
            filename=filename,
            file_path=saved_path,
            file_size_bytes=file_size,
            file_fingerprint=fingerprint,
            status=InputStatusEnum.ACCEPTED,
            registered_by=actor_id,
            detected_at=datetime.now(timezone.utc),
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(input_entry)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.INPUT_REGISTERED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="input_registry",
            object_id=str(input_entry.id),
            after_state={"filename": filename, "fingerprint": fingerprint, "status": "ACCEPTED"},
            description=f"Accepted incoming file {filename} with fingerprint {fingerprint}",
        )

        # 7. Create Batch and Wave 0 BatchStages
        active_version = feed.get_active_version() or feed.versions[-1]
        batch = Batch(
            id=uuid.uuid4(),
            feed_id=feed.id,
            feed_version_id=active_version.id,
            input_registry_id=input_entry.id,
            status=BatchStatusEnum.PENDING,
            triggered_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(batch)
        self.db.flush()

        for idx, stage_name in enumerate(WAVE0_STAGE_ORDER, start=1):
            bs = BatchStage(
                id=uuid.uuid4(),
                batch_id=batch.id,
                stage_name=stage_name,
                stage_order=idx,
                status=StageStatusEnum.PENDING,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self.db.add(bs)

        self.audit.emit(
            action=AuditActionEnum.BATCH_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="batches",
            object_id=str(batch.id),
            after_state={"feed_id": str(feed.id), "status": "PENDING"},
            description=f"Created batch {batch.id} for accepted input {filename}",
        )

        self.db.commit()
        self.db.refresh(input_entry)
        self.db.refresh(batch)
        return input_entry, batch, False

    def list_inputs(
        self,
        feed_id: Optional[uuid.UUID] = None,
        status_filter: Optional[InputStatusEnum] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[InputRegistry], int]:
        query = self.db.query(InputRegistry)
        if feed_id:
            query = query.filter(InputRegistry.feed_id == feed_id)
        if status_filter:
            query = query.filter(InputRegistry.status == status_filter)

        total = query.count()
        items = query.order_by(InputRegistry.detected_at.desc()).offset(offset).limit(limit).all()
        return items, total
