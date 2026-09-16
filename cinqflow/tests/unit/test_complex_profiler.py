"""
Unit Tests for Deterministic Complex Formats Profiler — Wave 3 Slice 1 (CF-V3-E5-05)
"""
import pytest
import json
from backend.engine.profiler import DeterministicProfiler
from backend.models.schema import SchemaDataTypeEnum


def test_detect_format():
    assert DeterministicProfiler.detect_format("id,name,dob\n1,Alice,1980-01-01") == "CSV"
    assert DeterministicProfiler.detect_format('{"resourceType": "Bundle", "type": "collection"}') == "FHIR"
    assert DeterministicProfiler.detect_format('{"patient": {"name": "Alice"}}') == "JSON"
    assert DeterministicProfiler.detect_format('{"id": 1}\n{"id": 2}\n{"id": 3}') == "NDJSON"
    assert DeterministicProfiler.detect_format('<?xml version="1.0"?><ClinicalDocument><title>Test</title></ClinicalDocument>') == "XML"


def test_profile_fhir_bundle():
    fhir_bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "total": 2,
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-001",
                    "name": [
                        {
                            "use": "official",
                            "family": "Johnson",
                            "given": ["Alice"]
                        }
                    ],
                    "gender": "female",
                    "birthDate": "1985-06-15",
                    "telecom": [
                        {"system": "phone", "value": "555-0101"}
                    ]
                }
            },
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-002",
                    "name": [
                        {
                            "use": "official",
                            "family": "Smith",
                            "given": ["Bob"]
                        }
                    ],
                    "gender": "male",
                    "birthDate": "1990-03-22",
                    "telecom": [
                        {"system": "email", "value": "bob@example.com"}
                    ]
                }
            }
        ]
    }
    content_str = json.dumps(fhir_bundle)
    res = DeterministicProfiler.profile_auto(content_str)

    assert res["format"] == "FHIR"
    assert res["is_complex"] is True
    assert res["row_count"] == 2
    assert "hierarchical_paths" in res
    assert res["summary"]["nested_array_count"] >= 1

    paths = {p["path"]: p for p in res["hierarchical_paths"]}
    assert "resourceType" in paths
    assert "id" in paths
    assert "gender" in paths
    assert "birthDate" in paths
    assert paths["birthDate"]["inferred_type"] == SchemaDataTypeEnum.DATE.value


def test_profile_ndjson():
    ndjson_content = "\n".join([
        json.dumps({"claim_id": "CLM001", "amount": 150.50, "status": "PAID"}),
        json.dumps({"claim_id": "CLM002", "amount": 220.00, "status": "PENDING"}),
        json.dumps({"claim_id": "CLM003", "amount": 89.25, "status": "DENIED"}),
    ])
    res = DeterministicProfiler.profile_auto(ndjson_content)

    assert res["format"] == "JSON" or res["format"] == "NDJSON"
    assert res["row_count"] == 3
    assert res["column_count"] == 3
    cols = {c["column_name"]: c for c in res["columns"]}
    assert cols["amount"]["inferred_type"] == SchemaDataTypeEnum.DECIMAL


def test_profile_xml():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <ClinicalDocument xmlns="urn:hl7-org:v3">
        <recordTarget>
            <patientRole>
                <id extension="MRN-1001" root="2.16.840.1.113883.19.5"/>
                <patient>
                    <name>
                        <given>Alice</given>
                        <family>Williams</family>
                    </name>
                    <administrativeGenderCode code="F"/>
                    <birthTime value="19781108"/>
                </patient>
            </patientRole>
        </recordTarget>
    </ClinicalDocument>
    """
    res = DeterministicProfiler.profile_auto(xml_content)

    assert res["format"] == "XML"
    assert res["is_complex"] is True
    assert res["column_count"] > 0
    paths = {p["path"]: p for p in res["hierarchical_paths"]}
    # Check that paths were discovered
    assert any("patient" in p for p in paths.keys())
