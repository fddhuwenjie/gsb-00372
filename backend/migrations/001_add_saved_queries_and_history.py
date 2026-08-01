"""
Database migration script to add saved_queries and query_history tables.
Run this script to create new tables without affecting existing data.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import SavedQuery, QueryHistory

def run_migration():
    app = create_app()
    
    with app.app_context():
        print("Checking existing tables...")
        inspector = db.inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        print(f"Existing tables: {existing_tables}")
        
        new_tables = []
        if 'saved_queries' not in existing_tables:
            new_tables.append('saved_queries')
        if 'query_history' not in existing_tables:
            new_tables.append('query_history')
        
        if not new_tables:
            print("All new tables already exist. No migration needed.")
            return
        
        print(f"Creating new tables: {new_tables}")
        
        for table_name in new_tables:
            if table_name == 'saved_queries':
                db.session.execute(db.text("""
                    CREATE TABLE IF NOT EXISTS saved_queries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(200) NOT NULL,
                        description TEXT,
                        query_structure JSON NOT NULL,
                        chart_config JSON,
                        share_token VARCHAR(10) UNIQUE,
                        share_expires_at DATETIME,
                        share_access_count INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                print("  - Created saved_queries table")
            
            elif table_name == 'query_history':
                db.session.execute(db.text("""
                    CREATE TABLE IF NOT EXISTS query_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_session VARCHAR(100) NOT NULL,
                        query_structure JSON NOT NULL,
                        sql TEXT NOT NULL,
                        params JSON,
                        duration REAL,
                        row_count INTEGER,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                print("  - Created query_history table")
                
                db.session.execute(db.text("""
                    CREATE INDEX IF NOT EXISTS idx_query_history_session 
                    ON query_history(user_session, created_at DESC)
                """))
                print("  - Created index on query_history")
        
        db.session.commit()
        print("\nMigration completed successfully!")
        
        inspector = db.inspect(db.engine)
        all_tables = inspector.get_table_names()
        print(f"All tables now: {all_tables}")

if __name__ == '__main__':
    run_migration()
