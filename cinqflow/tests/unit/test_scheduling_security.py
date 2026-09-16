"""
Unit Tests for Wave 1 Slice 6: Scheduling & Dependency RBAC & Security (CF-V1-E8-03).
"""
import uuid
import pytest
from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum
from backend.models.schedule import FeedDependency, DependencyTypeEnum


def _create_test_feed(db, name: str) -> Feed:
    feed = Feed(
        id=uuid.uuid4(),
        name=name,
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder=f"./data/landing/{name.lower()}",
        filename_pattern="*.csv",
        schedule_expression="0 0 * * *",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
        status=FeedStatusEnum.ACTIVE,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


# 27. READ_ONLY role receives 403 on all mutations
def test_readonly_forbidden_on_all_schedule_mutations(client, readonly_headers, db):
    feed1 = _create_test_feed(db, "RO_Sec_Feed1")
    feed2 = _create_test_feed(db, "RO_Sec_Feed2")

    dep = FeedDependency(
        id=uuid.uuid4(),
        downstream_feed_id=feed2.id,
        upstream_feed_id=feed1.id,
        dependency_type=DependencyTypeEnum.HARD,
        created_by="system",
        updated_by="system",
    )
    db.add(dep)
    db.commit()

    # Schedule mutations
    res_create_sched = client.post(
        f"/api/v1/schedules/feed/{feed1.id}",
        json={"schedule_expression": "0 12 * * *", "timezone": "UTC", "catchup": False},
        headers=readonly_headers,
    )
    assert res_create_sched.status_code == 403

    res_update_sched = client.put(
        f"/api/v1/schedules/feed/{feed1.id}",
        json={"schedule_expression": "0 12 * * *", "timezone": "UTC", "catchup": False},
        headers=readonly_headers,
    )
    assert res_update_sched.status_code == 403

    res_pause = client.post(f"/api/v1/schedules/feed/{feed1.id}/pause", headers=readonly_headers)
    assert res_pause.status_code == 403

    res_resume = client.post(f"/api/v1/schedules/feed/{feed1.id}/resume", headers=readonly_headers)
    assert res_resume.status_code == 403

    res_disable = client.post(f"/api/v1/schedules/feed/{feed1.id}/disable", headers=readonly_headers)
    assert res_disable.status_code == 403

    res_enable = client.post(f"/api/v1/schedules/feed/{feed1.id}/enable", headers=readonly_headers)
    assert res_enable.status_code == 403

    # Dependency mutations
    res_create_dep = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed1.id), "upstream_feed_id": str(feed2.id)},
        headers=readonly_headers,
    )
    assert res_create_dep.status_code == 403

    res_update_dep = client.put(
        f"/api/v1/dependencies/{dep.id}",
        json={"max_lag_hours": 12},
        headers=readonly_headers,
    )
    assert res_update_dep.status_code == 403

    res_del_dep = client.delete(f"/api/v1/dependencies/{dep.id}", headers=readonly_headers)
    assert res_del_dep.status_code == 403


# 28. BUSINESS_ANALYST role forbidden on mutations, allowed on inspection
def test_analyst_forbidden_on_schedule_modification(client, analyst_headers, db):
    feed1 = _create_test_feed(db, "BA_Sec_Feed1")
    feed2 = _create_test_feed(db, "BA_Sec_Feed2")

    dep = FeedDependency(
        id=uuid.uuid4(),
        downstream_feed_id=feed2.id,
        upstream_feed_id=feed1.id,
        dependency_type=DependencyTypeEnum.HARD,
        created_by="system",
        updated_by="system",
    )
    db.add(dep)
    db.commit()

    # Mutation forbidden (403)
    res_create = client.post(
        f"/api/v1/schedules/feed/{feed1.id}",
        json={"schedule_expression": "0 12 * * *", "timezone": "UTC", "catchup": False},
        headers=analyst_headers,
    )
    assert res_create.status_code == 403

    res_update = client.put(
        f"/api/v1/schedules/feed/{feed1.id}",
        json={"schedule_expression": "0 12 * * *", "timezone": "UTC", "catchup": False},
        headers=analyst_headers,
    )
    assert res_update.status_code == 403

    res_pause = client.post(f"/api/v1/schedules/feed/{feed1.id}/pause", headers=analyst_headers)
    assert res_pause.status_code == 403

    res_disable = client.post(f"/api/v1/schedules/feed/{feed1.id}/disable", headers=analyst_headers)
    assert res_disable.status_code == 403

    res_create_dep = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed1.id), "upstream_feed_id": str(feed2.id)},
        headers=analyst_headers,
    )
    assert res_create_dep.status_code == 403

    res_del_dep = client.delete(f"/api/v1/dependencies/{dep.id}", headers=analyst_headers)
    assert res_del_dep.status_code == 403

    # Read/Inspection allowed (200)
    res_sched = client.get(f"/api/v1/schedules/feed/{feed1.id}", headers=analyst_headers)
    assert res_sched.status_code == 200

    res_dag = client.get("/api/v1/dependencies/dag", headers=analyst_headers)
    assert res_dag.status_code == 200

    res_gate = client.get(f"/api/v1/dependencies/gate-check/{feed1.id}", headers=analyst_headers)
    assert res_gate.status_code == 200


# 29. ENGINEER authorized for complete management lifecycle
def test_engineer_authorized_to_manage_schedules_and_dependencies(client, engineer_headers, db):
    feed1 = _create_test_feed(db, "ENG_Sec_Feed1")
    feed2 = _create_test_feed(db, "ENG_Sec_Feed2")

    # Update schedule (idempotent upsert)
    res_update = client.put(
        f"/api/v1/schedules/feed/{feed1.id}",
        json={"schedule_expression": "30 2 * * *", "timezone": "America/New_York", "catchup": False},
        headers=engineer_headers,
    )
    assert res_update.status_code == 200
    assert res_update.json()["schedule_expression"] == "30 2 * * *"

    # Pause & Resume
    res_pause = client.post(f"/api/v1/schedules/feed/{feed1.id}/pause", headers=engineer_headers)
    assert res_pause.status_code == 200
    assert res_pause.json()["status"] == "PAUSED"

    res_resume = client.post(f"/api/v1/schedules/feed/{feed1.id}/resume", headers=engineer_headers)
    assert res_resume.status_code == 200
    assert res_resume.json()["status"] == "ACTIVE"

    # Disable & Enable
    res_disable = client.post(f"/api/v1/schedules/feed/{feed1.id}/disable", headers=engineer_headers)
    assert res_disable.status_code == 200
    assert res_disable.json()["status"] == "DISABLED"

    res_enable = client.post(f"/api/v1/schedules/feed/{feed1.id}/enable", headers=engineer_headers)
    assert res_enable.status_code == 200
    assert res_enable.json()["status"] == "ACTIVE"

    # Create dependency
    res_create_dep = client.post(
        "/api/v1/dependencies",
        json={"downstream_feed_id": str(feed2.id), "upstream_feed_id": str(feed1.id), "max_lag_hours": 18},
        headers=engineer_headers,
    )
    assert res_create_dep.status_code == 201
    dep_id = res_create_dep.json()["id"]

    # Update dependency
    res_update_dep = client.put(
        f"/api/v1/dependencies/{dep_id}",
        json={"max_lag_hours": 36},
        headers=engineer_headers,
    )
    assert res_update_dep.status_code == 200
    assert res_update_dep.json()["max_lag_hours"] == 36

    # Delete dependency
    res_del_dep = client.delete(f"/api/v1/dependencies/{dep_id}", headers=engineer_headers)
    assert res_del_dep.status_code == 200
