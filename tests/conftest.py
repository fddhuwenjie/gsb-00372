"""Shared pytest fixtures.

Running ``pytest`` from the repository root collects every test with an
isolated temporary SQLite database. No absolute paths, no PYTHONPATH, no
pre-started server and no reliance on the checked-in ``sakila.db`` are
required: the backend package is put on ``sys.path`` here and a throwaway
database file is created (and torn down) per test session.
"""
import os
import sys
import tempfile
import shutil

import pytest

# Make the backend package importable without PYTHONPATH.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, 'backend')
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(scope='session')
def temp_db_path():
    tmp_dir = tempfile.mkdtemp(prefix='vqb_test_db_')
    path = os.path.join(tmp_dir, 'test.db')
    yield path
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope='session')
def app(temp_db_path):
    # Point the app at the isolated temp DB before it is created/seeded.
    os.environ['DATABASE_URI'] = f'sqlite:///{temp_db_path}'
    from app import create_app
    application = create_app(config={'TESTING': True})
    yield application
    os.environ.pop('DATABASE_URI', None)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(scope='session')
def sqlite_conn(app, temp_db_path):
    """A raw read-only SQLite connection to the same seeded database, used by
    differential tests to run hand-written parameterized SQL."""
    import sqlite3
    conn = sqlite3.connect(temp_db_path)
    yield conn
    conn.close()
