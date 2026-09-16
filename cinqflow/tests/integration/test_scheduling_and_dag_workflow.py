"""
Integration Tests for Wave 1 Slice 6: Scheduling, DAG Graph, and Downstream Protection Workflow (CF-V1-E8-03).
"""
import uuid
import pytest
from datetime import datetime, timezone

from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.models.schedule import DependencyTypeEnum


def _create_feed(db, name: str, domain: str = "CLAIMS") -> Feed:
    feed = Feed(
        id=uuid.uuid4(),
        name=name,
        domain=domain,
        format=FeedFormatEnum.CSV,
        schedule_expression="0 0 * * *",
        landing_folder=f"./data/landing/{name.lower()}",
        filename_pattern=f"{name}_*.csv",
        status=FeedStatusEnum.ACTIVE,
        created_by="mock-engineer-001",
        updated_by="mock-engineer-001",
    )
    db.add(feed)
    db.flush()

    version = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={"fields": []},
        created_by="mock-engineer-001",
        updated_by="mock-engineer-001",
    )
    db.add(version)
    db.commit()
    db.refresh(feed)
    return feed


# 30. End-to-end DAG generation and visualization
def test_e2e_dag_generation_and_visualization(client, engineer_headers, db):
    feed_enrollment = _create_feed(db, "E2E_Enrollment_Feed", "MEMBERSHIP")
    feed_eligibility = _create_feed(db, "E2E_Eligibility_Feed", "MEMBERSHIP")
    feed_claims = _create_feed(db, "E2E_Claims_Feed", "CLAIMS")

    # Update schedules
    res_sched_a = client.put(
        f"/api/v1/schedules/feed/{feed_enrollment.id}",
        json={"schedule_expression": "0 1 * * *", "timezone": "UTC", "catchup": False},
        headers=engineer_headers,
    )
    assert res_sched_a.status_code == 200

    res_sched_b = client.put(
        f"/api/v1/schedules/feed/{feed_eligibility.id}",
        json={"schedule_expression": "0 2 * * *", "timezone": "UTC", "catchup": False},
        headers=engineer_headers,
    )
    assert res_sched_b.status_code == 200

    # Dependencies: Eligibility depends on Enrollment; Claims depends on Eligibility
    res_dep1 = client.post(
        "/api/v1/dependencies",
        json={
            "downstream_feed_id": str(feed_eligibility.id),
            "upstream_feed_id": str(feed_enrollment.id),
            "dependency_type": "HARD",
        },
        headers=engineer_headers,
    )
    assert res_dep1.status_code == 201

    res_dep2 = client.post(
        "/api/v1/dependencies",
        json={
            "downstream_feed_id": str(feed_claims.id),
            "upstream_feed_id": str(feed_eligibility.id),
            "dependency_type": "HARD",
        },
        headers=engineer_headers,
    )
    assert res_dep2.status_code == 201

    # Fetch DAG
    res_dag = client.get("/api/v1/dependencies/dag", headers=engineer_headers)
    assert res_dag.status_code == 200
    dag = res_dag.json()

    assert dag["is_acyclic"] is True
    assert dag["total_feeds"] >= 3
    assert dag["total_dependencies"] >= 2

    node_ids = {n["id"] for n in dag["nodes"]}
    assert str(feed_enrollment.id) in node_ids
    assert str(feed_eligibility.id) in node_ids
    assert str(feed_claims.id) in node_ids

    edges = {(e["source_feed_id"], e["target_feed_id"]) for e in dag["edges"]}
    assert (str(feed_enrollment.id), str(feed_eligibility.id)) in edges
    assert (str(feed_eligibility.id), str(feed_claims.id)) in edges


# 31. E2E pipeline execution pre-flight gate enforcement (412 Precondition Failed)
def test_e2e_pipeline_execution_preflight_gate_enforcement(client, engineer_headers, db):
    upstream_feed = _create_feed(db, "Preflight_Upstream")
    downstream_feed = _create_feed(db, "Preflight_Downstream")

    # Upstream has a FAILED batch
    upstream_batch = Batch(
        id=uuid.uuid4(),
        feed_id=upstream_feed.id,
        feed_version_id=upstream_feed.versions[0].id,
        status=BatchStatusEnum.FAILED,
        triggered_by="mock-engineer-001",
        created_by="system",
        updated_by="system",
    )
    db.add(upstream_batch)

    # Establish dependency
    res_dep = client.post(
        "/api/v1/dependencies",
        json={
            "downstream_feed_id": str(downstream_feed.id),
            "upstream_feed_id": str(upstream_feed.id),
            "dependency_type": "HARD",
            "block_on_upstream_failure": True,
        },
        headers=engineer_headers,
    )
    assert res_dep.status_code == 201

    # Create batch for downstream feed
    downstream_batch = Batch(
        id=uuid.uuid4(),
        feed_id=downstream_feed.id,
        feed_version_id=downstream_feed.versions[0].id,
        status=BatchStatusEnum.PENDING,
        triggered_by="mock-engineer-001",
        created_by="system",
        updated_by="system",
    )
    db.add(downstream_batch)
    db.commit()

    # Attempt to execute downstream batch -> Preflight gate blocks with HTTP 412
    res_exec = client.post(
        f"/api/v1/pipeline/batches/{downstream_batch.id}/execute",
        headers=engineer_headers,
    )
    assert res_exec.status_code == 412
    error_detail = res_exec.json()["detail"]
    assert "Downstream protection gate blocked execution" in error_detail
    assert "is FAILED" in error_detail

    # Verify audit event emitted for gate blockage during execution attempt
    blocked_audit = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == AuditActionEnum.DEPENDENCY_GATE_BLOCKED,
            AuditEvent.object_id == str(downstream_feed.id),
        )
        .first()
    )
    assert blocked_audit is not None
    assert "Downstream protection gate blocked" in blocked_audit.description


# 32. E2E schedule and dependency audit trail with zero PHI
def test_e2e_schedule_and_dependency_audit_trail(client, engineer_headers, db):
    feed_a = _create_feed(db, "Audit_Feed_A")
    feed_b = _create_feed(db, "Audit_Feed_B")

    # 1. Schedule created / updated
    res1 = client.put(
        f"/api/v1/schedules/feed/{feed_a.id}",
        json={"schedule_expression": "15 3 * * *", "timezone": "UTC", "catchup": False},
        headers=engineer_headers,
    )
    assert res1.status_code == 200

    # 2. Schedule paused
    res2 = client.post(f"/api/v1/schedules/feed/{feed_a.id}/pause", headers=engineer_headers)
    assert res2.status_code == 200

    # 3. Schedule resumed
    res3 = client.post(f"/api/v1/schedules/feed/{feed_a.id}/resume", headers=engineer_headers)
    assert res3.status_code == 200

    # 4. Dependency created
    res4 = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed_b.id), "upstream_feed_id": str(feed_a.id)},
        headers=engineer_headers,
    )
    assert res4.status_code == 201
    dep_id = res4.json()["id"]

    # 5. Dependency deleted
    res5 = client.delete(f"/api/v1/dependencies/{dep_id}", headers=engineer_headers)
    assert res5.status_code == 200

    # Inspect all emitted audits
    emitted_audits = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action.in_([
                AuditActionEnum.SCHEDULE_CREATED,
                AuditActionEnum.SCHEDULE_UPDATED,
                AuditActionEnum.SCHEDULE_PAUSED,
                AuditActionEnum.SCHEDULE_RESUMED,
                AuditActionEnum.DEPENDENCY_CREATED,
                AuditActionEnum.DEPENDENCY_DELETED,
            ])
        )
        .all()
    )
    assert len(emitted_audits) >= 5

    # Privacy verification: Assert ZERO patient PHI keywords in any emitted audit record
    phi_indicators = ["patient", "dob", "ssn", "mrn", "diagnosis", "johnson", "smith", "williams"]
    for audit in emitted_audits:
        assert audit.actor_id is not None
        text_payload = f"{audit.description} {audit.before_state} {audit.after_state}".lower()
        for phi in phi_indicators:
            assert phi not in text_payload, f"Found potential PHI '{phi}' in audit {audit.id}"


# 33. Read-only gate check endpoint does NOT emit audit events
def test_gate_check_read_only_endpoint_emits_no_audit(client, engineer_headers, db):
    up = _create_feed(db, "Audit_Gate_Up")
    down = _create_feed(db, "Audit_Gate_Down")

    # Establish dependency
    client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(down.id), "upstream_feed_id": str(up.id)},
        headers=engineer_headers,
    )

    # Initial count of gate_blocked audits
    initial_blocked_count = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.DEPENDENCY_GATE_BLOCKED)
        .count()
    )

    # Call read-only GET gate-check (upstream has no batches, so it is blocked)
    res = client.get(f"/api/v1/dependencies/gate-check/{down.id}", headers=engineer_headers)
    assert res.status_code == 200
    assert res.json()["is_allowed"] is False

    # Verify NO new audit event was emitted
    post_count = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.DEPENDENCY_GATE_BLOCKED)
        .count()
    )
    assert post_count == initial_blocked_count
