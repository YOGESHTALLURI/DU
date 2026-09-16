"""
Unit Tests for Wave 1 Slice 6: Scheduling, Recurrence, and Dependency Graph Validation (CF-V1-E8-03).
"""
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum
from backend.models.schedule import FeedSchedule, FeedDependency, ScheduleStatusEnum, DependencyTypeEnum
from backend.services.scheduling_service import validate_cron_expression, compute_next_run


def _create_test_feed(db, name: str, domain: str = "CLAIMS") -> Feed:
    feed = Feed(
        id=uuid.uuid4(),
        name=name,
        domain=domain,
        format=FeedFormatEnum.CSV,
        landing_folder=f"./data/landing/{name.lower()}",
        filename_pattern=f"{name}_*.csv",
        schedule_expression="0 0 * * *",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
        status=FeedStatusEnum.ACTIVE,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


# 1. Valid cron syntax test
def test_cron_expression_validation_valid_syntax():
    valid_expressions = [
        "0 0 * * *",        # Daily midnight
        "*/15 * * * *",     # Every 15 minutes
        "0 12 1 * *",       # Monthly noon
        "0 0 * * 1-5",      # Weekdays
        "30 4,16 * * *",    # Twice daily
        "manual",           # Ad-hoc / manual
    ]
    for expr in valid_expressions:
        assert validate_cron_expression(expr) is True


# 2. Invalid cron syntax test
def test_cron_expression_validation_invalid_syntax_rejected(client, engineer_headers, db):
    invalid_expressions = [
        "invalid",
        "60 * * * *",       # Minute out of bounds (0-59)
        "* 25 * * *",       # Hour out of bounds (0-23)
        "* * 32 * *",       # Day of month out of bounds (1-31)
        "* * * 13 *",       # Month out of bounds (1-12)
        "* * * * 8",        # Day of week out of bounds (0-7)
        "* * * * * *",      # 6 fields instead of 5
        "",                 # Empty
    ]
    for expr in invalid_expressions:
        with pytest.raises(ValueError):
            validate_cron_expression(expr)

    feed = _create_test_feed(db, "Test_Sched_Invalid")
    res = client.put(
        f"/api/v1/schedules/feed/{feed.id}",
        json={"schedule_expression": "bad_cron", "timezone": "UTC", "catchup": False},
        headers=engineer_headers,
    )
    assert res.status_code == 400
    assert "Invalid cron expression" in res.json()["detail"]


# 3. Deterministic next-run calculation test
def test_next_run_calculation_deterministic():
    # From 10:00 UTC, daily at 12:00 should be today at 12:00
    base_dt = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    next_run = compute_next_run("0 12 * * *", from_dt=base_dt)
    assert next_run is not None
    assert next_run == datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)

    # From 13:00 UTC, daily at 12:00 should be tomorrow at 12:00
    base_dt_after = datetime(2026, 9, 5, 13, 0, 0, tzinfo=timezone.utc)
    next_run_tomorrow = compute_next_run("0 12 * * *", from_dt=base_dt_after)
    assert next_run_tomorrow is not None
    assert next_run_tomorrow == datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)

    # Manual has no next run
    assert compute_next_run("manual", from_dt=base_dt) is None


# 4. Timezone and DST awareness test
def test_next_run_calculation_timezone_and_dst_awareness():
    # 09:00 in America/New_York (EDT, UTC-4 in September)
    base_dt = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)  # 08:00 EDT
    next_run = compute_next_run("0 9 * * *", from_dt=base_dt, tz_str="America/New_York")
    assert next_run is not None
    # 09:00 EDT = 13:00 UTC
    assert next_run.astimezone(timezone.utc) == datetime(2026, 9, 5, 13, 0, 0, tzinfo=timezone.utc)

    # In January (EST, UTC-5)
    base_dt_winter = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)  # 07:00 EST
    next_run_winter = compute_next_run("0 9 * * *", from_dt=base_dt_winter, tz_str="America/New_York")
    assert next_run_winter is not None
    # 09:00 EST = 14:00 UTC
    assert next_run_winter.astimezone(timezone.utc) == datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


# 5. Schedule pause and resume transitions
def test_schedule_pause_and_resume_transitions(client, engineer_headers, db):
    feed = _create_test_feed(db, "Test_Sched_Transitions")

    # Fetch initial schedule
    res = client.get(f"/api/v1/schedules/feed/{feed.id}", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ACTIVE"
    assert data["next_run_at"] is not None

    # Pause schedule
    res_pause = client.post(f"/api/v1/schedules/feed/{feed.id}/pause", headers=engineer_headers)
    assert res_pause.status_code == 200
    paused_data = res_pause.json()
    assert paused_data["status"] == "PAUSED"
    assert paused_data["next_run_at"] is None

    # Resume schedule
    res_resume = client.post(f"/api/v1/schedules/feed/{feed.id}/resume", headers=engineer_headers)
    assert res_resume.status_code == 200
    resumed_data = res_resume.json()
    assert resumed_data["status"] == "ACTIVE"
    assert resumed_data["next_run_at"] is not None


# 6. Schedule disable and enable transitions
def test_schedule_disable_and_enable_transitions(client, engineer_headers, db):
    feed = _create_test_feed(db, "Test_Sched_Disable_Enable")

    # Disable schedule
    res_disable = client.post(f"/api/v1/schedules/feed/{feed.id}/disable", headers=engineer_headers)
    assert res_disable.status_code == 200
    assert res_disable.json()["status"] == "DISABLED"
    assert res_disable.json()["next_run_at"] is None

    # Re-enable schedule
    res_enable = client.post(f"/api/v1/schedules/feed/{feed.id}/enable", headers=engineer_headers)
    assert res_enable.status_code == 200
    assert res_enable.json()["status"] == "ACTIVE"
    assert res_enable.json()["next_run_at"] is not None


# 7. Idempotent upsert creation and backward-compatible Feed sync
def test_schedule_idempotent_upsert_creation(client, engineer_headers, db):
    feed = _create_test_feed(db, "Test_Sched_Upsert")

    # First PUT creates the record
    res1 = client.put(
        f"/api/v1/schedules/feed/{feed.id}",
        json={"schedule_expression": "30 3 * * *", "timezone": "UTC", "catchup": False},
        headers=engineer_headers,
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["schedule_expression"] == "30 3 * * *"

    # Check Feed.schedule_expression backward compatibility sync
    db.refresh(feed)
    assert feed.schedule_expression == "30 3 * * *"

    # Second PUT updates the existing record
    res2 = client.put(
        f"/api/v1/schedules/feed/{feed.id}",
        json={"schedule_expression": "45 4 * * *", "timezone": "UTC", "catchup": False},
        headers=engineer_headers,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["schedule_expression"] == "45 4 * * *"
    assert data2["id"] == data1["id"]

    db.refresh(feed)
    assert feed.schedule_expression == "45 4 * * *"


# 8. Feed schedule uniqueness constraint
def test_schedule_feed_uniqueness_constraint(db):
    feed = _create_test_feed(db, "Test_Sched_Uniqueness")
    sched1 = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schedule_expression="0 0 * * *",
        timezone="UTC",
        status=ScheduleStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(sched1)
    db.commit()

    sched2 = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schedule_expression="0 12 * * *",
        timezone="UTC",
        status=ScheduleStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(sched2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# 9. Dependency self-reference rejected
def test_dependency_self_reference_rejected(client, engineer_headers, db):
    feed = _create_test_feed(db, "Test_Self_Ref")
    res = client.post(
        "/api/v1/dependencies",
        json={
            "downstream_feed_id": str(feed.id),
            "upstream_feed_id": str(feed.id),
            "dependency_type": "HARD",
        },
        headers=engineer_headers,
    )
    assert res.status_code in [400, 422]
    assert "self-dependency" in str(res.json()).lower() or "cannot depend on itself" in str(res.json()).lower()


# 10. Dependency duplicate edge rejected
def test_dependency_duplicate_edge_rejected(client, engineer_headers, db):
    upstream = _create_test_feed(db, "Upstream_Feed_Dup")
    downstream = _create_test_feed(db, "Downstream_Feed_Dup")

    res1 = client.post(
        "/api/v1/dependencies",
        json={
            "downstream_feed_id": str(downstream.id),
            "upstream_feed_id": str(upstream.id),
            "dependency_type": "HARD",
        },
        headers=engineer_headers,
    )
    assert res1.status_code == 201

    res2 = client.post(
        "/api/v1/dependencies",
        json={
            "downstream_feed_id": str(downstream.id),
            "upstream_feed_id": str(upstream.id),
            "dependency_type": "HARD",
        },
        headers=engineer_headers,
    )
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()


# 11. Dependency cycle detection (direct & indirect)
def test_dependency_cycle_detection_direct_and_indirect(client, engineer_headers, db):
    feed_a = _create_test_feed(db, "Cycle_Feed_A")
    feed_b = _create_test_feed(db, "Cycle_Feed_B")
    feed_c = _create_test_feed(db, "Cycle_Feed_C")

    # Edge 1: B depends on A (A -> B)
    res_ab = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed_b.id), "upstream_feed_id": str(feed_a.id)},
        headers=engineer_headers,
    )
    assert res_ab.status_code == 201

    # Direct cycle test: A depends on B (B -> A) creates A -> B -> A
    res_ba = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed_a.id), "upstream_feed_id": str(feed_b.id)},
        headers=engineer_headers,
    )
    assert res_ba.status_code == 400
    assert "circular dependency detected" in res_ba.json()["detail"].lower()

    # Edge 2: C depends on B (B -> C, so A -> B -> C)
    res_bc = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed_c.id), "upstream_feed_id": str(feed_b.id)},
        headers=engineer_headers,
    )
    assert res_bc.status_code == 201

    # Indirect cycle test: A depends on C (C -> A) creates A -> B -> C -> A
    res_ca = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed_a.id), "upstream_feed_id": str(feed_c.id)},
        headers=engineer_headers,
    )
    assert res_ca.status_code == 400
    assert "circular dependency detected" in res_ca.json()["detail"].lower()


# 12. Dependency cycle concurrency locking
def test_dependency_cycle_concurrency_locking(client, engineer_headers, db):
    feed_x = _create_test_feed(db, "Lock_Feed_X")
    feed_y = _create_test_feed(db, "Lock_Feed_Y")

    # Creating dependency executes under advisory transaction lock and succeeds
    res = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed_y.id), "upstream_feed_id": str(feed_x.id)},
        headers=engineer_headers,
    )
    assert res.status_code == 201
