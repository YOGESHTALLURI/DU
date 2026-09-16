import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.main import app
from backend.core.database import get_db
from backend.models.base import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://cinqflow:cinqflow@localhost:5432/cinqflow_test"
)

test_engine = create_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def create_test_database():
    with test_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist;"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS internal_ods"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ods_certified"))
        conn.commit()
    Base.metadata.create_all(bind=test_engine)
    with test_engine.connect() as conn:
        conn.execute(text("""
        CREATE OR REPLACE FUNCTION fn_protect_published_ods_model_versions()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status = 'PUBLISHED' THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Immutability Violation: Cannot delete published ODS model version %', OLD.version_number
                    USING ERRCODE = 'check_violation';
                ELSIF TG_OP = 'UPDATE' THEN
                    IF NEW.version_number != OLD.version_number 
                       OR NEW.schema_definition != OLD.schema_definition 
                       OR NEW.domain != OLD.domain THEN
                        RAISE EXCEPTION 'Immutability Violation: Cannot modify definition of published ODS model version %', OLD.version_number
                        USING ERRCODE = 'check_violation';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_protect_published_ods_model_versions ON ods_model_versions;
        CREATE TRIGGER trg_protect_published_ods_model_versions
        BEFORE UPDATE OR DELETE ON ods_model_versions
        FOR EACH ROW
        EXECUTE FUNCTION fn_protect_published_ods_model_versions();

        -- Triggers for ODS Model Version and Claim/Claim-Line Integrity (Blockers 4 & 5)
        CREATE OR REPLACE FUNCTION fn_check_ods_batch_version_match()
        RETURNS TRIGGER AS $$
        DECLARE
            v_batch_version UUID;
        BEGIN
            SELECT ods_model_version_id INTO v_batch_version FROM batches WHERE id = NEW.batch_id;
            IF v_batch_version IS NULL THEN
                RAISE EXCEPTION 'Model Version Integrity Violation: Batch % has no ODS model version assigned', NEW.batch_id
                USING ERRCODE = 'check_violation';
            END IF;
            IF v_batch_version != NEW.ods_model_version_id THEN
                RAISE EXCEPTION 'Model Version Integrity Violation: Row ODS model version % does not match Batch % model version %',
                    NEW.ods_model_version_id, NEW.batch_id, v_batch_version
                USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_check_ods_members_batch_version ON internal_ods.ods_members_v1;
        CREATE TRIGGER trg_check_ods_members_batch_version
        BEFORE INSERT OR UPDATE ON internal_ods.ods_members_v1
        FOR EACH ROW EXECUTE FUNCTION fn_check_ods_batch_version_match();

        DROP TRIGGER IF EXISTS trg_check_ods_claims_batch_version ON internal_ods.ods_claims_v1;
        CREATE TRIGGER trg_check_ods_claims_batch_version
        BEFORE INSERT OR UPDATE ON internal_ods.ods_claims_v1
        FOR EACH ROW EXECUTE FUNCTION fn_check_ods_batch_version_match();

        DROP TRIGGER IF EXISTS trg_check_ods_claim_lines_batch_version ON internal_ods.ods_claim_lines_v1;
        CREATE TRIGGER trg_check_ods_claim_lines_batch_version
        BEFORE INSERT OR UPDATE ON internal_ods.ods_claim_lines_v1
        FOR EACH ROW EXECUTE FUNCTION fn_check_ods_batch_version_match();

        CREATE OR REPLACE FUNCTION fn_check_claim_line_parent_match()
        RETURNS TRIGGER AS $$
        DECLARE
            v_claim RECORD;
        BEGIN
            SELECT batch_id, ods_model_version_id INTO v_claim FROM internal_ods.ods_claims_v1 WHERE claim_id = NEW.claim_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Claim Integrity Violation: Claim line references non-existent claim %', NEW.claim_id
                USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF v_claim.batch_id != NEW.batch_id THEN
                RAISE EXCEPTION 'Claim Integrity Violation: Claim line batch % does not match Claim batch %', NEW.batch_id, v_claim.batch_id
                USING ERRCODE = 'check_violation';
            END IF;
            IF v_claim.ods_model_version_id != NEW.ods_model_version_id THEN
                RAISE EXCEPTION 'Claim Integrity Violation: Claim line model version % does not match Claim model version %', NEW.ods_model_version_id, v_claim.ods_model_version_id
                USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_check_ods_claim_line_parent_match ON internal_ods.ods_claim_lines_v1;
        CREATE TRIGGER trg_check_ods_claim_line_parent_match
        BEFORE INSERT OR UPDATE ON internal_ods.ods_claim_lines_v1
        FOR EACH ROW EXECUTE FUNCTION fn_check_claim_line_parent_match();

        -- Wave 3 Slice 3: Identity triggers & partial unique index
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_crosswalk_source 
        ON identity_crosswalk (source_system, source_identifier_hash) 
        WHERE is_active = TRUE;

        CREATE OR REPLACE FUNCTION trg_prevent_identity_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Physical DELETE on master_identities is strictly prohibited. Use soft status update.';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_prevent_master_identities_delete ON master_identities;
        CREATE TRIGGER trg_prevent_master_identities_delete
        BEFORE DELETE ON master_identities
        FOR EACH ROW EXECUTE FUNCTION trg_prevent_identity_delete();

        CREATE OR REPLACE FUNCTION trg_prevent_decision_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'identity_decisions is append-only and immutable. UPDATE and DELETE are prohibited.';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_prevent_identity_decisions_mutation ON identity_decisions;
        CREATE TRIGGER trg_prevent_identity_decisions_mutation
        BEFORE UPDATE OR DELETE ON identity_decisions
        FOR EACH ROW EXECUTE FUNCTION trg_prevent_decision_mutation();

        -- Migration 023: Event Ledger Immutability Trigger
        CREATE OR REPLACE FUNCTION fn_prevent_merge_split_event_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'identity_merge_split_event is append-only and immutable. UPDATE and DELETE are prohibited.'
            USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_prevent_identity_merge_split_event_mutation ON identity_merge_split_event;
        CREATE TRIGGER trg_prevent_identity_merge_split_event_mutation
        BEFORE UPDATE OR DELETE ON identity_merge_split_event
        FOR EACH ROW EXECUTE FUNCTION fn_prevent_merge_split_event_mutation();

        -- Migration 023: MasterIdentity Status Transition Enforcement Trigger
        CREATE OR REPLACE FUNCTION fn_enforce_master_identity_status_transition()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status = 'MERGED' AND NEW.status != 'MERGED' THEN
                RAISE EXCEPTION 'Illegal status transition on master_identities: MERGED status cannot be reverted to %', NEW.status
                USING ERRCODE = 'check_violation';
            END IF;

            IF OLD.status = 'INACTIVE' AND NEW.status = 'MERGED' THEN
                RAISE EXCEPTION 'Illegal status transition on master_identities: INACTIVE identity cannot be directly MERGED without reactivation'
                USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_enforce_master_identity_status_transition ON master_identities;
        CREATE TRIGGER trg_enforce_master_identity_status_transition
        BEFORE UPDATE OF status ON master_identities
        FOR EACH ROW EXECUTE FUNCTION fn_enforce_master_identity_status_transition();

        -- Migration 024: ODS Certification transition trigger & certified views
        CREATE OR REPLACE FUNCTION fn_protect_ods_certification_transition()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ods_certifications records are append-only and immutable. DELETE operations are strictly prohibited.'
                USING ERRCODE = 'check_violation';
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF OLD.status IN ('CERTIFIED', 'FAILED') THEN
                    RAISE EXCEPTION 'ods_certifications record % is sealed in % status and cannot be modified.', OLD.id, OLD.status
                    USING ERRCODE = 'check_violation';
                END IF;

                IF NEW.status NOT IN ('PENDING', 'CERTIFIED', 'FAILED') THEN
                    RAISE EXCEPTION 'Invalid status transition on ods_certifications from % to %', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
                END IF;

                IF NEW.batch_id != OLD.batch_id THEN
                    RAISE EXCEPTION 'batch_id on ods_certifications is immutable'
                    USING ERRCODE = 'check_violation';
                END IF;

                IF NEW.ods_model_version_id != OLD.ods_model_version_id THEN
                    RAISE EXCEPTION 'ods_model_version_id on ods_certifications is immutable'
                    USING ERRCODE = 'check_violation';
                END IF;

                IF NEW.created_at != OLD.created_at THEN
                    RAISE EXCEPTION 'created_at on ods_certifications is immutable'
                    USING ERRCODE = 'check_violation';
                END IF;

                IF NEW.created_by != OLD.created_by THEN
                    RAISE EXCEPTION 'created_by on ods_certifications is immutable'
                    USING ERRCODE = 'check_violation';
                END IF;

                RETURN NEW;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_protect_ods_certification_transition ON ods_certifications;
        CREATE TRIGGER trg_protect_ods_certification_transition
        BEFORE UPDATE OR DELETE ON ods_certifications
        FOR EACH ROW EXECUTE FUNCTION fn_protect_ods_certification_transition();

        CREATE OR REPLACE VIEW ods_certified.members_v1 AS
        SELECT m.cinq_id, m.batch_id, m.ods_model_version_id, m.first_name, m.last_name,
               m.date_of_birth, m.gender, m.address_line1, m.city, m.state, m.postal_code,
               m.survivorship_applied, m.created_at, m.updated_at
        FROM internal_ods.ods_members_v1 m
        JOIN ods_certifications c ON m.batch_id = c.batch_id
        WHERE c.status = 'CERTIFIED';

        CREATE OR REPLACE VIEW ods_certified.claims_v1 AS
        SELECT cl.claim_id, cl.cinq_id, cl.batch_id, cl.ods_model_version_id, cl.claim_type,
               cl.total_charge_amount, cl.claim_date, cl.created_at, cl.updated_at
        FROM internal_ods.ods_claims_v1 cl
        JOIN ods_certifications c ON cl.batch_id = c.batch_id
        WHERE c.status = 'CERTIFIED';

        CREATE OR REPLACE VIEW ods_certified.claim_lines_v1 AS
        SELECT cll.claim_line_id, cll.claim_id, cll.batch_id, cll.ods_model_version_id,
               cll.line_number, cll.service_date, cll.procedure_code, cll.allowed_amount,
               cll.paid_amount, cll.created_at, cll.updated_at
        FROM internal_ods.ods_claim_lines_v1 cll
        JOIN ods_certifications c ON cll.batch_id = c.batch_id
        WHERE c.status = 'CERTIFIED';

        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cinqflow_consumer_base') THEN
                CREATE ROLE cinqflow_consumer_base NOLOGIN;
            END IF;
        END $$;

        GRANT USAGE ON SCHEMA ods_certified TO cinqflow_consumer_base;
        GRANT SELECT ON ALL TABLES IN SCHEMA ods_certified TO cinqflow_consumer_base;
        ALTER DEFAULT PRIVILEGES IN SCHEMA ods_certified GRANT SELECT ON TABLES TO cinqflow_consumer_base;
        REVOKE ALL ON SCHEMA internal_ods FROM cinqflow_consumer_base;
        """))
        conn.commit()
    yield
    with test_engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS ods_certified.claim_lines_v1 CASCADE"))
        conn.execute(text("DROP VIEW IF EXISTS ods_certified.claims_v1 CASCADE"))
        conn.execute(text("DROP VIEW IF EXISTS ods_certified.members_v1 CASCADE"))
        conn.execute(text("ALTER TABLE IF EXISTS recovery_playbooks DROP CONSTRAINT IF EXISTS recovery_playbooks_current_version_id_fkey CASCADE"))
        conn.execute(text("ALTER TABLE IF EXISTS recovery_playbooks DROP CONSTRAINT IF EXISTS fk_recovery_playbooks_current_version CASCADE"))
        conn.commit()
    Base.metadata.drop_all(bind=test_engine)

@pytest.fixture
def db():
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def client(db):
    def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture
def engineer_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert res.status_code == 200
    return res.json()["access_token"]

@pytest.fixture
def readonly_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "readonly:readonly123"})
    assert res.status_code == 200
    return res.json()["access_token"]

@pytest.fixture
def engineer_headers(engineer_token):
    return {"Authorization": f"Bearer {engineer_token}"}

@pytest.fixture
def readonly_headers(readonly_token):
    return {"Authorization": f"Bearer {readonly_token}"}

@pytest.fixture
def analyst_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "analyst:analyst123"})
    assert res.status_code == 200
    return res.json()["access_token"]

@pytest.fixture
def analyst_headers(analyst_token):
    return {"Authorization": f"Bearer {analyst_token}"}

@pytest.fixture
def engineer2_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "engineer2:engineer123"})
    assert res.status_code == 200
    return res.json()["access_token"]

@pytest.fixture
def engineer2_headers(engineer2_token):
    return {"Authorization": f"Bearer {engineer2_token}"}

@pytest.fixture
def steward_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "steward:steward123"})
    assert res.status_code == 200
    return res.json()["access_token"]

@pytest.fixture
def steward_headers(steward_token):
    return {"Authorization": f"Bearer {steward_token}"}