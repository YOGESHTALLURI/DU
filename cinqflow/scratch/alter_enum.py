import psycopg

for db_name in ["cinqflow", "cinqflow_test"]:
    conn = psycopg.connect(f"postgresql://cinqflow:cinqflow@localhost:5432/{db_name}", autocommit=True)
    cur = conn.cursor()
    cur.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'dependency.cycle_rejected'")
    cur.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.disabled'")
    cur.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.enabled'")
    conn.close()
    print(f"Altered enum on {db_name} successfully.")
