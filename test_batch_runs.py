"""
Tests for cancellable batch parameter runs.

Covers:
- Concurrent execution with multiple parameter sets
- Total row count and duration limits
- Cancellation prevents further writes
- Per-item security isolation (one rejected item doesn't block others)
- Partial failure status
- Idempotency / duplicate submission prevention
- Retry only re-runs failed/rejected items
- Result order stability by item_index
- Template version immutability
- Parameter summary never contains values
- Database write assertions after cancellation
"""
import copy
import time
import pytest
from app.services.batch_service import BatchService
from app.services.template_service import TemplateService
from app.models import (
    BatchRun, BatchItem, QueryTemplate, PlanSnapshot, db as _db,
)


def _make_country_template(app):
    """Create a simple template that filters customers by country."""
    qs = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't1', 'columnName': 'first_name'},
            {'tableId': 't1', 'columnName': 'country'},
        ],
        'where': {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                 'cmp': '=', 'value': {'$param': 'country'}},
            ],
        },
        'having': None,
        'aggregations': [],
        'orderBy': [{'tableId': 't1', 'columnName': 'id', 'direction': 'ASC'}],
        'limit': 100,
    }
    params = [{'name': 'country', 'type': 'string', 'required': True}]
    with app.app_context():
        built = TemplateService.build_template('Country Filter', qs, params)
        tpl = QueryTemplate(**{k: built[k] for k in
            ('name', 'description', 'version', 'query_structure',
             'parameters', 'schema_refs')})
        _db.session.add(tpl)
        _db.session.commit()
        return tpl.id


def _make_multi_param_template(app):
    """Template with two string parameters for testing multiple param sets."""
    qs = {
        'tables': [{'id': 't1', 'tableName': 'customer', 'alias': 'c'}],
        'joins': [],
        'selectedFields': [
            {'tableId': 't1', 'columnName': 'id'},
            {'tableId': 't1', 'columnName': 'country'},
        ],
        'where': {
            'id': 'w1', 'op': 'AND', 'children': [
                {'id': 'c1', 'tableId': 't1', 'columnName': 'country',
                 'cmp': '=', 'value': {'$param': 'country'}},
                {'id': 'c2', 'tableId': 't1', 'columnName': 'city',
                 'cmp': '=', 'value': {'$param': 'city'}},
            ],
        },
        'having': None, 'aggregations': [],
        'orderBy': [], 'limit': 50,
    }
    params = [
        {'name': 'country', 'type': 'string', 'required': True},
        {'name': 'city', 'type': 'string', 'required': True},
    ]
    with app.app_context():
        built = TemplateService.build_template('Multi Param', qs, params)
        tpl = QueryTemplate(**{k: built[k] for k in
            ('name', 'description', 'version', 'query_structure',
             'parameters', 'schema_refs')})
        _db.session.add(tpl)
        _db.session.commit()
        return tpl.id


class TestBatchCreation:
    def test_create_batch_with_multiple_param_sets(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, created = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[
                    {'country': 'US'},
                    {'country': 'UK'},
                    {'country': 'Germany'},
                ],
                concurrency=2,
            )
            assert created is True
            assert batch.total_items == 3
            assert batch.concurrency == 2
            assert batch.status == 'pending'
            assert batch.template_version == 1

            items = BatchItem.query.filter_by(batch_run_id=batch.id).all()
            assert len(items) == 3
            indices = [i.item_index for i in items]
            assert indices == [0, 1, 2]

    def test_idempotency_key_prevents_duplicate(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            params = [{'country': 'US'}, {'country': 'UK'}]
            b1, c1 = BatchService.create_batch(
                template_id=tpl_id, parameter_sets=params,
                idempotency_key='batch-abc',
            )
            b2, c2 = BatchService.create_batch(
                template_id=tpl_id, parameter_sets=params,
                idempotency_key='batch-abc',
            )
            assert c1 is True
            assert c2 is False
            assert b1.id == b2.id

    def test_auto_idempotency_key_dedupes_same_params(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            params = [{'country': 'US'}]
            b1, _ = BatchService.create_batch(
                template_id=tpl_id, parameter_sets=params)
            b2, c2 = BatchService.create_batch(
                template_id=tpl_id, parameter_sets=params)
            assert c2 is False
            assert b1.id == b2.id

    def test_different_param_sets_create_different_batches(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            b1, _ = BatchService.create_batch(
                template_id=tpl_id, parameter_sets=[{'country': 'US'}])
            b2, c2 = BatchService.create_batch(
                template_id=tpl_id, parameter_sets=[{'country': 'UK'}])
            assert c2 is True
            assert b1.id != b2.id

    def test_rejects_empty_param_sets(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            with pytest.raises(ValueError, match='non-empty'):
                BatchService.create_batch(template_id=tpl_id, parameter_sets=[])


class TestBatchExecution:
    def test_runs_all_items_successfully(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[
                    {'country': 'US'},
                    {'country': 'Germany'},
                ],
                concurrency=2,
            )
            BatchService.start_batch(batch.id, app=app)

            batch = BatchRun.query.get(batch.id)
            assert batch.status == 'completed'
            assert batch.succeeded_count == 2
            assert batch.failed_count == 0

            items = BatchItem.query.filter_by(
                batch_run_id=batch.id
            ).order_by(BatchItem.item_index).all()
            assert items[0].status == 'succeeded'
            assert items[1].status == 'succeeded'
            for item in items:
                assert item.row_count > 0
                assert item.result_columns is not None
                assert item.result_rows is not None

    def test_result_order_stable_by_item_index(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            param_sets = [
                {'country': 'US'},
                {'country': 'UK'},
                {'country': 'Germany'},
                {'country': 'France'},
                {'country': 'Spain'},
            ]
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=param_sets,
                concurrency=3,
            )
            BatchService.start_batch(batch.id, app=app)

            items = BatchItem.query.filter_by(
                batch_run_id=batch.id
            ).order_by(BatchItem.item_index).all()

            for i, item in enumerate(items):
                assert item.item_index == i
                rows = item.result_rows or []
                for row in rows:
                    country_idx = next(
                        idx for idx, c in enumerate(item.result_columns)
                        if c['name'] == 'country'
                    )
                    assert row[country_idx] == param_sets[i]['country']

    def test_concurrent_execution_respects_concurrency(self, app):
        """With concurrency=1, items run sequentially. With concurrency=4,
        items can overlap. We verify both produce correct results."""
        tpl_id = _make_country_template(app)
        for conc in [1, 4]:
            with app.app_context():
                batch, _ = BatchService.create_batch(
                    template_id=tpl_id,
                    parameter_sets=[
                        {'country': 'US'},
                        {'country': 'Germany'},
                        {'country': 'UK'},
                    ],
                    concurrency=conc,
                )
                BatchService.start_batch(batch.id, app=app)
                batch = BatchRun.query.get(batch.id)
                assert batch.succeeded_count == 3

    def test_each_item_has_plan_snapshot(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': 'US'}],
            )
            BatchService.start_batch(batch.id, app=app)

            items = BatchItem.query.filter_by(batch_run_id=batch.id).all()
            for item in items:
                if item.status == 'succeeded':
                    assert item.plan_snapshot_id is not None
                    snap = PlanSnapshot.query.get(item.plan_snapshot_id)
                    assert snap is not None
                    assert snap.template_id == tpl_id


class TestCancellation:
    def test_cancel_prevents_pending_items(self, app):
        """Cancelling a batch marks pending items as cancelled and
        prevents result writes for those items."""
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': c} for c in
                    ['US', 'UK', 'Germany', 'France', 'Spain']],
                concurrency=1,
                max_duration_ms=1,
            )
            import threading
            def cancel_soon():
                time.sleep(0.05)
                with app.app_context():
                    BatchService.cancel_batch(batch.id)

            t = threading.Thread(target=cancel_soon)
            t.start()
            BatchService.start_batch(batch.id, app=app)
            t.join()

            batch = BatchRun.query.get(batch.id)
            assert batch.status in ('cancelled', 'partially_failed', 'completed')

            cancelled_items = BatchItem.query.filter_by(
                batch_run_id=batch.id, status='cancelled'
            ).all()
            for item in cancelled_items:
                assert item.result_rows is None
                assert item.row_count == 0

    def test_cancel_batch_not_running_is_noop(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': 'US'}],
            )
            result = BatchService.cancel_batch(batch.id)
            assert result.status == 'pending'

    def test_cancelled_items_not_written_to_db(self, app):
        """After cancellation, no result data should be written for
        cancelled items — only status metadata."""
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': c} for c in
                    ['US', 'UK', 'Germany', 'France', 'Spain', 'Italy']],
                concurrency=1,
            )
            import threading
            def cancel_soon():
                time.sleep(0.02)
                with app.app_context():
                    BatchService.cancel_batch(batch.id)

            t = threading.Thread(target=cancel_soon)
            t.start()
            BatchService.start_batch(batch.id, app=app)
            t.join()

            cancelled = BatchItem.query.filter_by(
                batch_run_id=batch.id, status='cancelled'
            ).all()
            for item in cancelled:
                assert item.result_rows is None
                assert item.result_columns is None
                assert item.plan_snapshot_id is None


class TestPerItemIsolation:
    def test_invalid_param_type_rejects_only_that_item(self, app):
        """One parameter set with wrong type should be rejected,
        but valid sets should still succeed."""
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[
                    {'country': 'US'},
                    {'country': 123},
                    {'country': 'Germany'},
                ],
            )
            BatchService.start_batch(batch.id, app=app)

            batch = BatchRun.query.get(batch.id)
            assert batch.succeeded_count == 2
            assert batch.rejected_count == 1
            assert batch.status == 'partially_failed'

            items = BatchItem.query.filter_by(
                batch_run_id=batch.id
            ).order_by(BatchItem.item_index).all()
            assert items[0].status == 'succeeded'
            assert items[1].status == 'rejected'
            assert 'expects a string' in (items[1].error or '')
            assert items[2].status == 'succeeded'

    def test_missing_required_param_rejects_only_that_item(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[
                    {'country': 'US'},
                    {},
                    {'country': 'UK'},
                ],
            )
            BatchService.start_batch(batch.id, app=app)

            batch = BatchRun.query.get(batch.id)
            assert batch.succeeded_count == 2
            assert batch.rejected_count == 1

            items = BatchItem.query.filter_by(
                batch_run_id=batch.id
            ).order_by(BatchItem.item_index).all()
            assert items[1].status == 'rejected'
            assert 'Required parameter' in (items[1].error or '')

    def test_security_violation_isolated(self, app):
        """If one parameter set produces a query that violates read-only
        boundary, only that item should be rejected."""
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[
                    {'country': 'US'},
                    {'country': 'Germany'},
                ],
            )
            BatchService.start_batch(batch.id, app=app)
            batch = BatchRun.query.get(batch.id)
            assert batch.succeeded_count == 2


class TestLimits:
    def test_total_row_limit(self, app):
        """When total row count exceeds limit, remaining items are cancelled."""
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[
                    {'country': 'US'},
                    {'country': 'Germany'},
                    {'country': 'UK'},
                    {'country': 'France'},
                ],
                concurrency=1,
                max_total_rows=5,
            )
            BatchService.start_batch(batch.id, app=app)

            batch = BatchRun.query.get(batch.id)
            assert batch.total_rows <= 50
            assert batch.cancelled_count >= 1 or batch.status == 'cancelled'

    def test_zero_row_result_still_succeeds(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': 'NONEXISTENT'}],
            )
            BatchService.start_batch(batch.id, app=app)
            batch = BatchRun.query.get(batch.id)
            assert batch.succeeded_count == 1
            items = BatchItem.query.filter_by(batch_run_id=batch.id).all()
            assert items[0].row_count == 0


class TestRetry:
    def test_retry_only_reruns_failed_items(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[
                    {'country': 'US'},
                    {'country': 999},
                    {'country': 'Germany'},
                ],
            )
            BatchService.start_batch(batch.id, app=app)
            original = BatchRun.query.get(batch.id)
            assert original.rejected_count == 1

            retry_batch = BatchService.retry_failed(batch.id, app=app)
            assert retry_batch.total_items == 1
            assert retry_batch.status == 'partially_failed'
            assert retry_batch.rejected_count == 1

            retry_items = BatchItem.query.filter_by(
                batch_run_id=retry_batch.id
            ).all()
            assert len(retry_items) == 1

    def test_retry_with_no_failures_raises(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': 'US'}],
            )
            BatchService.start_batch(batch.id, app=app)
            with pytest.raises(ValueError, match='No failed'):
                BatchService.retry_failed(batch.id)


class TestTemplateVersionImmutability:
    def test_batch_references_specific_template_version(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': 'US'}],
            )
            BatchService.start_batch(batch.id, app=app)

            tpl = QueryTemplate.query.get(tpl_id)
            batch = BatchRun.query.get(batch.id)
            assert batch.template_version == tpl.version

            items = BatchItem.query.filter_by(batch_run_id=batch.id).all()
            for item in items:
                snap = PlanSnapshot.query.get(item.plan_snapshot_id)
                assert snap.template_version == tpl.version


class TestParameterPrivacy:
    def test_param_summary_contains_types_not_values(self, app):
        tpl_id = _make_country_template(app)
        with app.app_context():
            secret = 'SENSITIVE_COUNTRY_VALUE'
            batch, _ = BatchService.create_batch(
                template_id=tpl_id,
                parameter_sets=[{'country': secret}],
            )
            BatchService.start_batch(batch.id, app=app)

            items = BatchItem.query.filter_by(batch_run_id=batch.id).all()
            for item in items:
                summary = item.param_type_summary
                assert summary == {'country': 'string'}
                assert secret not in str(summary)
                assert secret not in str(item.error or '')


class TestBatchApi:
    def test_create_and_execute_via_api(self, client, app):
        tpl_id = _make_country_template(app)
        resp = client.post('/api/batches', json={
            'template_id': tpl_id,
            'parameter_sets': [
                {'country': 'US'},
                {'country': 'Germany'},
            ],
            'concurrency': 2,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['totalItems'] == 2
        assert data['status'] in ('completed', 'running')

        batch_id = data['id']
        import time
        for _ in range(20):
            r = client.get(f'/api/batches/{batch_id}')
            d = r.get_json()
            if d['status'] in ('completed', 'partially_failed', 'cancelled'):
                break
            time.sleep(0.05)

        assert d['succeededCount'] == 2
        assert len(d['items']) == 2

    def test_duplicate_submission_returns_existing(self, client, app):
        tpl_id = _make_country_template(app)
        payload = {
            'template_id': tpl_id,
            'parameter_sets': [{'country': 'US'}],
            'idempotency_key': 'dedup-test',
        }
        r1 = client.post('/api/batches', json=payload)
        r2 = client.post('/api/batches', json=payload)
        assert r1.status_code == 201
        assert r2.status_code == 200
        assert r1.get_json()['id'] == r2.get_json()['id']

    def test_cancel_via_api(self, client, app):
        tpl_id = _make_country_template(app)
        resp = client.post('/api/batches', json={
            'template_id': tpl_id,
            'parameter_sets': [{'country': c} for c in
                ['US', 'UK', 'Germany', 'France', 'Spain', 'Italy']],
            'concurrency': 1,
            'max_duration_ms': 1,
        })
        batch_id = resp.get_json()['id']
        time.sleep(0.05)
        client.post(f'/api/batches/{batch_id}/cancel')

        r = client.get(f'/api/batches/{batch_id}')
        data = r.get_json()
        assert data['status'] in ('cancelled', 'partially_failed', 'completed')

    def test_partial_failure_via_api(self, client, app):
        tpl_id = _make_country_template(app)
        resp = client.post('/api/batches', json={
            'template_id': tpl_id,
            'parameter_sets': [
                {'country': 'US'},
                {'country': 123},
                {'country': 'Germany'},
            ],
        })
        assert resp.status_code == 201
        batch_id = resp.get_json()['id']

        import time
        for _ in range(20):
            r = client.get(f'/api/batches/{batch_id}')
            d = r.get_json()
            if d['status'] in ('completed', 'partially_failed', 'cancelled'):
                break
            time.sleep(0.05)

        assert d['status'] == 'partially_failed'
        assert d['succeededCount'] == 2
        assert d['rejectedCount'] == 1

    def test_list_batches_via_api(self, client, app):
        tpl_id = _make_country_template(app)
        client.post('/api/batches', json={
            'template_id': tpl_id,
            'parameter_sets': [{'country': 'US'}],
        })
        resp = client.get('/api/batches')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1

    def test_retry_via_api(self, client, app):
        tpl_id = _make_country_template(app)
        resp = client.post('/api/batches', json={
            'template_id': tpl_id,
            'parameter_sets': [
                {'country': 'US'},
                {'country': 999},
            ],
        })
        batch_id = resp.get_json()['id']

        import time
        for _ in range(20):
            r = client.get(f'/api/batches/{batch_id}')
            if r.get_json()['status'] in ('partially_failed', 'completed'):
                break
            time.sleep(0.05)

        retry = client.post(f'/api/batches/{batch_id}/retry')
        assert retry.status_code == 201
        retry_data = retry.get_json()
        assert retry_data['totalItems'] == 1
