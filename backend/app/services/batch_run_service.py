"""Cancellable batch parameter runs.

A batch run executes ONE immutable template version against many parameter
sets under three hard budgets fixed at submit time:

  * ``max_concurrency`` -- at most N items run in parallel;
  * ``max_total_rows``  -- global row budget across all items;
  * ``max_total_ms``    -- wall-clock budget for the whole batch.

Guarantees:
  * Cancellation is cooperative and durable: once cancel is requested, no
    further item result is written -- an in-flight query is aborted via the
    executor's progress handler, and any item that has not reached a terminal
    state is marked ``cancelled`` without touching the database with its data.
  * Retry re-runs only items that did not succeed (failed / rejected /
    cancelled); succeeded items are never re-executed.
  * Each item is isolated: an item that crosses the read-only safety boundary
    (or violates the schema) is rejected on its own and cannot pollute other
    items or the shared database.
  * Nothing sensitive is persisted -- only parameter *type* summaries and the
    linked execution-plan record.
  * Result order is stable: items keep the ``item_index`` they were submitted
    with, regardless of completion order.

Execution happens on a background thread per batch; the Flask app is captured
so each worker can open its own application/DB context. SQLite writes for
item bookkeeping are serialized through a lock to stay safe under threads.
"""
import threading
import time
from datetime import datetime

from app.database import db
from app.services.metadata_service import MetadataService
from app.services.template_service import (
    TemplateService, TemplateError, SchemaMigrationError,
)
from app.services.plan_analysis_service import summarize_param_types
from app.services.query_executor import (
    QueryExecutor, QueryCancelledError, QueryTimeoutError,
)
from app.services.sql_guard import UnsafeQueryError
from app.models import (
    db as _db, BatchRun, BatchRunItem, ExecutionPlanRecord,
)

# Registry of live cancel events, keyed by batch id, so a cancel request from a
# request thread can signal the running workers immediately (in addition to the
# durable ``cancel_requested`` flag persisted on the row).
_cancel_events = {}
_registry_lock = threading.Lock()

# Hard ceilings so a submit can never request unbounded fan-out.
MAX_CONCURRENCY_LIMIT = 16
MAX_ITEMS = 500


class BatchRunService:
    @staticmethod
    def _get_cancel_event(batch_id):
        with _registry_lock:
            ev = _cancel_events.get(batch_id)
            if ev is None:
                ev = threading.Event()
                _cancel_events[batch_id] = ev
            return ev

    @staticmethod
    def request_cancel(batch_id):
        with _registry_lock:
            ev = _cancel_events.get(batch_id)
        if ev is not None:
            ev.set()

    # -------------------------------------------------------------- submit
    @staticmethod
    def create_batch(template, version, query_structure, parameters, value_sets,
                     *, max_concurrency=4, max_total_rows=None, max_total_ms=None,
                     per_item_timeout_ms=5000, per_item_max_rows=1000,
                     idempotency_key=None):
        if not isinstance(value_sets, list) or not value_sets:
            raise TemplateError('value_sets must be a non-empty list')
        if len(value_sets) > MAX_ITEMS:
            raise TemplateError(f'Too many items (max {MAX_ITEMS})')

        max_concurrency = max(1, min(int(max_concurrency or 1), MAX_CONCURRENCY_LIMIT))

        batch = BatchRun(
            template_id=template.id,
            template_version=version,
            idempotency_key=idempotency_key,
            status='pending',
            max_concurrency=max_concurrency,
            max_total_rows=max_total_rows,
            max_total_ms=max_total_ms,
            per_item_timeout_ms=per_item_timeout_ms,
            per_item_max_rows=per_item_max_rows,
        )
        db.session.add(batch)
        db.session.flush()

        for i in range(len(value_sets)):
            db.session.add(BatchRunItem(batch_id=batch.id, item_index=i, status='pending'))
        db.session.commit()
        return batch.id

    # -------------------------------------------------------------- run
    @staticmethod
    def run_batch(app, batch_id, query_structure, parameters, value_sets, retry=False):
        """Execute (or retry) a batch synchronously in the calling thread.
        Intended to be launched on a background thread via ``start_batch``."""
        cancel_event = BatchRunService._get_cancel_event(batch_id)

        with app.app_context():
            batch = db.session.get(BatchRun, batch_id)
            if batch is None:
                return
            if batch.cancel_requested:
                cancel_event.set()

            # Select the items to run: everything pending on a fresh run, or the
            # non-succeeded items on a retry (succeeded items are never re-run).
            items = (BatchRunItem.query
                     .filter_by(batch_id=batch_id)
                     .order_by(BatchRunItem.item_index)
                     .all())
            if retry:
                todo = [it for it in items if it.status != 'succeeded']
                for it in todo:
                    it.status = 'pending'
                    it.error = None
            else:
                todo = [it for it in items if it.status == 'pending']

            batch.status = 'running'
            if batch.started_at is None:
                batch.started_at = datetime.utcnow()
            db.session.commit()

            template_def = {'queryStructure': query_structure, 'parameters': parameters}
            metadata = MetadataService.get_all_metadata()
            deadline = None
            if batch.max_total_ms:
                deadline = time.monotonic() + (batch.max_total_ms / 1000.0)

            write_lock = threading.Lock()
            budget = {'total_rows': batch.total_rows or 0}
            max_total_rows = batch.max_total_rows
            per_item_timeout_ms = batch.per_item_timeout_ms
            per_item_max_rows = batch.per_item_max_rows

            todo_indices = [it.item_index for it in todo]

            def run_one(item_index):
                # Re-open everything inside the worker's own context.
                with app.app_context():
                    return BatchRunService._run_item(
                        app, batch_id, item_index, template_def, value_sets,
                        metadata, cancel_event, deadline, write_lock, budget,
                        max_total_rows, per_item_timeout_ms, per_item_max_rows,
                    )

            BatchRunService._run_pool(todo_indices, batch.max_concurrency, run_one, cancel_event)

            # Finalize batch status from the durable item states.
            BatchRunService._finalize(batch_id, cancel_event)

        with _registry_lock:
            _cancel_events.pop(batch_id, None)

    @staticmethod
    def _run_pool(indices, concurrency, run_one, cancel_event):
        """A tiny bounded worker pool. Workers pull indices off a shared queue
        and stop pulling new work as soon as cancellation is requested."""
        lock = threading.Lock()
        pos = {'i': 0}

        def worker():
            while True:
                if cancel_event.is_set():
                    return
                with lock:
                    if pos['i'] >= len(indices):
                        return
                    idx = indices[pos['i']]
                    pos['i'] += 1
                run_one(idx)

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(min(concurrency, max(1, len(indices))))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    @staticmethod
    def _run_item(app, batch_id, item_index, template_def, value_sets, metadata,
                  cancel_event, deadline, write_lock, budget, max_total_rows,
                  per_item_timeout_ms, per_item_max_rows):
        item = (BatchRunItem.query
                .filter_by(batch_id=batch_id, item_index=item_index)
                .first())
        if item is None:
            return

        # Respect cancellation / global time budget BEFORE doing any work.
        if cancel_event.is_set():
            BatchRunService._mark(write_lock, item, 'cancelled', error='Batch cancelled before start')
            return
        if deadline is not None and time.monotonic() > deadline:
            cancel_event.set()
            BatchRunService._mark(write_lock, item, 'cancelled', error='Batch time budget exceeded')
            return
        # Global row budget already spent: do not start more work.
        if max_total_rows is not None:
            with write_lock:
                if budget['total_rows'] >= max_total_rows:
                    item.status = 'cancelled'
                    item.error = 'Batch row budget exhausted'
                    db.session.commit()
                    return

        with write_lock:
            item.status = 'running'
            item.attempts = (item.attempts or 0) + 1
            db.session.commit()

        values = value_sets[item_index] if item_index < len(value_sets) else {}

        # Compute how many rows this item may read without overshooting the
        # global budget (still capped by the per-item maximum).
        item_max_rows = per_item_max_rows
        if max_total_rows is not None:
            with write_lock:
                remaining = max_total_rows - budget['total_rows']
            item_max_rows = max(0, min(per_item_max_rows, remaining))

        # --- query execution happens OUTSIDE the write lock (its own
        # read-only connection), so items truly run concurrently. ---
        try:
            concrete = TemplateService.instantiate(template_def, values, metadata=metadata)
            record = QueryExecutor.capture_plan_record(
                concrete,
                template_id=None, template_version=None,
                timeout_ms=per_item_timeout_ms,
                max_rows=item_max_rows if item_max_rows > 0 else 1,
                cancel_event=cancel_event,
                persist=False,
            )
        except QueryCancelledError:
            # Cooperative cancel mid-flight: never write result data.
            BatchRunService._mark(write_lock, item, 'cancelled', error='Cancelled during execution')
            return
        except QueryTimeoutError as e:
            BatchRunService._mark(write_lock, item, 'failed', error=str(e))
            return
        except (UnsafeQueryError,) as e:
            # Read-only boundary violation is isolated to THIS item.
            BatchRunService._mark(write_lock, item, 'rejected', error=f'Read-only boundary: {e}')
            return
        except SchemaMigrationError as e:
            BatchRunService._mark(write_lock, item, 'rejected', error=str(e))
            return
        except TemplateError as e:
            BatchRunService._mark(write_lock, item, 'rejected', error=str(e))
            return
        except Exception as e:  # pragma: no cover - defensive
            BatchRunService._mark(write_lock, item, 'failed', error=str(e))
            return

        # If cancellation landed while we were running, do NOT persist results.
        if cancel_event.is_set():
            BatchRunService._mark(write_lock, item, 'cancelled', error='Cancelled during execution')
            return

        with write_lock:
            # Persist the plan record and attribute rows to the global budget
            # atomically so concurrent items cannot overshoot the cap.
            if max_total_rows is not None and budget['total_rows'] >= max_total_rows:
                item.status = 'cancelled'
                item.error = 'Batch row budget exhausted'
                db.session.commit()
                return
            batch = db.session.get(BatchRun, batch_id)
            plan = ExecutionPlanRecord(
                template_id=batch.template_id,
                template_version=batch.template_version,
                ast_hash=record['ast_hash'],
                canonical_ast=record['canonical_ast'],
                param_type_summary=record['param_type_summary'],
                normalized_plan=record['normalized_plan'],
                raw_plan=record['raw_plan'],
                duration_ms=record['duration_ms'],
                row_count=record['row_count'],
            )
            db.session.add(plan)
            db.session.flush()

            item.status = 'succeeded'
            item.plan_record_id = plan.id
            item.param_type_summary = record['param_type_summary']
            item.row_count = record['row_count']
            item.duration_ms = record['duration_ms']
            item.error = None

            budget['total_rows'] += record['row_count'] or 0
            batch.total_rows = budget['total_rows']
            db.session.commit()

            # If this item exhausted the global budget, stop scheduling more.
            if max_total_rows is not None and budget['total_rows'] >= max_total_rows:
                cancel_event.set()

    @staticmethod
    def _mark(write_lock, item, status, error=None):
        with write_lock:
            item.status = status
            if error is not None:
                item.error = error
            db.session.commit()

    @staticmethod
    def _finalize(batch_id, cancel_event):
        # Workers committed item states in their own thread-local sessions;
        # drop any cached identity so we read the true, durable states.
        db.session.expire_all()
        batch = db.session.get(BatchRun, batch_id)
        if batch is None:
            return
        items = BatchRunItem.query.filter_by(batch_id=batch_id).all()
        # Any item still pending/running when cancelled becomes cancelled.
        if cancel_event.is_set() or batch.cancel_requested:
            for it in items:
                if it.status in ('pending', 'running'):
                    it.status = 'cancelled'
                    it.error = it.error or 'Batch cancelled'
            batch.status = 'cancelled'
        else:
            statuses = {it.status for it in items}
            if statuses <= {'succeeded'}:
                batch.status = 'completed'
            elif 'pending' in statuses or 'running' in statuses:
                batch.status = 'running'
            else:
                # A mix with no in-flight items: completed with failures.
                batch.status = 'completed'
        batch.finished_at = datetime.utcnow()
        db.session.commit()

    # -------------------------------------------------------------- launch
    @staticmethod
    def start_batch(app, batch_id, query_structure, parameters, value_sets, retry=False):
        BatchRunService._get_cancel_event(batch_id)
        t = threading.Thread(
            target=BatchRunService.run_batch,
            args=(app, batch_id, query_structure, parameters, value_sets),
            kwargs={'retry': retry},
            daemon=True,
        )
        t.start()
        return t
