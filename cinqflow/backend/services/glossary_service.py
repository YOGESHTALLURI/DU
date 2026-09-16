"""
Wave 1 Slice 7 Service — Enterprise Business Glossary & Canonical Semantics (CF-V1-E14-01)

Provides:
- Governed Healthcare Glossary Term CRUD & Lifecycle (DRAFT -> APPROVED -> DEPRECATED)
- Canonical Model & Field Bidirectional Linking
- Sub-300ms Search & Faceted Filtering
- Pre-seeded Core Healthcare Reference Dictionary
- Zero-PHI Synchronous Audit Emission
"""
import uuid
import re
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from fastapi import HTTPException, status

from backend.models.glossary import (
    GlossaryTerm,
    GlossaryCanonicalLink,
    GlossaryTermStatusEnum,
    GlossaryPhiClassificationEnum,
    GlossaryCodeSetEnum,
)
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.core.security import CurrentUser
from backend.schemas.glossary import (
    GlossaryTermCreate,
    GlossaryTermUpdate,
    GlossaryTermDeprecateRequest,
    GlossaryTermResponse,
    CanonicalFieldLinkResponse,
    GlossarySearchResponse,
)


CORE_HEALTHCARE_GLOSSARY_SEED = [
    {
        "name": "Member Identifier",
        "acronym": "MID",
        "synonyms": ["Subscriber ID", "Beneficiary ID", "Member No", "Enrollee ID"],
        "domain": "Eligibility",
        "definition": "Unique alphanumeric enterprise identifier assigned to an enrolled health plan member.",
        "clinical_context": "Critical cross-cutting identifier for member eligibility verification, claim adjudication, and clinical history tracking.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.CONFIRMED_PHI,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Member", "member_id"), ("Claim", "member_id")],
    },
    {
        "name": "Date of Birth",
        "acronym": "DOB",
        "synonyms": ["Birth Date", "DOB", "Patient Birthdate"],
        "domain": "Eligibility",
        "definition": "The calendar date on which the patient or enrolled health plan member was born (ISO-8601 format: YYYY-MM-DD).",
        "clinical_context": "Mandatory demographic attribute required for patient identity matching and age-dependent clinical decision support.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.CONFIRMED_PHI,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Member", "date_of_birth")],
    },
    {
        "name": "Administrative Gender",
        "acronym": "GENDER",
        "synonyms": ["Sex", "Biological Sex", "Administrative Sex"],
        "domain": "Eligibility",
        "definition": "The gender classification of a person for administrative and legal purposes (MALE, FEMALE, OTHER, UNKNOWN).",
        "clinical_context": "Used in clinical risk adjustment and preventive health screening protocols.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.POTENTIAL_PHI,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Member", "gender")],
    },
    {
        "name": "Claim Identifier",
        "acronym": "ICN",
        "synonyms": ["Claim Number", "Internal Control Number", "Claim ID"],
        "domain": "Claims",
        "definition": "Unique tracking number assigned to a healthcare claim submission for institutional or professional services.",
        "clinical_context": "Authoritative financial key utilized across EDI 837 ingestion, claim adjudication, and remittance processing.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.NONE,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Claim", "claim_id")],
    },
    {
        "name": "National Provider Identifier",
        "acronym": "NPI",
        "synonyms": ["Rendering NPI", "Billing NPI", "Provider ID"],
        "domain": "Provider",
        "definition": "Standard 10-digit unique identification number for covered healthcare providers in the United States.",
        "clinical_context": "Mandated by HIPAA for electronic healthcare transactions to uniquely identify physicians and facilities.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.POTENTIAL_PHI,
        "code_set": GlossaryCodeSetEnum.NPI,
        "canonical_targets": [("Claim", "provider_id")],
    },
    {
        "name": "Service Date",
        "acronym": "DOS",
        "synonyms": ["Date of Service", "Treatment Date", "Procedure Date"],
        "domain": "Claims",
        "definition": "The date on which healthcare services or items were rendered to the patient.",
        "clinical_context": "Determines member benefit coverage eligibility at the time care was provided.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.POTENTIAL_PHI,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Claim", "service_date")],
    },
    {
        "name": "Billed Claim Amount",
        "acronym": "CHG",
        "synonyms": ["Charge Amount", "Billed Charges", "Total Billed Amount"],
        "domain": "Financial",
        "definition": "The total dollar amount billed by the rendering healthcare provider before contractual discounts or payer adjudication.",
        "clinical_context": "Used in financial auditing, charge variance analysis, and initial fee-for-service evaluation.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.NONE,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Claim", "claim_amount")],
    },
    {
        "name": "Claim Adjudication Status",
        "acronym": "STATUS",
        "synonyms": ["Claim Status", "Processing Disposition", "Payment Status"],
        "domain": "Claims",
        "definition": "Current processing outcome or adjudication determination of the healthcare claim (PAID, DENIED, PENDING).",
        "clinical_context": "Indicates whether payer financial obligation has been settled or rejected.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.NONE,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Claim", "claim_status")],
    },
    {
        "name": "Encounter Identifier",
        "acronym": "ENC",
        "synonyms": ["Visit Number", "Encounter ID", "Account Number"],
        "domain": "Clinical",
        "definition": "Unique identifier for an interaction between a patient and healthcare provider (inpatient stay, ambulatory visit, or ER visit).",
        "clinical_context": "Links clinical orders, diagnostic notes, vital signs, and discharge summaries to an episode of care.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.NONE,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Encounter", "encounter_id")],
    },
    {
        "name": "Patient Identifier",
        "acronym": "PID",
        "synonyms": ["Medical Record Number", "MRN", "Patient ID", "Enterprise Master Patient ID"],
        "domain": "Clinical",
        "definition": "Primary identifier for a patient within an electronic medical record (EMR) or clinical health system.",
        "clinical_context": "Used across inpatient admissions, clinical labs, and pharmacy dispensing systems.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.CONFIRMED_PHI,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Encounter", "patient_id"), ("Observation", "patient_id")],
    },
    {
        "name": "Encounter Admission Date",
        "acronym": "ADM",
        "synonyms": ["Admit Date", "Admission Date", "Check-in Date"],
        "domain": "Clinical",
        "definition": "The calendar date and time when the patient was formally admitted to a healthcare facility.",
        "clinical_context": "Calculates inpatient length of stay (LOS) and defines readmission measurement windows.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.POTENTIAL_PHI,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Encounter", "admit_date")],
    },
    {
        "name": "Observation Identifier",
        "acronym": "OBS",
        "synonyms": ["Observation ID", "Lab Result ID", "Measurement ID"],
        "domain": "Clinical",
        "definition": "Unique tracking key for an individual clinical measurement, lab test, or diagnostic finding.",
        "clinical_context": "Granular record of vital signs, laboratory panels, or physiological measurements.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.NONE,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Observation", "observation_id")],
    },
    {
        "name": "Clinical Observation Code",
        "acronym": "LOINC_CD",
        "synonyms": ["LOINC Code", "Test Code", "Observation Code", "Analyte Code"],
        "domain": "Clinical",
        "definition": "Standard clinical vocabulary code identifying the specific laboratory test or clinical observation.",
        "clinical_context": "Uses Logical Observation Identifiers Names and Codes (LOINC) for universal interoperability.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.NONE,
        "code_set": GlossaryCodeSetEnum.LOINC,
        "canonical_targets": [("Observation", "observation_code")],
    },
    {
        "name": "Observation Result Value",
        "acronym": "VAL",
        "synonyms": ["Measurement Value", "Result Value", "Test Result"],
        "domain": "Clinical",
        "definition": "Quantitative or qualitative outcome value determined for a clinical test or physiological observation.",
        "clinical_context": "Evaluated against normal reference ranges to detect clinical abnormalities.",
        "status": GlossaryTermStatusEnum.APPROVED,
        "phi_classification": GlossaryPhiClassificationEnum.POTENTIAL_PHI,
        "code_set": GlossaryCodeSetEnum.NONE,
        "canonical_targets": [("Observation", "result_value")],
    },
]


def normalize_term_name(name: str) -> str:
    """Produces a canonical lowercased and whitespace-trimmed string for uniqueness comparison."""
    return re.sub(r"\s+", " ", name.strip().lower())


class GlossaryService:
    def __init__(self, db: Session, audit: Optional[AuditService] = None):
        self.db = db
        self.audit = audit or AuditService(db)

    def seed_default_terms_if_needed(self) -> int:
        """
        Seeds standard healthcare glossary terms and automatically links them to existing
        canonical reference fields (Member, Claim, Encounter, Observation).
        """
        seeded_count = 0
        for term_def in CORE_HEALTHCARE_GLOSSARY_SEED:
            norm_name = normalize_term_name(term_def["name"])
            existing = self.db.query(GlossaryTerm).filter(GlossaryTerm.normalized_name == norm_name).first()
            if not existing:
                term = GlossaryTerm(
                    name=term_def["name"],
                    normalized_name=norm_name,
                    acronym=term_def["acronym"],
                    synonyms=term_def["synonyms"],
                    domain=term_def["domain"],
                    definition=term_def["definition"],
                    clinical_context=term_def["clinical_context"],
                    data_steward="system_seed@cinqflow.local",
                    status=term_def["status"],
                    phi_classification=term_def["phi_classification"],
                    code_set=term_def["code_set"],
                    created_by="system_seed",
                    updated_by="system_seed",
                )
                self.db.add(term)
                self.db.flush()
                seeded_count += 1

                # Link to canonical fields if available
                for model_name, field_name in term_def.get("canonical_targets", []):
                    c_field = (
                        self.db.query(CanonicalField)
                        .join(CanonicalModel, CanonicalField.canonical_model_id == CanonicalModel.id)
                        .filter(CanonicalModel.name == model_name, CanonicalField.field_name == field_name)
                        .first()
                    )
                    if c_field:
                        link = GlossaryCanonicalLink(
                            glossary_term_id=term.id,
                            canonical_field_id=c_field.id,
                            created_by="system_seed",
                            updated_by="system_seed",
                        )
                        self.db.add(link)

        if seeded_count > 0:
            self.db.commit()
        return seeded_count

    def _build_term_response(self, term: GlossaryTerm) -> GlossaryTermResponse:
        """Builds a hydrated GlossaryTermResponse with canonical field details."""
        links: List[CanonicalFieldLinkResponse] = []
        for cl in term.canonical_links:
            if cl.canonical_field and cl.canonical_field.canonical_model:
                links.append(
                    CanonicalFieldLinkResponse(
                        link_id=cl.id,
                        canonical_field_id=cl.canonical_field.id,
                        canonical_field_name=cl.canonical_field.field_name,
                        canonical_model_id=cl.canonical_field.canonical_model.id,
                        canonical_model_name=cl.canonical_field.canonical_model.name,
                        data_type=cl.canonical_field.data_type.value if hasattr(cl.canonical_field.data_type, "value") else str(cl.canonical_field.data_type),
                        is_required=cl.canonical_field.is_required,
                        is_nullable=cl.canonical_field.is_nullable,
                    )
                )

        return GlossaryTermResponse(
            id=term.id,
            name=term.name,
            normalized_name=term.normalized_name,
            acronym=term.acronym,
            synonyms=term.synonyms or [],
            domain=term.domain,
            definition=term.definition,
            clinical_context=term.clinical_context,
            data_steward=term.data_steward,
            status=term.status,
            phi_classification=term.phi_classification,
            code_set=term.code_set,
            deprecation_reason=term.deprecation_reason,
            replaced_by_term_id=term.replaced_by_term_id,
            linked_canonical_fields_count=len(links),
            linked_canonical_fields=links,
            created_at=term.created_at,
            created_by=term.created_by,
            updated_at=term.updated_at,
            updated_by=term.updated_by,
            version=term.version,
        )

    def search_terms(
        self,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        status: Optional[GlossaryTermStatusEnum] = None,
        phi_classification: Optional[GlossaryPhiClassificationEnum] = None,
        code_set: Optional[GlossaryCodeSetEnum] = None,
        canonical_model_id: Optional[uuid.UUID] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> GlossarySearchResponse:
        """
        Fast search and filtering across terms.
        Target performance: sub-300ms.
        """
        q = (
            self.db.query(GlossaryTerm)
            .options(
                joinedload(GlossaryTerm.canonical_links)
                .joinedload(GlossaryCanonicalLink.canonical_field)
                .joinedload(CanonicalField.canonical_model)
            )
        )

        if query:
            clean_q = f"%{query.strip().lower()}%"
            q = q.filter(
                or_(
                    func.lower(GlossaryTerm.name).like(clean_q),
                    func.lower(GlossaryTerm.acronym).like(clean_q),
                    func.lower(GlossaryTerm.definition).like(clean_q),
                    func.lower(GlossaryTerm.domain).like(clean_q),
                )
            )

        if domain and domain.upper() != "ALL":
            q = q.filter(GlossaryTerm.domain == domain)

        if status:
            q = q.filter(GlossaryTerm.status == status)

        if phi_classification:
            q = q.filter(GlossaryTerm.phi_classification == phi_classification)

        if code_set and code_set != GlossaryCodeSetEnum.NONE:
            q = q.filter(GlossaryTerm.code_set == code_set)

        if canonical_model_id:
            q = q.join(GlossaryTerm.canonical_links).join(GlossaryCanonicalLink.canonical_field).filter(
                CanonicalField.canonical_model_id == canonical_model_id
            )

        total = q.distinct(GlossaryTerm.id).count() if canonical_model_id else q.count()
        terms = q.order_by(GlossaryTerm.domain.asc(), GlossaryTerm.name.asc()).offset(skip).limit(limit).all()

        # Compute summary facets
        domains_query = self.db.query(GlossaryTerm.domain).distinct().all()
        domains = sorted([d[0] for d in domains_query if d[0]])

        phi_stats = (
            self.db.query(GlossaryTerm.phi_classification, func.count(GlossaryTerm.id))
            .group_by(GlossaryTerm.phi_classification)
            .all()
        )
        phi_counts = {p[0].value if hasattr(p[0], "value") else str(p[0]): p[1] for p in phi_stats}

        status_stats = (
            self.db.query(GlossaryTerm.status, func.count(GlossaryTerm.id))
            .group_by(GlossaryTerm.status)
            .all()
        )
        status_counts = {s[0].value if hasattr(s[0], "value") else str(s[0]): s[1] for s in status_stats}

        items = [self._build_term_response(t) for t in terms]

        return GlossarySearchResponse(
            total=total,
            items=items,
            domains=domains,
            phi_counts=phi_counts,
            status_counts=status_counts,
        )

    def get_term(self, term_id: uuid.UUID) -> GlossaryTermResponse:
        """Retrieves a single term with full canonical linkages."""
        term = (
            self.db.query(GlossaryTerm)
            .options(
                joinedload(GlossaryTerm.canonical_links)
                .joinedload(GlossaryCanonicalLink.canonical_field)
                .joinedload(CanonicalField.canonical_model)
            )
            .filter(GlossaryTerm.id == term_id)
            .first()
        )
        if not term:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Glossary term '{term_id}' not found")
        return self._build_term_response(term)

    def create_term(self, payload: GlossaryTermCreate, user: CurrentUser) -> GlossaryTermResponse:
        """Creates a new business glossary term. Defaults to DRAFT status."""
        norm_name = normalize_term_name(payload.name)
        existing = self.db.query(GlossaryTerm).filter(GlossaryTerm.normalized_name == norm_name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Glossary term with name '{payload.name}' already exists (ID: {existing.id})"
            )

        term = GlossaryTerm(
            name=payload.name.strip(),
            normalized_name=norm_name,
            acronym=payload.acronym.strip() if payload.acronym else None,
            synonyms=payload.synonyms or [],
            domain=payload.domain.strip(),
            definition=payload.definition.strip(),
            clinical_context=payload.clinical_context.strip() if payload.clinical_context else None,
            data_steward=payload.data_steward or user.email,
            status=GlossaryTermStatusEnum.DRAFT,
            phi_classification=payload.phi_classification,
            code_set=payload.code_set,
            created_by=user.email,
            updated_by=user.email,
        )
        self.db.add(term)
        self.db.flush()

        # Link any initial canonical fields
        for field_id in payload.canonical_field_ids:
            c_field = self.db.query(CanonicalField).filter(CanonicalField.id == field_id).first()
            if c_field:
                link = GlossaryCanonicalLink(
                    glossary_term_id=term.id,
                    canonical_field_id=c_field.id,
                    created_by=user.email,
                    updated_by=user.email,
                )
                self.db.add(link)

        self.audit.emit(
            action=AuditActionEnum.GLOSSARY_TERM_CREATED,
            actor_id=user.user_id,
            actor_email=user.email,
            object_type="glossary_terms",
            object_id=str(term.id),
            after_state={
                "name": term.name,
                "domain": term.domain,
                "status": term.status.value,
                "phi_classification": term.phi_classification.value,
                "code_set": term.code_set.value,
                "linked_fields_count": len(payload.canonical_field_ids),
            },
            description=f"Created glossary term '{term.name}' in domain '{term.domain}'",
        )
        self.db.commit()
        return self.get_term(term.id)

    def update_term(self, term_id: uuid.UUID, payload: GlossaryTermUpdate, user: CurrentUser) -> GlossaryTermResponse:
        """Updates metadata of a glossary term. Modifying approved terms increments version."""
        term = self.db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
        if not term:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Glossary term '{term_id}' not found")

        if term.status == GlossaryTermStatusEnum.DEPRECATED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit deprecated glossary term '{term.name}'. Re-activate or propose a new term."
            )

        # Business analysts can only edit DRAFT terms
        if "DATA_STEWARD" not in user.roles and "ENGINEER" not in user.roles:
            if term.status != GlossaryTermStatusEnum.DRAFT:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Business analysts can only modify terms in DRAFT status"
                )

        before_state = {
            "name": term.name,
            "domain": term.domain,
            "definition": term.definition,
            "phi_classification": term.phi_classification.value,
            "code_set": term.code_set.value,
            "version": term.version,
        }

        if payload.name is not None:
            new_norm = normalize_term_name(payload.name)
            if new_norm != term.normalized_name:
                collision = self.db.query(GlossaryTerm).filter(
                    GlossaryTerm.normalized_name == new_norm,
                    GlossaryTerm.id != term.id
                ).first()
                if collision:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Glossary term with name '{payload.name}' already exists"
                    )
                term.name = payload.name.strip()
                term.normalized_name = new_norm

        if payload.acronym is not None:
            term.acronym = payload.acronym.strip() if payload.acronym else None
        if payload.synonyms is not None:
            term.synonyms = payload.synonyms
        if payload.domain is not None:
            term.domain = payload.domain.strip()
        if payload.definition is not None:
            term.definition = payload.definition.strip()
        if payload.clinical_context is not None:
            term.clinical_context = payload.clinical_context.strip() if payload.clinical_context else None
        if payload.data_steward is not None:
            term.data_steward = payload.data_steward.strip() if payload.data_steward else None
        if payload.phi_classification is not None:
            term.phi_classification = payload.phi_classification
        if payload.code_set is not None:
            term.code_set = payload.code_set

        term.updated_by = user.email
        term.updated_at = datetime.now(timezone.utc)
        term.version += 1

        self.audit.emit(
            action=AuditActionEnum.GLOSSARY_TERM_UPDATED,
            actor_id=user.user_id,
            actor_email=user.email,
            object_type="glossary_terms",
            object_id=str(term.id),
            before_state=before_state,
            after_state={
                "name": term.name,
                "domain": term.domain,
                "definition": term.definition,
                "phi_classification": term.phi_classification.value,
                "code_set": term.code_set.value,
                "version": term.version,
            },
            description=f"Updated glossary term '{term.name}' to version {term.version}",
        )
        self.db.commit()
        return self.get_term(term.id)

    def approve_term(self, term_id: uuid.UUID, user: CurrentUser) -> GlossaryTermResponse:
        """Approves a draft term. Requires DATA_STEWARD or ENGINEER role."""
        if "DATA_STEWARD" not in user.roles and "ENGINEER" not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Data Stewards or Engineers can approve business glossary terms"
            )

        term = self.db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
        if not term:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Glossary term '{term_id}' not found")

        if term.status == GlossaryTermStatusEnum.DEPRECATED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve deprecated term '{term.name}'. Must propose a new version."
            )

        if term.status == GlossaryTermStatusEnum.APPROVED:
            return self.get_term(term.id)

        term.status = GlossaryTermStatusEnum.APPROVED
        term.updated_by = user.email
        term.updated_at = datetime.now(timezone.utc)
        term.version += 1

        self.audit.emit(
            action=AuditActionEnum.GLOSSARY_TERM_APPROVED,
            actor_id=user.user_id,
            actor_email=user.email,
            object_type="glossary_terms",
            object_id=str(term.id),
            after_state={
                "name": term.name,
                "domain": term.domain,
                "status": term.status.value,
                "version": term.version,
            },
            description=f"Approved glossary term '{term.name}' (status: APPROVED)",
        )
        self.db.commit()
        return self.get_term(term.id)

    def deprecate_term(
        self, term_id: uuid.UUID, payload: GlossaryTermDeprecateRequest, user: CurrentUser
    ) -> GlossaryTermResponse:
        """Deprecates an active term. Requires DATA_STEWARD or ENGINEER role and mandatory reason."""
        if "DATA_STEWARD" not in user.roles and "ENGINEER" not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Data Stewards or Engineers can deprecate business glossary terms"
            )

        term = self.db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
        if not term:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Glossary term '{term_id}' not found")

        reason = payload.deprecation_reason.strip()
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Deprecation reason must be provided and cannot be empty"
            )

        if payload.replaced_by_term_id:
            replacement = self.db.query(GlossaryTerm).filter(GlossaryTerm.id == payload.replaced_by_term_id).first()
            if not replacement:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Replacement term '{payload.replaced_by_term_id}' does not exist"
                )

        term.status = GlossaryTermStatusEnum.DEPRECATED
        term.deprecation_reason = reason
        term.replaced_by_term_id = payload.replaced_by_term_id
        term.updated_by = user.email
        term.updated_at = datetime.now(timezone.utc)
        term.version += 1

        self.audit.emit(
            action=AuditActionEnum.GLOSSARY_TERM_DEPRECATED,
            actor_id=user.user_id,
            actor_email=user.email,
            object_type="glossary_terms",
            object_id=str(term.id),
            after_state={
                "name": term.name,
                "status": term.status.value,
                "deprecation_reason": term.deprecation_reason,
                "replaced_by_term_id": str(term.replaced_by_term_id) if term.replaced_by_term_id else None,
            },
            description=f"Deprecated glossary term '{term.name}': {term.deprecation_reason}",
        )
        self.db.commit()
        return self.get_term(term.id)

    def delete_draft_term(self, term_id: uuid.UUID, user: CurrentUser) -> Dict[str, str]:
        """Permanently deletes a term ONLY if it is in DRAFT status."""
        term = self.db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
        if not term:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Glossary term '{term_id}' not found")

        if term.status != GlossaryTermStatusEnum.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete term in '{term.status.value}' status. Only DRAFT terms may be deleted. Approved terms must be deprecated."
            )

        term_name = term.name
        self.audit.emit(
            action=AuditActionEnum.GLOSSARY_TERM_DELETED,
            actor_id=user.user_id,
            actor_email=user.email,
            object_type="glossary_terms",
            object_id=str(term.id),
            before_state={
                "name": term.name,
                "domain": term.domain,
                "status": term.status.value,
            },
            description=f"Deleted draft glossary term '{term_name}'",
        )
        self.db.delete(term)
        self.db.commit()
        return {"message": f"Draft glossary term '{term_name}' deleted successfully"}

    def link_canonical_field(
        self, term_id: uuid.UUID, canonical_field_id: uuid.UUID, user: CurrentUser
    ) -> CanonicalFieldLinkResponse:
        """Links a glossary term to a canonical reference field."""
        term = self.db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
        if not term:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Glossary term '{term_id}' not found")

        c_field = (
            self.db.query(CanonicalField)
            .options(joinedload(CanonicalField.canonical_model))
            .filter(CanonicalField.id == canonical_field_id)
            .first()
        )
        if not c_field:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Canonical field '{canonical_field_id}' not found"
            )

        existing_link = self.db.query(GlossaryCanonicalLink).filter(
            GlossaryCanonicalLink.glossary_term_id == term.id,
            GlossaryCanonicalLink.canonical_field_id == c_field.id
        ).first()
        if existing_link:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Term '{term.name}' is already linked to canonical field '{c_field.field_name}'"
            )

        link = GlossaryCanonicalLink(
            glossary_term_id=term.id,
            canonical_field_id=c_field.id,
            created_by=user.email,
            updated_by=user.email,
        )
        self.db.add(link)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.GLOSSARY_FIELD_LINKED,
            actor_id=user.user_id,
            actor_email=user.email,
            object_type="glossary_canonical_links",
            object_id=str(link.id),
            after_state={
                "glossary_term_id": str(term.id),
                "glossary_term_name": term.name,
                "canonical_field_id": str(c_field.id),
                "canonical_field_name": c_field.field_name,
                "canonical_model_name": c_field.canonical_model.name if c_field.canonical_model else None,
            },
            description=f"Linked glossary term '{term.name}' to canonical field '{c_field.canonical_model.name}.{c_field.field_name}'",
        )
        self.db.commit()

        return CanonicalFieldLinkResponse(
            link_id=link.id,
            canonical_field_id=c_field.id,
            canonical_field_name=c_field.field_name,
            canonical_model_id=c_field.canonical_model.id,
            canonical_model_name=c_field.canonical_model.name,
            data_type=c_field.data_type.value if hasattr(c_field.data_type, "value") else str(c_field.data_type),
            is_required=c_field.is_required,
            is_nullable=c_field.is_nullable,
        )

    def unlink_canonical_field(
        self, term_id: uuid.UUID, canonical_field_id: uuid.UUID, user: CurrentUser
    ) -> Dict[str, str]:
        """Removes the association between a glossary term and a canonical field."""
        link = (
            self.db.query(GlossaryCanonicalLink)
            .join(GlossaryTerm)
            .join(CanonicalField)
            .filter(
                GlossaryCanonicalLink.glossary_term_id == term_id,
                GlossaryCanonicalLink.canonical_field_id == canonical_field_id
            )
            .first()
        )
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Canonical link between term '{term_id}' and field '{canonical_field_id}' not found"
            )

        link_id = str(link.id)
        self.audit.emit(
            action=AuditActionEnum.GLOSSARY_FIELD_UNLINKED,
            actor_id=user.user_id,
            actor_email=user.email,
            object_type="glossary_canonical_links",
            object_id=link_id,
            before_state={
                "glossary_term_id": str(term_id),
                "canonical_field_id": str(canonical_field_id),
            },
            description=f"Removed link between glossary term '{term_id}' and canonical field '{canonical_field_id}'",
        )
        self.db.delete(link)
        self.db.commit()
        return {"message": "Canonical field link removed successfully"}

    def get_terms_for_canonical_model(self, canonical_model_id: uuid.UUID) -> List[GlossaryTermResponse]:
        """Retrieves all business glossary terms associated with fields in a given canonical model."""
        terms = (
            self.db.query(GlossaryTerm)
            .join(GlossaryCanonicalLink, GlossaryTerm.id == GlossaryCanonicalLink.glossary_term_id)
            .join(CanonicalField, GlossaryCanonicalLink.canonical_field_id == CanonicalField.id)
            .filter(CanonicalField.canonical_model_id == canonical_model_id)
            .distinct(GlossaryTerm.id)
            .all()
        )
        return [self._build_term_response(t) for t in terms]
