"""
Unit Tests for Wave 1 Slice 6: Downstream Protection Gate Policy Evaluation (CF-V1-E8-03).
"""
import uuid
from datetime import datetime, timezone, timedelta
import pytest

from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.input_registry import QuarantineRecord, QuarantineReasonEnum
from backend.models.schedule import FeedDependency, DependencyTypeEnum
from backend.models.approval import SandboxTestRun, SandboxRunStatusEnum
from backend.models.schema import SampleFile, Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.canonical_model import CanonicalModel
from backend.models.mapping import Mapping, MappingVersion, MappingVersionStatusEnum
from backend.services.dependency_service import DependencyService


def _setup_feed_pair(db, prefix: str):
    """Helper to create upstream and downstream feed with published versions and a dependency edge."""
    upstream = Feed(
        id=uuid.uuid4(),
        name=f"{prefix}_Upstream",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder=f"./data/landing/{prefix.lower()}_up",
        filename_pattern="*.csv",
        schedule_expression="0 0 * * *",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
        status=FeedStatusEnum.ACTIVE,
    )
    downstream = Feed(
        id=uuid.uuid4(),
        name=f"{prefix}_Downstream",
        domain="ENCOUNTERS",
        format=FeedFormatEnum.CSV,
        landing_folder=f"./data/landing/{prefix.lower()}_down",
        filename_pattern="*.csv",
        schedule_expression="0 2 * * *",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
        status=FeedStatusEnum.ACTIVE,
    )
    db.add_all([upstream, downstream])
    db.flush()

    v_up = FeedVersion(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={"fields": []},
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    v_down = FeedVersion(
        id=uuid.uuid4(),
        feed_id=downstream.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={"fields": []},
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add_all([v_up, v_down])
    db.flush()

    dep = FeedDependency(
        id=uuid.uuid4(),
        downstream_feed_id=downstream.id,
        upstream_feed_id=upstream.id,
        dependency_type=DependencyTypeEnum.HARD,
        max_lag_hours=24,
        block_on_upstream_failure=True,
        block_on_reject_file=True,
        block_on_unbalanced_reconciliation=True,
        max_quarantine_rate_pct=5.0,
        is_active=True,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(dep)
    db.commit()
    db.refresh(upstream)
    db.refresh(downstream)
    db.refresh(dep)
    return upstream, downstream, dep


# 13. Clean upstream run passes
def test_gate_check_passes_when_upstream_completed_and_clean(db):
    upstream, downstream, dep = _setup_feed_pair(db, "CleanPass")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=100,
        rows_quarantined=0,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is True
    assert len(result.blocking_reasons) == 0
    assert result.dependencies_evaluated[0].is_satisfied is True


# 14. Upstream with no batches blocks downstream run
def test_gate_check_blocks_when_upstream_has_no_batches(db):
    upstream, downstream, dep = _setup_feed_pair(db, "NoBatches")

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("never completed any pipeline run" in r for r in result.blocking_reasons)
    assert result.dependencies_evaluated[0].is_satisfied is False


# 15. Upstream batch FAILED blocks downstream
def test_gate_check_blocks_when_upstream_batch_failed(db):
    upstream, downstream, dep = _setup_feed_pair(db, "FailedUpstream")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.FAILED,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch)
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("is FAILED" in r for r in result.blocking_reasons)
    assert result.dependencies_evaluated[0].is_satisfied is False


# 16. Upstream batch RUNNING blocks downstream
def test_gate_check_blocks_when_upstream_batch_running(db):
    upstream, downstream, dep = _setup_feed_pair(db, "RunningUpstream")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.RUNNING,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch)
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("currently executing" in r for r in result.blocking_reasons)
    assert result.dependencies_evaluated[0].is_satisfied is False


# 17. Upstream quarantine rate exceeded blocks downstream
def test_gate_check_blocks_when_upstream_quarantine_rate_exceeded(db):
    upstream, downstream, dep = _setup_feed_pair(db, "QuarantineBreach")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    # 10 quarantined out of 100 = 10.0% > 5.0%
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=90,
        rows_quarantined=10,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("quarantine rate" in r.lower() for r in result.blocking_reasons)
    assert result.dependencies_evaluated[0].quarantine_rate_pct == 10.0


# 18. Quarantine rate boundary: strictly below threshold passes (4.9% < 5.0%)
def test_quarantine_rate_boundary_below_threshold_passes(db):
    upstream, downstream, dep = _setup_feed_pair(db, "QBoundBelow")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    # 49 quarantined out of 1000 = 4.9% <= 5.0%
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=1000,
        rows_silver_raw=951,
        rows_quarantined=49,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is True
    assert len(result.blocking_reasons) == 0


# 19. Quarantine rate boundary: exactly at threshold passes (5.0% == 5.0%)
def test_quarantine_rate_boundary_exactly_threshold_passes(db):
    upstream, downstream, dep = _setup_feed_pair(db, "QBoundExact")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    # 5 quarantined out of 100 = 5.0% <= 5.0% (passes!)
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=95,
        rows_quarantined=5,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is True
    assert len(result.blocking_reasons) == 0


# 20. Quarantine rate boundary: strictly above threshold blocks (5.1% > 5.0%)
def test_quarantine_rate_boundary_above_threshold_blocks(db):
    upstream, downstream, dep = _setup_feed_pair(db, "QBoundAbove")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    # 51 quarantined out of 1000 = 5.1% > 5.0% (blocks!)
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=1000,
        rows_silver_raw=949,
        rows_quarantined=51,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("quarantine rate" in r.lower() for r in result.blocking_reasons)


# 21. Upstream REJECT_FILE DQ violation in production QuarantineRecord blocks
def test_gate_check_blocks_when_upstream_has_reject_file_severity(db):
    upstream, downstream, dep = _setup_feed_pair(db, "RejectFileBreach")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=99,
        rows_quarantined=1,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name="SILVER_RAW",
        source_row_number=5,
        field_name="patient_id",
        reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
        reason_detail="Rule 'NotNull_Patient' failed: severity REJECT_FILE",
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon, qr])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("REJECT_FILE" in r for r in result.blocking_reasons)


# 22. Downstream gate ignores test/sandbox results and evaluates only production batches
def test_gate_check_reject_file_ignores_sandbox_evidence(db):
    upstream, downstream, dep = _setup_feed_pair(db, "SandboxIsolation")

    # Upstream has a FAILED sandbox test run with REJECT_FILE
    sample = SampleFile(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        filename="sample_test.csv",
        storage_path="./data/landing/sample_test.csv",
        file_size_bytes=100,
        file_fingerprint="fingerprint_123",
        uploaded_by="engineer@cinqflow.local",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    contract = Schema(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        name="SandboxIsolation_Contract",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add_all([sample, contract])
    db.flush()

    s_ver = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=contract.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(s_ver)
    db.flush()

    cm = db.query(CanonicalModel).first()
    if not cm:
        cm = CanonicalModel(
            id=uuid.uuid4(),
            name="Sandbox_Isolation_Model",
            domain="CLAIMS",
            created_by="engineer@cinqflow.local",
            updated_by="engineer@cinqflow.local",
        )
        db.add(cm)
        db.flush()

    mapping = Mapping(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        schema_id=contract.id,
        canonical_model_id=cm.id,
        name="Sandbox_Mapping",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(mapping)
    db.flush()

    m_ver = MappingVersion(
        id=uuid.uuid4(),
        mapping_id=mapping.id,
        schema_version_id=s_ver.id,
        version_number=1,
        status=MappingVersionStatusEnum.PUBLISHED,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(m_ver)
    db.flush()

    sandbox_run = SandboxTestRun(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        sample_file_id=sample.id,
        schema_version_id=s_ver.id,
        mapping_version_id=m_ver.id,
        status=SandboxRunStatusEnum.FAILED,
        has_reject_file_violation=True,
        total_rows=10,
        passed_rows=5,
        quarantined_rows=5,
        dropped_rows=0,
        pass_rate=50.0,
        reconciliation_status="BALANCED",
        rule_metrics={"Rule_RF": {"severity": "REJECT_FILE", "failures": 5}},
        executed_by="mock-analyst-001",
        created_by="mock-analyst-001",
        updated_by="mock-analyst-001",
    )
    db.add(sandbox_run)

    # But upstream production batch is 100% SUCCESS and clean
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=100,
        rows_quarantined=0,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    # Downstream gate must evaluate only production batch -> PASSES!
    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is True
    assert len(result.blocking_reasons) == 0


# 23. Upstream unbalanced reconciliation blocks downstream
def test_gate_check_blocks_when_upstream_reconciliation_unbalanced(db):
    upstream, downstream, dep = _setup_feed_pair(db, "UnbalancedRecon")

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=90,
        rows_quarantined=5,  # 5 missing -> unbalanced!
        rows_dropped=0,
        balance_check_passed=False,
        status=ReconciliationStatusEnum.FAIL,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("UNBALANCED" in r for r in result.blocking_reasons)


# 24. Upstream stale run beyond max_lag_hours blocks downstream
def test_gate_check_blocks_when_upstream_exceeds_max_lag_hours(db):
    upstream, downstream, dep = _setup_feed_pair(db, "StaleLag")

    # Completed 48 hours ago, while max_lag_hours is 24
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=48),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=100,
        rows_quarantined=0,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch, recon])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    assert result.is_allowed is False
    assert any("stale" in r.lower() for r in result.blocking_reasons)


# 25. Multiple upstream dependencies with mixed results (one failure blocks downstream)
def test_gate_check_blocks_when_multiple_upstreams_have_mixed_results(db):
    up_clean, downstream, dep_clean = _setup_feed_pair(db, "MultiUp")

    # Add second upstream that fails
    up_failed = Feed(
        id=uuid.uuid4(),
        name="MultiUp_FailedUpstream",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing/multi_failed",
        filename_pattern="*.csv",
        schedule_expression="0 0 * * *",
        created_by="system",
        updated_by="system",
        status=FeedStatusEnum.ACTIVE,
    )
    db.add(up_failed)
    db.flush()

    v_failed = FeedVersion(
        id=uuid.uuid4(),
        feed_id=up_failed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={"fields": []},
        created_by="system",
        updated_by="system",
    )
    db.add(v_failed)
    db.flush()

    dep_failed = FeedDependency(
        id=uuid.uuid4(),
        downstream_feed_id=downstream.id,
        upstream_feed_id=up_failed.id,
        dependency_type=DependencyTypeEnum.HARD,
        is_active=True,
        created_by="system",
        updated_by="system",
    )
    db.add(dep_failed)

    # Clean upstream has SUCCESS batch
    batch_clean = Batch(
        id=uuid.uuid4(),
        feed_id=up_clean.id,
        feed_version_id=up_clean.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    recon_clean = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch_clean.id,
        rows_in=100,
        rows_silver_raw=100,
        rows_quarantined=0,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="system",
        updated_by="system",
    )
    # Failed upstream has FAILED batch
    batch_failed = Batch(
        id=uuid.uuid4(),
        feed_id=up_failed.id,
        feed_version_id=v_failed.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add_all([batch_clean, recon_clean, batch_failed])
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    # Downstream must be blocked due to up_failed
    assert result.is_allowed is False
    assert len(result.blocking_reasons) == 1
    assert "MultiUp_FailedUpstream" in result.blocking_reasons[0]


# 26. Soft dependency warns without blocking downstream run
def test_gate_check_soft_dependency_warns_without_blocking(db):
    upstream, downstream, dep = _setup_feed_pair(db, "SoftWarn")
    dep.dependency_type = DependencyTypeEnum.SOFT
    db.commit()

    # Upstream failed
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream.id,
        feed_version_id=upstream.versions[0].id,
        status=BatchStatusEnum.FAILED,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch)
    db.commit()

    service = DependencyService(db)
    result = service.evaluate_execution_gate(downstream.id, audit_on_block=False)
    # SOFT dependency does not block overall execution
    assert result.is_allowed is True
    assert len(result.blocking_reasons) == 0
    # But reports warning in warnings list
    assert len(result.warnings) == 1
    assert "is FAILED" in result.warnings[0]
    assert result.dependencies_evaluated[0].is_satisfied is False
    assert "is FAILED" in result.dependencies_evaluated[0].warning_reason
