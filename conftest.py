import sys
import os
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app import create_app
from app.database import db as _db
from sqlalchemy import create_engine, text


@pytest.fixture(scope='session')
def app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    db_uri = f'sqlite:///{db_path}'

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': db_uri,
        'SEED_DATA': True,
        'QUERY_TIMEOUT': 5,
        'MAX_ROWS': 1000,
    })

    yield app

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def app_context(app):
    with app.app_context():
        yield


@pytest.fixture(scope='session')
def client(app):
    return app.test_client()


@pytest.fixture(scope='session')
def db_engine(app):
    with app.app_context():
        engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
        yield engine
        engine.dispose()


@pytest.fixture
def db_connection(db_engine):
    conn = db_engine.connect()
    yield conn
    conn.close()
