import threading
import time
from flask import current_app
from sqlalchemy import text
from app.database import db
from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService
from app.services.utils import parse_explain_query_plan, parse_explain_bytecode
from app.services.plan_service import ast_hash, params_summary, normalize_explain_plan
from app.models import QueryHistory, ExecutionSnapshot


class QueryCancelled(Exception):
    """Raised when a running query is cancelled via the cancel registry."""


class QueryTimeout(Exception):
    """Raised when a running query exceeds the configured timeout."""


class QueryExecutor:
    DEFAULT_TIMEOUT_MS = 5000
    DEFAULT_MAX_ROWS = 1000

    # session id -> threading.Event; setting the event cancels the query
    # that is currently running for that session.
    _cancel_events = {}
    _cancel_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Cancellation registry
    # ------------------------------------------------------------------
    @classmethod
    def request_cancel(cls, session_id):
        with cls._cancel_lock:
            event = cls._cancel_events.get(session_id)
            if event is None:
                event = threading.Event()
                cls._cancel_events[session_id] = event
            event.set()

    @classmethod
    def clear_cancel(cls, session_id):
        """Remove any pending cancellation for a key (e.g. before a retry
        reuses the same cancel key)."""
        with cls._cancel_lock:
            cls._cancel_events.pop(session_id, None)

    @classmethod
    def _take_cancel_event(cls, session_id):
        with cls._cancel_lock:
            event = cls._cancel_events.get(session_id)
            if event is None:
                event = threading.Event()
                cls._cancel_events[session_id] = event
            return event

    @classmethod
    def _release_cancel_event(cls, session_id, event):
        with cls._cancel_lock:
            if cls._cancel_events.get(session_id) is event:
                del cls._cancel_events[session_id]

    # ------------------------------------------------------------------
    # SQL generation (single source of truth)
    # ------------------------------------------------------------------
    @staticmethod
    def generate_sql(query_structure):
        generator = SQLGenerator(query_structure)
        sql = generator.generate()
        params = generator.get_params()
        return {'sql': sql, 'params': params}

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    @staticmethod
    def _alias_map(query_structure):
        """alias -> base table name, for plan normalization."""
        mapping = {}
        for table in (query_structure or {}).get('tables') or []:
            if table.get('alias'):
                mapping[table['alias']] = table['tableName']
            mapping[table['tableName']] = table['tableName']
        return mapping

    @staticmethod
    def compute_normalized_plan(sql, params, query_structure):
        """Normalized EXPLAIN QUERY PLAN for an already-generated query."""
        with db.engine.connect() as connection:
            plan_result = connection.execute(text(f'EXPLAIN QUERY PLAN {sql}'), params)
            plan_rows = [tuple(row) for row in plan_result.fetchall()]
        return normalize_explain_plan(plan_rows, QueryExecutor._alias_map(query_structure))

    @staticmethod
    def _record_snapshot(query_structure, sql, params, execution_time,
                         row_count, template_id, template_version):
        """Best-effort audit snapshot. Stores the AST hash, a parameter
        *type* summary (never raw values) and the normalized EXPLAIN plan.
        Runs after the query connection is closed so the audit write never
        blocks on a read lock."""
        snapshot = ExecutionSnapshot(
            template_id=template_id,
            template_version=template_version,
            ast_hash=ast_hash(query_structure),
            params_summary=params_summary(params),
            plan_json=QueryExecutor.compute_normalized_plan(sql, params, query_structure),
            duration_ms=round(execution_time, 2),
            row_count=row_count,
        )
        db.session.add(snapshot)
        db.session.commit()

    @staticmethod
    def execute(query_structure, user_session=None, template_id=None,
                template_version=None, record_snapshot=True,
                cancel_key=None, timeout_ms=None):
        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']

        # Defense in depth: only a single read-only statement may execute.
        SecurityService.validate_read_only_sql(sql)

        if timeout_ms is None:
            timeout_ms = current_app.config.get('QUERY_TIMEOUT_MS', QueryExecutor.DEFAULT_TIMEOUT_MS)
        max_rows = current_app.config.get('MAX_ROWS', QueryExecutor.DEFAULT_MAX_ROWS)

        start_time = time.time()
        # monotonic clock for the timeout so wall-clock changes don't matter
        deadline_monotonic = time.monotonic() + timeout_ms / 1000.0

        cancel_id = cancel_key or user_session
        cancel_event = (
            QueryExecutor._take_cancel_event(cancel_id)
            if cancel_id else threading.Event()
        )

        interrupted = {'cancelled': False, 'timeout': False}

        def guarded_progress_handler():
            if cancel_event.is_set():
                interrupted['cancelled'] = True
                return 1
            if time.monotonic() > deadline_monotonic:
                interrupted['timeout'] = True
                return 1
            return 0

        # Pre-execution check so even trivially fast queries honor an
        # already-requested cancellation or an expired deadline.
        if cancel_event.is_set():
            if cancel_id:
                QueryExecutor._release_cancel_event(cancel_id, cancel_event)
            raise QueryCancelled('Query was cancelled')
        if time.monotonic() > deadline_monotonic:
            if cancel_id:
                QueryExecutor._release_cancel_event(cancel_id, cancel_event)
            raise QueryTimeout(f'Query exceeded timeout of {timeout_ms} ms')

        try:
            with db.engine.connect() as connection:
                raw_connection = connection.connection.driver_connection
                # 100k VM-step interval: sub-millisecond cancellation on
                # huge scans without flooding the GIL with callbacks
                raw_connection.set_progress_handler(guarded_progress_handler, 100000)
                try:
                    query_result = connection.execute(text(sql), params)
                    # Fetch one extra row to detect truncation.
                    raw_rows = query_result.fetchmany(max_rows + 1)
                    column_names = list(query_result.keys())
                    # Close explicitly: an unexhausted cursor keeps the read
                    # statement (and its shared lock) alive on the connection.
                    query_result.close()
                finally:
                    raw_connection.set_progress_handler(None, 0)
        except Exception as e:
            if interrupted['cancelled']:
                raise QueryCancelled('Query was cancelled') from e
            if interrupted['timeout']:
                raise QueryTimeout(f'Query exceeded timeout of {timeout_ms} ms') from e
            raise
        finally:
            if cancel_id:
                QueryExecutor._release_cancel_event(cancel_id, cancel_event)

        truncated = len(raw_rows) > max_rows
        rows = [list(row) for row in raw_rows[:max_rows]]

        execution_time = (time.time() - start_time) * 1000

        if record_snapshot:
            try:
                QueryExecutor._record_snapshot(
                    query_structure, sql, params, execution_time, len(rows),
                    template_id, template_version)
            except Exception:
                # audit is best-effort and must never break the query
                db.session.rollback()

        columns = []
        for idx, col_name in enumerate(column_names):
            type_name = QueryExecutor._infer_type_from_data(rows, idx)
            columns.append({
                'name': col_name,
                'type': type_name
            })

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
            'truncated': truncated,
            'sql': sql,
            'params': params
        }

    @staticmethod
    def explain(query_structure):
        # EXPLAIN runs the exact same AST and parameter set as execution.
        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']

        SecurityService.validate_read_only_sql(sql)

        with db.engine.connect() as connection:
            plan_result = connection.execute(text(f'EXPLAIN QUERY PLAN {sql}'), params)
            plan_rows = [tuple(row) for row in plan_result.fetchall()]

            bytecode_result = connection.execute(text(f'EXPLAIN {sql}'), params)
            bytecode_rows = [tuple(row) for row in bytecode_result.fetchall()]

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
