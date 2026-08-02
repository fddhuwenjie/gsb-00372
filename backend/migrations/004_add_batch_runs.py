"""Database migration: add batch_runs and batch_run_items tables.

Idempotent; safe to run against an existing database without touching data.
Batch runs execute one immutable template version against many parameter sets
with concurrency, total-row and total-time budgets. Only parameter *type*
summaries are stored, never raw values.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def run_migration():
    app = create_app(seed=False)

    with app.app_context():
        inspector = db.inspect(db.engine)
        existing = inspector.get_table_names()
        print(f"Existing tables: {existing}")

        if 'batch_runs' not in existing:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS batch_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL REFERENCES query_templates(id),
                    template_version INTEGER NOT NULL,
                    idempotency_key VARCHAR(80) UNIQUE,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    max_concurrency INTEGER NOT NULL DEFAULT 4,
                    max_total_rows INTEGER,
                    max_total_ms INTEGER,
                    per_item_timeout_ms INTEGER NOT NULL DEFAULT 5000,
                    per_item_max_rows INTEGER NOT NULL DEFAULT 1000,
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    cancel_requested BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME,
                    finished_at DATETIME
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_batch_runs_template "
                "ON batch_runs(template_id)"
            ))
            print("  - Created batch_runs table")

        if 'batch_run_items' not in existing:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS batch_run_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INTEGER NOT NULL REFERENCES batch_runs(id),
                    item_index INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    param_type_summary JSON,
                    plan_record_id INTEGER REFERENCES execution_plan_records(id),
                    row_count INTEGER,
                    duration_ms REAL,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(batch_id, item_index)
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_batch_items_batch "
                "ON batch_run_items(batch_id)"
            ))
            print("  - Created batch_run_items table")

        db.session.commit()
        print("Migration completed successfully!")
        print(f"All tables now: {db.inspect(db.engine).get_table_names()}")


if __name__ == '__main__':
    run_migration()
