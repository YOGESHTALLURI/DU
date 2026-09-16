"""
Canonical Model Service — Wave 1 Slice 3

Provides read-only access to governed healthcare canonical reference models.
No mutation APIs exist for BAs or Engineers.
"""
import uuid
from typing import List
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.schema import SchemaDataTypeEnum
from backend.schemas.canonical_model import CanonicalModelSummary, CanonicalModelDetail, CanonicalFieldResponse


CANONICAL_SEED_DATA = [
    {
        "id": uuid.UUID("c0000000-0000-0000-0000-000000000001"),
        "name": "Member",
        "domain": "Eligibility",
        "description": "Standard healthcare member/patient enrollment demographics and identity entity.",
        "fields": [
            {"name": "member_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Unique identifier for the health plan member", "ord": 1},
            {"name": "first_name", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Member legal given name", "ord": 2},
            {"name": "last_name", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Member legal surname", "ord": 3},
            {"name": "date_of_birth", "type": SchemaDataTypeEnum.DATE, "required": True, "nullable": False, "desc": "Member date of birth (ISO YYYY-MM-DD)", "ord": 4},
            {"name": "gender", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Member administrative gender (MALE, FEMALE, OTHER, UNKNOWN)", "ord": 5},
            {"name": "address_line1", "type": SchemaDataTypeEnum.STRING, "required": False, "nullable": True, "desc": "Primary residential street address", "ord": 6},
            {"name": "city", "type": SchemaDataTypeEnum.STRING, "required": False, "nullable": True, "desc": "Primary address city", "ord": 7},
            {"name": "state", "type": SchemaDataTypeEnum.STRING, "required": False, "nullable": True, "desc": "Two-letter US state postal code", "ord": 8},
            {"name": "postal_code", "type": SchemaDataTypeEnum.STRING, "required": False, "nullable": True, "desc": "Five or nine digit postal ZIP code", "ord": 9},
        ]
    },
    {
        "id": uuid.UUID("c0000000-0000-0000-0000-000000000002"),
        "name": "Claim",
        "domain": "Claims",
        "description": "Standard healthcare medical or pharmacy claim transaction entity.",
        "fields": [
            {"name": "claim_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Unique identifier for the claim transaction", "ord": 1},
            {"name": "member_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Identifier of the enrolled member receiving services", "ord": 2},
            {"name": "provider_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "National Provider Identifier (NPI) or rendering provider code", "ord": 3},
            {"name": "service_date", "type": SchemaDataTypeEnum.DATE, "required": True, "nullable": False, "desc": "Date on which healthcare service was performed (ISO YYYY-MM-DD)", "ord": 4},
            {"name": "claim_amount", "type": SchemaDataTypeEnum.DECIMAL, "required": True, "nullable": False, "desc": "Total billed dollar amount for the claim", "ord": 5},
            {"name": "claim_status", "type": SchemaDataTypeEnum.STRING, "required": False, "nullable": True, "desc": "Adjudication status (PAID, DENIED, PENDING)", "ord": 6},
        ]
    },
    {
        "id": uuid.UUID("c0000000-0000-0000-0000-000000000003"),
        "name": "Encounter",
        "domain": "Clinical",
        "description": "Standard clinical healthcare encounter or inpatient/outpatient admission event.",
        "fields": [
            {"name": "encounter_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Unique identifier for the healthcare visit or encounter", "ord": 1},
            {"name": "patient_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Identifier of the patient", "ord": 2},
            {"name": "facility_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Identifier of the hospital or clinical facility", "ord": 3},
            {"name": "admit_date", "type": SchemaDataTypeEnum.DATE, "required": True, "nullable": False, "desc": "Encounter admission date (ISO YYYY-MM-DD)", "ord": 4},
            {"name": "discharge_date", "type": SchemaDataTypeEnum.DATE, "required": False, "nullable": True, "desc": "Encounter discharge date (ISO YYYY-MM-DD)", "ord": 5},
            {"name": "encounter_type", "type": SchemaDataTypeEnum.STRING, "required": False, "nullable": True, "desc": "Encounter classification (INPATIENT, OUTPATIENT, EMERGENCY)", "ord": 6},
        ]
    },
    {
        "id": uuid.UUID("c0000000-0000-0000-0000-000000000004"),
        "name": "Observation",
        "domain": "Clinical",
        "description": "Standard clinical observation, laboratory result, or vital sign measurement.",
        "fields": [
            {"name": "observation_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Unique identifier for the clinical observation measurement", "ord": 1},
            {"name": "patient_id", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Identifier of the patient", "ord": 2},
            {"name": "observation_code", "type": SchemaDataTypeEnum.STRING, "required": True, "nullable": False, "desc": "Standard LOINC or clinical measurement code", "ord": 3},
            {"name": "observation_date", "type": SchemaDataTypeEnum.DATE, "required": True, "nullable": False, "desc": "Observation/specimen collection timestamp (ISO YYYY-MM-DD)", "ord": 4},
            {"name": "result_value", "type": SchemaDataTypeEnum.DECIMAL, "required": False, "nullable": True, "desc": "Quantitative numerical measurement result", "ord": 5},
            {"name": "units", "type": SchemaDataTypeEnum.STRING, "required": False, "nullable": True, "desc": "Standard units of measure (e.g., mg/dL, mmHg)", "ord": 6},
        ]
    },
]


class CanonicalModelService:
    def __init__(self, db: Session):
        self.db = db

    def seed_default_models_if_needed(self) -> None:
        """Ensures default reference models are present (used in testing & initial startup)."""
        count = self.db.query(CanonicalModel).count()
        if count >= len(CANONICAL_SEED_DATA):
            return

        for m_data in CANONICAL_SEED_DATA:
            existing = self.db.query(CanonicalModel).filter(CanonicalModel.name == m_data["name"]).first()
            if not existing:
                model = CanonicalModel(
                    id=m_data["id"],
                    name=m_data["name"],
                    domain=m_data["domain"],
                    description=m_data["description"],
                    created_by="system_seed",
                    updated_by="system_seed",
                )
                self.db.add(model)
                self.db.flush()

                for f_data in m_data["fields"]:
                    field = CanonicalField(
                        id=uuid.uuid4(),
                        canonical_model_id=model.id,
                        field_name=f_data["name"],
                        data_type=f_data["type"],
                        is_required=f_data["required"],
                        is_nullable=f_data["nullable"],
                        description=f_data["desc"],
                        ordinal_position=f_data["ord"],
                        created_by="system_seed",
                        updated_by="system_seed",
                    )
                    self.db.add(field)
                self.db.commit()

    def list_models(self) -> List[CanonicalModelSummary]:
        self.seed_default_models_if_needed()
        models = self.db.query(CanonicalModel).order_by(CanonicalModel.name).all()
        result = []
        for m in models:
            result.append(
                CanonicalModelSummary(
                    id=m.id,
                    name=m.name,
                    domain=m.domain,
                    description=m.description,
                    field_count=len(m.fields),
                )
            )
        return result

    def get_model(self, model_id: uuid.UUID) -> CanonicalModelDetail:
        self.seed_default_models_if_needed()
        model = self.db.query(CanonicalModel).filter(CanonicalModel.id == model_id).first()
        if not model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Canonical model {model_id} not found",
            )
        return CanonicalModelDetail(
            id=model.id,
            name=model.name,
            domain=model.domain,
            description=model.description,
            fields=[CanonicalFieldResponse.model_validate(f) for f in model.fields],
        )
