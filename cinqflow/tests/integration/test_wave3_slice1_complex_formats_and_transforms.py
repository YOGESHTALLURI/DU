"""
Integration Tests for Wave 3 Slice 1:
Complex Healthcare Formats & Structural Transforms (CF-V3-E5-05, CF-V3-E6-05)
"""
import pytest
import json
import uuid
from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum, SchemaDataTypeEnum, SchemaField
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.mapping import Mapping, MappingVersion, MappingLine, TransformTypeEnum
from backend.engine.sandbox_executor import SandboxExecutor


@pytest.fixture
def test_feed_and_canonical(db, engineer_headers):
    # 1. Create Feed
    feed = Feed(
        id=uuid.uuid4(),
        name=f"FHIR Patient Ingestion {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="FHIR JSON bundle ingestion feed",
        format=FeedFormatEnum.JSON,
        landing_folder="/data/landing/fhir",
        filename_pattern="patient_*.json",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(feed)

    # 2. Create Schema & Published Version
    schema_obj = Schema(
        id=uuid.uuid4(),
        feed_id=feed.id,
        name="Patient FHIR Schema",
        description="FHIR Schema Contract",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(schema_obj)
    db.flush()

    schema_ver = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema_obj.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(schema_ver)
    db.flush()

    # Add schema fields matching discovered paths
    field_defs = [
        ("id", SchemaDataTypeEnum.STRING, True),
        ("resourceType", SchemaDataTypeEnum.STRING, True),
        ("name", SchemaDataTypeEnum.STRING, False),
        ("gender", SchemaDataTypeEnum.STRING, False),
        ("birthDate", SchemaDataTypeEnum.DATE, False),
        ("telecom", SchemaDataTypeEnum.STRING, False),
    ]
    for idx, (f_name, f_type, is_req) in enumerate(field_defs, 1):
        f = SchemaField(
            id=uuid.uuid4(),
            schema_version_id=schema_ver.id,
            field_name=f_name,
            data_type=f_type,
            ordinal_position=idx,
            is_required=is_req,
            is_nullable=not is_req,
            created_by="engineer@cinqflow.local",
            updated_by="engineer@cinqflow.local",
        )
        db.add(f)

    # 3. Create Canonical Model
    cm = CanonicalModel(
        id=uuid.uuid4(),
        name=f"Canonical Patient Model {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="Enterprise patient model",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(cm)
    db.flush()

    # Canonical fields
    c_fields = [
        ("patient_id", SchemaDataTypeEnum.STRING, True),
        ("full_name", SchemaDataTypeEnum.STRING, False),
        ("gender_code", SchemaDataTypeEnum.STRING, False),
        ("birth_date", SchemaDataTypeEnum.DATE, False),
        ("primary_phone", SchemaDataTypeEnum.STRING, False),
    ]
    cf_objs = []
    for idx, (cf_name, cf_type, cf_req) in enumerate(c_fields, 1):
        cf = CanonicalField(
            id=uuid.uuid4(),
            canonical_model_id=cm.id,
            field_name=cf_name,
            data_type=cf_type,
            ordinal_position=idx,
            is_required=cf_req,
            is_nullable=not cf_req,
            created_by="engineer@cinqflow.local",
            updated_by="engineer@cinqflow.local",
        )
        db.add(cf)
        cf_objs.append(cf)

    db.commit()
    return feed, schema_obj, schema_ver, cm, cf_objs


def test_complex_profiling_and_paths_api(client, engineer_headers, test_feed_and_canonical):
    feed, schema_obj, schema_ver, cm, cf_objs = test_feed_and_canonical

    # 1. Upload sample FHIR file
    fhir_data = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-100",
                    "name": [{"family": "Doe", "given": ["Jane"]}],
                    "gender": "female",
                    "birthDate": "1992-04-10",
                    "telecom": [{"system": "phone", "value": "555-4321"}],
                }
            }
        ]
    }
    file_bytes = json.dumps(fhir_data).encode("utf-8")
    upload_res = client.post(
        f"/api/v1/feeds/{feed.id}/samples",
        headers=engineer_headers,
        files={"file": ("sample_patient.json", file_bytes, "application/json")},
    )
    assert upload_res.status_code == 201
    sample_id = upload_res.json()["id"]

    # 2. Run profiling on sample
    profile_res = client.post(
        f"/api/v1/feeds/{feed.id}/samples/{sample_id}/profile",
        headers=engineer_headers,
    )
    assert profile_res.status_code == 201
    run_id = profile_res.json()["id"]

    # 3. Retrieve hierarchical paths
    paths_res = client.get(
        f"/api/v1/profiling-runs/{run_id}/paths",
        headers=engineer_headers,
    )
    assert paths_res.status_code == 200
    paths_data = paths_res.json()
    assert paths_data["count"] > 0
    path_names = [p["path"] for p in paths_data["paths"]]
    assert "id" in path_names or any("id" in p for p in path_names)

    # 4. Direct inspect-complex endpoint test
    inspect_res = client.post(
        "/api/v1/inspect-complex",
        headers=engineer_headers,
        files={"file": ("bundle.json", file_bytes, "application/json")},
    )
    assert inspect_res.status_code == 200
    inspect_data = inspect_res.json()
    assert inspect_data["format"] == "FHIR"
    assert inspect_data["is_complex"] is True


def test_test_structural_transform_api(client, engineer_headers, readonly_headers):
    payload = {
        "transform_type": "PATH_EXTRACT",
        "transform_params": {"path": "patient.telecom[?(@.system=='phone')].value"},
        "source_fields": ["patient"],
        "sample_input": {
            "patient": {
                "telecom": [
                    {"system": "email", "value": "user@example.com"},
                    {"system": "phone", "value": "555-8888"},
                ]
            }
        },
    }

    # Engineer success
    res = client.post(
        "/api/v1/mappings/test-structural-transform",
        headers=engineer_headers,
        json=payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["result"] == "555-8888"

    # Test EXPLODE
    explode_payload = {
        "transform_type": "EXPLODE",
        "transform_params": {"array_path": "diagnoses"},
        "source_fields": ["diagnoses"],
        "sample_input": {"diagnoses": ["A01", "B02"]},
    }
    res_exp = client.post(
        "/api/v1/mappings/test-structural-transform",
        headers=engineer_headers,
        json=explode_payload,
    )
    assert res_exp.status_code == 200
    assert res_exp.json()["success"] is True

    # READ_ONLY rejected with 403
    ro_res = client.post(
        "/api/v1/mappings/test-structural-transform",
        headers=readonly_headers,
        json=payload,
    )
    assert ro_res.status_code == 403


def test_mapping_with_structural_transforms_lifecycle(client, engineer_headers, test_feed_and_canonical):
    feed, schema_obj, schema_ver, cm, cf_objs = test_feed_and_canonical
    cf_map = {cf.field_name: cf for cf in cf_objs}

    # 1. Create Mapping Draft
    create_res = client.post(
        "/api/v1/mappings",
        headers=engineer_headers,
        json={
            "feed_id": str(feed.id),
            "canonical_model_id": str(cm.id),
            "name": "FHIR to Canonical Patient Mapping",
        },
    )
    assert create_res.status_code == 201
    mapping_id = create_res.json()["id"]
    version_id = create_res.json()["draft_version"]["id"]

    # 2. Update Lines with Structural Transforms:
    # - patient_id: DIRECT from id
    # - full_name: PATH_EXTRACT from name[0].family
    # - gender_code: DIRECT from gender
    # - birth_date: DIRECT from birthDate
    # - primary_phone: PATH_EXTRACT from telecom[0].value
    lines = [
        {
            "canonical_field_id": str(cf_map["patient_id"].id),
            "source_field_names": ["id"],
            "transform_type": "DIRECT",
            "transform_params": {},
        },
        {
            "canonical_field_id": str(cf_map["full_name"].id),
            "source_field_names": ["name"],
            "transform_type": "PATH_EXTRACT",
            "transform_params": {"path": "name[0].family"},
        },
        {
            "canonical_field_id": str(cf_map["gender_code"].id),
            "source_field_names": ["gender"],
            "transform_type": "DIRECT",
            "transform_params": {},
        },
        {
            "canonical_field_id": str(cf_map["birth_date"].id),
            "source_field_names": ["birthDate"],
            "transform_type": "DIRECT",
            "transform_params": {},
        },
        {
            "canonical_field_id": str(cf_map["primary_phone"].id),
            "source_field_names": ["telecom"],
            "transform_type": "PATH_EXTRACT",
            "transform_params": {"path": "telecom[0].value"},
        },
    ]

    put_res = client.put(
        f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines",
        headers=engineer_headers,
        json={"lines": lines},
    )
    assert put_res.status_code == 200

    # 3. Validate mapping
    val_res = client.post(
        f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate",
        headers=engineer_headers,
    )
    assert val_res.status_code == 200
    report = val_res.json()
    assert report["is_valid"] is True
    assert len(report["errors"]) == 0

    # 4. Publish mapping version
    pub_res = client.post(
        f"/api/v1/mappings/{mapping_id}/versions/{version_id}/publish",
        headers=engineer_headers,
        json={"change_notes": "Published v1 with structural transforms"},
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "PUBLISHED"
    compiled_spec = pub_res.json()["compiled_spec"]
    assert compiled_spec is not None
    assert len(compiled_spec["fields"]) == 5
    assert any(f["transform_type"] == "PATH_EXTRACT" for f in compiled_spec["fields"])
