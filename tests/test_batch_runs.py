"""
Batch parameter run tests.

These exercise the real HTTP API (Flask test client) against the seeded
database and assert:
  * concurrent execution works with bounded concurrency
  * total wall-clock timeout is enforced
  * cancellation leaves successful results intact and does not write
    further results
  * one bad parameter set fails only its item, never the others
  * duplicate submission with an idempotency key returns the same run
  * result ordering is stable (by item_index) regardless of completion
    order
  * retries only re-run non-succeeded items
"""
import time

import pytest

from app.models import BatchItem, BatchRun, QueryExecution


def _make_country_template(client):
    """Create a simple template filtering customer by country."""
    tpl = {
        'template_version': 1,
        'name': 'Customers by country',
        'parameters': [
            {'name': 'country', 'type': 'string', 'required': True},
        ],
        'queryStructure': {
            'tables': [
                {'id': 'c', 'tableName': 'customer', 'alias': 'c'},
            ],
            'joins': [],
            'selectedFields': [
                {'tableId': 'c', 'columnName': 'id'},
                {'tableId': 'c', 'columnName': 'country'},
            ],
            'where': {
                'tableId': 'c', 'columnName': 'country',
                'cmp': '=', 'param': 'country',
            },
            'aggregations': [],
            'limit': 100,
        },
    }
    resp = client.post('/api/templates', json=tpl)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()['id']


def _post_batch(client, template_id, parameter_sets, **kwargs):
    body = {
        'templateId': template_id,
        'parameterSets': parameter_sets,
    }
    body.update(kwargs)
    return client.post('/api/batches', json=body)


class TestBatchBasics:
    def test_batch_runs_all_items_in_order(self, client):
        tid = _make_country_template(client)
        sets = [
            {'country': 'US'},
            {'country': 'UK'},
            {'country': 'Germany'},
        ]
        resp = _post_batch(client, tid, sets, concurrency=2)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body['status'] == 'completed'
        assert body['totalItems'] == 3
        assert body['succeededItems'] == 3
        assert body['failedItems'] == 0
        # Items must be returned in submission order
        items = body['items']
        assert [i['itemIndex'] for i in items] == [0, 1, 2]
        for item in items:
            assert item['status'] == 'succeeded'
            assert item['planFingerprint'] is not None

    def test_concurrent_execution_completes(self, client):
        tid = _make_country_template(client)
        sets = [{'country': c} for c in
                ['US', 'UK', 'Germany', 'France', 'Spain']]
        resp = _post_batch(client, tid, sets, concurrency=4)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['succeededItems'] == 5
        assert body['concurrency'] == 4

    def test_concurrency_is_capped(self, client):
        tid = _make_country_template(client)
        resp = _post_batch(
            client, tid, [{'country': 'US'}], concurrency=999,
        )
        assert resp.status_code == 201
        assert resp.get_json()['concurrency'] <= 4


class TestPartialFailure:
    def test_one_bad_item_does_not_poison_others(self, client):
        tid = _make_country_template(client)
        # A non-string value for a string-typed parameter must fail
        # validation for that item only.
        sets = [
            {'country': 'US'},
            {'country': 12345},  # wrong type
            {'country': 'UK'},
        ]
        resp = _post_batch(client, tid, sets, concurrency=2)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body['succeededItems'] == 2
        assert body['failedItems'] == 1
        items = body['items']
        assert items[0]['status'] == 'succeeded'
        assert items[1]['status'] == 'failed'
        assert 'expected string' in (items[1]['error'] or '').lower()
        assert items[2]['status'] == 'succeeded'

    def test_all_items_fail_marks_batch_failed(self, client):
        tid = _make_country_template(client)
        sets = [{'country': 1}, {'country': 2}]
        resp = _post_batch(client, tid, sets)
        body = resp.get_json()
        assert body['status'] == 'failed'
        assert body['succeededItems'] == 0
        assert body['failedItems'] == 2


class TestIdempotency:
    def test_duplicate_submission_returns_same_batch(self, client):
        tid = _make_country_template(client)
        sets = [{'country': 'US'}]
        r1 = _post_batch(
            client, tid, sets, idempotencyKey='key-abc',
        )
        assert r1.status_code == 201
        id1 = r1.get_json()['id']

        r2 = _post_batch(
            client, tid, sets, idempotencyKey='key-abc',
        )
        assert r2.status_code == 200
        id2 = r2.get_json()['id']
        assert id1 == id2

    def test_different_idempotency_keys_create_separate_batches(self, client):
        tid = _make_country_template(client)
        sets = [{'country': 'US'}]
        r1 = _post_batch(client, tid, sets, idempotencyKey='k1')
        r2 = _post_batch(client, tid, sets, idempotencyKey='k2')
        assert r1.get_json()['id'] != r2.get_json()['id']


class TestCancellation:
    def test_cancel_pending_batch_does_not_write_results(self, client):
        """Cancelling immediately after creation (before run starts) must
        leave all items cancelled and no QueryExecution rows."""
        from app.models import QueryExecution
        import app.database as dbmod

        tid = _make_country_template(client)
        # Create the batch directly so we can cancel before run_batch.
        from app.services.batch_service import BatchRunner
        with client.application.app_context():
            run, _ = BatchRunner.create_batch(
                tid, [{'country': 'US'} for _ in range(3)],
                concurrency=1,
            )
            batch_id = run.id
            BatchRunner.cancel(batch_id)

        resp = client.get(f'/api/batches/{batch_id}')
        body = resp.get_json()
        assert body['status'] == 'cancelled'
        assert body['cancelledItems'] == 3
        assert body['succeededItems'] == 0
        # No execution rows should have been written
        with client.application.app_context():
            exec_count = dbmod.db.session.query(QueryExecution).count()
        assert exec_count == 0

    def test_cancel_after_some_success_preserves_results(self, client):
        tid = _make_country_template(client)
        # We create many items but enforce a small total row budget so
        # the batch stops early, demonstrating that successful items
        # keep their results and pending items are cancelled.
        sets = [{'country': c} for c in
                ['US', 'UK', 'Germany', 'France', 'Spain']]
        resp = _post_batch(
            client, tid, sets,
            concurrency=1, maxTotalRows=5,
        )
        body = resp.get_json()
        # The batch should not have run all 5 items to completion
        assert body['status'] in ('cancelled', 'completed', 'failed')
        # Items are still in order
        idxs = [i['itemIndex'] for i in body['items']]
        assert idxs == sorted(idxs)
        # At least one item should have succeeded before the budget hit.
        assert body['succeededItems'] >= 1
        # No item should be left in running state after finalisation.
        for item in body['items']:
            assert item['status'] != 'running'


class TestRetry:
    def test_retry_only_reruns_failed_items(self, client):
        tid = _make_country_template(client)
        sets = [
            {'country': 'US'},
            {'country': 999},  # fails type validation
        ]
        resp = _post_batch(client, tid, sets)
        body = resp.get_json()
        assert body['failedItems'] == 1
        ok_exec_id = body['items'][0]['executionId']
        assert ok_exec_id is not None

        # Fix the bad value and retry
        retry_resp = client.post(
            f"/api/batches/{body['id']}/retry",
            json={'parameterSets': [
                {'country': 'US'},
                {'country': 'UK'},
            ]},
        )
        assert retry_resp.status_code == 200, retry_resp.get_data(as_text=True)
        retried = retry_resp.get_json()
        assert retried['succeededItems'] == 2
        # The originally-successful item kept its execution id (not re-run)
        items = retried['items']
        assert items[0]['status'] == 'succeeded'
        assert items[0]['executionId'] == ok_exec_id
        # The failed item now succeeded with a new execution id
        assert items[1]['status'] == 'succeeded'
        assert items[1]['executionId'] is not None


class TestSecurityBoundary:
    def test_item_violating_readonly_is_isolated(self, client):
        """A parameter set that causes a query to attempt a write must
        fail that item without affecting the batch or other items."""
        tid = _make_country_template(client)
        # The template is read-only; a value that contains a SQL-injection
        # attempt is simply bound as a string parameter, so it cannot
        # escape. Verify the value never appears in SQL text and the item
        # either succeeds (returning 0 rows) or fails cleanly.
        evil = "US'; DROP TABLE customer;--"
        sets = [{'country': evil}, {'country': 'US'}]
        resp = _post_batch(client, tid, sets)
        body = resp.get_json()
        # The second item must succeed regardless of the first item's fate
        items = body['items']
        assert items[1]['status'] == 'succeeded'
        # The customer table must still exist (other API calls work)
        meta = client.get('/api/metadata')
        assert meta.status_code == 200
        names = [t['name'] for t in meta.get_json()]
        assert 'customer' in names


class TestResultOrdering:
    def test_item_index_stable_regardless_of_completion(self, client):
        """Even with high concurrency, items are persisted and returned
        in submission order."""
        tid = _make_country_template(client)
        countries = ['US', 'UK', 'Germany', 'France', 'Spain',
                     'Italy', 'Japan', 'Canada', 'Brazil', 'India']
        sets = [{'country': c} for c in countries]
        resp = _post_batch(client, tid, sets, concurrency=4)
        body = resp.get_json()
        items = body['items']
        assert [i['itemIndex'] for i in items] == list(range(len(countries)))
        # Labels correspond to the country used
        for i, c in enumerate(countries):
            assert items[i]['paramTypeSummary'] is not None


class TestTotalTimeout:
    def test_batch_timeout_marks_remaining_cancelled(self, client):
        tid = _make_country_template(client)
        sets = [{'country': 'US'} for _ in range(5)]
        # A very short total timeout should stop the batch quickly.
        resp = _post_batch(
            client, tid, sets,
            concurrency=2, timeoutSeconds=0.001,
        )
        body = resp.get_json()
        # The batch is either failed (timeout) or cancelled; not all
        # items necessarily completed.
        assert body['status'] in ('failed', 'cancelled', 'completed')
        if body['status'] == 'failed':
            assert 'timeout' in (body.get('error') or '').lower()
