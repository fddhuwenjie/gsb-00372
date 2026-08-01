"""
Database migration script to add template_versions and execution_snapshots.
Run this script to create the new tables without affecting existing data.
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
        if 'template_versions' not in existing_tables:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS template_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL REFERENCES query_templates(id),
                    version INTEGER NOT NULL,
                    parameters JSON NOT NULL,
                    query_structure JSON NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_template_version UNIQUE (template_id, version)
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_template_versions_tpl ON template_versions(template_id)"
            ))
            created.append('template_versions')

        if 'execution_snapshots' not in existing_tables:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS execution_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER,
                    template_version INTEGER,
                    ast_hash VARCHAR(32) NOT NULL,
                    params_summary JSON,
                    plan_json JSON,
                    duration_ms REAL,
                    row_count INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_execution_snapshots_tpl ON execution_snapshots(template_id, ast_hash)"
            ))
            created.append('execution_snapshots')

        db.session.commit()
        if created:
            print(f"Created tables: {created}")
        else:
            print("All tables already exist. No migration needed.")
        print("\nMigration completed successfully!")

if __name__ == '__main__':
    run_migration()
