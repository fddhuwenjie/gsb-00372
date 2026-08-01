"""
Database migration script to add batch_runs and batch_run_items.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

def run_migration():
    app = create_app()

    with app.app_context():
        inspector = db.inspect(db.engine)
        existing_tables = inspector.get_table_names()
        print(f"Existing tables: {existing_tables}")

        created = []
        if 'batch_runs' not in existing_tables:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS batch_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL,
                    template_version INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'running',
                    stopped_reason VARCHAR(30),
                    idempotency_key VARCHAR(100) UNIQUE,
                    items_input JSON NOT NULL,
                    total_items INTEGER NOT NULL DEFAULT 0,
                    succeeded_items INTEGER NOT NULL DEFAULT 0,
                    failed_items INTEGER NOT NULL DEFAULT 0,
                    cancelled_items INTEGER NOT NULL DEFAULT 0,
                    skipped_items INTEGER NOT NULL DEFAULT 0,
                    max_concurrency INTEGER NOT NULL DEFAULT 2,
                    max_total_rows INTEGER NOT NULL DEFAULT 10000,
                    max_total_time_ms INTEGER NOT NULL DEFAULT 60000,
                    item_timeout_ms INTEGER,
                    item_delay_ms INTEGER NOT NULL DEFAULT 0,
                    cancel_requested BOOLEAN NOT NULL DEFAULT 0,
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    finished_at DATETIME
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_batch_runs_tpl ON batch_runs(template_id, status)"
            ))
            created.append('batch_runs')

        if 'batch_run_items' not in existing_tables:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS batch_run_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_run_id INTEGER NOT NULL REFERENCES batch_runs(id),
                    seq INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    params_summary JSON,
                    ast_hash VARCHAR(32),
                    sql TEXT,
                    plan_json JSON,
                    row_count INTEGER,
                    truncated BOOLEAN DEFAULT 0,
                    duration_ms REAL,
                    error TEXT,
                    error_code VARCHAR(40),
                    started_ts REAL,
                    finished_ts REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_batch_item_seq UNIQUE (batch_run_id, seq)
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_batch_items_run ON batch_run_items(batch_run_id, status)"
            ))
            created.append('batch_run_items')

        db.session.commit()
        if created:
            print(f"Created tables: {created}")
        else:
            print("All tables already exist. No migration needed.")
        print("\nMigration completed successfully!")

if __name__ == '__main__':
    run_migration()
