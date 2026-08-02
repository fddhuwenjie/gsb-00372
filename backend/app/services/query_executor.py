import time
import sqlite3

from app.database import db
from app.services.sql_generator import SQLGenerator
from app.services.sql_guard import (
    validate_read_only_sql,
    read_only_authorizer,
    UnsafeQueryError,
)
from app.services.utils import parse_explain_query_plan, parse_explain_bytecode
from app.services.plan_analysis_service import PlanAnalysisService, summarize_param_types
from app.models import QueryHistory, ExecutionPlanRecord

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_MAX_ROWS = 1000
# Progress handler is invoked every N virtual-machine instructions; small
# enough to react quickly to timeout/cancel without dominating runtime.
PROGRESS_INSTRUCTIONS = 1000


class QueryTimeoutError(Exception):
    pass


class QueryCancelledError(Exception):
    pass


class QueryExecutor:
    @staticmethod
    def generate_sql(query_structure):
        generator = SQLGenerator(query_structure)
        sql = generator.generate()
        params = generator.get_params()
        # The generated SQL must itself pass the read-only guard: this is the
        # single source of truth that the builder never emits anything unsafe.
        validate_read_only_sql(sql)
        return {'sql': sql, 'params': params}

    # ---- low level read-only execution against an isolated connection ----
    @staticmethod
    def _db_path():
        url = db.engine.url
        if url.get_backend_name() != 'sqlite':
            raise RuntimeError('Read-only execution requires a SQLite backend')
        database = url.database
        if not database or database == ':memory:':
            # Shared in-memory or default: fall back to the engine's raw path.
            return database or ':memory:'
        return database

    @staticmethod
    def _open_readonly_connection():
        path = QueryExecutor._db_path()
        if path == ':memory:':
            raise RuntimeError('Cannot open a read-only view of an in-memory database')
        uri = f'file:{path}?mode=ro'
        conn = sqlite3.connect(uri, uri=True, timeout=1)
        conn.set_authorizer(read_only_authorizer)
        return conn

    @staticmethod
    def _run_readonly(sql, params, timeout_ms, max_rows, cancel_event):
        validate_read_only_sql(sql)
        conn = QueryExecutor._open_readonly_connection()
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        state = {'timed_out': False, 'cancelled': False}

        def progress():
            if cancel_event is not None and cancel_event.is_set():
                state['cancelled'] = True
                return 1
            if time.monotonic() > deadline:
                state['timed_out'] = True
                return 1
            return 0

        conn.set_progress_handler(progress, PROGRESS_INSTRUCTIONS)
        try:
            cur = conn.execute(sql, params or {})
            rows = cur.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]
            column_names = [d[0] for d in cur.description] if cur.description else []
            return {
                'rows': [list(r) for r in rows],
                'columns': column_names,
                'truncated': truncated,
            }
        except sqlite3.OperationalError as e:
            if state['cancelled']:
                raise QueryCancelledError('Query was cancelled')
            if state['timed_out']:
                raise QueryTimeoutError(f'Query exceeded timeout of {timeout_ms} ms')
            raise
        except sqlite3.DatabaseError as e:
            if state['cancelled']:
                raise QueryCancelledError('Query was cancelled')
            if state['timed_out']:
                raise QueryTimeoutError(f'Query exceeded timeout of {timeout_ms} ms')
            # Authorizer denials surface as "not authorized".
            raise UnsafeQueryError(str(e))
        finally:
            conn.set_progress_handler(None, 0)
            conn.close()

    @staticmethod
    def execute(query_structure, user_session=None, timeout_ms=DEFAULT_TIMEOUT_MS,
                max_rows=DEFAULT_MAX_ROWS, cancel_event=None):
        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']

        start_time = time.time()
        run = QueryExecutor._run_readonly(sql, params, timeout_ms, max_rows, cancel_event)
        execution_time = (time.time() - start_time) * 1000

        rows = run['rows']
        column_names = run['columns']
        columns = [
            {'name': name, 'type': QueryExecutor._infer_type_from_data(rows, idx)}
            for idx, name in enumerate(column_names)
        ]

        if user_session:
            history = QueryHistory(
                user_session=user_session,
                query_structure=query_structure,
                sql=sql,
                params=params,
                duration=round(execution_time, 2),
                row_count=len(rows),
            )
            db.session.add(history)
            db.session.commit()
            QueryHistory.prune_old_records(user_session)

        return {
            'columns': columns,
            'rows': rows,
            'executionTime': round(execution_time, 2),
            'rowCount': len(rows),
            'truncated': run['truncated'],
            'sql': sql,
            'params': params,
        }

    @staticmethod
    def explain(query_structure, timeout_ms=DEFAULT_TIMEOUT_MS, cancel_event=None):
        # Explain runs on the very same AST/params as execute and chart.
        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']

        plan = QueryExecutor._run_readonly(
            f'EXPLAIN QUERY PLAN {sql}', params, timeout_ms, 10000, cancel_event
        )
        bytecode = QueryExecutor._run_readonly(
            f'EXPLAIN {sql}', params, timeout_ms, 100000, cancel_event
        )

        plan_rows = [tuple(r) for r in plan['rows']]
        bytecode_rows = [tuple(r) for r in bytecode['rows']]

        return {
            'queryPlan': parse_explain_query_plan(plan_rows),
            'bytecode': parse_explain_bytecode(bytecode_rows),
            'sql': sql,
            'rawPlanRows': plan_rows,
            'rawBytecodeRows': bytecode_rows,
        }

    @staticmethod
    def capture_plan_record(query_structure, template_id=None, template_version=None,
                            timeout_ms=DEFAULT_TIMEOUT_MS, max_rows=DEFAULT_MAX_ROWS,
                            cancel_event=None, persist=True):
        """Execute a query while capturing everything needed for plan
        comparison: AST hash, parameter *type* summary (no raw values),
        normalized SQLite plan, duration and row count. Returns the (optionally
        persisted) ExecutionPlanRecord as a dict."""
        gen = QueryExecutor.generate_sql(query_structure)
        sql, params = gen['sql'], gen['params']

        # Normalized plan from EXPLAIN QUERY PLAN (structural; bound params only
        # influence the plan shape, their values are never stored).
        plan = QueryExecutor._run_readonly(
            f'EXPLAIN QUERY PLAN {sql}', params, timeout_ms, 10000, cancel_event
        )
        raw_plan_rows = [list(r) for r in plan['rows']]
        normalized = PlanAnalysisService.normalize_plan(raw_plan_rows, query_structure)

        # Timed execution for cost (row count + duration).
        start = time.time()
        run = QueryExecutor._run_readonly(sql, params, timeout_ms, max_rows, cancel_event)
        duration_ms = round((time.time() - start) * 1000, 2)

        canonical = PlanAnalysisService.canonicalize_ast(query_structure)
        record = ExecutionPlanRecord(
            template_id=template_id,
            template_version=template_version,
            ast_hash=PlanAnalysisService.ast_hash(query_structure),
            canonical_ast=canonical,
            param_type_summary=summarize_param_types(params),
            normalized_plan=normalized,
            raw_plan=raw_plan_rows,
            duration_ms=duration_ms,
            row_count=len(run['rows']),
        )
        if persist:
            db.session.add(record)
            db.session.commit()
        return record.to_dict()

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
