from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    db.init_app(app)
    migrate.init_app(app, db)

    # Importar modelos para que SQLAlchemy y Alembic los detecten
    from app import models  # noqa: F401

    @app.route("/")
    def home():
        return "Hola Fuenti"

    return app