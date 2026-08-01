import os
from flask import Flask
from flask_cors import CORS
from app.database import db
from app.routes import api_bp


def create_app(config=None):
    """Application factory.

    The database URI (and every other setting) can be overridden via the
    ``config`` dict, so tests can run against an isolated temporary SQLite
    database without touching the development database.
    """
    app = Flask(__name__)

    os.makedirs(app.instance_path, exist_ok=True)
    default_db_path = os.path.join(app.instance_path, 'sakila.db')

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{default_db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['QUERY_TIMEOUT_MS'] = 5000
    app.config['MAX_ROWS'] = 1000
    app.config['SEED_DATA'] = True

    if config:
        app.config.update(config)

    CORS(app)
    db.init_app(app)

    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        from app import models
        db.create_all()
        if app.config.get('SEED_DATA', True):
            from app.seed import seed_data
            seed_data()
        # batches whose runner died with the previous process become
        # 'interrupted' and can be resumed via the retry endpoint
        from app.services.batch_service import BatchService
        BatchService.recover_interrupted()

    return app
