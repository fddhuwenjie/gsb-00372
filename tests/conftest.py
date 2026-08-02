"""Shared pytest fixtures.

A single command from the repository root (``pytest``) collects every test.
Each test session gets its own temporary SQLite database -- no absolute
paths, no ``PYTHONPATH`` manipulation, no pre-started server, and no
dependency on a fixed ``sakila.db`` file.
"""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, 'backend')
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


@pytest.fixture()
def app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)
    try:
        from app import create_app
        flask_app = create_app(
            database_uri=f'sqlite:///{db_path}',
            seed=True,
        )
        flask_app.config.update(TESTING=True)
        yield flask_app
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def app_context(app):
    with app.app_context():
        yield app


@pytest.fixture()
def fixed_db(app):
    """
    A deterministic, small SQLite database for plan-normalisation tests.

    Unlike the seeded app (which uses random order dates), this fixture
    creates two tables with known content and a secondary index so that
    plan fingerprints are completely stable across runs. It proves that
    non-semantic AST changes do not produce version differences while
    real JOIN/filter/index changes do.
    """
    from sqlalchemy import text
    from app.database import db

    with app.app_context():
        db.session.execute(text('DROP TABLE IF EXISTS items'))
        db.session.execute(text('DROP TABLE IF EXISTS categories'))
        db.session.execute(text('''
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        '''))
        db.session.execute(text('''
            CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                category_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                price NUMERIC NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        '''))
        db.session.execute(text(
            'CREATE INDEX idx_items_category ON items(category_id)'
        ))
        db.session.execute(text(
            'CREATE INDEX idx_items_price ON items(price)'
        ))
        categories = [
            (1, 'Books'),
            (2, 'Music'),
            (3, 'Games'),
        ]
        db.session.execute(
            text('INSERT INTO categories (id, name) VALUES (:id, :name)'),
            [{'id': i, 'name': n} for i, n in categories],
        )
        items = [
            (1, 1, 'Novel', 9.99, 1),
            (2, 1, 'Atlas', 24.50, 1),
            (3, 2, 'Album', 12.00, 1),
            (4, 2, 'Single', 1.99, 0),
            (5, 3, 'Board Game', 39.99, 1),
            (6, 3, 'Card Game', 5.50, 1),
            (7, 3, 'Video Game', 59.99, 0),
            (8, 1, 'Comic', 4.99, 1),
        ]
        db.session.execute(
            text(
                'INSERT INTO items (id, category_id, name, price, active) '
                'VALUES (:id, :cid, :name, :price, :active)'
            ),
            [
                {'id': i, 'cid': c, 'name': n, 'price': p, 'active': a}
                for i, c, n, p, a in items
            ],
        )
        db.session.commit()
        yield app
