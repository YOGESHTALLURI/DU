"""
Wave 0 SQLAlchemy models.
All models imported here so Alembic auto-discovers them.
"""
from backend.models.base import Base, AuditMixin
from backend.models.user import User, Role, UserRole, Session, AuthProviderEnum, RoleEnum
from backend.models.contract import ContractRegisterEntry, ContractUnknown, ContractStatusEnum, UnknownStatusEnum, RiskLevelEnum
from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum, StageStatusEnum, WAVE0_STAGE_ORDER
from backend.models.input_registry import InputRegistry, QuarantineRecord, InputStatusEnum, QuarantineReasonEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationLedgerEntry, ReconciliationStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.models.schema import (
    Schema,
    SchemaVersion,
    SchemaField,
    SampleFile,
    ProfilingRun,
    ProfilingColumnStat,
    SchemaDataTypeEnum,
    SchemaVersionStatusEnum,
    ProfilingRunStatusEnum,
    OnboardingSession,
    OnboardingStatusEnum,
)
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.mapping import (
    Mapping,
    MappingVersion,
    MappingLine,
    MappingVersionStatusEnum,
    TransformTypeEnum,
)

__all__ = [
    "Base", "AuditMixin",
    # Auth
    "User", "Role", "UserRole", "Session", "AuthProviderEnum", "RoleEnum",
    # Contract
    "ContractRegisterEntry", "ContractUnknown", "ContractStatusEnum", "UnknownStatusEnum", "RiskLevelEnum",
    # Feed
    "Feed", "FeedVersion", "FeedFormatEnum", "FeedStatusEnum", "FeedVersionStatusEnum",
    # Pipeline
    "Batch", "BatchStage", "BatchStatusEnum", "StageNameEnum", "StageStatusEnum", "WAVE0_STAGE_ORDER",
    # Input / Quarantine
    "InputRegistry", "QuarantineRecord", "InputStatusEnum", "QuarantineReasonEnum",
    # Reconciliation
    "BatchReconciliation", "ReconciliationLedgerEntry", "ReconciliationStatusEnum",
    # Audit
    "AuditEvent", "AuditActionEnum",
    # Wave 1 Slice 1: Schema & Profiling
    "Schema", "SchemaVersion", "SchemaField", "SampleFile", "ProfilingRun", "ProfilingColumnStat",
    "SchemaDataTypeEnum", "SchemaVersionStatusEnum", "ProfilingRunStatusEnum",
    # Wave 1 Slice 2: Onboarding
    "OnboardingSession", "OnboardingStatusEnum",
    # Wave 1 Slice 3: Canonical Models & Mapping Studio
    "CanonicalModel", "CanonicalField",
    "Mapping", "MappingVersion", "MappingLine",
    "MappingVersionStatusEnum", "TransformTypeEnum",
    # Wave 1 Slice 4: Data Quality Rules Engine
    "DataQualityRule", "RuleVersion", "RuleTestRun",
    "RuleVersionStatusEnum", "RuleTypeEnum", "RuleSeverityEnum", "TestRunStatusEnum",
    # Wave 1 Slice 5: Review, Sandbox Evidence Pack & Governed Activation
    "SandboxTestRun", "ApprovalRequest", "FeedActivationRecord",
    "SandboxRunStatusEnum", "ApprovalRequestStatusEnum",
    # Wave 1 Slice 6: Scheduling, Dependencies & Downstream Protection
    "FeedSchedule", "FeedDependency", "ScheduleStatusEnum", "DependencyTypeEnum",
    # Wave 1 Slice 7: Business Glossary Service & Canonical Semantics
    "GlossaryTerm", "GlossaryCanonicalLink",
    "GlossaryTermStatusEnum", "GlossaryPhiClassificationEnum", "GlossaryCodeSetEnum",
    # Wave 2 Slice 1: Production DQ & Schema Drift Detection
    "SchemaDriftReport", "DriftSeverityEnum", "DriftStatusEnum",
    "DQResult", "DQActionTakenEnum",
    # Wave 2 Slice 3: Governed Action Surface & Recovery Operations
    "OperationalActionRequest", "ActionTypeEnum", "ActionRiskLevelEnum", "ActionStatusEnum",
    "QuarantineStatusEnum",
    # Wave 3 Slice 4: ODS Execution Lease Fencing & Pipeline Checkpoint
    "BatchStageCheckpoint",
    "IdentityRunStatus",
]

from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleTestRun,
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
    TestRunStatusEnum,
)
from backend.models.approval import (
    SandboxTestRun,
    ApprovalRequest,
    FeedActivationRecord,
    SandboxRunStatusEnum,
    ApprovalRequestStatusEnum,
)
from backend.models.schedule import (
    FeedSchedule,
    FeedDependency,
    ScheduleStatusEnum,
    DependencyTypeEnum,
)
from backend.models.glossary import (
    GlossaryTerm,
    GlossaryCanonicalLink,
    GlossaryTermStatusEnum,
    GlossaryPhiClassificationEnum,
    GlossaryCodeSetEnum,
)
from backend.models.drift import (
    SchemaDriftReport,
    DriftSeverityEnum,
    DriftStatusEnum,
)
from backend.models.dq_result import (
    DQResult,
    DQActionTakenEnum,
)
from backend.models.input_registry import (
    QuarantineStatusEnum,
)
from backend.models.ops_action import (
    OperationalActionRequest,
    ActionTypeEnum,
    ActionRiskLevelEnum,
    ActionStatusEnum,
)
from backend.models.incident import (
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
    PlaybookStatusEnum,
    FailureFingerprint,
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    FingerprintPlaybookBinding,
    OperationalAlert,
    AlertOccurrence,
)
from backend.models.governance import (
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
    CertificationStatusEnum,
    OperationalVariance,
    OperationalWaiver,
    BatchDataCertification,
)
from backend.models.ods import (
    OdsModelVersion,
    ConsumerRegistration,
    OdsMemberV1,
    OdsClaimV1,
    OdsClaimLineV1,
    OdsModelVersionStatusEnum,
    ConsumerStatusEnum,
    ConsumerTypeEnum,
    OdsCertification,
    OdsCertificationStatusEnum,
)
from backend.models.identity import (
    MasterIdentity,
    IdentityCrosswalk,
    IdentityException,
    IdentityDecision,
    MasterIdentityStatusEnum,
    IdentityTypeEnum,
    CrosswalkMatchTypeEnum,
    IdentityExceptionTypeEnum,
    IdentityExceptionStatusEnum,
    StewardResolutionTypeEnum,
)
# Wave 3 Slice 4: ODS Execution Lease Fencing & Pipeline Checkpoint
from backend.models.checkpoint import BatchStageCheckpoint, OdsOperationHash
from backend.models.identity_run_status import IdentityRunStatus

from backend.models.merge_split import (
    IdentityMergeSplitProposal,
    IdentityMergeSplitEvent,
    ProposalStateEnum,
    OperationTypeEnum,
)

__all__ = list(globals().get("__all__", [])) + [
    "IdentityMergeSplitProposal",
    "IdentityMergeSplitEvent",
    "ProposalStateEnum",
    "OperationTypeEnum",
    "OdsCertification",
    "OdsCertificationStatusEnum",
]
