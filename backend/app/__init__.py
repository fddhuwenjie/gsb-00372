from flask import Flask
from flask_cors import CORS
from app.database import db
from app.routes import api_bp

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sakila.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    CORS(app)
    db.init_app(app)
    
    app.register_blueprint(api_bp, url_prefix='/api')
    
    with app.app_context():
        from app import models
        db.create_all()
        from app.seed import seed_data
        seed_data()
    
    return app
