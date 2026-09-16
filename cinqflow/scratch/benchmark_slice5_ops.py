"""
Performance Benchmark for Wave 2 Slice 5 Governance & Operations Endpoints:
- GET /api/v1/ops/batches/{batch_id}/certification-evaluation
- POST /api/v1/ops/batches/{batch_id}/certify
- GET /api/v1/ops/waivers
- GET /api/v1/ops/waivers/{waiver_id}

Measures:
- p50, p95, p99 latency (ms) across 50 iterations
- Exact SQL query count per endpoint call using SQLAlchemy query listener
"""
import sys
sys.path.insert(0, "d:/Digitalurth/cinqflow")
import time
import uuid
import statistics
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.main import app
from backend.core.database import engine, SessionLocal
from backend.models.governance import (
    OperationalVariance,
    OperationalWaiver,
    BatchDataCertification,
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
)
from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum, BatchStage, StageNameEnum, StageStatusEnum, WAVE0_STAGE_ORDER
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.services.fingerprint_service import FingerprintService

def run_benchmark():
    print("================================================================================")
    print("WAVE 2 SLICE 5 -- PERFORMANCE & QUERY BENCHMARK")
    print("================================================================================")
    db = SessionLocal()
    client = TestClient(app)

    # Setup seed data
    test_id = uuid.uuid4().hex[:6]
    feed = Feed(
        id=uuid.uuid4(), name=f"BENCH_FEED_{test_id}", domain="MEMBERS",
        format=FeedFormatEnum.CSV, status=FeedStatusEnum.ACTIVE,
        landing_folder=f"./data/landing/{test_id}", filename_pattern="*.csv",
        created_by="bench", updated_by="bench",
    )
    db.add(feed)
    fv = FeedVersion(
        id=uuid.uuid4(), feed_id=feed.id, version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED, created_by="bench", updated_by="bench",
    )
    db.add(fv)
    inp = InputRegistry(
        id=uuid.uuid4(), feed_id=feed.id, filename=f"bench_{test_id}.csv",
        file_path=f"./data/landing/bench_{test_id}.csv", file_size_bytes=1024,
        file_fingerprint=uuid.uuid4().hex, status=InputStatusEnum.ACCEPTED,
        registered_by="bench", detected_at=datetime.now(timezone.utc),
        created_by="bench", updated_by="bench",
    )
    db.add(inp)

    # Batch 1: completely clean, ready for certification
    batch = Batch(
        id=uuid.uuid4(), feed_id=feed.id, feed_version_id=fv.id, input_registry_id=inp.id,
        status=BatchStatusEnum.SUCCESS, triggered_by="operator_trigger", created_by="bench", updated_by="bench",
    )
    db.add(batch)
    for idx, sname in enumerate(WAVE0_STAGE_ORDER, start=1):
        db.add(BatchStage(
            id=uuid.uuid4(), batch_id=batch.id, stage_name=sname, stage_order=idx,
            status=StageStatusEnum.SUCCESS, created_by="bench", updated_by="bench",
        ))
    db.add(BatchReconciliation(
        id=uuid.uuid4(), batch_id=batch.id, rows_in=100, rows_silver_raw=100,
        rows_quarantined=0, rows_dropped=0, balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS, discrepancy=0,
        created_by="bench", updated_by="bench",
    ))

    # Variance and Waiver for testing waiver endpoints
    var = OperationalVariance(
        id=uuid.uuid4(), feed_id=feed.id, batch_id=batch.id, control_type="MANUAL",
        control_id="CTRL_BENCH", title="Bench variance", description="Benchmark variance description",
        status=VarianceStatusEnum.OPEN, created_by="bench", updated_by="bench",
    )
    db.add(var)
    waiver = OperationalWaiver(
        id=uuid.uuid4(), variance_id=var.id, feed_id=feed.id, batch_id=batch.id,
        scope=WaiverScopeEnum.SINGLE_BATCH, affected_control_type="MANUAL", affected_control_id="CTRL_BENCH",
        business_justification="Benchmark waiver justification", risk_assessment="Bench risk assessment",
        mitigation_notes="Bench mitigation notes", expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        status=WaiverStatusEnum.PENDING_APPROVAL, requested_by="bench_requester",
        requested_by_email="requester@cinqflow.local", requested_at=datetime.now(timezone.utc),
        created_by="bench", updated_by="bench",
    )
    db.add(waiver)
    db.commit()

    # Login tokens
    res_steward = client.post("/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    token_steward = res_steward.json()["access_token"]
    headers_steward = {"Authorization": f"Bearer {token_steward}"}

    # Query counter
    query_count = 0
    def count_query(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", count_query)

    try:
        # 1. Benchmark GET /api/v1/ops/batches/{batch_id}/certification-evaluation
        latencies = []
        q_counts = []
        for _ in range(50):
            query_count = 0
            t_start = time.perf_counter()
            resp = client.get(f"/api/v1/ops/batches/{batch.id}/certification-evaluation", headers=headers_steward)
            t_elapsed = (time.perf_counter() - t_start) * 1000
            assert resp.status_code == 200, resp.text
            latencies.append(t_elapsed)
            q_counts.append(query_count)

        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        avg_q = statistics.mean(q_counts)
        print(f"\n1. GET /api/v1/ops/batches/{{id}}/certification-evaluation (50 iterations):")
        print(f"   p50: {p50:.2f} ms | p95: {p95:.2f} ms | p99: {p99:.2f} ms | SQL Queries: {avg_q:.0f}")

        # 2. Benchmark POST /api/v1/ops/batches/{batch_id}/certify (Idempotent replay)
        latencies = []
        q_counts = []
        for _ in range(50):
            query_count = 0
            t_start = time.perf_counter()
            resp = client.post(
                f"/api/v1/ops/batches/{batch.id}/certify",
                json={"certification_notes": "Benchmark certification validation"},
                headers=headers_steward,
            )
            t_elapsed = (time.perf_counter() - t_start) * 1000
            assert resp.status_code == 201, resp.text
            latencies.append(t_elapsed)
            q_counts.append(query_count)

        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        avg_q = statistics.mean(q_counts)
        print(f"\n2. POST /api/v1/ops/batches/{{id}}/certify (50 iterations):")
        print(f"   p50: {p50:.2f} ms | p95: {p95:.2f} ms | p99: {p99:.2f} ms | SQL Queries: {avg_q:.0f}")

        # 3. Benchmark GET /api/v1/ops/waivers
        latencies = []
        q_counts = []
        for _ in range(50):
            query_count = 0
            t_start = time.perf_counter()
            resp = client.get("/api/v1/ops/waivers", headers=headers_steward)
            t_elapsed = (time.perf_counter() - t_start) * 1000
            assert resp.status_code == 200, resp.text
            latencies.append(t_elapsed)
            q_counts.append(query_count)

        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        avg_q = statistics.mean(q_counts)
        print(f"\n3. GET /api/v1/ops/waivers (50 iterations):")
        print(f"   p50: {p50:.2f} ms | p95: {p95:.2f} ms | p99: {p99:.2f} ms | SQL Queries: {avg_q:.0f}")

        # 4. Benchmark GET /api/v1/ops/waivers/{waiver_id}
        latencies = []
        q_counts = []
        for _ in range(50):
            query_count = 0
            t_start = time.perf_counter()
            resp = client.get(f"/api/v1/ops/waivers/{waiver.id}", headers=headers_steward)
            t_elapsed = (time.perf_counter() - t_start) * 1000
            assert resp.status_code == 200, resp.text
            latencies.append(t_elapsed)
            q_counts.append(query_count)

        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        avg_q = statistics.mean(q_counts)
        print(f"\n4. GET /api/v1/ops/waivers/{{id}} (50 iterations):")
        print(f"   p50: {p50:.2f} ms | p95: {p95:.2f} ms | p99: {p99:.2f} ms | SQL Queries: {avg_q:.0f}")

    finally:
        event.remove(engine, "before_cursor_execute", count_query)
        db.close()

if __name__ == "__main__":
    run_benchmark()
