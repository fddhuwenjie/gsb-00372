"""Batch parameter run tests: real API concurrency, timeout, cancellation,
partial failure, duplicate submission, recovery and stable result order.

Assertions target the database directly: nothing is written after cancel,
batch state is recoverable, per-item results stay in stable seq order and
carry template version + parameter type summary + execution plan (never raw
parameter values).
"""
import json
import time

import pytest

from app import create_app
from app.database import db
from app.models import BatchRun, BatchRunItem
from app.services.query_executor import QueryExecutor
from app.services.plan_service import ast_hash


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def wait_batch(client, batch_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        batch = client.get(f'/api/batch-runs/{batch_id}').get_json()
        if batch['status'] != 'running':
            return batch
        time.sleep(0.05)
    raise AssertionError(f'batch {batch_id} still running after {timeout}s')


def get_items(client, batch_id):
    return client.get(f'/api/batch-runs/{batch_id}/items').get_json()


def poll_items_until(client, batch_id, predicate, timeout=30.0):
    """Poll items until predicate(items) is truthy; returns the items."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = get_items(client, batch_id)
        if predicate(items):
            return items
        time.sleep(0.05)
    raise AssertionError(f'predicate not met for batch {batch_id} within {timeout}s')


def simple_structure():
    return {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'country'},
            {'tableId': 't1', 'columnName': 'id'},
        ],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'country', 'cmp': '=', 'value': 'US'},
        ]},
        'aggregations': [], 'limit': 100, 'offset': 0,
    }


def heavy_structure():
    """~39^5-row cross product with COUNT: takes a noticeable amount of
    time per item so concurrency/cancellation are observable."""
    tables = [{'id': f't{i}', 'tableName': 'order_item', 'alias': f'a{i}'}
              for i in range(1, 6)]
    joins = [
        {'id': f'j{i}', 'type': 'CROSS', 'leftTableId': f't{i}',
         'rightTableId': f't{i+1}', 'leftTable': 'order_item', 'rightTable': 'order_item'}
        for i in range(1, 5)
    ]
    return {
        'tables': tables,
        'joins': joins,
        'selectedFields': [{'tableId': 't1', 'columnName': 'id'}],
        'where': {'id': 'w', 'op': 'AND', 'children': [
            {'id': 'c1', 'tableId': 't1', 'columnName': 'id', 'cmp': '>=', 'value': 0},
        ]},
        'aggregations': [{'tableId': 't1', 'columnName': 'id', 'function': 'COUNT'}],
        'limit': 10, 'offset': 0,
    }


def simple_parameters():
    return [
        {'id': 'p-c', 'name': 'country', 'type': 'string', 'required': True,
         'target': {'kind': 'where', 'nodeId': 'c1'}},
        {'id': 'p-l', 'name': 'page_size', 'type': 'integer', 'required': False,
         'default': 100, 'target': {'kind': 'limit'}},
    ]


def heavy_parameters():
    return [
        {'id': 'p-min', 'name': 'min_id', 'type': 'integer', 'required': False,
         'default': 0, 'target': {'kind': 'where', 'nodeId': 'c1'}},
    ]


def make_template(client, name='batch-tpl', heavy=False):
    response = client.post('/api/templates', json={
        'name': name,
        'parameters': heavy_parameters() if heavy else simple_parameters(),
        'query_structure': heavy_structure() if heavy else simple_structure(),
    })
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def max_overlap(intervals):
    """Maximum number of [start, end] intervals overlapping at any point."""
    points = []
    for start, end in intervals:
        points.append((start, 1))
        points.append((end, -1))
    points.sort(key=lambda p: (p[0], p[1]))
    current = best = 0
    for _, delta in points:
        current += delta
        best = max(best, current)
    return best


# ----------------------------------------------------------------------
# Happy path / item results
# ----------------------------------------------------------------------

class TestBatchBasics:
    def test_batch_completes_with_ordered_results(self, client):
        tpl = make_template(client)
        countries = ['US', 'UK', 'Germany', 'France', 'Spain']
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [{'values': {'country': c}} for c in countries],
            'max_concurrency': 2,
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'])

        assert batch['status'] == 'completed'
        assert batch['succeeded_items'] == len(countries)
        assert batch['failed_items'] == 0

        items = get_items(client, batch['id'])
        # stable seq order regardless of completion order
        assert [i['seq'] for i in items] == list(range(len(countries)))
        for item in items:
            assert item['status'] == 'succeeded'
            # each result links version + type summary + plan, no raw values
            assert item['params_summary'] == {'p1': 'string', 'p2': 'integer'}
            assert item['ast_hash']
            assert item['plan_json']['nodes']
            assert ':p' in item['sql']
            assert json.dumps(item) != ''
            for country in countries:
                assert country not in json.dumps(item['params_summary'])

        # results reference the immutable template version
        assert batch['template_version'] == tpl['version']
        expected_hash = ast_hash(tpl['query_structure'])
        assert all(i['ast_hash'] == expected_hash for i in items)

    def test_batch_uses_archived_immutable_version(self, client):
        tpl = make_template(client)
        v1_structure = tpl['query_structure']

        changed = simple_structure()
        changed['selectedFields'] = [{'tableId': 't1', 'columnName': 'first_name'}]
        client.put(f"/api/templates/{tpl['id']}", json={'query_structure': changed})

        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'], 'version': 1,
            'items': [{'values': {'country': 'US'}}],
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'])
        assert batch['template_version'] == 1
        items = get_items(client, batch['id'])
        assert items[0]['ast_hash'] == ast_hash(v1_structure)
        assert items[0]['ast_hash'] != ast_hash(changed)


# ----------------------------------------------------------------------
# Concurrency
# ----------------------------------------------------------------------

class TestConcurrency:
    def test_concurrency_limit_is_enforced(self, client):
        tpl = make_template(client, heavy=True)
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [{'values': {'min_id': i}} for i in range(4)],
            'max_concurrency': 2,
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'], timeout=60)
        assert batch['status'] == 'completed'

        items = get_items(client, batch['id'])
        assert all(i['status'] == 'succeeded' for i in items)
        intervals = [(i['started_ts'], i['finished_ts']) for i in items]
        overlap = max_overlap(intervals)
        assert overlap <= 2, f'concurrency limit violated: overlap={overlap}'
        assert overlap == 2, 'workers never ran in parallel'


# ----------------------------------------------------------------------
# Timeout
# ----------------------------------------------------------------------

class TestTimeout:
    def test_item_timeout_fails_items_without_writing_results(self, client, app):
        tpl = make_template(client, heavy=True)
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [{'values': {}}, {'values': {}}],
            'max_concurrency': 2,
            'item_timeout_ms': 1,
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'], timeout=60)

        assert batch['status'] == 'completed'
        assert batch['succeeded_items'] == 0
        assert batch['failed_items'] == 2
        items = get_items(client, batch['id'])
        for item in items:
            assert item['status'] == 'failed'
            assert item['error_code'] == 'timeout'
            # nothing was written for the timed-out items
            assert item['row_count'] is None
            assert item['plan_json'] is None
            assert item['sql'] is None

        with app.app_context():
            persisted = BatchRunItem.query.filter_by(batch_run_id=batch['id']).all()
            assert all(i.row_count is None for i in persisted)


# ----------------------------------------------------------------------
# Total budgets (rows / time)
# ----------------------------------------------------------------------

class TestBudgets:
    def test_total_row_limit_skips_remaining_items(self, client):
        tpl = make_template(client)  # 'US' yields 3 rows per item
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [{'values': {'country': 'US'}} for _ in range(4)],
            'max_concurrency': 1,
            'max_total_rows': 4,
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'])

        assert batch['status'] == 'completed'
        assert batch['stopped_reason'] == 'row_limit'
        assert batch['succeeded_items'] == 2      # 2 items x 3 rows >= 4
        assert batch['skipped_items'] == 2
        assert batch['total_rows'] == 6
        items = get_items(client, batch['id'])
        assert [i['status'] for i in items] == ['succeeded', 'succeeded', 'skipped', 'skipped']

    def test_total_time_limit_skips_remaining_items(self, client):
        tpl = make_template(client, heavy=True)
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [{'values': {}} for _ in range(4)],
            'max_concurrency': 1,
            'item_delay_ms': 800,
            'max_total_time_ms': 500,   # deadline passes during item 1's pacing
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'], timeout=60)

        assert batch['status'] == 'completed'
        assert batch['stopped_reason'] == 'time_limit'
        assert batch['succeeded_items'] == 1
        assert batch['skipped_items'] == 3


# ----------------------------------------------------------------------
# Cancellation
# ----------------------------------------------------------------------

class TestCancellation:
    def test_cancel_stops_scheduling_and_writes_nothing_more(self, client):
        tpl = make_template(client, heavy=True)
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            # pacing makes cancellation deterministic: items 3-6 cannot
            # finish before the cancel lands
            'items': [{'values': {}} for _ in range(6)],
            'max_concurrency': 2,
            'item_delay_ms': 1000,
        })
        assert response.status_code == 201
        batch_id = response.get_json()['id']

        # wait until the run is actually processing, then cancel
        poll_items_until(client, batch_id,
                         lambda items: any(i['status'] == 'running' for i in items),
                         timeout=60)
        cancelled = client.post(f'/api/batch-runs/{batch_id}/cancel')
        assert cancelled.status_code == 200, cancelled.get_json()
        assert cancelled.get_json()['cancel_requested'] is True

        batch = wait_batch(client, batch_id, timeout=60)
        assert batch['status'] == 'cancelled'
        assert batch['stopped_reason'] == 'cancelled'

        # state is stable after cancellation: poll twice, nothing changes
        first = get_items(client, batch_id)
        time.sleep(1.0)
        second = get_items(client, batch_id)
        assert [(i['seq'], i['status'], i['row_count']) for i in first] == \
               [(i['seq'], i['status'], i['row_count']) for i in second]

        statuses = {i['status'] for i in second}
        assert 'running' not in statuses
        assert 'pending' not in statuses
        # items that did not succeed before the cancel carry no results
        for item in second:
            if item['status'] in ('cancelled', 'skipped'):
                assert item['row_count'] is None
                assert item['plan_json'] is None
        # items 3-6 never reached execution
        assert batch['succeeded_items'] <= 2

    def test_retry_after_cancel_only_reruns_unsuccessful_items(self, client):
        tpl = make_template(client, heavy=True)
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            # pacing guarantees: when items 1-2 succeed (~1s), items 3-6 are
            # still in their pacing delay or unscheduled
            'items': [{'values': {}} for _ in range(6)],
            'max_concurrency': 2,
            'item_delay_ms': 1000,
        })
        batch_id = response.get_json()['id']

        # wait until at least one item has completed, then cancel the rest
        poll_items_until(client, batch_id,
                         lambda items: any(i['status'] == 'succeeded' for i in items),
                         timeout=60)
        cancel_response = client.post(f'/api/batch-runs/{batch_id}/cancel')
        assert cancel_response.status_code == 200, cancel_response.get_json()
        assert cancel_response.get_json()['cancel_requested'] is True
        batch = wait_batch(client, batch_id, timeout=60)
        assert batch['status'] == 'cancelled'

        before = {i['seq']: i for i in get_items(client, batch_id)}
        succeeded_before = {seq: i for seq, i in before.items()
                            if i['status'] == 'succeeded'}

        retry = client.post(f'/api/batch-runs/{batch_id}/retry')
        assert retry.status_code == 200
        batch = wait_batch(client, batch_id, timeout=60)
        assert batch['status'] == 'completed'

        after = {i['seq']: i for i in get_items(client, batch_id)}
        assert all(i['status'] == 'succeeded' for i in after.values())
        for seq, item in succeeded_before.items():
            # previously succeeded items were NOT rerun
            assert after[seq]['finished_ts'] == item['finished_ts']
            assert after[seq]['started_ts'] == item['started_ts']
        for seq, item in after.items():
            if seq not in succeeded_before:
                assert item['finished_ts'] != before[seq]['finished_ts'] or \
                    before[seq]['finished_ts'] is None


# ----------------------------------------------------------------------
# Partial failure / safety isolation
# ----------------------------------------------------------------------

class TestPartialFailure:
    def test_invalid_values_fail_only_their_item(self, client):
        tpl = make_template(client)
        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [
                {'values': {'country': 'US'}},
                {'values': {'country': 'UK', 'page_size': 0}},      # invalid limit
                {'values': {'country': 'Spain', 'page_size': 'xx'}},  # illegal type
                {'values': {'country': 'France'}},
            ],
            'max_concurrency': 2,
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'])

        assert batch['status'] == 'completed'
        assert batch['succeeded_items'] == 2
        assert batch['failed_items'] == 2

        items = get_items(client, batch['id'])
        by_seq = {i['seq']: i for i in items}
        assert by_seq[0]['status'] == 'succeeded'
        assert by_seq[3]['status'] == 'succeeded'
        assert by_seq[1]['status'] == 'failed'
        assert by_seq[2]['status'] == 'failed'
        assert by_seq[2]['error_code'] == 'invalid_parameters'
        # siblings are not polluted by the failures
        assert by_seq[0]['plan_json']['nodes']
        assert by_seq[3]['row_count'] is not None

    def test_read_only_violation_is_rejected_per_item(self, client, monkeypatch):
        tpl = make_template(client)

        original = QueryExecutor.generate_sql

        def patched(query_structure):
            result = original(query_structure)
            if 'evil-marker' in (result['params'] or {}).values():
                # simulate a compromised generator for this one item
                return {'sql': 'SELECT 1; DROP TABLE customer', 'params': {}}
            return result

        monkeypatch.setattr(QueryExecutor, 'generate_sql', staticmethod(patched))

        response = client.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [
                {'values': {'country': 'US'}},
                {'values': {'country': 'evil-marker'}},
                {'values': {'country': 'UK'}},
            ],
            'max_concurrency': 2,
        })
        assert response.status_code == 201
        batch = wait_batch(client, response.get_json()['id'])

        items = get_items(client, batch['id'])
        by_seq = {i['seq']: i for i in items}
        assert by_seq[0]['status'] == 'succeeded'
        assert by_seq[1]['status'] == 'failed'
        assert by_seq[1]['error_code'] == 'safety_rejected'
        assert 'Multiple SQL statements' in by_seq[1]['error']
        assert by_seq[2]['status'] == 'succeeded'


# ----------------------------------------------------------------------
# Duplicate submission
# ----------------------------------------------------------------------

class TestIdempotency:
    def test_duplicate_submission_returns_same_batch(self, client):
        tpl = make_template(client)
        payload = {
            'template_id': tpl['id'],
            'items': [{'values': {'country': 'US'}}, {'values': {'country': 'UK'}}],
            'idempotency_key': 'submit-42',
        }
        first = client.post('/api/batch-runs', json=payload)
        assert first.status_code == 201
        second = client.post('/api/batch-runs', json=payload)
        assert second.status_code == 200
        assert second.get_json()['id'] == first.get_json()['id']

        batch = wait_batch(client, first.get_json()['id'])
        assert batch['total_items'] == 2
        assert len(get_items(client, batch['id'])) == 2


# ----------------------------------------------------------------------
# Recovery
# ----------------------------------------------------------------------

class TestRecovery:
    def test_interrupted_batch_recovers_and_retry_resumes(self, tmp_path):
        db_path = tmp_path / 'recover.db'
        uri = f'sqlite:///{db_path}'
        app1 = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': uri})
        client1 = app1.test_client()

        tpl = make_template(client1)
        response = client1.post('/api/batch-runs', json={
            'template_id': tpl['id'],
            'items': [{'values': {'country': 'US'}}, {'values': {'country': 'UK'}}],
        })
        batch_id = response.get_json()['id']
        batch = wait_batch(client1, batch_id)
        assert batch['status'] == 'completed'
        items_before = get_items(client1, batch_id)
        succeeded_finished = items_before[0]['finished_ts']

        # simulate a crash: batch and one item stuck in 'running'
        with app1.app_context():
            stuck = db.session.get(BatchRun, batch_id)
            stuck.status = 'running'
            stuck.finished_at = None
            stuck_item = BatchRunItem.query.filter_by(batch_run_id=batch_id, seq=1).first()
            stuck_item.status = 'running'
            db.session.commit()

        # "restart": a new app instance on the same database file
        app2 = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': uri})
        client2 = app2.test_client()

        recovered = client2.get(f'/api/batch-runs/{batch_id}').get_json()
        assert recovered['status'] == 'interrupted'

        retry = client2.post(f'/api/batch-runs/{batch_id}/retry')
        assert retry.status_code == 200
        batch = wait_batch(client2, batch_id)
        assert batch['status'] == 'completed'
        assert batch['succeeded_items'] == 2

        items_after = get_items(client2, batch_id)
        assert [i['seq'] for i in items_after] == [0, 1]
        # the item that succeeded before the crash was not rerun
        assert items_after[0]['finished_ts'] == succeeded_finished
        assert items_after[1]['status'] == 'succeeded'
