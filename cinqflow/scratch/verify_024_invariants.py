import sys
sys.path.insert(0, '.')
import uuid
from sqlalchemy import text
from backend.core.database import engine

def verify_invariants():
    print("Verifying Migration 024 Invariants on PostgreSQL...")
    with engine.connect() as conn:
        # 1. Check table existence
        tbl_res = conn.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'ods_certifications';
        """)).scalar()
        print(f"1. ods_certifications table exists: {tbl_res == 'ods_certifications'}")
        assert tbl_res == 'ods_certifications'

        # 2. Check views existence
        views = conn.execute(text("""
            SELECT table_name FROM information_schema.views 
            WHERE table_schema = 'ods_certified' 
            ORDER BY table_name;
        """)).scalars().all()
        print(f"2. ods_certified views: {views}")
        assert set(views) == {'claim_lines_v1', 'claims_v1', 'members_v1'}

        # 3. Check role existence
        role = conn.execute(text("""
            SELECT rolname FROM pg_roles WHERE rolname = 'cinqflow_consumer_base';
        """)).scalar()
        print(f"3. cinqflow_consumer_base role exists: {role == 'cinqflow_consumer_base'}")
        assert role == 'cinqflow_consumer_base'

        # 4. Check trigger existence
        trg = conn.execute(text("""
            SELECT trigger_name FROM information_schema.triggers 
            WHERE event_object_table = 'ods_certifications' 
              AND trigger_name = 'trg_protect_ods_certification_transition';
        """)).scalar()
        print(f"4. trg_protect_ods_certification_transition trigger exists: {trg == 'trg_protect_ods_certification_transition'}")
        assert trg == 'trg_protect_ods_certification_transition'

        # 5. Check trigger enforcement in a rollback transaction
        # Get existing batch_id and model_version_id
        batch_row = conn.execute(text("SELECT id FROM batches WHERE status = 'SUCCESS' LIMIT 1")).first()
        if not batch_row:
            batch_row = conn.execute(text("SELECT id FROM batches LIMIT 1")).first()
        batch_id = batch_row[0]

        model_row = conn.execute(text("SELECT id FROM ods_model_versions LIMIT 1")).first()
        model_id = model_row[0]

        print(f"Using batch_id: {batch_id}, model_id: {model_id}")

        cert_id = conn.execute(text(f"""
            INSERT INTO ods_certifications (id, batch_id, ods_model_version_id, status, certified_by, certified_at, created_by, updated_by)
            VALUES (gen_random_uuid(), '{batch_id}', '{model_id}', 'CERTIFIED', 'steward', now(), 'steward', 'steward')
            ON CONFLICT (batch_id) DO UPDATE SET status = 'CERTIFIED'
            RETURNING id;
        """)).scalar()
        print(f"Inserted/updated CERTIFIED row: {cert_id}")

        # Savepoint 1: CERTIFIED -> PENDING
        conn.execute(text("SAVEPOINT sp1;"))
        try:
            conn.execute(text(f"""
                UPDATE ods_certifications SET status = 'PENDING' WHERE id = '{cert_id}';
            """))
            raise AssertionError("Trigger did not block update from CERTIFIED to PENDING!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp1;"))
            print(f"5a. Successfully blocked CERTIFIED -> PENDING update: {e}")
            assert "check_violation" in str(e) or "Illegal status transition" in str(e)

        # Savepoint 2: CERTIFIED -> FAILED
        conn.execute(text("SAVEPOINT sp2;"))
        try:
            conn.execute(text(f"""
                UPDATE ods_certifications SET status = 'FAILED' WHERE id = '{cert_id}';
            """))
            raise AssertionError("Trigger did not block update from CERTIFIED to FAILED!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp2;"))
            print(f"5b. Successfully blocked CERTIFIED -> FAILED update: {e}")
            assert "check_violation" in str(e) or "Illegal status transition" in str(e)

        # Clean up
        conn.execute(text(f"DELETE FROM ods_certifications WHERE id = '{cert_id}';"))
        conn.commit()
        print("Cleaned up test row and committed clean state.")

    print("\nALL MIGRATION 024 INVARIANTS VERIFIED SUCCESSFULLY!")

if __name__ == '__main__':
    verify_invariants()
