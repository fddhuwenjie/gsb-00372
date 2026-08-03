import os
from flask import Flask
from flask_cors import CORS
from app.database import db
from app.routes import api_bp

def create_app(config=None):
    app = Flask(__name__)
    
    db_uri = os.environ.get('DATABASE_URL') or 'sqlite:///sakila.db'
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['QUERY_TIMEOUT'] = int(os.environ.get('QUERY_TIMEOUT', '5'))
    app.config['MAX_ROWS'] = int(os.environ.get('MAX_ROWS', '1000'))
    
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
    
    return app
