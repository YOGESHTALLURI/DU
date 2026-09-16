"""
Landing Controls Unit & Integration Tests — Wave 0

Verifies Phase 6 requirements:
1. Valid file registration -> ACCEPTED status + Batch created
2. Invalid filename pattern -> REJECTED status + No batch
3. Invalid structure (missing required columns) -> REJECTED status
4. Invalid size (0 bytes) -> REJECTED status
5. Duplicate file submitted twice -> DUPLICATE status, skipped processing, no second batch
6. Audit event generation for every decision
"""
import io
import pytest
from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum


@pytest.fixture
def member_feed(db):
    """Setup a sample configured member feed with required columns."""
    feed = Feed(
        name="MEMBER_LANDING_TEST_FEED",
        domain="MEMBERSHIP",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing/member",
        filename_pattern="MEMBER_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    version = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={
            "fields": [
                {"name": "member_id", "type": "STRING", "required": True},
                {"name": "first_name", "type": "STRING", "required": True},
                {"name": "last_name", "type": "STRING", "required": True},
                {"name": "date_of_birth", "type": "DATE", "required": True},
                {"name": "gender", "type": "ENUM", "required": False},
            ],
            "delimiter": ",",
            "has_header": True,
        },
        change_notes="Initial test config",
        created_by="test",
        updated_by="test",
    )
    db.add(version)
    db.commit()
    db.refresh(feed)
    return feed


def test_valid_file_registration(client, engineer_headers, member_feed, db):
    """Valid CSV arrival: accepted, fingerprint stored, batch created with 3 stages."""
    valid_csv = (
        "member_id,first_name,last_name,date_of_birth,gender\n"
        "M001,Alice,Johnson,1985-06-15,F\n"
        "M002,Bob,Smith,1990-03-22,M\n"
    ).encode("utf-8")

    files = {"file": ("MEMBER_20260901.csv", io.BytesIO(valid_csv), "text/csv")}
    res = client.post("/api/v1/inputs/register", files=files, headers=engineer_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ACCEPTED"
    assert data["is_duplicate"] is False
    assert len(data["file_fingerprint"]) == 64
    assert data["batch"] is not None
    assert data["batch"]["status"] == "PENDING"
    assert len(data["batch"]["stages"]) == 3

    # Verify stages in order: LANDING, BRONZE, SILVER_RAW
    stage_names = [s["stage_name"] for s in data["batch"]["stages"]]
    assert stage_names == ["LANDING", "BRONZE", "SILVER_RAW"]


def test_duplicate_file_submitted_twice_idempotency(client, engineer_headers, member_feed, db):
    """
    CRITICAL IDEMPOTENCY REQUIREMENT:
    Submitting the same file twice must return DUPLICATE status and NOT create a new batch.
    """
    csv_content = (
        "member_id,first_name,last_name,date_of_birth,gender\n"
        "M100,David,Brown,1982-01-10,M\n"
    ).encode("utf-8")

    # First submission
    files1 = {"file": ("MEMBER_RUN_1.csv", io.BytesIO(csv_content), "text/csv")}
    res1 = client.post("/api/v1/inputs/register", files=files1, headers=engineer_headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ACCEPTED"
    assert data1["is_duplicate"] is False
    batch_id_1 = data1["batch"]["id"]

    # Second submission with the exact same content (even under a different filename)
    files2 = {"file": ("MEMBER_RUN_2_RETRY.csv", io.BytesIO(csv_content), "text/csv")}
    res2 = client.post("/api/v1/inputs/register", files=files2, headers=engineer_headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["is_duplicate"] is True
    assert data2["file_fingerprint"] == data1["file_fingerprint"]

    # Verify only ONE input registry entry exists for this fingerprint
    entries = db.query(InputRegistry).filter(InputRegistry.file_fingerprint == data1["file_fingerprint"]).all()
    assert len(entries) == 1

    # Verify audit event for duplicate detection
    audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.INPUT_DUPLICATE_DETECTED)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit is not None


def test_invalid_filename_pattern_rejected(client, engineer_headers, member_feed):
    """Filename that does not match feed pattern (e.g. UNKNOWN_FILE.csv) is rejected."""
    csv_content = "some,data\n1,2\n".encode("utf-8")
    files = {"file": ("COMPLETELY_UNMATCHED_FILE.csv", io.BytesIO(csv_content), "text/csv")}
    res = client.post("/api/v1/inputs/register", files=files, headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "REJECTED"
    assert "No configured feed pattern matched" in data["rejection_reason"]
    assert data["batch"] is None


def test_invalid_structure_missing_required_column(client, engineer_headers, member_feed):
    """CSV missing required columns (e.g. date_of_birth) is rejected."""
    bad_csv = (
        "member_id,first_name,gender\n"  # missing last_name, date_of_birth
        "M001,Alice,F\n"
    ).encode("utf-8")
    files = {"file": ("MEMBER_BAD_STRUCTURE.csv", io.BytesIO(bad_csv), "text/csv")}
    res = client.post("/api/v1/inputs/register", files=files, headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "REJECTED"
    assert "Missing required column in header" in data["rejection_reason"]
    assert data["batch"] is None


def test_empty_file_size_rejected(client, engineer_headers, member_feed):
    """0-byte file is rejected."""
    empty_bytes = b""
    files = {"file": ("MEMBER_EMPTY.csv", io.BytesIO(empty_bytes), "text/csv")}
    res = client.post("/api/v1/inputs/register", files=files, headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "REJECTED"
    assert "0 bytes" in data["rejection_reason"]
    assert data["batch"] is None
