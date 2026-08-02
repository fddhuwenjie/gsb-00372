import os
from flask import Flask
from flask_cors import CORS
from app.database import db
from app.routes import api_bp

# Absolute default path so the app works regardless of the current working
# directory, while remaining overridable for tests via config / env.
INSTANCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance')
DEFAULT_DB_PATH = os.path.abspath(os.path.join(INSTANCE_DIR, 'sakila.db'))


def create_app(config=None, seed=True):
    app = Flask(__name__)

    db_uri = os.environ.get('DATABASE_URI')
    if not db_uri:
        db_uri = f'sqlite:///{DEFAULT_DB_PATH}'
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # Batch runs execute items on background threads, each with its own session.
    # Allow cross-thread SQLite connections and wait on the write lock instead of
    # failing fast with "database is locked".
    if db_uri.startswith('sqlite'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {'check_same_thread': False, 'timeout': 30},
        }

    if config:
        app.config.update(config)

    CORS(app)
    db.init_app(app)

    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        # Ensure the instance directory exists for file-backed SQLite.
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        if uri.startswith('sqlite:///'):
            path = uri[len('sqlite:///'):]
            if path and path != ':memory:':
                os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

        from app import models  # noqa: F401
        db.create_all()
        if seed:
            from app.seed import seed_data
            seed_data()

    return app
