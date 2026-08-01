from sqlalchemy import inspect, text
from app.database import db

class MetadataService:
    @staticmethod
    def get_all_metadata():
        inspector = inspect(db.engine)
        tables = []
        
        for table_name in inspector.get_table_names():
            table_meta = MetadataService._get_table_metadata(inspector, table_name)
            tables.append(table_meta)
        
        return tables
    
    @staticmethod
    def _get_table_metadata(inspector, table_name):
        columns = []
        for col in inspector.get_columns(table_name):
            columns.append({
                'name': col['name'],
                'type': str(col['type']),
                'nullable': col.get('nullable', True),
                'isPrimaryKey': col['name'] in inspector.get_pk_constraint(table_name)['constrained_columns']
            })
        
        foreign_keys = []
        for fk in inspector.get_foreign_keys(table_name):
            foreign_keys.append({
                'constraintName': fk['name'],
                'fromColumn': fk['constrained_columns'][0],
                'toTable': fk['referred_table'],
                'toColumn': fk['referred_columns'][0]
            })
        
        return {
            'name': table_name,
            'columns': columns,
            'foreignKeys': foreign_keys
        }
