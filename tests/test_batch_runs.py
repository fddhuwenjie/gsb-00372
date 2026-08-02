"""Real batch-run API tests: concurrency, budgets, cancel, partial failure
isolation, duplicate submit idempotency, recoverable state and stable order.

These exercise the threaded BatchRunService through the Flask test client and
assert on the durable database state (which is the source of truth for
recovery), never on transient in-memory values.
"""
import time
import threading
import pytest

from app import create_app  # noqa: F401 (ensures package import path)
from app.models import db, BatchRun, BatchRunItem, ExecutionPlanRecord, QueryTemplate
from app.services.batch_run_service import BatchRunService
from app.routes import _load_template_definition


# ---- helpers ---------------------------------------------------------------

def make_template(client, cmp='=', value='US'):
    qs = {
        'tables': [
            {'id': 'o', 'tableName': 'order', 'alias': 'o', 'position': {}},
            {'id': 'c', 'tableName': 'customer', 'alias': 'c', 'position': {}},
        ],
        'joins': [{'id': 'j', 'type': 'INNER', 'leftTableId': 'o', 'leftColumn': 'customer_id',
                   'rightTableId': 'c', 'rightColumn': 'id', 'leftTable': 'order', 'rightTable': 'customer'}],
        'selectedFields': [{'tableId': 'c', 'columnName': 'country'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'ct', 'tableId': 'c', 'columnName': 'country', 'cmp': cmp, 'value': value}]},
        'aggregations': [],
        'orderBy': [{'tableId': 'o', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100, 'offset': 0,
    }
    param = client.post('/api/templates/parameterize', json={
        'query_structure': qs,
        'specs': [{'name': 'country', 'type': 'string', 'required': True,
                   'target': {'kind': 'filter', 'clauseId': 'ct'}}],
    }).get_json()
    return client.post('/api/templates', json={
        'name': 'batch-t', 'query_structure': param['queryStructure'], 'parameters': param['parameters'],
    }).get_json()['id']


def poll_batch(client, batch_id, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        b = client.get(f'/api/batch-runs/{batch_id}').get_json()
        if b['status'] in ('completed', 'cancelled', 'failed'):
            return b
        time.sleep(0.05)
    return client.get(f'/api/batch-runs/{batch_id}').get_json()


# ---- concurrency + success + stable order ---------------------------------

def test_batch_runs_all_items_stable_order(client):
    tid = make_template(client)
    value_sets = [{'country': c} for c in ['US', 'UK', 'Germany', 'France', 'Spain']]
    resp = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': value_sets, 'max_concurrency': 3,
    })
    assert resp.status_code == 201
    bid = resp.get_json()['id']
    b = poll_batch(client, bid)
    assert b['status'] == 'completed'
    assert b['counts']['succeeded'] == 5
    # Items are returned in submission order regardless of completion order.
    assert [it['item_index'] for it in b['items']] == [0, 1, 2, 3, 4]
    # Each succeeded item links a plan record and stores parameter *types* only
    # (keyed by the generated bound-parameter names, never raw values).
    for it in b['items']:
        assert it['plan_record_id'] is not None
        types = set(it['param_type_summary']['byName'].values())
        assert types <= {'integer', 'number', 'string', 'date', 'boolean', 'list', 'null'}
        assert 'US' not in str(it['param_type_summary'])


def test_immutable_version_frozen(client):
    tid = make_template(client)
    submitted = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': [{'country': 'US'}],
    }).get_json()
    assert submitted['template_version'] == 1
    # Bumping the template to v2 must not change the batch's frozen version.
    client.put(f'/api/templates/{tid}', json={
        'query_structure': {**client.get(f'/api/templates/{tid}').get_json()['query_structure'], 'limit': 50},
        'parameters': client.get(f'/api/templates/{tid}').get_json()['parameters'],
    })
    b = poll_batch(client, submitted['id'])
    assert b['template_version'] == 1


# ---- total-row budget ------------------------------------------------------
def test_total_row_budget_caps_batch(client):
    tid = make_template(client)
    # Each 'US' item returns several rows; cap the whole batch at 2 rows.
    value_sets = [{'country': 'US'}] * 5
    bid = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': value_sets, 'max_concurrency': 1,
        'max_total_rows': 2, 'per_item_max_rows': 1,
    }).get_json()['id']
    b = poll_batch(client, bid)
    # Never exceed the global row budget across succeeded items.
    total = sum((it['row_count'] or 0) for it in b['items'] if it['status'] == 'succeeded')
    assert total <= 2


# ---- concurrency actually parallelizes ------------------------------------

def test_concurrency_limit_runs_items_in_parallel(app, client, monkeypatch):
    """With concurrency=4, at least 2 items must be observed running at the same
    time; the peak observed concurrency must never exceed the configured limit."""
    tid = make_template(client)
    from app.services import batch_run_service as brs
    real_capture = brs.QueryExecutor.capture_plan_record

    state = {'current': 0, 'peak': 0}
    lock = threading.Lock()

    def slow_capture(concrete, *args, **kwargs):
        with lock:
            state['current'] += 1
            state['peak'] = max(state['peak'], state['current'])
        try:
            time.sleep(0.15)   # hold the slot so overlap is observable
            return real_capture(concrete, *args, **kwargs)
        finally:
            with lock:
                state['current'] -= 1

    monkeypatch.setattr(brs.QueryExecutor, 'capture_plan_record', staticmethod(slow_capture))

    bid = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': [{'country': 'US'}] * 6, 'max_concurrency': 3,
    }).get_json()['id']
    b = poll_batch(client, bid)
    assert b['status'] == 'completed'
    assert state['peak'] >= 2            # genuinely parallel
    assert state['peak'] <= 3            # never exceeds the limit


# ---- per-item timeout ------------------------------------------------------

def test_per_item_timeout_fails_item_not_batch(app, client, monkeypatch):
    """An item that exceeds its per-item timeout is marked failed on its own;
    other items still succeed."""
    tid = make_template(client)
    from app.services import batch_run_service as brs
    from app.services.query_executor import QueryTimeoutError
    real_capture = brs.QueryExecutor.capture_plan_record

    def maybe_timeout(concrete, *args, **kwargs):
        if 'TIMEOUT_ME' in str(concrete):
            raise QueryTimeoutError('Query exceeded timeout')
        return real_capture(concrete, *args, **kwargs)

    monkeypatch.setattr(brs.QueryExecutor, 'capture_plan_record', staticmethod(maybe_timeout))

    bid = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': [{'country': 'US'}, {'country': 'TIMEOUT_ME'}, {'country': 'UK'}],
        'max_concurrency': 3,
    }).get_json()['id']
    b = poll_batch(client, bid)
    by_index = {it['item_index']: it for it in b['items']}
    assert by_index[0]['status'] == 'succeeded'
    assert by_index[2]['status'] == 'succeeded'
    assert by_index[1]['status'] == 'failed'
    assert by_index[1]['plan_record_id'] is None


# ---- cancel: no writes after cancel ---------------------------------------

def test_cancel_before_start_writes_no_results(app, client):
    """Pre-set the durable cancel flag so the batch is cancelled before any item
    runs; assert the database holds zero execution plan records for it."""
    tid = make_template(client)
    value_sets = [{'country': 'US'}] * 6

    with app.app_context():
        # Create the batch rows without launching the worker, then mark cancel.
        template = db.session.get(QueryTemplate, tid)
        qs, params = _load_template_definition(template, template.current_version)
        batch_id = BatchRunService.create_batch(
            template, template.current_version, qs, params, value_sets,
            max_concurrency=2,
        )
        batch = db.session.get(BatchRun, batch_id)
        batch.cancel_requested = True
        db.session.commit()
        plan_ids_before = {r.id for r in ExecutionPlanRecord.query.all()}

    # Now run the (already-cancelled) batch synchronously.
    with app.app_context():
        template = db.session.get(QueryTemplate, tid)
        qs, params = _load_template_definition(template, template.current_version)
    BatchRunService.run_batch(app, batch_id, qs, params, value_sets)

    with app.app_context():
        db.session.expire_all()
        batch = db.session.get(BatchRun, batch_id)
        assert batch.status == 'cancelled'
        items = BatchRunItem.query.filter_by(batch_id=batch_id).all()
        # No item succeeded and none produced a plan record.
        assert all(it.status == 'cancelled' for it in items)
        assert all(it.plan_record_id is None for it in items)
        plan_ids_after = {r.id for r in ExecutionPlanRecord.query.all()}
        assert plan_ids_after == plan_ids_before   # DB not written with results
        assert batch.total_rows == 0


def test_cancel_is_recoverable_state(client):
    tid = make_template(client)
    bid = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': [{'country': 'US'}] * 8, 'max_concurrency': 1,
    }).get_json()['id']
    client.post(f'/api/batch-runs/{bid}/cancel')
    b = poll_batch(client, bid)
    assert b['status'] == 'cancelled'
    # State is fully recoverable via a fresh GET: terminal, no pending/running.
    reloaded = client.get(f'/api/batch-runs/{bid}').get_json()
    assert reloaded['status'] == 'cancelled'
    assert reloaded['counts']['pending'] == 0
    assert reloaded['counts']['running'] == 0


# ---- partial failure isolation --------------------------------------------

def test_one_rejected_item_does_not_pollute_others(client):
    """A parameter set with the wrong type is rejected on its own; the other
    items still succeed. Isolation is proven from durable item states."""
    tid = make_template(client)
    value_sets = [
        {'country': 'US'},         # ok
        {'country': 12345},        # wrong type -> rejected (string expected)
        {'country': 'UK'},         # ok
    ]
    bid = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': value_sets, 'max_concurrency': 3,
    }).get_json()['id']
    b = poll_batch(client, bid)
    by_index = {it['item_index']: it for it in b['items']}
    assert by_index[0]['status'] == 'succeeded'
    assert by_index[2]['status'] == 'succeeded'
    assert by_index[1]['status'] == 'rejected'
    assert by_index[0]['plan_record_id'] and by_index[2]['plan_record_id']
    assert by_index[1]['plan_record_id'] is None


def test_read_only_boundary_rejection_isolated(app, client, monkeypatch):
    """If instantiation for one item somehow produces SQL that the read-only
    guard rejects, only that item is rejected; the others succeed and no data
    is written for the rejected item."""
    tid = make_template(client)
    value_sets = [{'country': 'US'}, {'country': 'TRIGGER_UNSAFE'}, {'country': 'UK'}]

    # Force capture_plan_record to raise UnsafeQueryError for the marked value,
    # simulating a per-item boundary violation without affecting the others.
    from app.services import batch_run_service as brs
    from app.services.sql_guard import UnsafeQueryError
    real_capture = brs.QueryExecutor.capture_plan_record

    def fake_capture(concrete, *args, **kwargs):
        blob = str(concrete)
        if 'TRIGGER_UNSAFE' in blob:
            raise UnsafeQueryError('simulated read-only violation')
        return real_capture(concrete, *args, **kwargs)

    monkeypatch.setattr(brs.QueryExecutor, 'capture_plan_record', staticmethod(fake_capture))

    bid = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': value_sets, 'max_concurrency': 3,
    }).get_json()['id']
    b = poll_batch(client, bid)
    by_index = {it['item_index']: it for it in b['items']}
    assert by_index[0]['status'] == 'succeeded'
    assert by_index[2]['status'] == 'succeeded'
    assert by_index[1]['status'] == 'rejected'
    assert 'read-only' in (by_index[1]['error'] or '').lower()
    assert by_index[1]['plan_record_id'] is None


# ---- duplicate submit idempotency -----------------------------------------

def test_duplicate_submit_is_idempotent(client):
    tid = make_template(client)
    body = {'value_sets': [{'country': 'US'}, {'country': 'UK'}], 'idempotency_key': 'dup-key-1'}
    r1 = client.post(f'/api/templates/{tid}/batch-runs', json=body)
    r2 = client.post(f'/api/templates/{tid}/batch-runs', json=body)
    assert r1.status_code == 201
    assert r2.status_code == 200            # duplicate returns existing
    assert r1.get_json()['id'] == r2.get_json()['id']
    # Exactly one batch exists for that key.
    runs = client.get(f'/api/templates/{tid}/batch-runs').get_json()
    keyed = [r for r in runs if r['idempotency_key'] == 'dup-key-1']
    assert len(keyed) == 1


# ---- retry only re-runs non-succeeded -------------------------------------

def test_retry_reruns_only_failed_items(client):
    tid = make_template(client)
    value_sets = [{'country': 'US'}, {'country': 999}, {'country': 'UK'}]  # middle rejected
    bid = client.post(f'/api/templates/{tid}/batch-runs', json={
        'value_sets': value_sets, 'max_concurrency': 2,
    }).get_json()['id']
    b = poll_batch(client, bid)
    by_index = {it['item_index']: it for it in b['items']}
    assert by_index[1]['status'] == 'rejected'
    succeeded_attempts_before = by_index[0]['attempts']
    plan0_before = by_index[0]['plan_record_id']

    # Retry with corrected values for the failed item only mattering.
    fixed = [{'country': 'US'}, {'country': 'Germany'}, {'country': 'UK'}]
    client.post(f'/api/batch-runs/{bid}/retry', json={'value_sets': fixed})
    b2 = poll_batch(client, bid)
    by_index2 = {it['item_index']: it for it in b2['items']}
    # The previously-succeeded items were not re-run (attempts unchanged, same plan).
    assert by_index2[0]['attempts'] == succeeded_attempts_before
    assert by_index2[0]['plan_record_id'] == plan0_before
    # The formerly-rejected item ran again and now succeeds.
    assert by_index2[1]['status'] == 'succeeded'
    assert by_index2[1]['attempts'] >= 2
