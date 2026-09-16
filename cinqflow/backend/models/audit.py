"""
Wave 0 Database Models — Audit Events

Immutable, append-only audit log.
Every important state change produces an audit event.
Audit records are NEVER modified or deleted.

Auditable actions (Wave 0):
- feed.created, feed.updated
- feed_version.published
- input.registered, input.duplicate_detected
- batch.created, batch.started, batch.completed, batch.failed
- stage.started, stage.completed, stage.failed
- quarantine.record_added
- reconciliation.computed
- batch.restart_requested
"""
import uuid
import enum
from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from backend.models.base import Base, AuditMixin


class AuditActionEnum(str, enum.Enum):
    # Auth
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_FAILED = "auth.failed"

    # Contract Register
    CONTRACT_CREATED = "contract.created"
    CONTRACT_UPDATED = "contract.updated"
    CONTRACT_UNKNOWN_ADDED = "contract.unknown_added"
    CONTRACT_UNKNOWN_CONFIRMED = "contract.unknown_confirmed"

    # Feed Registry
    FEED_CREATED = "feed.created"
    FEED_UPDATED = "feed.updated"
    FEED_STATUS_CHANGED = "feed.status_changed"
    FEED_VERSION_CREATED = "feed_version.created"
    FEED_VERSION_PUBLISHED = "feed_version.published"

    # Input Registry
    INPUT_REGISTERED = "input.registered"
    INPUT_DUPLICATE_DETECTED = "input.duplicate_detected"
    INPUT_REJECTED = "input.rejected"

    # Pipeline
    BATCH_CREATED = "batch.created"
    BATCH_STARTED = "batch.started"
    BATCH_COMPLETED = "batch.completed"
    BATCH_FAILED = "batch.failed"
    BATCH_CANCELLED = "batch.cancelled"
    BATCH_RESTART_REQUESTED = "batch.restart_requested"

    # Stages
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"

    # Quarantine
    QUARANTINE_RECORD_ADDED = "quarantine.record_added"

    # Reconciliation
    RECONCILIATION_COMPUTED = "reconciliation.computed"
    RECONCILIATION_FAILED = "reconciliation.failed"

    # Wave 1: Sample & Profiling
    SAMPLE_UPLOADED = "sample.uploaded"
    PROFILING_STARTED = "profiling.started"
    PROFILING_COMPLETED = "profiling.completed"
    PROFILING_FAILED = "profiling.failed"

    # Wave 1: Schema Contracts
    SCHEMA_CREATED = "schema.created"
    SCHEMA_DRAFT_UPDATED = "schema.draft_updated"
    SCHEMA_VERSION_CREATED = "schema.version_created"
    SCHEMA_PUBLISHED = "schema.published"

    # Wave 1 Slice 2: Feed Cloning & Onboarding
    FEED_CLONED = "feed.cloned"
    ONBOARDING_STARTED = "onboarding.started"
    ONBOARDING_STEP_COMPLETED = "onboarding.step_completed"
    ONBOARDING_COMPLETED = "onboarding.completed"

    # Wave 1 Slice 3: Mapping Studio Foundation
    MAPPING_CREATED = "mapping.created"
    MAPPING_DRAFT_UPDATED = "mapping.draft_updated"
    MAPPING_VERSION_CREATED = "mapping.version_created"
    MAPPING_PUBLISHED = "mapping.published"

    # Wave 1 Slice 4: Deterministic Data Quality Rules Engine
    RULE_CREATED = "rule.created"
    RULE_DRAFT_UPDATED = "rule.draft_updated"
    RULE_VERSION_CREATED = "rule.version_created"
    RULE_PUBLISHED = "rule.published"
    RULE_TEST_EXECUTED = "rule.test_executed"
    RULE_DELETED = "rule.deleted"

    # Wave 1 Slice 5: Review, Sandbox Evidence Pack & Governed Activation
    SANDBOX_TEST_STARTED = "sandbox_test.started"
    SANDBOX_TEST_COMPLETED = "sandbox_test.completed"
    SANDBOX_TEST_FAILED = "sandbox_test.failed"
    APPROVAL_SUBMITTED = "approval.submitted"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"

    # Wave 1 Slice 6: Scheduling, Dependencies & Downstream Protection
    SCHEDULE_CREATED = "schedule.created"
    SCHEDULE_UPDATED = "schedule.updated"
    SCHEDULE_PAUSED = "schedule.paused"
    SCHEDULE_RESUMED = "schedule.resumed"
    SCHEDULE_DISABLED = "schedule.disabled"
    SCHEDULE_ENABLED = "schedule.enabled"
    DEPENDENCY_CREATED = "dependency.created"
    DEPENDENCY_DELETED = "dependency.deleted"
    DEPENDENCY_CYCLE_REJECTED = "dependency.cycle_rejected"
    DEPENDENCY_GATE_BLOCKED = "dependency.gate_blocked"

    # Wave 1 Slice 7: Business Glossary Service & Canonical Semantics
    GLOSSARY_TERM_CREATED = "glossary.term_created"
    GLOSSARY_TERM_UPDATED = "glossary.term_updated"
    GLOSSARY_TERM_APPROVED = "glossary.term_approved"
    GLOSSARY_TERM_DEPRECATED = "glossary.term_deprecated"
    GLOSSARY_TERM_DELETED = "glossary.term_deleted"
    GLOSSARY_FIELD_LINKED = "glossary.field_linked"
    GLOSSARY_FIELD_UNLINKED = "glossary.field_unlinked"

    # Wave 2 Slice 1: Production DQ & Schema Drift Detection
    SCHEMA_DRIFT_DETECTED = "schema.drift_detected"
    SCHEMA_DRIFT_ACKNOWLEDGED = "schema.drift_acknowledged"
    RULE_PRODUCTION_EXECUTED = "rule.production_executed"
    RULE_BATCH_ABORTED = "rule.batch_aborted"

    # Wave 2 Slice 2: Operations Control Center & File-Arrival Board
    OPS_DASHBOARD_VIEWED = "ops.dashboard_viewed"
    OPS_ARRIVALS_EVALUATED = "ops.arrivals_evaluated"
    OPS_SLA_BREACHED = "ops.sla_breached"

    # Wave 2 Slice 3: Governed Action Surface & Recovery Operations
    OPS_ACTION_REQUESTED = "ops.action_requested"
    OPS_ACTION_APPROVED = "ops.action_approved"
    OPS_ACTION_REJECTED = "ops.action_rejected"
    OPS_ACTION_EXECUTED = "ops.action_executed"
    OPS_ACTION_FAILED = "ops.action_failed"
    OPS_QUARANTINE_REPROCESSED = "ops.quarantine_reprocessed"
    OPS_QUARANTINE_DISCARDED = "ops.quarantine_discarded"

    # Wave 2 Slice 4: Failure Fingerprinting, Recovery Playbooks & Self-Explaining Alerts
    OPS_FINGERPRINT_CREATED = "ops.fingerprint_created"
    OPS_ALERT_CREATED = "ops.alert_created"
    OPS_ALERT_ACKNOWLEDGED = "ops.alert_acknowledged"
    OPS_ALERT_RESOLVED = "ops.alert_resolved"
    OPS_ALERT_REOPENED = "ops.alert_reopened"
    OPS_PLAYBOOK_CREATED = "ops.playbook_created"
    OPS_PLAYBOOK_UPDATED = "ops.playbook_updated"
    OPS_PLAYBOOK_APPROVED = "ops.playbook_approved"
    OPS_PLAYBOOK_DEPRECATED = "ops.playbook_deprecated"

    # Wave 2 Slice 5: Governance — Variances, Waivers & Batch Data Certification
    OPS_VARIANCE_CREATED = "ops.variance_created"
    OPS_VARIANCE_RESOLVED = "ops.variance_resolved"
    OPS_WAIVER_REQUESTED = "ops.waiver_requested"
    OPS_WAIVER_APPROVED = "ops.waiver_approved"
    OPS_WAIVER_REJECTED = "ops.waiver_rejected"
    OPS_WAIVER_REVOKED = "ops.waiver_revoked"
    OPS_BATCH_CERTIFIED = "ops.batch_certified"
    OPS_CERTIFICATION_REVOKED = "ops.certification_revoked"

    # Wave 3 Slice 2: ODS Model Versions & Consumer Governance
    ODS_MODEL_VERSION_CREATED = "ods.model_version_created"
    ODS_MODEL_VERSION_PUBLISHED = "ods.model_version_published"
    ODS_CONSUMER_REGISTERED = "ods.consumer_registered"
    ODS_CONSUMER_UPDATED = "ods.consumer_updated"
    ODS_CONSUMER_DEACTIVATED = "ods.consumer_deactivated"
    ODS_CONSUMER_MISMATCH = "ods.consumer_mismatch"
    ODS_BATCH_CERTIFIED = "ods.batch_certified"
    ODS_BATCH_CERTIFICATION_FAILED = "ods.batch_certification_failed"
    ODS_BATCH_CERTIFICATION_REVOKED = "ods.batch_certification_revoked"

    # Wave 3 Slice 3: Identity Foundation & Exceptions
    IDENTITY_MATCHED = "identity.matched"
    IDENTITY_EXCEPTION_CREATED = "identity.exception_created"
    IDENTITY_EXCEPTION_CLAIMED = "identity.exception_claimed"
    IDENTITY_EXCEPTION_RESOLVED = "identity.exception_resolved"
    IDENTITY_DECISION_RECORDED = "identity.decision_recorded"



class AuditEvent(Base, AuditMixin):
    """
    Immutable audit event. Never updated or deleted.
    Every row here is a permanent record of a state change.

    DO NOT add UPDATE or DELETE operations on this table.
    """
    __tablename__ = "audit_events"

    action: Mapped[AuditActionEnum] = mapped_column(
        SAEnum(AuditActionEnum, name="audit_action_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True,
        doc="User ID or system identifier that performed the action")
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Object being acted upon
    object_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True,
        doc="Table/entity name, e.g. 'batch', 'feed', 'input_registry'")
    object_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # State change snapshot
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True,
        doc="State before the action (PHI masked)")
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True,
        doc="State after the action (PHI masked)")

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Correlation — links related audit events (e.g., all events in a batch run)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    __table_args__ = (
        Index("ix_audit_actor_action", "actor_id", "action"),
        Index("ix_audit_object", "object_type", "object_id"),
    )
