from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
from flask_login import LoginManager
from flask_login import LoginManager, login_required
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, render_template, request, flash, redirect, url_for

from app.config import Config

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Inicia sesión para acceder a esta página."
login_manager.login_message_category = "warning"

# Limitador de peticiones para los formularios publicos de escritura.
#
# Almacenamiento en memoria a proposito: Render free corre UN worker
# (gunicorn --threads 4, sin -w), asi que todos los threads comparten el mismo
# proceso y el mismo contador. No hace falta Redis. El costo es que los
# contadores se pierden cuando Render duerme el servicio, lo que no importa: un
# atacante no gana nada esperando quince minutos entre tandas.
#
# default_limits vacio: NADA queda limitado salvo lo que se marque de forma
# explicita con @limiter.limit. Un limite global golpearia el flujo del
# participante, donde una sala entera de capacitacion sale por la MISMA IP
# publica y treinta personas ingresando a la vez son trafico legitimo.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    # Explicito para dejar constancia de que la eleccion es deliberada y no un
    # descuido (sin este parametro la libreria emite un warning al arrancar).
    storage_uri="memory://",
)

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

    # Render sirve la app detras de un proxy. Sin esto request.remote_addr es
    # la IP del proxy y NO la del visitante, de modo que el limitador contaria
    # a todo el mundo como un solo cliente y bloquearia a usuarios legitimos
    # apenas otro gastara la cuota. Es obligatorio para que el rate limiting
    # sirva de algo; x_for=1 porque hay un unico proxy por delante.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    limiter.init_app(app)

    # Filtro de plantilla: {{ fecha | hora_local }} muestra la hora en Chile.
    app.jinja_env.filters["hora_local"] = hora_local

    # Importar modelos para que Alembic los detecte
    from app import models  # noqa: F401
    # Registra el listener que crea las vistas de BD tras db.create_all().
    from app import vistas  # noqa: F401

    # user_loader: cómo recuperar un Facilitador desde el id guardado en la sesión
    @login_manager.user_loader
    def load_user(user_id: str):
        from app.models import Facilitador
        facilitador = db.session.get(Facilitador, int(user_id))
        # Un facilitador desactivado deja de estar autenticado de inmediato
        # (su sesión existente se corta en la siguiente petición).
        if facilitador is None or not facilitador.activo:
            return None
        return facilitador

    # Blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.evaluaciones import bp as evaluaciones_bp
    app.register_blueprint(evaluaciones_bp)

    from app.participante import bp as participante_bp
    app.register_blueprint(participante_bp)

    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    # Comandos de consola (flask analisis-backfill ...)
    from app.cli import registrar_cli
    registrar_cli(app)

    @app.route("/")
    def index():
        return render_template("index.html")
    
    @app.route("/ayuda")
    def ayuda():
        """Manual del facilitador. Pagina fija, sin estado: es el destino del
        modal de bienvenida y del enlace del menu.

        Publica a proposito. No consulta la base de datos ni recibe parametros:
        no hay dato de nadie que proteger, y las capturas que muestra son de la
        interfaz. Abrirla permite citarla desde el informe, compartirla por
        enlace y que un facilitador la lea antes de que le creen la cuenta."""
        return render_template("ayuda.html")

    @app.route("/dashboard")
    @login_required
    def dashboard():
        from flask_login import current_user
        # Badge de "algo espera revisión" en la tarjeta de Administración.
        # Solo se calcula para un admin: un facilitador normal no ve el panel
        # y no tiene por qué pagar el costo de esta consulta.
        pendientes_admin = 0
        if current_user.es_admin:
            from app.models import Facilitador, SolicitudEliminacion
            pendientes_facilitadores = db.session.scalar(
                db.select(db.func.count())
                .select_from(Facilitador)
                .where(Facilitador.aprobado.is_(False))
            )
            pendientes_eliminaciones = db.session.scalar(
                db.select(db.func.count())
                .select_from(SolicitudEliminacion)
                .where(SolicitudEliminacion.estado == "pendiente")
            )
            pendientes_admin = pendientes_facilitadores + pendientes_eliminaciones
        return render_template(
            "dashboard.html",
            nombre=current_user.nombre,
            pendientes_admin=pendientes_admin,
        )

    @app.route("/privacidad", methods=["GET", "POST"])
    @limiter.limit("3 per hour; 10 per day", methods=["POST"])
    def privacidad():
        """Página pública de privacidad y solicitud de eliminación de datos.

        Sin sesión, y sin dato de nadie salvo lo que la propia persona escribe
        en el formulario. El RUT nunca se guarda: solo su hash, calculado con
        la misma función que usa el ingreso de un participante
        (app/utils/rut.hash_rut), así que una solicitud aquí y una
        participación allá quedan enlazadas por el mismo valor sin que en
        ningún punto quede el RUT en texto plano.

        La respuesta de éxito es siempre la misma exista o no una coincidencia
        real: decir "no encontramos datos con ese RUT" convertiría el
        formulario en un instrumento para confirmar si alguien participó de
        una capacitación, que es exactamente el tipo de filtración que esta
        página existe para evitar. Mismo razonamiento que auth.solicitud.
        """
        from app.models import SolicitudEliminacion
        from app.utils.rut import validar_rut, es_rut_bloqueado, hash_rut

        if request.method == "POST":
            # Trampa para bots ("honeypot"). El campo 'website' esta fuera de
            # la pantalla y fuera del orden de tabulacion, asi que un navegador
            # manejado por una persona nunca lo envia con contenido; un bot que
            # parsea el HTML y rellena todo lo que encuentra, si.
            #
            # Se responde con el MISMO mensaje de exito de siempre y sin
            # guardar nada. Si se rechazara de forma visible, el autor del bot
            # veria el fallo, encontraria el campo escondido y ajustaria su
            # script: la trampa se quema. Ademas es coherente con la regla que
            # ya rige esta pagina —la respuesta no cambia nunca— por la que no
            # sirve para averiguar nada sobre quien esta en el sistema.
            if request.form.get("website"):
                flash(
                    "Recibimos tu solicitud. Un administrador la revisará y tus "
                    "datos serán eliminados si corresponde.",
                    "success",
                )
                return redirect(url_for("privacidad"))

            rut = request.form.get("rut", "").strip()
            contacto = request.form.get("contacto", "").strip()

            if not validar_rut(rut):
                flash("Revisa el RUT: no corresponde a uno válido.", "danger")
                return render_template("privacidad.html", rut=rut, contacto=contacto)

            # Mismo segundo chequeo que el ingreso de participante (ver
            # app/participante/routes.py): un RUT como 11.111.111-1 pasa el
            # módulo 11 pero es uno de los que se usan como ejemplo y no se
            # acepta como identidad real. Debe rechazarse aquí también, o
            # cualquiera podría crear una solicitud "de prueba" que nunca
            # correspondería a un participante de verdad.
            if es_rut_bloqueado(rut):
                flash(
                    "Ese RUT no se acepta: es uno de los que se usan como "
                    "ejemplo. Ingresa tu RUT real.",
                    "danger",
                )
                return render_template("privacidad.html", rut=rut, contacto=contacto)

            salt = app.config["RUT_SALT"]
            solicitud = SolicitudEliminacion(
                identificador_hash=hash_rut(rut, salt),
                contacto=contacto[:255] if contacto else None,
            )
            db.session.add(solicitud)
            db.session.commit()

            flash(
                "Recibimos tu solicitud. Un administrador la revisará y tus "
                "datos serán eliminados si corresponde.",
                "success",
            )
            return redirect(url_for("privacidad"))

        return render_template("privacidad.html", rut="", contacto="")

    @app.errorhandler(429)
    def demasiadas_peticiones(e):
        """Respuesta al superar un limite de peticiones.

        Sin esto Flask-Limiter devuelve una pagina de Werkzeug sin el layout
        del sitio. Se devuelve a la pantalla de login con un flash, que es el
        camino de vuelta correcto desde los tres formularios limitados.
        """
        flash(
            "Demasiados intentos. Espera unos minutos antes de volver a "
            "intentarlo.",
            "warning",
        )
        return redirect(url_for("auth.login"))

    return app