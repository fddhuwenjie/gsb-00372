import time
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.database import db
from app.models import QueryHistory
from app.services.security_service import SecurityService
from app.services.sql_generator import SQLGenerator
from app.services.plan_service import (
    build_plan_fingerprint,
    hash_ast,
    parameter_type_summary,
    parse_plan_rows,
    summarize_result_stats,
    table_instances_from_ast,
)
from app.services.utils import (
    parse_explain_bytecode,
    parse_explain_query_plan,
)


class QueryCancelled(Exception):
    pass


class QueryExecutor:
    """
    Executes visual-builder ASTs.

    A single compilation path is used for result tables, charts and EXPLAIN
    output so that all three always run the exact same SQL and bound
    parameters.
    """

    @staticmethod
    def compile(query_structure):
        """Validate the AST and produce (sql, params)."""
        generator = SQLGenerator(query_structure)
        sql = generator.generate()
        params = generator.get_params()
        SecurityService.audit_sql_text(sql)
        return sql, params

    @staticmethod
    def generate_sql(query_structure):
        sql, params = QueryExecutor.compile(query_structure)
        return {'sql': sql, 'params': params}

    @staticmethod
    def execute(query_structure, user_session=None, max_rows=None, timeout=None,
                template_id=None, template_version=None, record=True):
        sql, params = QueryExecutor.compile(query_structure)
        return QueryExecutor._run(
            sql,
            params,
            query_structure=query_structure,
            user_session=user_session,
            max_rows=max_rows,
            timeout=timeout,
            template_id=template_id,
            template_version=template_version,
            record=record,
        )

    @staticmethod
    def explain(query_structure):
        sql, params = QueryExecutor.compile(query_structure)

        plan_sql = f'EXPLAIN QUERY PLAN\n{sql}'
        bytecode_sql = f'EXPLAIN\n{sql}'
        SecurityService.audit_sql_text(plan_sql)

        with QueryExecutor._read_only_connection(timeout=SecurityService.QUERY_TIMEOUT_SECONDS) as conn:
            plan_rows = [tuple(r) for r in conn.execute(text(plan_sql), params).fetchall()]
            bytecode_rows = [tuple(r) for r in conn.execute(text(bytecode_sql), params).fetchall()]

        return {
            'queryPlan': parse_explain_query_plan(plan_rows),
            'bytecode': parse_explain_bytecode(bytecode_rows),
            'sql': sql,
            'params': params,
            'rawPlanRows': plan_rows,
            'rawBytecodeRows': bytecode_rows,
        }

    @staticmethod
    def execute_template(template_definition, values, user_session=None,
                         timeout=None, record=True, max_rows=None):
        """
        Instantiate and execute a template, returning a result that also
        carries the execution record id. This is the single entry point
        used by both the single-template API and the batch runner so that
        plan capture, read-only enforcement and recording stay consistent.
        """
        from app.services.template_service import TemplateService
        compiled = TemplateService.instantiate(template_definition, values)
        return QueryExecutor._run(
            compiled['sql'],
            compiled['params'],
            query_structure=compiled['queryStructure'],
            user_session=user_session,
            timeout=timeout,
            max_rows=max_rows,
            record=record,
            resolved_parameters=compiled.get('resolvedParameters'),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    @contextmanager
    def _read_only_connection(timeout=None):
        """
        Context-managed connection configured as read-only for SQLite.

        Uses a *separate* engine with :class:`NullPool` so that the
        ``PRAGMA query_only = ON`` setting -- which persists at the
        DBAPI-connection level -- can never leak back into the main
        connection pool and break ORM writes (history, saved queries,
        templates). The connection is closed (not pooled) on exit.
        """
        engine = db.engine
        timeout = timeout or SecurityService.QUERY_TIMEOUT_SECONDS
        is_sqlite = engine.dialect.name == 'sqlite'

        if is_sqlite:
            ro_engine = create_engine(
                engine.url,
                poolclass=NullPool,
                connect_args={'timeout': timeout},
            )
            conn = ro_engine.connect()
            try:
                conn.execution_options(isolation_level='AUTOCOMMIT')
                conn.execute(text('PRAGMA query_only = ON'))
                conn.execute(text(f'PRAGMA busy_timeout = {int(timeout * 1000)}'))
                yield conn
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                ro_engine.dispose()
        else:
            conn = engine.connect()
            try:
                yield conn
            finally:
                conn.close()

    @staticmethod
    def _run(sql, params, query_structure=None, user_session=None,
             max_rows=None, timeout=None, template_id=None,
             template_version=None, record=True, resolved_parameters=None):
        max_rows = max_rows or SecurityService.MAX_ROWS
        timeout = timeout or SecurityService.QUERY_TIMEOUT_SECONDS
        start_time = time.time()
        deadline = start_time + timeout

        # Capture the EXPLAIN QUERY PLAN in the same read-only session so
        # the plan and result come from one consistent compilation. The
        # plan is captured even when we don't persist an execution record
        # because the API response includes it for display.
        plan_nodes = []
        plan_raw = []
        plan_fingerprint = None
        with QueryExecutor._read_only_connection(timeout=timeout) as conn:
            try:
                if query_structure is not None:
                    plan_sql = f'EXPLAIN QUERY PLAN\n{sql}'
                    plan_raw = [
                        tuple(r)
                        for r in conn.execute(text(plan_sql), params).fetchall()
                    ]
                    plan_nodes = parse_plan_rows(plan_raw)
                    instances = table_instances_from_ast(query_structure)
                    plan_fingerprint = build_plan_fingerprint(
                        plan_nodes, instances
                    )

                result = conn.execute(text(sql), params)
                cursor = result.cursor
                if cursor is not None and hasattr(cursor, 'connection'):
                    raw_conn = cursor.connection
                    if hasattr(raw_conn, 'set_progress_handler'):
                        def progress_handler():
                            if time.time() > deadline:
                                return 1
                            return 0
                        raw_conn.set_progress_handler(progress_handler, 1000)

                rows = []
                while True:
                    batch = result.fetchmany(500)
                    if not batch:
                        break
                    for row in batch:
                        rows.append(list(row))
                        if len(rows) >= max_rows:
                            break
                    if len(rows) >= max_rows:
                        break
                    if time.time() > deadline:
                        raise TimeoutError(
                            f'Query exceeded timeout of {timeout} seconds'
                        )

                column_names = list(result.keys())
            except SQLAlchemyError as exc:
                message = str(getattr(exc, 'orig', exc))
                if 'interrupted' in message.lower():
                    raise TimeoutError(
                        f'Query exceeded timeout of {timeout} seconds'
                    ) from exc
                raise

        columns = []
        for idx, col_name in enumerate(column_names):
            columns.append({
                'name': col_name,
                'type': QueryExecutor._infer_type_from_data(rows, idx),
            })

        execution_time = (time.time() - start_time) * 1000

        if user_session and query_structure is not None:
            try:
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
            except Exception:
                db.session.rollback()

        # Persist a non-sensitive execution record (no parameter values).
        execution_record = None
        if record and query_structure is not None:
            execution_record = QueryExecutor._record_execution(
                query_structure=query_structure,
                params=resolved_parameters if resolved_parameters is not None else params,
                plan_nodes=plan_nodes,
                plan_fingerprint=plan_fingerprint,
                duration_ms=execution_time,
                rows=rows,
                template_id=template_id,
                template_version=template_version,
                user_session=user_session,
                sql=sql,
            )

        return {
            'columns': columns,
            'rows': rows,
            'executionTime': round(execution_time, 2),
            'rowCount': len(rows),
            'sql': sql,
            'params': params,
            'truncated': len(rows) >= max_rows,
            'planNodes': plan_nodes,
            'planFingerprint': plan_fingerprint,
            'astHash': hash_ast(query_structure),
            'executionId': execution_record.id if execution_record else None,
        }

    @staticmethod
    def _record_execution(query_structure, params, plan_nodes,
                          plan_fingerprint, duration_ms, rows,
                          template_id, template_version, user_session, sql):
        from app.models import QueryExecution
        try:
            record = QueryExecution(
                user_session=user_session,
                ast_hash=hash_ast(query_structure),
                ast_structure=query_structure,
                param_type_summary=parameter_type_summary(params),
                plan_fingerprint=plan_fingerprint,
                plan_nodes=plan_nodes,
                duration_ms=round(duration_ms, 2),
                row_count=len(rows),
                column_count=len(rows[0]) if rows else 0,
                template_id=template_id,
                template_version=template_version,
                sql_text=sql,
            )
            db.session.add(record)
            db.session.commit()
            return record
        except Exception:
            db.session.rollback()
            return None

    @staticmethod
    def _infer_type_from_data(rows, col_idx):
        for row in rows[:20]:
            val = row[col_idx] if col_idx < len(row) else None
            if val is None:
                continue
            if isinstance(val, bool):
                return 'BOOLEAN'
            if isinstance(val, int):
                return 'INTEGER'
            if isinstance(val, float):
                return 'NUMERIC'
            return 'STRING'
        return 'UNKNOWN'
