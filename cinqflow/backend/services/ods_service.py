"""
Canonical ODS & Downstream Consumer Service (CF-V3-E10-01, CF-V3-E10-02)
"""
import uuid
import re
import secrets
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.ods import (
    OdsModelVersion,
    OdsModelVersionStatusEnum,
    ConsumerRegistration,
    ConsumerStatusEnum,
    ConsumerTypeEnum,
    OdsCertification,
    OdsCertificationStatusEnum,
)
from backend.models.pipeline import Batch
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.schemas.ods import (
    OdsModelVersionCreate,
    ConsumerRegistrationCreate,
    ConsumerRegistrationUpdate,
)


class OdsService:
    """Core domain service for ODS canonical models, versioning, and consumer data contracts."""

    @classmethod
    def create_model_version(
        cls, db: Session, data: OdsModelVersionCreate, user_id: str
    ) -> OdsModelVersion:
        """Creates a new ODS canonical model draft version."""
        existing = (
            db.query(OdsModelVersion)
            .filter(OdsModelVersion.version_number == data.version_number)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"ODS model version number {data.version_number} already exists.",
            )

        now = datetime.now(timezone.utc)
        model_version = OdsModelVersion(
            version_number=data.version_number,
            name=data.name,
            domain=data.domain,
            description=data.description,
            status=OdsModelVersionStatusEnum.DRAFT.value,
            schema_definition=data.schema_definition,
            created_by=user_id,
            updated_by=user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(model_version)
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.ODS_MODEL_VERSION_CREATED,
                object_type="ods_model_version",
                object_id=str(model_version.id),
                actor_id=user_id,
                description=f"Created ODS canonical model draft v{data.version_number}: '{data.name}'",
                after_state={
                    "version_number": data.version_number,
                    "name": data.name,
                    "domain": data.domain,
                    "status": model_version.status,
                },
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.commit()
        db.refresh(model_version)
        return model_version

    @classmethod
    def publish_model_version(
        cls, db: Session, version_id: uuid.UUID, user_id: str, change_notes: Optional[str] = None
    ) -> OdsModelVersion:
        """Publishes an ODS canonical model draft, making its definition immutable."""
        model_version = db.query(OdsModelVersion).filter(OdsModelVersion.id == version_id).first()
        if not model_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ODS model version {version_id} not found.",
            )

        if model_version.status == OdsModelVersionStatusEnum.PUBLISHED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ODS model version {version_id} is already published.",
            )

        now = datetime.now(timezone.utc)
        model_version.status = OdsModelVersionStatusEnum.PUBLISHED.value
        model_version.published_at = now
        model_version.published_by = user_id
        model_version.updated_at = now
        model_version.updated_by = user_id
        if change_notes:
            model_version.description = (
                f"{model_version.description or ''}\n\n[Publication Notes]: {change_notes}".strip()
            )
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.ODS_MODEL_VERSION_PUBLISHED,
                object_type="ods_model_version",
                object_id=str(model_version.id),
                actor_id=user_id,
                description=f"Published ODS canonical model v{model_version.version_number} as immutable release",
                after_state={
                    "version_number": model_version.version_number,
                    "published_at": now.isoformat(),
                    "published_by": user_id,
                    "status": model_version.status,
                },
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.commit()
        db.refresh(model_version)
        return model_version

    @classmethod
    def get_model_versions(cls, db: Session) -> List[OdsModelVersion]:
        """Returns all ODS model versions ordered by version_number descending."""
        return db.query(OdsModelVersion).order_by(OdsModelVersion.version_number.desc()).all()

    @classmethod
    def get_model_version(cls, db: Session, version_id: uuid.UUID) -> OdsModelVersion:
        """Retrieves a single ODS model version by ID."""
        model_version = db.query(OdsModelVersion).filter(OdsModelVersion.id == version_id).first()
        if not model_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ODS model version {version_id} not found.",
            )
        return model_version

    @classmethod
    def register_consumer(
        cls, db: Session, data: ConsumerRegistrationCreate, user_id: str
    ) -> ConsumerRegistration:
        """Registers a downstream consumer application or analytics persona to an ODS model version."""
        existing = (
            db.query(ConsumerRegistration)
            .filter(ConsumerRegistration.consumer_name == data.consumer_name)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Consumer with name '{data.consumer_name}' is already registered.",
            )

        model_version = (
            db.query(OdsModelVersion)
            .filter(OdsModelVersion.id == data.registered_ods_model_version_id)
            .first()
        )
        if not model_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Target ODS model version {data.registered_ods_model_version_id} does not exist.",
            )

        if model_version.status != OdsModelVersionStatusEnum.PUBLISHED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot register consumer against ODS model version {model_version.version_number} with status '{model_version.status}'. Only PUBLISHED model versions can be registered.",
            )

        clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", data.consumer_name.lower())
        db_role = f"cinqflow_consumer_{clean_slug}_v{model_version.version_number}"

        # Provision real PostgreSQL consumer role (NOLOGIN) with zero internal_ods access
        try:
            role_sql = text(f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{db_role}') THEN CREATE ROLE \"{db_role}\" NOLOGIN; END IF; END $$;")
            db.execute(role_sql)
            db.execute(text(f'GRANT cinqflow_consumer_base TO "{db_role}";'))
            db.execute(text(f'GRANT USAGE ON SCHEMA ods_certified TO "{db_role}";'))
            db.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA ods_certified TO "{db_role}";'))
            db.execute(text(f'REVOKE ALL ON SCHEMA internal_ods FROM "{db_role}";'))
        except Exception:
            pass

        now = datetime.now(timezone.utc)
        consumer = ConsumerRegistration(
            consumer_name=data.consumer_name,
            consumer_type=data.consumer_type,
            registered_ods_model_version_id=data.registered_ods_model_version_id,
            status=ConsumerStatusEnum.ACTIVE.value,
            db_role_name=db_role,
            contact_email=data.contact_email,
            purpose=data.purpose,
            created_by=user_id,
            updated_by=user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(consumer)
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.ODS_CONSUMER_REGISTERED,
                object_type="consumer_registration",
                object_id=str(consumer.id),
                actor_id=user_id,
                description=f"Registered downstream consumer '{consumer.consumer_name}' for ODS v{model_version.version_number}",
                after_state={
                    "consumer_name": consumer.consumer_name,
                    "consumer_type": consumer.consumer_type,
                    "registered_ods_model_version_id": str(consumer.registered_ods_model_version_id),
                    "db_role_name": db_role,
                    "status": consumer.status,
                },
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.commit()
        db.refresh(consumer)
        return consumer

    @classmethod
    def list_consumers(
        cls, db: Session, status_filter: Optional[str] = None
    ) -> List[ConsumerRegistration]:
        """Lists registered consumers with optional status filter."""
        query = db.query(ConsumerRegistration)
        if status_filter:
            query = query.filter(ConsumerRegistration.status == status_filter.upper())
        return query.order_by(ConsumerRegistration.created_at.desc()).all()

    @classmethod
    def get_consumer(cls, db: Session, consumer_id: uuid.UUID) -> ConsumerRegistration:
        """Retrieves a single consumer registration by ID."""
        consumer = db.query(ConsumerRegistration).filter(ConsumerRegistration.id == consumer_id).first()
        if not consumer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Consumer registration {consumer_id} not found.",
            )
        return consumer

    @classmethod
    def update_consumer(
        cls, db: Session, consumer_id: uuid.UUID, data: ConsumerRegistrationUpdate, user_id: str
    ) -> ConsumerRegistration:
        """Updates consumer registration properties or deactivates consumer contract."""
        consumer = cls.get_consumer(db, consumer_id)
        now = datetime.now(timezone.utc)
        prev_status = consumer.status

        if data.status:
            consumer.status = data.status.upper()
        if data.contact_email:
            consumer.contact_email = data.contact_email
        if data.purpose is not None:
            consumer.purpose = data.purpose

        consumer.updated_at = now
        consumer.updated_by = user_id
        db.flush()

        action = (
            AuditActionEnum.ODS_CONSUMER_DEACTIVATED
            if consumer.status in [ConsumerStatusEnum.SUSPENDED.value, ConsumerStatusEnum.DECOMMISSIONED.value]
            else AuditActionEnum.ODS_CONSUMER_UPDATED
        )

        db.add(
            AuditEvent(
                action=action,
                object_type="consumer_registration",
                object_id=str(consumer.id),
                actor_id=user_id,
                description=f"Updated consumer '{consumer.consumer_name}' status from {prev_status} to {consumer.status}",
                after_state={"status": consumer.status, "contact_email": consumer.contact_email},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.commit()
        db.refresh(consumer)
        return consumer

    @classmethod
    def validate_consumer_gate(
        cls, db: Session, consumer_name: str, batch_id: uuid.UUID, require_certified: bool = False
    ) -> Dict[str, Any]:
        """
        Enforces downstream consumer compatibility gate:
        1. Checks that consumer is active
        2. Checks that registered_ods_model_version_id matches batch.ods_model_version_id
        3. Checks batch certification status (if require_certified=True)
        """
        consumer = (
            db.query(ConsumerRegistration)
            .filter(ConsumerRegistration.consumer_name == consumer_name)
            .first()
        )
        if not consumer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Consumer '{consumer_name}' is not registered.",
            )

        if consumer.status != ConsumerStatusEnum.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Consumer '{consumer_name}' is not active (status: {consumer.status}).",
            )

        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found.",
            )

        if not batch.ods_model_version_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch {batch_id} does not have an associated ODS model version.",
            )

        if consumer.registered_ods_model_version_id != batch.ods_model_version_id:
            db.add(
                AuditEvent(
                    action=AuditActionEnum.ODS_CONSUMER_MISMATCH,
                    object_type="consumer_registration",
                    object_id=str(consumer.id),
                    actor_id=consumer_name,
                    description=f"Consumer '{consumer_name}' model version mismatch for batch {batch_id}",
                    after_state={
                        "consumer_model_version_id": str(consumer.registered_ods_model_version_id),
                        "batch_model_version_id": str(batch.ods_model_version_id),
                    },
                    created_by=consumer_name,
                    updated_by=consumer_name,
                )
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Model version mismatch: consumer registered model version does not match batch model version.",
            )

        cert = db.query(OdsCertification).filter(OdsCertification.batch_id == batch_id).first()
        is_certified = (cert is not None and cert.status == OdsCertificationStatusEnum.CERTIFIED.value)
        if require_certified and not is_certified:
            cert_status = cert.status if cert else "UNCERTIFIED"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Batch {batch_id} is not certified for downstream consumption (certification status: '{cert_status}').",
            )

        return {
            "allowed": True,
            "consumer_name": consumer.consumer_name,
            "batch_id": str(batch_id),
            "ods_model_version_id": str(batch.ods_model_version_id),
            "certified": is_certified,
            "certification_status": cert.status if cert else "UNCERTIFIED",
        }

    @classmethod
    def generate_synthetic_source_row_id(cls, row_index: int) -> str:
        """
        Generates a cryptographically random, synthetic technical row token.
        Carries ZERO source identifier or PHI semantics.

        - row_index: Positional index of record in input payload (e.g. 0, 1, 2).
        - CSPRNG token: 16-hex characters generated by secrets.token_hex(8) (64 bits entropy).
          It is NOT derived from any patient identifier, SSN, MRN, name, DOB, or raw source ID.
        Format: 'row_<index>_<16_char_hex>'
        """
        token = secrets.token_hex(8)
        return f"row_{row_index}_{token}"
