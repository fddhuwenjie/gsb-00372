"""Cancellable batch parameter runs.

One batch run binds one immutable template version to N parameter sets and
executes them with:
- a concurrency limit (worker pool sized by ``max_concurrency``),
- a total row budget (``max_total_rows`` across succeeded items),
- a total time budget (``max_total_time_ms`` for the whole run),
- per-item timeout (``item_timeout_ms`` or the app default),
- cooperative cancellation: after cancel, no further results are written
  (in-flight items are aborted through the progress handler; results that
  race in are discarded, never persisted).

Each item is isolated: a parameter value that breaks validation or the
read-only safety boundary fails that item alone. Retry re-runs only items
that did not succeed.

Threading model: one runner thread per batch (scheduler) plus a small
worker pool. Every worker pushes its own Flask app context, so each thread
gets an isolated SQLAlchemy session; a process-local write lock serializes
result commits (SQLite allows one writer at a time).
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime

from flask import current_app

from app.database import db
from app.models import BatchRun, BatchRunItem, QueryTemplate, TemplateVersion
from app.services.template_service import TemplateService, TemplateError
from app.services.metadata_service import MetadataService
from app.services.query_executor import (
    QueryExecutor, QueryCancelled, QueryTimeout,
)
from app.services.plan_service import params_summary, ast_hash

FINAL_BATCH_STATUSES = {'completed', 'cancelled', 'failed', 'interrupted'}
ITEM_FINAL_STATUSES = {'succeeded', 'failed', 'cancelled', 'skipped'}

# serializes item-result commits (SQLite single-writer)
_db_write_lock = threading.Lock()


class BatchService:
    # ------------------------------------------------------------------
    # Creation / retry / cancel
    # ------------------------------------------------------------------
    @staticmethod
    def create_batch(template, version, items_input, limits, idempotency_key=None):
        if idempotency_key:
            existing = BatchRun.query.filter_by(idempotency_key=idempotency_key).first()
            if existing:
                return existing, False

        if not items_input:
            raise TemplateError('Batch run requires at least one parameter set')
        if len(items_input) > 200:
            raise TemplateError('Batch run is limited to 200 parameter sets')

        # the version must resolve to an immutable archived row (or the
        # template's current state, which is itself archived on save)
        BatchService._load_version(template, version)

        for entry in items_input:
            if not isinstance(entry.get('values', {}), dict):
                raise TemplateError('Each batch item must provide a values object')

        batch = BatchRun(
            template_id=template.id,
            template_version=version,
            status='running',
            idempotency_key=idempotency_key,
            items_input=[{'values': e.get('values', {})} for e in items_input],
            total_items=len(items_input),
            max_concurrency=max(1, min(int(limits.get('max_concurrency', 2)), 8)),
            max_total_rows=max(1, int(limits.get('max_total_rows', 10000))),
            max_total_time_ms=max(100, int(limits.get('max_total_time_ms', 60000))),
            item_timeout_ms=limits.get('item_timeout_ms'),
            item_delay_ms=max(0, min(int(limits.get('item_delay_ms', 0) or 0), 60000)),
        )
        db.session.add(batch)
        db.session.flush()
        for seq in range(len(items_input)):
            db.session.add(BatchRunItem(batch_run_id=batch.id, seq=seq, status='pending'))
        db.session.commit()

        BatchService._start_runner(batch.id)
        return batch, True

    @staticmethod
    def retry(batch_id):
        batch = db.session.get(BatchRun, batch_id)
        if not batch:
            raise TemplateError(f'Batch run {batch_id} not found', status=404)
        if batch.status == 'running':
            raise TemplateError('Batch run is still running; cancel it first')

        # Only unsuccessful items are re-queued; succeeded results stay intact.
        for item in BatchRunItem.query.filter_by(batch_run_id=batch.id).all():
            if item.status != 'succeeded':
                item.status = 'pending'
                item.params_summary = None
                item.ast_hash = None
                item.sql = None
                item.plan_json = None
                item.row_count = None
                item.truncated = False
                item.duration_ms = None
                item.error = None
                item.error_code = None
                item.started_ts = None
                item.finished_ts = None
        batch.status = 'running'
        batch.stopped_reason = None
        batch.cancel_requested = False
        batch.finished_at = None
        batch.error = None
        db.session.commit()

        BatchService._start_runner(batch.id)
        return batch

    @staticmethod
    def cancel(batch_id):
        with _db_write_lock:
            batch = db.session.get(BatchRun, batch_id)
            if not batch:
                raise TemplateError(f'Batch run {batch_id} not found', status=404)
            db.session.refresh(batch)
            if batch.status in FINAL_BATCH_STATUSES:
                return batch
            batch.cancel_requested = True
            db.session.commit()
        # abort in-flight items cooperatively
        running = BatchRunItem.query.filter_by(batch_run_id=batch.id, status='running').all()
        for item in running:
            QueryExecutor.request_cancel(BatchService._cancel_key(batch.id, item.id))
        return batch

    @staticmethod
    def recover_interrupted():
        """Mark batches whose runner died with the process as interrupted.
        Called once at app startup; affected runs can be resumed via retry."""
        stale = BatchRun.query.filter_by(status='running').all()
        for batch in stale:
            batch.status = 'interrupted'
            batch.stopped_reason = 'interrupted'
            for item in BatchRunItem.query.filter_by(
                    batch_run_id=batch.id, status='running').all():
                item.status = 'pending'
                item.started_ts = None
        if stale:
            db.session.commit()
        return len(stale)

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------
    @staticmethod
    def _start_runner(batch_id):
        app = current_app._get_current_object()

        def runner():
            with app.app_context():
                try:
                    BatchService._run(app, batch_id)
                except Exception as e:  # noqa: BLE001 - engine must not die silently
                    with _db_write_lock:
                        try:
                            batch = db.session.get(BatchRun, batch_id)
                            if batch and batch.status == 'running':
                                batch.status = 'failed'
                                batch.error = str(e)
                                batch.finished_at = datetime.utcnow()
                                for item in BatchRunItem.query.filter_by(
                                        batch_run_id=batch_id).all():
                                    if item.status not in ITEM_FINAL_STATUSES:
                                        item.status = 'failed'
                                        item.error = str(e)
                                        item.error_code = 'engine_error'
                                db.session.commit()
                        except Exception:
                            db.session.rollback()

        thread = threading.Thread(target=runner, daemon=True,
                                  name=f'batch-run-{batch_id}')
        thread.start()
        return thread

    @staticmethod
    def _cancel_key(batch_id, item_id):
        return f'batch-{batch_id}-item-{item_id}'

    @staticmethod
    def _load_version(template, version):
        if version == template.version:
            return template.parameters or [], template.query_structure
        row = TemplateVersion.query.filter_by(
            template_id=template.id, version=version).first()
        if not row:
            raise TemplateError(f'Version {version} not found for template {template.id}',
                                status=404)
        return row.parameters or [], row.query_structure

    @staticmethod
    def _run(app, batch_id):
        batch = db.session.get(BatchRun, batch_id)
        template = db.session.get(QueryTemplate, batch.template_id)
        parameters, structure = BatchService._load_version(template, batch.template_version)

        # schema drift fails the whole batch before anything runs
        metadata = MetadataService.get_all_metadata()
        issues = TemplateService.validate_against_schema(parameters, structure, metadata)
        if issues:
            raise TemplateError('Template requires migration: schema references changed',
                                issues=issues)

        pending_rows = BatchRunItem.query.filter_by(
            batch_run_id=batch_id, status='pending') \
            .order_by(BatchRunItem.seq.asc()).all()
        inputs = [entry.get('values', {}) for entry in (batch.items_input or [])]

        # drop any stale cancellation left over from a previous run/cancel:
        # cancel keys are derived from item ids and are reused on retry
        for item in BatchRunItem.query.filter_by(batch_run_id=batch_id).all():
            QueryExecutor.clear_cancel(BatchService._cancel_key(batch_id, item.id))

        deadline = time.monotonic() + batch.max_total_time_ms / 1000.0
        state = {'total_rows': batch.total_rows or 0, 'stopped_reason': None}
        state_lock = threading.Lock()

        def is_cancelled():
            # fresh read (runner thread session may hold stale objects)
            db.session.expire_all()
            current = db.session.get(BatchRun, batch_id)
            return current is None or current.cancel_requested or current.status != 'running'

        def run_item(item_id, seq):
            with app.app_context():
                cancel_key = BatchService._cancel_key(batch_id, item_id)
                if is_cancelled():
                    BatchService._finalize_item(item_id, 'cancelled')
                    return

                with _db_write_lock:
                    item = db.session.get(BatchRunItem, item_id)
                    if item.status != 'pending':
                        return
                    item.status = 'running'
                    item.started_ts = time.time()
                    db.session.commit()

                try:
                    # pacing: optional per-item delay (rate limiting). Slept
                    # in small slices so cancellation stays responsive and a
                    # cancelled item never reaches execution.
                    delay_s = (batch.item_delay_ms or 0) / 1000.0
                    while delay_s > 0:
                        if is_cancelled():
                            BatchService._finalize_item(item_id, 'cancelled')
                            return
                        step = min(0.05, delay_s)
                        time.sleep(step)
                        delay_s -= step

                    values = inputs[seq] if seq < len(inputs) else {}
                    ast = TemplateService.instantiate(parameters, structure, values)
                    result = QueryExecutor.execute(
                        ast, record_snapshot=False,
                        cancel_key=cancel_key,
                        timeout_ms=batch.item_timeout_ms,
                    )
                    # never write results after a cancel was requested
                    if is_cancelled():
                        QueryExecutor.request_cancel(cancel_key)
                        BatchService._finalize_item(item_id, 'cancelled')
                        return
                    plan = QueryExecutor.compute_normalized_plan(
                        result['sql'], result['params'], ast)
                    with state_lock:
                        state['total_rows'] += result['rowCount']
                    BatchService._finalize_item(
                        item_id, 'succeeded', batch_id=batch_id,
                        params_summary=params_summary(result['params']),
                        ast_hash=ast_hash(ast),
                        sql=result['sql'],
                        plan_json=plan,
                        row_count=result['rowCount'],
                        truncated=result['truncated'],
                        duration_ms=result['executionTime'],
                    )
                except QueryCancelled:
                    BatchService._finalize_item(item_id, 'cancelled')
                except QueryTimeout as e:
                    BatchService._finalize_item(item_id, 'failed', error=str(e),
                                                error_code='timeout')
                except TemplateError as e:
                    BatchService._finalize_item(item_id, 'failed', error=str(e),
                                                error_code='invalid_parameters')
                except ValueError as e:
                    # validation / read-only safety rejection: item-local failure
                    BatchService._finalize_item(item_id, 'failed', error=str(e),
                                                error_code='safety_rejected')
                except Exception as e:  # noqa: BLE001
                    BatchService._finalize_item(item_id, 'failed', error=str(e),
                                                error_code='execution_error')

        queue = [(item.id, item.seq) for item in pending_rows]
        with ThreadPoolExecutor(max_workers=batch.max_concurrency,
                                thread_name_prefix=f'batch-{batch_id}') as pool:
            futures = set()
            while queue or futures:
                while queue and len(futures) < batch.max_concurrency:
                    stop = is_cancelled() and 'cancelled'
                    if not stop and time.monotonic() > deadline:
                        stop = 'time_limit'
                    if not stop:
                        with state_lock:
                            if state['total_rows'] >= batch.max_total_rows:
                                stop = 'row_limit'
                    if stop:
                        state['stopped_reason'] = stop
                        # abort in-flight items; the rest never start
                        running = BatchRunItem.query.filter_by(
                            batch_run_id=batch_id, status='running').all()
                        for f_item in running:
                            QueryExecutor.request_cancel(
                                BatchService._cancel_key(batch_id, f_item.id))
                        leftover_status = 'cancelled' if stop == 'cancelled' else 'skipped'
                        for item_id, _ in queue:
                            BatchService._finalize_item(item_id, leftover_status)
                        queue = []
                        break
                    item_id, seq = queue.pop(0)
                    futures.add(pool.submit(run_item, item_id, seq))
                if not futures:
                    break
                done, futures = wait(futures, return_when=FIRST_COMPLETED)

        # finalize counters (under the write lock, re-reading the cancel
        # flag so a cancel committed during the drain always wins)
        with _db_write_lock:
            db.session.expire_all()
            items = BatchRunItem.query.filter_by(batch_run_id=batch_id).all()
            batch = db.session.get(BatchRun, batch_id)
            db.session.refresh(batch)
            batch.succeeded_items = sum(1 for i in items if i.status == 'succeeded')
            batch.failed_items = sum(1 for i in items if i.status == 'failed')
            batch.cancelled_items = sum(1 for i in items if i.status == 'cancelled')
            batch.skipped_items = sum(1 for i in items if i.status == 'skipped')
            batch.total_rows = state['total_rows']
            if batch.cancel_requested:
                batch.status = 'cancelled'
                batch.stopped_reason = 'cancelled'
            else:
                batch.status = 'completed'
                batch.stopped_reason = state['stopped_reason']
            batch.finished_at = datetime.utcnow()
            db.session.commit()

    @staticmethod
    def _finalize_item(item_id, status, batch_id=None, **fields):
        with _db_write_lock:
            item = db.session.get(BatchRunItem, item_id)
            if item is None or item.status in ITEM_FINAL_STATUSES:
                return  # final statuses are immutable
            if status == 'succeeded' and batch_id is not None:
                # last-line-of-defense: re-verify cancellation under the
                # write lock so no result is written after cancel
                batch = db.session.get(BatchRun, batch_id)
                db.session.refresh(batch)
                if batch is None or batch.cancel_requested or batch.status != 'running':
                    status, fields = 'cancelled', {}
            item.status = status
            for key, value in fields.items():
                setattr(item, key, value)
            item.finished_ts = time.time()
            db.session.commit()
