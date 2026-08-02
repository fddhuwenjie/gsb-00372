"""Database migration: add execution_plan_records table.

Idempotent; safe to run against an existing database without touching data.
Stores AST hash, parameter *type* summary, normalized SQLite plan, and cost
for each recorded execution -- never raw parameter values.
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

        if 'execution_plan_records' not in existing:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS execution_plan_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER REFERENCES query_templates(id),
                    template_version INTEGER,
                    ast_hash VARCHAR(64) NOT NULL,
                    canonical_ast JSON NOT NULL,
                    param_type_summary JSON NOT NULL,
                    normalized_plan JSON NOT NULL,
                    raw_plan JSON,
                    duration_ms REAL,
                    row_count INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_plan_records_template "
                "ON execution_plan_records(template_id, template_version)"
            ))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_plan_records_hash "
                "ON execution_plan_records(ast_hash)"
            ))
            print("  - Created execution_plan_records table")

        db.session.commit()
        print("Migration completed successfully!")
        print(f"All tables now: {db.inspect(db.engine).get_table_names()}")


if __name__ == '__main__':
    run_migration()
