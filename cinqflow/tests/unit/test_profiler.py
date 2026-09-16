"""
Unit tests for Deterministic Data Profiler Engine — Wave 1 Slice 1
"""
import io
import pytest
from backend.engine.profiler import DeterministicProfiler
from backend.models.schema import SchemaDataTypeEnum


def test_profiler_member_feed_csv():
    csv_data = (
        "member_id,first_name,last_name,date_of_birth,gender,balance\n"
        "M001,Alice,Johnson,1985-06-15,F,120.50\n"
        "M002,Bob,Smith,1990-03-22,M,0.00\n"
        "M003,Carol,Williams,1978-11-08,F,-45.20\n"
        "M004,David,,1982-01-30,M,1500.00\n"
    )
    stream = io.StringIO(csv_data)
    result = DeterministicProfiler.profile_csv(stream)

    assert result["row_count"] == 4
    assert result["column_count"] == 6

    cols = {c["column_name"]: c for c in result["columns"]}

    # member_id
    assert cols["member_id"]["inferred_type"] == SchemaDataTypeEnum.STRING
    assert cols["member_id"]["null_count"] == 0
    assert cols["member_id"]["distinct_count"] == 4

    # last_name has 1 null
    assert cols["last_name"]["null_count"] == 1
    assert cols["last_name"]["null_percentage"] == 25.0
    assert cols["last_name"]["distinct_count"] == 3

    # date_of_birth inferred as DATE
    assert cols["date_of_birth"]["inferred_type"] == SchemaDataTypeEnum.DATE
    assert len(cols["date_of_birth"]["detected_date_patterns"]) > 0
    assert cols["date_of_birth"]["detected_date_patterns"][0]["pattern"] == "YYYY-MM-DD"

    # balance inferred as DECIMAL
    assert cols["balance"]["inferred_type"] == SchemaDataTypeEnum.DECIMAL
    assert cols["balance"]["null_count"] == 0


def test_profiler_claims_feed_csv():
    """Validates profiler against an entirely different dataset with different columns and types."""
    csv_data = (
        "claim_id,provider_id,claim_amount,service_date,is_emergency\n"
        "C101,PRV01,250.75,2026-01-15,true\n"
        "C102,PRV02,1500.00,2026-01-16,false\n"
        "C103,PRV01,,2026-01-18,true\n"
    )
    stream = io.StringIO(csv_data)
    result = DeterministicProfiler.profile_csv(stream)

    assert result["row_count"] == 3
    assert result["column_count"] == 5

    cols = {c["column_name"]: c for c in result["columns"]}
    assert cols["claim_id"]["distinct_count"] == 3
    assert cols["claim_amount"]["null_count"] == 1
    assert cols["claim_amount"]["inferred_type"] == SchemaDataTypeEnum.DECIMAL
    assert cols["service_date"]["inferred_type"] == SchemaDataTypeEnum.DATE
    assert cols["is_emergency"]["inferred_type"] == SchemaDataTypeEnum.BOOLEAN


def test_profiler_empty_file_rejected():
    stream = io.StringIO("")
    with pytest.raises(ValueError, match="empty or missing a valid header row"):
        DeterministicProfiler.profile_csv(stream)


def test_profiler_whitespace_only_header_rejected():
    stream = io.StringIO("   ,   \n")
    with pytest.raises(ValueError, match="empty or missing a valid header row"):
        DeterministicProfiler.profile_csv(stream)


def test_profiler_numeric_min_max_regression():
    """
    Regression test: ensures numeric min/max are evaluated numerically,
    not lexicographically (e.g. 48 < 125.5 < 450, and 450 > 75.25).
    """
    csv_data = (
        "claim_id,claim_amount\n"
        "C01,125.5\n"
        "C02,450\n"
        "C03,48\n"
        "C04,75.25\n"
    )
    stream = io.StringIO(csv_data)
    result = DeterministicProfiler.profile_csv(stream)
    cols = {c["column_name"]: c for c in result["columns"]}

    assert cols["claim_amount"]["inferred_type"] == SchemaDataTypeEnum.DECIMAL
    assert cols["claim_amount"]["min_value"] == "48"
    assert cols["claim_amount"]["max_value"] == "450"


def test_profiler_dd_mm_yyyy_date_detection():
    """
    Regression test: verifies deterministic detection of DD/MM/YYYY date patterns
    and chronological min/max ordering.
    """
    csv_data = (
        "service_id,service_date\n"
        "S01,15/01/2026\n"
        "S02,17/01/2026\n"
        "S03,20/01/2026\n"
        "S04,22/01/2026\n"
    )
    stream = io.StringIO(csv_data)
    result = DeterministicProfiler.profile_csv(stream)
    cols = {c["column_name"]: c for c in result["columns"]}

    assert cols["service_date"]["inferred_type"] == SchemaDataTypeEnum.DATE
    assert len(cols["service_date"]["detected_date_patterns"]) > 0
    assert any(p["pattern"] == "DD/MM/YYYY" for p in cols["service_date"]["detected_date_patterns"])
    assert cols["service_date"]["min_value"] == "15/01/2026"
    assert cols["service_date"]["max_value"] == "22/01/2026"

