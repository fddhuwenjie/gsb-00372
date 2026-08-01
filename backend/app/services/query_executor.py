import time
from sqlalchemy import text
from app.database import db
from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService
from app.services.utils import parse_explain_query_plan, parse_explain_bytecode
from app.models import QueryHistory
from datetime import datetime

class QueryExecutor:
    @staticmethod
    def generate_sql(query_structure):
        generator = SQLGenerator(query_structure)
        sql = generator.generate()
        params = generator.get_params()
        return {'sql': sql, 'params': params}
    
    @staticmethod
    def execute(query_structure, user_session=None):
        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']
        
        start_time = time.time()
        
        try:
            query_result = db.session.execute(text(sql), params)
            
            raw_rows = query_result.fetchall()
            rows = [list(row) for row in raw_rows]
            
            column_names = list(query_result.keys())
            
            columns = []
            for idx, col_name in enumerate(column_names):
                type_name = QueryExecutor._infer_type_from_data(rows, idx)
                columns.append({
                    'name': col_name,
                    'type': type_name
                })
            
            execution_time = (time.time() - start_time) * 1000
            
            if user_session:
                history = QueryHistory(
                    user_session=user_session,
                    query_structure=query_structure,
                    sql=sql,
                    params=params,
                    duration=round(execution_time, 2),
                    row_count=len(rows)
                )
                db.session.add(history)
                db.session.commit()
                QueryHistory.prune_old_records(user_session)
            
            return {
                'columns': columns,
                'rows': rows,
                'executionTime': round(execution_time, 2),
                'rowCount': len(rows),
                'sql': sql,
                'params': params
            }
        except Exception as e:
            raise e
    
    @staticmethod
    def explain(query_structure):
        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']
        
        try:
            query_plan_sql = f'EXPLAIN QUERY PLAN {sql}'
            plan_result = db.session.execute(text(query_plan_sql), params)
            plan_rows = [tuple(row) for row in plan_result.fetchall()]
            
            explain_sql = f'EXPLAIN {sql}'
            bytecode_result = db.session.execute(text(explain_sql), params)
            bytecode_rows = [tuple(row) for row in bytecode_result.fetchall()]
            
            plan_tree = parse_explain_query_plan(plan_rows)
            bytecode = parse_explain_bytecode(bytecode_rows)
            
            return {
                'queryPlan': plan_tree,
                'bytecode': bytecode,
                'sql': sql,
                'rawPlanRows': plan_rows,
                'rawBytecodeRows': bytecode_rows
            }
        except Exception as e:
            raise e
    
    @staticmethod
    def _infer_type_from_data(rows, col_idx):
        for row in rows[:10]:
            val = row[col_idx]
            if val is not None:
                if isinstance(val, bool):
                    return 'BOOLEAN'
                elif isinstance(val, int):
                    return 'INTEGER'
                elif isinstance(val, float):
                    return 'NUMERIC'
                else:
                    return 'STRING'
        return 'UNKNOWN'
