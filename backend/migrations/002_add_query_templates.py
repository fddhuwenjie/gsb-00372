"""Database migration: add query_templates and template_versions tables.

Idempotent; safe to run against an existing database without touching data.
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

        if 'query_templates' not in existing:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS query_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(200) NOT NULL,
                    description TEXT,
                    query_structure JSON NOT NULL,
                    parameters JSON NOT NULL,
                    current_version INTEGER NOT NULL DEFAULT 1,
                    share_token VARCHAR(10) UNIQUE,
                    share_expires_at DATETIME,
                    share_access_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_query_templates_share "
                "ON query_templates(share_token)"
            ))
            print("  - Created query_templates table")

        if 'template_versions' not in existing:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS template_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL REFERENCES query_templates(id),
                    version INTEGER NOT NULL,
                    query_structure JSON NOT NULL,
                    parameters JSON NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(template_id, version)
                )
            """))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_template_versions_template "
                "ON template_versions(template_id)"
            ))
            print("  - Created template_versions table")

        db.session.commit()
        print("Migration completed successfully!")
        print(f"All tables now: {db.inspect(db.engine).get_table_names()}")


if __name__ == '__main__':
    run_migration()
