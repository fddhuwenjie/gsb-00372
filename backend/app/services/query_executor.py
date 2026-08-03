import time
from sqlalchemy import text, event
from app.database import db
from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService
from app.services.utils import parse_explain_query_plan, parse_explain_bytecode
from app.services.plan_service import create_snapshot, normalize_explain_plan
from app.models import QueryHistory, PlanSnapshot
from datetime import datetime


class QueryExecutor:
    DEFAULT_TIMEOUT = 5
    MAX_ROWS = 1000

    @staticmethod
    def generate_sql(query_structure):
        generator = SQLGenerator(query_structure)
        sql = generator.generate()
        params = generator.get_params()
        return {'sql': sql, 'params': params}

    @staticmethod
    def _validate_and_prepare(query_structure):
        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']
        SecurityService.validate_readonly_sql(sql)
        return sql, params

    @staticmethod
    def _fetch_raw_explain_plan(conn, sql, params):
        plan_sql = f'EXPLAIN QUERY PLAN {sql}'
        plan_result = conn.execute(text(plan_sql), params)
        return [tuple(row) for row in plan_result.fetchall()]

    @staticmethod
    def execute(query_structure, user_session=None, timeout=None, max_rows=None,
                capture_snapshot=False, template_id=None, template_version=None,
                parameters=None, label=None):
        sql, params = QueryExecutor._validate_and_prepare(query_structure)

        if timeout is None:
            timeout = QueryExecutor.DEFAULT_TIMEOUT
        if max_rows is None:
            max_rows = QueryExecutor.MAX_ROWS

        start_time = time.time()

        try:
            conn = db.engine.connect()
            try:
                conn = conn.execution_options(timeout=timeout)

                raw_plan_rows = []
                if capture_snapshot:
                    raw_plan_rows = QueryExecutor._fetch_raw_explain_plan(conn, sql, params)

                query_result = conn.execute(text(sql), params)

                raw_rows = query_result.fetchmany(max_rows + 1)
                row_count = len(raw_rows)
                truncated = row_count > max_rows
                if truncated:
                    raw_rows = raw_rows[:max_rows]
                    row_count = max_rows

                rows = [list(row) for row in raw_rows]
                column_names = list(query_result.keys())

                columns = []
                for idx, col_name in enumerate(column_names):
                    type_name = QueryExecutor._infer_type_from_data(rows, idx)
                    columns.append({
                        'name': col_name,
                        'type': type_name
                    })
            finally:
                conn.close()

            execution_time = (time.time() - start_time) * 1000

            snapshot = None
            if capture_snapshot and raw_plan_rows:
                try:
                    snap_data = create_snapshot(
                        query_structure=query_structure,
                        raw_plan_rows=raw_plan_rows,
                        row_count=row_count,
                        duration_ms=execution_time,
                        parameters=parameters,
                        template_id=template_id,
                        template_version=template_version,
                        label=label,
                    )
                    snap = PlanSnapshot(**snap_data)
                    db.session.add(snap)
                    db.session.flush()
                    snapshot = snap.to_dict()
                except Exception:
                    db.session.rollback()

            if user_session:
                try:
                    history = QueryHistory(
                        user_session=user_session,
                        query_structure=query_structure,
                        sql=sql,
                        params=params,
                        duration=round(execution_time, 2),
                        row_count=row_count
                    )
                    db.session.add(history)
                    db.session.commit()
                    QueryHistory.prune_old_records(user_session)
                except Exception:
                    db.session.rollback()
            elif capture_snapshot:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            result = {
                'columns': columns,
                'rows': rows,
                'executionTime': round(execution_time, 2),
                'rowCount': row_count,
                'truncated': truncated,
                'sql': sql,
                'params': params
            }
            if snapshot:
                result['snapshot'] = snapshot
            return result
        except Exception as e:
            raise e

    @staticmethod
    def explain(query_structure):
        sql, params = QueryExecutor._validate_and_prepare(query_structure)

        try:
            conn = db.engine.connect()
            try:
                query_plan_sql = f'EXPLAIN QUERY PLAN {sql}'
                plan_result = conn.execute(text(query_plan_sql), params)
                plan_rows = [tuple(row) for row in plan_result.fetchall()]

                explain_sql = f'EXPLAIN {sql}'
                bytecode_result = conn.execute(text(explain_sql), params)
                bytecode_rows = [tuple(row) for row in bytecode_result.fetchall()]
            finally:
                conn.close()

            plan_tree = parse_explain_query_plan(plan_rows)
            bytecode = parse_explain_bytecode(bytecode_rows)

            return {
                'queryPlan': plan_tree,
                'bytecode': bytecode,
                'sql': sql,
                'params': params,
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
