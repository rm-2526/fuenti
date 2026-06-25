from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
from flask_login import LoginManager
from flask_login import LoginManager, login_required
from flask import Flask, render_template

from app.config import Config

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Inicia sesión para acceder a esta página."
login_manager.login_message_category = "warning"


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Importar modelos para que Alembic los detecte
    from app import models  # noqa: F401

    # user_loader: cómo recuperar un Facilitador desde el id guardado en la sesión
    @login_manager.user_loader
    def load_user(user_id: str):
        from app.models import Facilitador
        return db.session.get(Facilitador, int(user_id))

    # Blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.evaluaciones import bp as evaluaciones_bp
    app.register_blueprint(evaluaciones_bp)

    from app.participante import bp as participante_bp
    app.register_blueprint(participante_bp)

    @app.route("/")
    def index():
        return "Hola Fuenti"
    
    @app.route("/dashboard")
    @login_required
    def dashboard():
        from flask_login import current_user
        return render_template("dashboard.html", nombre=current_user.nombre)

    return app