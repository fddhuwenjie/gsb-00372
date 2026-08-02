import os

from flask import Flask
from flask_cors import CORS

from app.database import db
from app.routes import api_bp


def create_app(database_uri=None, seed=True):
    app = Flask(__name__)

    uri = (
        database_uri
        or os.environ.get('DATABASE_URL')
        or os.environ.get('SQLALCHEMY_DATABASE_URI')
        or 'sqlite:///' + os.path.join(
            os.path.abspath(os.path.dirname(__file__)), '..', 'instance', 'sakila.db'
        )
    )
    app.config['SQLALCHEMY_DATABASE_URI'] = uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'timeout': 10},
    }

    CORS(app)
    db.init_app(app)

    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        from app import models  # noqa: F401  ensure models are registered
        db.create_all()
        if seed:
            from app.seed import seed_data
            seed_data()

    return app
