"""
Contract Service — Wave 0

Business logic for the Execution-Plane Contract Register and unknown production assumptions.
All state changes emit immutable audit events.
"""
import uuid
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from backend.models.contract import (
    ContractRegisterEntry,
    ContractUnknown,
    ContractStatusEnum,
    UnknownStatusEnum,
    RiskLevelEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.schemas.contract import (
    ContractCreateRequest,
    ContractUpdateRequest,
    UnknownCreateRequest,
    ConfirmUnknownRequest,
)


class ContractService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def create_contract(
        self, data: ContractCreateRequest, actor_id: str, actor_email: Optional[str] = None
    ) -> ContractRegisterEntry:
        contract = ContractRegisterEntry(
            id=uuid.uuid4(),
            source_system=data.source_system,
            target_domain=data.target_domain,
            description=data.description,
            data_owner=data.data_owner,
            story_id=data.story_id,
            notes=data.notes,
            status=ContractStatusEnum.DRAFT,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(contract)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.CONTRACT_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="contract_register_entries",
            object_id=str(contract.id),
            after_state={
                "source_system": contract.source_system,
                "target_domain": contract.target_domain,
                "status": contract.status.value,
            },
            description=f"Created contract {contract.source_system} -> {contract.target_domain}",
        )
        self.db.commit()
        self.db.refresh(contract)
        return contract

    def update_contract(
        self,
        contract_id: uuid.UUID,
        data: ContractUpdateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> ContractRegisterEntry:
        contract = self.get_contract_or_404(contract_id)

        # Lifecycle rule: retired contracts cannot be edited
        if contract.status == ContractStatusEnum.RETIRED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify a retired contract register entry",
            )

        before_state = {
            "description": contract.description,
            "data_owner": contract.data_owner,
            "status": contract.status.value,
        }

        if data.description is not None:
            contract.description = data.description
        if data.data_owner is not None:
            contract.data_owner = data.data_owner
        if data.status is not None:
            contract.status = data.status
        if data.story_id is not None:
            contract.story_id = data.story_id
        if data.notes is not None:
            contract.notes = data.notes

        contract.updated_by = actor_id
        contract.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.CONTRACT_UPDATED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="contract_register_entries",
            object_id=str(contract.id),
            before_state=before_state,
            after_state={
                "description": contract.description,
                "data_owner": contract.data_owner,
                "status": contract.status.value,
            },
            description=f"Updated contract {contract.id}",
        )
        self.db.commit()
        self.db.refresh(contract)
        return contract

    def get_contract_or_404(self, contract_id: uuid.UUID) -> ContractRegisterEntry:
        contract = (
            self.db.query(ContractRegisterEntry)
            .filter(ContractRegisterEntry.id == contract_id)
            .first()
        )
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Contract register entry {contract_id} not found",
            )
        return contract

    def list_contracts(
        self,
        source_system: Optional[str] = None,
        target_domain: Optional[str] = None,
        status_filter: Optional[ContractStatusEnum] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[ContractRegisterEntry], int]:
        query = self.db.query(ContractRegisterEntry)
        if source_system:
            query = query.filter(ContractRegisterEntry.source_system == source_system)
        if target_domain:
            query = query.filter(ContractRegisterEntry.target_domain == target_domain)
        if status_filter:
            query = query.filter(ContractRegisterEntry.status == status_filter)

        total = query.count()
        items = query.order_by(ContractRegisterEntry.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

    def add_unknown(
        self,
        contract_id: uuid.UUID,
        data: UnknownCreateRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> ContractUnknown:
        contract = self.get_contract_or_404(contract_id)

        unknown = ContractUnknown(
            id=uuid.uuid4(),
            contract_entry_id=contract.id,
            description=data.description,
            risk_level=data.risk_level,
            status=UnknownStatusEnum.OPEN,
            resolution_notes=data.resolution_notes,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(unknown)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.CONTRACT_UNKNOWN_ADDED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="contract_unknowns",
            object_id=str(unknown.id),
            after_state={
                "contract_entry_id": str(contract.id),
                "description": unknown.description,
                "risk_level": unknown.risk_level.value,
            },
            description=f"Recorded unconfirmed production assumption for contract {contract.id}",
        )
        self.db.commit()
        self.db.refresh(unknown)
        return unknown

    def confirm_unknown(
        self,
        unknown_id: uuid.UUID,
        data: ConfirmUnknownRequest,
        actor_id: str,
        actor_email: Optional[str] = None,
    ) -> ContractUnknown:
        unknown = (
            self.db.query(ContractUnknown)
            .filter(ContractUnknown.id == unknown_id)
            .first()
        )
        if not unknown:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown assumption {unknown_id} not found",
            )

        before_status = unknown.status.value
        unknown.status = UnknownStatusEnum.CONFIRMED
        unknown.resolution_notes = data.resolution_notes
        unknown.confirmed_by = actor_email or actor_id
        unknown.updated_by = actor_id
        unknown.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.CONTRACT_UNKNOWN_CONFIRMED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="contract_unknowns",
            object_id=str(unknown.id),
            before_state={"status": before_status},
            after_state={"status": unknown.status.value, "resolution_notes": unknown.resolution_notes},
            description=f"Confirmed unknown assumption {unknown.id}",
        )
        self.db.commit()
        self.db.refresh(unknown)
        return unknown

    def get_risk_view(self) -> dict:
        """Aggregated risk rollup of all unconfirmed production assumptions."""
        unknowns = (
            self.db.query(ContractUnknown, ContractRegisterEntry)
            .join(ContractRegisterEntry, ContractUnknown.contract_entry_id == ContractRegisterEntry.id)
            .filter(ContractUnknown.status == UnknownStatusEnum.OPEN)
            .all()
        )

        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        items = []
        for unk, contract in unknowns:
            counts[unk.risk_level.value] = counts.get(unk.risk_level.value, 0) + 1
            items.append({
                "id": unk.id,
                "contract_id": contract.id,
                "source_system": contract.source_system,
                "target_domain": contract.target_domain,
                "description": unk.description,
                "risk_level": unk.risk_level,
                "status": unk.status,
            })

        return {
            "total_unknowns": len(items),
            "open_unknowns": len(items),
            "by_risk_level": counts,
            "unknowns": items,
        }
