"""
Cancellable batch parameter execution for query templates.

Design:
- A BatchRun references one immutable template version and multiple parameter sets.
- Concurrency is controlled by a ThreadPoolExecutor with max_workers = concurrency.
- Cancellation uses a threading.Event; once set, no new items start and pending
  items are marked 'cancelled'. Running items are allowed to finish but their
  results are discarded if cancellation was requested during execution.
- Each item is validated and executed independently: a security violation in
  one item marks only that item as 'rejected' and never pollutes others.
- Total row count and total duration are enforced as soft limits; once exceeded,
  remaining pending items are cancelled.
- Idempotency key prevents duplicate submission of the same batch.
- Retry creates a new BatchRun that only re-runs failed/rejected items from
  a previous run, preserving the original template version and order.
- Result ordering is always stable by item_index regardless of completion order.
"""
import threading
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime

from sqlalchemy import text as sa_text, create_engine

from app.database import db
from app.models import (
    BatchRun, BatchItem, QueryTemplate, PlanSnapshot,
    BATCH_RUN_STATUSES, BATCH_ITEM_STATUSES,
)
from app.services.template_service import TemplateService, TemplateValidationError
from app.services.sql_generator import SQLGenerator
from app.services.security_service import SecurityService
from app.services.plan_service import create_snapshot


class BatchService:

    # In-memory registry of active cancellation events and runs.
    # Keyed by batch_run_id. This allows cancel API to signal running batches.
    _active_runs: dict = {}
    _registry_lock = threading.Lock()

    DEFAULT_CONCURRENCY = 1
    DEFAULT_MAX_TOTAL_ROWS = 10000
    DEFAULT_MAX_DURATION_MS = 60000

    # ------------------------------------------------------------------
    # Create / submit
    # ------------------------------------------------------------------

    @staticmethod
    def create_batch(template_id, parameter_sets, concurrency=None,
                     max_total_rows=None, max_duration_ms=None,
                     idempotency_key=None, label=None, app=None):
        """
        Create and optionally start a batch run.

        Args:
            template_id: ID of the QueryTemplate to execute.
            parameter_sets: List of {param_name: value} dicts.
            concurrency: Max parallel workers (default 1).
            max_total_rows: Soft limit on total result rows.
            max_duration_ms: Soft limit on total wall-clock time.
            idempotency_key: If provided, duplicate keys return existing run.
            app: Flask app instance (needed for thread-local contexts).
        """
        if not parameter_sets or not isinstance(parameter_sets, list):
            raise ValueError('parameter_sets must be a non-empty list')

        if concurrency is None:
            concurrency = BatchService.DEFAULT_CONCURRENCY
        if concurrency < 1:
            raise ValueError('concurrency must be >= 1')
        if max_total_rows is None:
            max_total_rows = BatchService.DEFAULT_MAX_TOTAL_ROWS
        if max_duration_ms is None:
            max_duration_ms = BatchService.DEFAULT_MAX_DURATION_MS

        if idempotency_key:
            existing = BatchRun.query.filter_by(idempotency_key=idempotency_key).first()
            if existing:
                return existing, False

        tpl = QueryTemplate.query.get_or_404(template_id)
        template_dict = tpl.to_dict()

        if not idempotency_key:
            idempotency_key = BatchService._compute_idempotency_key(
                template_id, tpl.version, parameter_sets
            )
            existing = BatchRun.query.filter_by(idempotency_key=idempotency_key).first()
            if existing:
                return existing, False

        batch = BatchRun(
            template_id=template_id,
            template_version=tpl.version,
            idempotency_key=idempotency_key,
            status='pending',
            concurrency=concurrency,
            max_total_rows=max_total_rows,
            max_duration_ms=max_duration_ms,
            total_items=len(parameter_sets),
            label=label,
        )
        db.session.add(batch)
        db.session.flush()

        param_type_summary = {
            p['name']: p['type'] for p in template_dict.get('parameters', [])
        }

        for idx, param_values in enumerate(parameter_sets):
            if not isinstance(param_values, dict):
                db.session.rollback()
                raise ValueError(f'parameter_sets[{idx}] must be an object')
            item = BatchItem(
                batch_run_id=batch.id,
                item_index=idx,
                parameter_values=deepcopy(param_values),
                param_type_summary=deepcopy(param_type_summary),
                status='pending',
            )
            db.session.add(item)

        db.session.commit()
        return batch, True

    @staticmethod
    def _compute_idempotency_key(template_id, template_version, parameter_sets):
        """Deterministic hash of template identity + all parameter sets."""
        import json
        canonical = json.dumps(
            {'tpl': template_id, 'ver': template_version,
             'params': parameter_sets},
            sort_keys=True, separators=(',', ':')
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @staticmethod
    def start_batch(batch_id, app=None):
        """Begin executing a pending batch. Returns the BatchRun."""
        batch = BatchRun.query.get_or_404(batch_id)
        if batch.status not in ('pending',):
            return batch

        batch.status = 'running'
        batch.started_at = datetime.utcnow()
        db.session.commit()

        cancel_event = threading.Event()
        state_lock = threading.Lock()
        shared_state = {
            'total_rows': 0,
            'total_duration_ms': 0.0,
            'succeeded': 0,
            'failed': 0,
            'cancelled': 0,
            'rejected': 0,
            'start_time': time.time(),
            'limit_reached': False,
        }

        with BatchService._registry_lock:
            BatchService._active_runs[batch.id] = cancel_event

        try:
            BatchService._execute(batch, cancel_event, state_lock, shared_state, app)
        finally:
            with BatchService._registry_lock:
                BatchService._active_runs.pop(batch.id, None)

        return batch

    @staticmethod
    def _execute(batch, cancel_event, state_lock, shared_state, app):
        items = BatchItem.query.filter_by(
            batch_run_id=batch.id, status='pending'
        ).order_by(BatchItem.item_index).all()

        tpl = QueryTemplate.query.get(batch.template_id)
        template_dict = tpl.to_dict()

        db_uri = app.config['SQLALCHEMY_DATABASE_URI'] if app else None
        engine = create_engine(db_uri) if db_uri else db.engine

        max_workers = min(batch.concurrency, len(items))

        def _worker(*args):
            """Worker wrapper that pushes a Flask app context."""
            with app.app_context():
                return BatchService._run_single_item(*args)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item = {}
            for item in items:
                if cancel_event.is_set() or shared_state['limit_reached']:
                    BatchService._mark_item_cancelled(item.id)
                    with state_lock:
                        shared_state['cancelled'] += 1
                    continue

                future = executor.submit(
                    _worker,
                    item.id,
                    template_dict,
                    item.parameter_values,
                    item.item_index,
                    engine,
                    cancel_event,
                    state_lock,
                    shared_state,
                    batch.max_total_rows,
                    batch.max_duration_ms,
                )
                future_to_item[future] = item

            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    result = future.result()
                    BatchService._persist_item_result(item.id, result)
                except Exception as e:
                    BatchService._persist_item_error(item.id, str(e))

        db.session.expire_all()
        batch = BatchRun.query.get(batch.id)
        BatchService._finalize_batch(batch, shared_state)

    @staticmethod
    def _run_single_item(item_id, template_dict, param_values, item_index,
                         engine, cancel_event, state_lock, shared_state,
                         max_total_rows, max_duration_ms):
        """Execute one parameter set. Runs in a worker thread. Returns a result dict."""
        if cancel_event.is_set():
            return {'status': 'cancelled', 'item_index': item_index}

        elapsed = (time.time() - shared_state['start_time']) * 1000
        if elapsed > max_duration_ms:
            with state_lock:
                shared_state['limit_reached'] = True
            return {'status': 'cancelled', 'item_index': item_index,
                    'error': 'Batch duration limit exceeded'}

        with state_lock:
            if shared_state['total_rows'] >= max_total_rows:
                shared_state['limit_reached'] = True
                return {'status': 'cancelled', 'item_index': item_index,
                        'error': 'Total row limit exceeded'}

        start = time.time()
        try:
            concrete = TemplateService.instantiate(template_dict, param_values)
        except TemplateValidationError as e:
            duration = (time.time() - start) * 1000
            return {
                'status': 'rejected',
                'item_index': item_index,
                'error': str(e),
                'duration_ms': duration,
                'attempt_count': 1,
            }
        except Exception as e:
            duration = (time.time() - start) * 1000
            return {
                'status': 'failed',
                'item_index': item_index,
                'error': f'Instantiation error: {e}',
                'duration_ms': duration,
                'attempt_count': 1,
            }

        if cancel_event.is_set():
            return {'status': 'cancelled', 'item_index': item_index}

        try:
            SecurityService.validate_query_structure(concrete)
            gen = SQLGenerator(concrete)
            sql = gen.generate()
            params = gen.get_params()
            SecurityService.validate_readonly_sql(sql)
        except Exception as e:
            duration = (time.time() - start) * 1000
            return {
                'status': 'rejected',
                'item_index': item_index,
                'error': f'Security violation: {e}',
                'duration_ms': duration,
                'attempt_count': 1,
            }

        if cancel_event.is_set():
            return {'status': 'cancelled', 'item_index': item_index}

        conn = engine.connect()
        try:
            plan_rows = conn.execute(
                sa_text(f'EXPLAIN QUERY PLAN {sql}'), params
            ).fetchall()
            raw_plan = [tuple(r) for r in plan_rows]

            result = conn.execute(sa_text(sql), params)
            raw_rows = result.fetchmany(max_total_rows + 1)
            rows = [list(r) for r in raw_rows]
            col_names = list(result.keys())
        except Exception as e:
            duration = (time.time() - start) * 1000
            return {
                'status': 'failed',
                'item_index': item_index,
                'error': f'Execution error: {e}',
                'duration_ms': duration,
                'attempt_count': 1,
            }
        finally:
            conn.close()

        duration = (time.time() - start) * 1000

        cancelled_during = cancel_event.is_set()

        plan_snap = None
        if not cancelled_during:
            try:
                snap_data = create_snapshot(
                    query_structure=concrete,
                    raw_plan_rows=raw_plan,
                    row_count=len(rows),
                    duration_ms=duration,
                    parameters=template_dict.get('parameters'),
                    template_id=template_dict.get('id'),
                    template_version=template_dict.get('version'),
                )
                plan_snap = snap_data
            except Exception:
                plan_snap = None

        if cancelled_during:
            return {'status': 'cancelled', 'item_index': item_index}

        with state_lock:
            shared_state['total_rows'] += len(rows)
            shared_state['total_duration_ms'] += duration
            if shared_state['total_rows'] >= max_total_rows:
                shared_state['limit_reached'] = True

        columns = [{'name': c, 'type': 'UNKNOWN'} for c in col_names]
        for i, _ in enumerate(col_names):
            for row in rows[:10]:
                val = row[i] if i < len(row) else None
                if val is not None:
                    if isinstance(val, bool):
                        columns[i]['type'] = 'BOOLEAN'
                    elif isinstance(val, int):
                        columns[i]['type'] = 'INTEGER'
                    elif isinstance(val, float):
                        columns[i]['type'] = 'NUMERIC'
                    else:
                        columns[i]['type'] = 'STRING'
                    break

        return {
            'status': 'succeeded',
            'item_index': item_index,
            'columns': columns,
            'rows': rows,
            'row_count': len(rows),
            'duration_ms': duration,
            'attempt_count': 1,
            'plan_snapshot': plan_snap,
        }

    # ------------------------------------------------------------------
    # Persistence (called from main thread after futures complete)
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_item_cancelled(item_id):
        item = BatchItem.query.get(item_id)
        if item and item.status == 'pending':
            item.status = 'cancelled'
            item.completed_at = datetime.utcnow()
            db.session.commit()

    @staticmethod
    def _persist_item_result(item_id, result):
        item = BatchItem.query.get(item_id)
        if not item:
            return
        status = result.get('status', 'failed')
        item.status = status
        item.attempt_count = result.get('attempt_count', 1)
        item.duration_ms = result.get('duration_ms', 0)
        item.started_at = item.started_at or datetime.utcnow()
        item.completed_at = datetime.utcnow()

        if status == 'succeeded':
            item.result_columns = result.get('columns')
            item.result_rows = result.get('rows')
            item.row_count = result.get('row_count', 0)
            plan_snap = result.get('plan_snapshot')
            if plan_snap:
                snap = PlanSnapshot(**plan_snap)
                db.session.add(snap)
                db.session.flush()
                item.plan_snapshot_id = snap.id
        elif status in ('failed', 'rejected'):
            item.error = result.get('error')
        elif status == 'cancelled':
            item.error = result.get('error', 'Cancelled')

        db.session.commit()

    @staticmethod
    def _persist_item_error(item_id, error_msg):
        item = BatchItem.query.get(item_id)
        if not item:
            return
        item.status = 'failed'
        item.error = f'Worker error: {error_msg}'
        item.completed_at = datetime.utcnow()
        item.attempt_count = 1
        db.session.commit()

    @staticmethod
    def _finalize_batch(batch, shared_state):
        items = BatchItem.query.filter_by(batch_run_id=batch.id).all()
        succeeded = sum(1 for i in items if i.status == 'succeeded')
        failed = sum(1 for i in items if i.status == 'failed')
        cancelled = sum(1 for i in items if i.status == 'cancelled')
        rejected = sum(1 for i in items if i.status == 'rejected')
        total_rows = sum(i.row_count or 0 for i in items)
        total_duration = sum(i.duration_ms or 0 for i in items)

        batch.succeeded_count = succeeded
        batch.failed_count = failed
        batch.cancelled_count = cancelled
        batch.rejected_count = rejected
        batch.total_rows = total_rows
        batch.total_duration_ms = total_duration
        batch.completed_at = datetime.utcnow()

        if cancelled > 0 and (failed == 0 and rejected == 0):
            batch.status = 'cancelled'
        elif failed > 0 or rejected > 0:
            batch.status = 'partially_failed'
        elif cancelled > 0:
            batch.status = 'cancelled'
        else:
            batch.status = 'completed'

        db.session.commit()

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    @staticmethod
    def cancel_batch(batch_id):
        """Signal cancellation. Already-running items finish but are discarded."""
        batch = BatchRun.query.get_or_404(batch_id)
        if batch.status in ('completed', 'cancelled', 'partially_failed'):
            return batch

        with BatchService._registry_lock:
            event = BatchService._active_runs.get(batch_id)

        if event:
            event.set()

        if batch.status == 'running':
            pending = BatchItem.query.filter_by(
                batch_run_id=batch_id, status='pending'
            ).all()
            for item in pending:
                item.status = 'cancelled'
                item.completed_at = datetime.utcnow()
            batch.status = 'cancelled'
            batch.completed_at = datetime.utcnow()
            db.session.commit()

        return batch

    # ------------------------------------------------------------------
    # Retry
    # ------------------------------------------------------------------

    @staticmethod
    def retry_failed(original_batch_id, app=None):
        """Create a new batch run that only re-runs failed/rejected items."""
        original = BatchRun.query.get_or_404(original_batch_id)
        failed_items = BatchItem.query.filter(
            BatchItem.batch_run_id == original_batch_id,
            BatchItem.status.in_(['failed', 'rejected'])
        ).order_by(BatchItem.item_index).all()

        if not failed_items:
            raise ValueError('No failed or rejected items to retry')

        parameter_sets = [item.parameter_values for item in failed_items]

        new_batch, created = BatchService.create_batch(
            template_id=original.template_id,
            parameter_sets=parameter_sets,
            concurrency=original.concurrency,
            max_total_rows=original.max_total_rows,
            max_duration_ms=original.max_duration_ms,
            label=f'Retry of batch #{original_batch_id}',
            app=app,
        )

        if created:
            BatchService.start_batch(new_batch.id, app=app)

        return new_batch

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    @staticmethod
    def get_batch(batch_id, include_items=True):
        batch = BatchRun.query.get_or_404(batch_id)
        return batch

    @staticmethod
    def list_batches(template_id=None, limit=50):
        q = BatchRun.query
        if template_id:
            q = q.filter_by(template_id=template_id)
        return q.order_by(BatchRun.created_at.desc()).limit(limit).all()
