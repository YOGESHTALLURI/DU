import sys
sys.path.insert(0, '.')
import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import text
from backend.core.database import engine

def run_comprehensive_verification():
    print("=" * 60)
    print("STARTING COMPREHENSIVE LIVE POSTGRESQL VERIFICATION")
    print("=" * 60)

    # Step 1: Ensure test roles exist
    with engine.connect() as conn:
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'test_live_consumer') THEN
                    CREATE ROLE test_live_consumer IN ROLE cinqflow_consumer_base;
                END IF;
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'test_live_unauthorized') THEN
                    CREATE ROLE test_live_unauthorized;
                END IF;
            END $$;
        """))
        conn.commit()

    # Step 2: Run verification checks inside an isolated transaction
    with engine.connect() as conn:
        # 1. Check ods_certifications table exists
        tbl_res = conn.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'ods_certifications';
        """)).scalar()
        print(f"1. ods_certifications table exists: {tbl_res == 'ods_certifications'}")
        assert tbl_res == 'ods_certifications'

        # 2. Check all three certified views exist
        views = conn.execute(text("""
            SELECT table_name FROM information_schema.views 
            WHERE table_schema = 'ods_certified' 
            ORDER BY table_name;
        """)).scalars().all()
        print(f"2. ods_certified views present: {views}")
        assert set(views) == {'claim_lines_v1', 'claims_v1', 'members_v1'}

        # 3. Check migration 024 is current
        cur_rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        print(f"3. Alembic current revision: {cur_rev}")
        assert cur_rev == '024_ods_certification_and_consumer_gate'

        # 4. Check consumer role exists
        role = conn.execute(text("SELECT rolname FROM pg_roles WHERE rolname = 'cinqflow_consumer_base';")).scalar()
        print(f"4. cinqflow_consumer_base role exists: {role == 'cinqflow_consumer_base'}")
        assert role == 'cinqflow_consumer_base'

        # 5-7. Live test view filtering: Certified, Uncertified, Failed
        batch_certified = uuid.uuid4()
        batch_uncertified = uuid.uuid4()
        batch_failed = uuid.uuid4()
        model_id = conn.execute(text("SELECT id FROM ods_model_versions WHERE status = 'PUBLISHED' LIMIT 1")).scalar()
        feed_id = conn.execute(text("SELECT id FROM feeds LIMIT 1")).scalar()
        fv_id = conn.execute(text(f"SELECT id FROM feed_versions WHERE feed_id = '{feed_id}' LIMIT 1")).scalar()

        print(f"Using test fixtures: model_id={model_id}, feed_id={feed_id}")

        # Insert 3 batches
        for b_id, name in [(batch_certified, 'cert'), (batch_uncertified, 'uncert'), (batch_failed, 'fail')]:
            conn.execute(text(f"""
                INSERT INTO batches (id, feed_id, feed_version_id, status, triggered_by, ods_model_version_id, created_by, updated_by)
                VALUES ('{b_id}', '{feed_id}', '{fv_id}', 'SUCCESS', 'tester', '{model_id}', 'tester', 'tester');
            """))
            # Insert members for each batch
            conn.execute(text(f"""
                INSERT INTO internal_ods.ods_members_v1 (cinq_id, batch_id, ods_model_version_id, first_name, last_name, date_of_birth, gender, created_by, updated_by)
                VALUES (gen_random_uuid(), '{b_id}', '{model_id}', 'Member_{name}', 'Test', '1990-01-01', 'U', 'tester', 'tester');
            """))

        # Insert certification for batch_certified (CERTIFIED)
        cert_row_id = conn.execute(text(f"""
            INSERT INTO ods_certifications (id, batch_id, ods_model_version_id, status, certified_by, certified_at, created_by, updated_by)
            VALUES (gen_random_uuid(), '{batch_certified}', '{model_id}', 'CERTIFIED', 'steward', now(), 'steward', 'steward')
            RETURNING id;
        """)).scalar()

        # Insert certification for batch_failed (FAILED)
        failed_row_id = conn.execute(text(f"""
            INSERT INTO ods_certifications (id, batch_id, ods_model_version_id, status, certified_by, certified_at, created_by, updated_by)
            VALUES (gen_random_uuid(), '{batch_failed}', '{model_id}', 'FAILED', 'steward', now(), 'steward', 'steward')
            RETURNING id;
        """)).scalar()

        # 5. Verify certified batch is visible in view
        cert_rows = conn.execute(text(f"SELECT count(*) FROM ods_certified.members_v1 WHERE batch_id = '{batch_certified}'")).scalar()
        print(f"5. Certified batch visible in ods_certified.members_v1: {cert_rows == 1} (count={cert_rows})")
        assert cert_rows == 1

        # 6. Verify uncertified batch is hidden in view
        uncert_rows = conn.execute(text(f"SELECT count(*) FROM ods_certified.members_v1 WHERE batch_id = '{batch_uncertified}'")).scalar()
        print(f"6. Uncertified batch hidden in ods_certified.members_v1: {uncert_rows == 0} (count={uncert_rows})")
        assert uncert_rows == 0

        # 7. Verify failed batch is hidden in view
        fail_rows = conn.execute(text(f"SELECT count(*) FROM ods_certified.members_v1 WHERE batch_id = '{batch_failed}'")).scalar()
        print(f"7. Failed batch hidden in ods_certified.members_v1: {fail_rows == 0} (count={fail_rows})")
        assert fail_rows == 0

        # 8-10. Verify Consumer Role Privilege Isolation
        conn.execute(text("SET ROLE test_live_consumer;"))
        consumer_view_count = conn.execute(text(f"SELECT count(*) FROM ods_certified.members_v1 WHERE batch_id = '{batch_certified}';")).scalar()
        print(f"8. Consumer can query ods_certified: {consumer_view_count == 1} (count={consumer_view_count})")
        assert consumer_view_count == 1

        conn.execute(text("SAVEPOINT sp_consumer_denied;"))
        try:
            conn.execute(text("SELECT * FROM internal_ods.ods_members_v1 LIMIT 1;"))
            raise AssertionError("Security failure: Consumer should NOT have access to internal_ods!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_consumer_denied;"))
            print(f"9. Consumer denied access to internal_ods with SQLSTATE 42501: {'permission denied' in str(e) or '42501' in str(e)}")
            assert 'permission denied' in str(e) or '42501' in str(e)

        conn.execute(text("RESET ROLE;"))

        conn.execute(text("SET ROLE test_live_unauthorized;"))
        conn.execute(text("SAVEPOINT sp_unauth_denied;"))
        try:
            conn.execute(text("SELECT * FROM ods_certified.members_v1 LIMIT 1;"))
            raise AssertionError("Security failure: Unauthorized role should NOT have access to ods_certified!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_unauth_denied;"))
            print(f"10. Unauthorized role denied access to ods_certified with SQLSTATE 42501: {'permission denied' in str(e) or '42501' in str(e)}")
            assert 'permission denied' in str(e) or '42501' in str(e)

        conn.execute(text("RESET ROLE;"))

        # 11. Immutability: CERTIFIED row status cannot be modified or reverted
        conn.execute(text("SAVEPOINT sp_immut_cert;"))
        try:
            conn.execute(text(f"UPDATE ods_certifications SET status = 'PENDING' WHERE id = '{cert_row_id}';"))
            raise AssertionError("Trigger failure: CERTIFIED row status mutation was not blocked!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_immut_cert;"))
            print(f"11. CERTIFIED row status mutation blocked by trigger with SQLSTATE 23514: {'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)}")
            assert 'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)

        # 12. Immutability: CERTIFIED row certified_by cannot be modified
        conn.execute(text("SAVEPOINT sp_immut_cert_by;"))
        try:
            conn.execute(text(f"UPDATE ods_certifications SET certified_by = 'tampered_user' WHERE id = '{cert_row_id}';"))
            raise AssertionError("Trigger failure: CERTIFIED row certified_by mutation was not blocked!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_immut_cert_by;"))
            print(f"12. CERTIFIED row certified_by mutation blocked by trigger with SQLSTATE 23514: {'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)}")
            assert 'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)

        # 13. Immutability: CERTIFIED row notes cannot be modified
        conn.execute(text("SAVEPOINT sp_immut_cert_notes;"))
        try:
            conn.execute(text(f"UPDATE ods_certifications SET certification_notes = 'tampered_notes' WHERE id = '{cert_row_id}';"))
            raise AssertionError("Trigger failure: CERTIFIED row notes mutation was not blocked!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_immut_cert_notes;"))
            print(f"13. CERTIFIED row notes mutation blocked by trigger with SQLSTATE 23514: {'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)}")
            assert 'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)

        # 14. Immutability: FAILED row cannot be modified or reverted
        conn.execute(text("SAVEPOINT sp_immut_fail;"))
        try:
            conn.execute(text(f"UPDATE ods_certifications SET status = 'CERTIFIED' WHERE id = '{failed_row_id}';"))
            raise AssertionError("Trigger failure: FAILED row reversion was not blocked!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_immut_fail;"))
            print(f"14. FAILED row reversion blocked by trigger with SQLSTATE 23514: {'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)}")
            assert 'check_violation' in str(e) or '23514' in str(e) or 'sealed' in str(e)

        # 15. Direct SQL DELETE protection against ods_certifications
        conn.execute(text("SAVEPOINT sp_del_cert;"))
        try:
            conn.execute(text(f"DELETE FROM ods_certifications WHERE id = '{cert_row_id}';"))
            raise AssertionError("Trigger failure: Direct DELETE on ods_certifications was not blocked!")
        except Exception as e:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_del_cert;"))
            print(f"15. Direct DELETE on ods_certifications blocked by trigger with SQLSTATE 23514: {'check_violation' in str(e) or '23514' in str(e) or 'strictly prohibited' in str(e)}")
            assert 'check_violation' in str(e) or '23514' in str(e) or 'strictly prohibited' in str(e)

        # 16. Parent batch deletion rejected (FK RESTRICT)
        conn.execute(text("SAVEPOINT sp_del_parent_batch;"))
        parent_del_sqlstate = None
        try:
            conn.execute(text(f"DELETE FROM batches WHERE id = '{batch_certified}';"))
            raise AssertionError("Constraint failure: Parent batch DELETE was not blocked!")
        except Exception as e:
            orig = getattr(e, 'orig', e)
            parent_del_sqlstate = getattr(orig, 'sqlstate', None)
            conn.execute(text("ROLLBACK TO SAVEPOINT sp_del_parent_batch;"))
            print("16. Parent batch DELETE blocked by foreign-key RESTRICT:")
            print(f"    SQLSTATE {parent_del_sqlstate} (foreign_key_violation)")
            assert parent_del_sqlstate == '23503'

        # Verify parent batch and certification record both remained present after the failed DELETE
        batch_still_present = conn.execute(text(f"SELECT count(*) FROM batches WHERE id = '{batch_certified}';")).scalar() == 1
        cert_still_present = conn.execute(text(f"SELECT count(*) FROM ods_certifications WHERE id = '{cert_row_id}';")).scalar() == 1
        print(f"    Parent batch remained present: {batch_still_present}")
        print(f"    Certification record remained present: {cert_still_present}")
        assert batch_still_present is True
        assert cert_still_present is True

        # 17. Clean up test transaction and drop temporary roles
        conn.rollback()

    # Step 3: Cleanup roles and verify database is clean
    with engine.connect() as conn:
        conn.execute(text("DROP ROLE IF EXISTS test_live_consumer;"))
        conn.execute(text("DROP ROLE IF EXISTS test_live_unauthorized;"))
        conn.commit()

        # Check clean state: temporary batches and certifications do not exist
        remaining_certs = conn.execute(text(f"SELECT count(*) FROM ods_certifications WHERE id IN ('{cert_row_id}', '{failed_row_id}');")).scalar()
        remaining_batches = conn.execute(text(f"SELECT count(*) FROM batches WHERE id IN ('{batch_certified}', '{batch_uncertified}', '{batch_failed}');")).scalar()
        db_clean = (remaining_certs == 0 and remaining_batches == 0)

        print("17. Transaction rolled back: True")
        print(f"    Database clean state confirmed: {db_clean}")
        assert db_clean is True

    print("=" * 60)
    print("ALL 17 LIVE POSTGRESQL VERIFICATION CHECKS PASSED!")
    print("=" * 60)

if __name__ == '__main__':
    run_comprehensive_verification()
