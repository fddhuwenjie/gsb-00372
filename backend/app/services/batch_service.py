"""
Cancellable batch execution of one immutable template version over many
parameter sets.

Design properties:

* The template (id + version) and parameter sets are immutable for the
  lifetime of the batch run.
* Concurrency is bounded by a small thread pool; each item is executed in
  isolation so a read-only violation or type error on one item is recorded
  as a failed item and never affects the others.
* A global wall-clock timeout and a maximum total-row budget are enforced;
  once either is exceeded no further items are started and the batch is
  marked cancelled/failed.
* Cancellation is cooperative: once requested, pending items are marked
  cancelled rather than executed; running items finish their current fetch
  (the executor only persists after a complete fetch, so no partial result
  is written).
* Retry only re-runs items that are not already ``succeeded``; successful
  items keep their original result and ordering, so retries are safe.
* Results are stored in submission order (``item_index``) regardless of
  completion order, giving stable output.
* No sensitive parameter *values* are persisted -- only the type/null
  summary per item.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import db
from app.models import BatchItem, BatchRun, QueryTemplate
from app.services.plan_service import parameter_type_summary
from app.services.query_executor import QueryExecutor
from app.services.template_service import (
    CURRENT_TEMPLATE_VERSION,
    TemplateMigrationError,
    TemplateValidationError,
    TemplateService,
)

MAX_CONCURRENCY = 4
MAX_BATCH_ITEMS = 100
DEFAULT_CONCURRENCY = 2
DEFAULT_ITEM_TIMEOUT = 15.0
PREVIEW_ROWS = 10


class BatchError(ValueError):
    pass


class BatchRunner:
    # In-process cancellation registry: batch_id -> threading.Event.
    _cancel_events = {}
    _lock = threading.Lock()

    # ------------------------------------------------------------------
    # Creation / submission
    # ------------------------------------------------------------------
    @staticmethod
    def create_batch(template_id, parameter_sets, *, idempotency_key=None,
                     user_session=None, concurrency=None, max_total_rows=None,
                     timeout_seconds=None, labels=None):
        template = QueryTemplate.query.get(template_id)
        if template is None:
            raise BatchError(f'Unknown template id: {template_id}')

        definition = template.template_definition
        try:
            normalised = TemplateService.validate_template(definition)
            TemplateService.check_schema(normalised)
        except (TemplateValidationError, TemplateMigrationError) as exc:
            raise BatchError(str(exc)) from exc

        if not isinstance(parameter_sets, list):
            raise BatchError('parameter_sets must be a list')
        if not parameter_sets:
            raise BatchError('parameter_sets must not be empty')
        if len(parameter_sets) > MAX_BATCH_ITEMS:
            raise BatchError(
                f'A batch may contain at most {MAX_BATCH_ITEMS} items'
            )

        if idempotency_key:
            existing = BatchRun.query.filter_by(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                return existing, False

        concurrency = max(1, min(int(concurrency or DEFAULT_CONCURRENCY),
                                  MAX_CONCURRENCY))
        if timeout_seconds is not None:
            timeout_seconds = float(timeout_seconds)
            if timeout_seconds <= 0:
                raise BatchError('timeout_seconds must be positive')
        if max_total_rows is not None:
            max_total_rows = int(max_total_rows)
            if max_total_rows <= 0:
                raise BatchError('max_total_rows must be positive')

        run = BatchRun(
            idempotency_key=idempotency_key,
            user_session=user_session,
            template_id=template_id,
            template_version=template.template_version or CURRENT_TEMPLATE_VERSION,
            status='pending',
            concurrency=concurrency,
            max_total_rows=max_total_rows,
            timeout_seconds=timeout_seconds,
            total_items=len(parameter_sets),
        )
        db.session.add(run)
        db.session.flush()

        labels = labels or [None] * len(parameter_sets)
        if len(labels) != len(parameter_sets):
            raise BatchError('labels length must match parameter_sets')

        for index, values in enumerate(parameter_sets):
            if not isinstance(values, dict):
                raise BatchError(
                    f'parameter_sets[{index}] must be an object'
                )
            db.session.add(BatchItem(
                batch_id=run.id,
                item_index=index,
                status=BatchItem.STATUS_PENDING,
                param_type_summary=parameter_type_summary(values),
                label=labels[index],
            ))
        db.session.commit()
        # Return the run plus the validated parameter sets so callers can
        # hand the values to run_batch without re-submitting them.
        return run, True

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    @staticmethod
    def run_batch(batch_id, parameter_sets, app=None):
        """
        Execute pending/failed items of a batch. ``parameter_sets`` is the
        ordered list of value dicts (same order as creation). The function
        is idempotent: items already in ``succeeded`` state are never
        re-run.
        """
        run = BatchRun.query.get(batch_id)
        if run is None:
            raise BatchError(f'Unknown batch id: {batch_id}')
        if run.status == 'running':
            return run

        template = QueryTemplate.query.get(run.template_id)
        definition = template.template_definition
        normalised = TemplateService.validate_template(definition)
        TemplateService.check_schema(normalised)

        items = (
            BatchItem.query
            .filter_by(batch_id=batch_id)
            .order_by(BatchItem.item_index.asc())
            .all()
        )
        if len(items) != len(parameter_sets):
            raise BatchError(
                'parameter_sets length does not match batch item count'
            )

        with BatchRunner._lock:
            event = BatchRunner._cancel_events.get(batch_id)
            if event is None:
                event = threading.Event()
                BatchRunner._cancel_events[batch_id] = event
            event.clear()

        run.status = 'running'
        run.started_at = datetime.utcnow()
        run.error = None
        db.session.commit()

        deadline = (
            time.time() + run.timeout_seconds
            if run.timeout_seconds else None
        )

        # Only items that are not yet succeeded are eligible.
        eligible = [
            (item, parameter_sets[item.item_index])
            for item in items
            if item.status != BatchItem.STATUS_SUCCEEDED
        ]

        total_rows_lock = threading.Lock()
        total_rows = run.total_rows or 0
        stop_reason = None

        def should_stop():
            if event.is_set():
                return 'cancelled'
            if deadline and time.time() > deadline:
                return 'timeout'
            if run.max_total_rows:
                with total_rows_lock:
                    if total_rows >= run.max_total_rows:
                        return 'row_budget'
            return None

        def run_item(args):
            item, values = args
            nonlocal total_rows
            reason = should_stop()
            if reason:
                return item, None, reason
            return BatchRunner._execute_one(
                run, definition, item, values, app
            )

        try:
            with ThreadPoolExecutor(max_workers=run.concurrency) as pool:
                futures = [pool.submit(run_item, pair) for pair in eligible]
                for future in as_completed(futures):
                    item, error, reason = future.result()
                    if reason == 'succeeded':
                        with total_rows_lock:
                            total_rows = BatchRunner._recompute_total_rows(batch_id)
                    elif reason in ('timeout', 'row_budget', 'cancelled'):
                        stop_reason = reason
                        event.set()
        finally:
            BatchRunner._finalise(batch_id, stop_reason)

        return BatchRun.query.get(batch_id)

    @staticmethod
    def _execute_one(run, definition, item, values, app):
        """Execute one parameter set in its own app/session context."""
        if app is None:
            return item, 'no app context', 'failed'
        with app.app_context():
            # Each thread gets a fresh session bound to its own connection.
            session = Session(bind=db.engine)
            try:
                item = session.get(BatchItem, item.id)
                item.started_at = datetime.utcnow()
                item.status = BatchItem.STATUS_RUNNING
                session.commit()

                result = QueryExecutor.execute_template(
                    definition,
                    values,
                    user_session=None,
                    timeout=DEFAULT_ITEM_TIMEOUT,
                    record=True,
                    max_rows=run.max_total_rows,
                )
                item.status = BatchItem.STATUS_SUCCEEDED
                item.execution_id = result.get('executionId')
                item.plan_fingerprint = result.get('planFingerprint')
                item.row_count = result.get('rowCount', 0)
                item.duration_ms = result.get('executionTime', 0)
                item.result_preview = (result.get('rows') or [])[:PREVIEW_ROWS]
                item.error = None
                item.finished_at = datetime.utcnow()
                session.commit()
                return item, None, 'succeeded'
            except Exception as exc:
                session.rollback()
                try:
                    item = session.get(BatchItem, item.id)
                    item.status = BatchItem.STATUS_FAILED
                    item.error = str(exc)[:1000]
                    item.finished_at = datetime.utcnow()
                    session.commit()
                except Exception:
                    session.rollback()
                return item, str(exc), 'failed'
            finally:
                session.close()

    @staticmethod
    def _recompute_total_rows(batch_id):
        # Expire any stale state in the current session so we see the
        # commits made by worker threads.
        db.session.expire_all()
        total = db.session.query(
            db.func.coalesce(db.func.sum(BatchItem.row_count), 0)
        ).filter(
            BatchItem.batch_id == batch_id,
            BatchItem.status == BatchItem.STATUS_SUCCEEDED,
        ).scalar() or 0
        run = db.session.get(BatchRun, batch_id)
        run.total_rows = int(total)
        run.succeeded_items = db.session.query(BatchItem).filter_by(
            batch_id=batch_id, status=BatchItem.STATUS_SUCCEEDED
        ).count()
        run.failed_items = db.session.query(BatchItem).filter_by(
            batch_id=batch_id, status=BatchItem.STATUS_FAILED
        ).count()
        run.cancelled_items = db.session.query(BatchItem).filter_by(
            batch_id=batch_id, status=BatchItem.STATUS_CANCELLED
        ).count()
        db.session.commit()
        return int(total)

    @staticmethod
    def _finalise(batch_id, stop_reason):
        db.session.expire_all()
        run = db.session.get(BatchRun, batch_id)
        pending = db.session.query(BatchItem).filter(
            BatchItem.batch_id == batch_id,
            BatchItem.status.in_([
                BatchItem.STATUS_PENDING,
            ]),
        ).all()
        for item in pending:
            item.status = BatchItem.STATUS_CANCELLED
            item.finished_at = datetime.utcnow()

        succeeded = db.session.query(BatchItem).filter_by(
            batch_id=batch_id, status=BatchItem.STATUS_SUCCEEDED
        ).count()
        failed = db.session.query(BatchItem).filter_by(
            batch_id=batch_id, status=BatchItem.STATUS_FAILED
        ).count()
        cancelled = db.session.query(BatchItem).filter_by(
            batch_id=batch_id, status=BatchItem.STATUS_CANCELLED
        ).count()
        run.succeeded_items = succeeded
        run.failed_items = failed
        run.cancelled_items = cancelled

        if stop_reason == 'timeout':
            run.status = 'failed'
            run.error = (
                f'Batch exceeded total timeout of '
                f'{run.timeout_seconds}s'
            )
        elif succeeded == 0 and failed > 0:
            run.status = 'failed'
            run.error = 'All items failed'
        elif cancelled or stop_reason in ('cancelled', 'row_budget'):
            run.status = 'cancelled'
            if stop_reason == 'row_budget':
                run.error = (
                    f'Batch reached max_total_rows='
                    f'{run.max_total_rows}'
                )
        else:
            run.status = 'completed'
        run.finished_at = datetime.utcnow()
        db.session.commit()

        with BatchRunner._lock:
            BatchRunner._cancel_events.pop(batch_id, None)

    # ------------------------------------------------------------------
    # Cancellation / retry
    # ------------------------------------------------------------------
    @staticmethod
    def cancel(batch_id):
        run = BatchRun.query.get(batch_id)
        if run is None:
            raise BatchError(f'Unknown batch id: {batch_id}')
        if run.status in ('completed', 'cancelled', 'failed'):
            return run
        with BatchRunner._lock:
            event = BatchRunner._cancel_events.get(batch_id)
            if event is None:
                event = threading.Event()
                BatchRunner._cancel_events[batch_id] = event
            event.set()
        if run.status == 'pending':
            pending = BatchItem.query.filter_by(
                batch_id=batch_id, status=BatchItem.STATUS_PENDING
            ).all()
            for item in pending:
                item.status = BatchItem.STATUS_CANCELLED
                item.finished_at = datetime.utcnow()
            run.status = 'cancelled'
            run.finished_at = datetime.utcnow()
            db.session.commit()
        return run

    @staticmethod
    def retry(batch_id, parameter_sets, app=None):
        """Reset non-succeeded items to pending and re-run."""
        run = BatchRun.query.get(batch_id)
        if run is None:
            raise BatchError(f'Unknown batch id: {batch_id}')
        if run.status == 'running':
            raise BatchError('Cannot retry a running batch')

        items = BatchItem.query.filter_by(batch_id=batch_id).order_by(
            BatchItem.item_index.asc()
        ).all()
        for item in items:
            if item.status != BatchItem.STATUS_SUCCEEDED:
                item.status = BatchItem.STATUS_PENDING
                item.error = None
                item.started_at = None
                item.finished_at = None
                item.execution_id = None
        run.status = 'pending'
        run.error = None
        run.finished_at = None
        db.session.commit()
        return BatchRunner.run_batch(batch_id, parameter_sets, app=app)
