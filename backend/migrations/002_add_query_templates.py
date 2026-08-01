"""
Database migration script to add the query_templates table.
Run this script to create the new table without affecting existing data.
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

        if 'query_templates' in existing_tables:
            print("query_templates already exists. No migration needed.")
            return

        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS query_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                parameters JSON NOT NULL,
                query_structure JSON NOT NULL,
                share_token VARCHAR(10) UNIQUE,
                share_expires_at DATETIME,
                share_access_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()
        print("  - Created query_templates table")
        print("\nMigration completed successfully!")

if __name__ == '__main__':
    run_migration()
