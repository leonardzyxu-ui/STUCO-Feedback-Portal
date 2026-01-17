from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
cors = CORS()


def init_extensions(app):
    db.init_app(app)
    cors.init_app(app)
