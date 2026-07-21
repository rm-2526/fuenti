from datetime import timezone
from zoneinfo import ZoneInfo

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

# Zona horaria de Chile. Se usa America/Santiago (y no un "-4" fijo) para que
# el cambio de horario de verano se ajuste solo.
ZONA_CHILE = ZoneInfo("America/Santiago")


def hora_local(dt, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Convierte una fecha/hora guardada en UTC a hora de Chile y la formatea.

    Las fechas se guardan en UTC. Al leerlas de la BD suelen venir 'ingenuas'
    (sin zona); aca se asume que son UTC y se convierten a America/Santiago.
    Devuelve "" si dt es None (p. ej. una sesion que aun no se cierra).
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZONA_CHILE).strftime(fmt)


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Filtro de plantilla: {{ fecha | hora_local }} muestra la hora en Chile.
    app.jinja_env.filters["hora_local"] = hora_local

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

    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        return "Hola Fuenti"
    
    @app.route("/dashboard")
    @login_required
    def dashboard():
        from flask_login import current_user
        return render_template("dashboard.html", nombre=current_user.nombre)

    return app