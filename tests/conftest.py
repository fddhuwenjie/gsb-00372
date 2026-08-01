"""Shared fixtures: every test runs against an isolated temporary SQLite
database created in a pytest tmp dir. No absolute paths, no running server,
no shared sakila.db.
"""
import pytest
from sqlalchemy import text

from app import create_app
from app.database import db as _db


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp('sqlite')
    db_path = db_dir / 'test.db'
    application = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'QUERY_TIMEOUT_MS': 5000,
        'MAX_ROWS': 1000,
    })
    # Extra rows exercising NULL semantics (not part of the default seed).
    with application.app_context():
        _db.session.execute(text(
            "INSERT INTO supplier (name, contact_name, country, phone) "
            "VALUES ('NullContact Ltd', NULL, NULL, NULL)"
        ))
        _db.session.execute(text(
            "INSERT INTO employee (first_name, last_name, position, department, hire_date) "
            "VALUES ('Noah', 'Unset', NULL, NULL, '2021-06-01')"
        ))
        _db.session.execute(text(
            "INSERT INTO \"order\" (customer_id, employee_id, order_date, total_amount, status) "
            "VALUES (1, NULL, '2025-06-01', 10.0, 'pending')"
        ))
        _db.session.commit()
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def connection(app):
    """A raw SQLAlchemy connection to the temporary test database, used to
    run hand-written reference SQL in the differential tests."""
    with app.app_context():
        with _db.engine.connect() as conn:
            yield conn
