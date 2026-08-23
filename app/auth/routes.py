from flask import current_app, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse

from app import db
from app.auth import bp
from app.models import Facilitador
from app.utils.activacion import ACTIVACION_MAX_AGE, huella, leer_token


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        facilitador = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == email)
        )

        if facilitador is None or not facilitador.check_password(password):
            flash("Credenciales inválidas.", "danger")
            return redirect(url_for("auth.login"))

        if not facilitador.activo:
            flash("Esta cuenta está desactivada. Contacta a un administrador.", "danger")
            return redirect(url_for("auth.login"))

        login_user(facilitador)

        # Protección open-redirect: solo aceptar "next" si es relativo
        next_page = request.args.get("next")
        if not next_page or urlparse(next_page).netloc != "":
            next_page = url_for("dashboard")
        return redirect(next_page)

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/activar/<token>", methods=["GET", "POST"])
def activar(token):
    """Establece la contraseña a partir de un enlace firmado.

    Cubre dos flujos con la misma máquina: la activación de una cuenta recién
    creada por el administrador y el restablecimiento de una contraseña
    olvidada. El enlace se invalida solo al usarse, porque lleva dentro la
    huella del password_hash vigente y ese hash cambia al guardar la nueva
    clave (ver app/utils/activacion.py).

    Ruta pública a propósito: quien llega aquí todavía no puede iniciar sesión.
    La autorización la da el token, no la sesión.
    """
    invalido = "El enlace no es válido o ya expiró. Solicita uno nuevo."

    datos = leer_token(token, current_app.config["SECRET_KEY"], ACTIVACION_MAX_AGE)
    if datos is None:
        flash(invalido, "danger")
        return redirect(url_for("auth.login"))

    facilitador = db.session.get(Facilitador, datos["id"])
    # Cuenta inexistente o desactivada: mismo mensaje, para no revelar cuáles
    # correos existen en el sistema.
    if facilitador is None or not facilitador.activo:
        flash(invalido, "danger")
        return redirect(url_for("auth.login"))

    # Huella distinta = la contraseña ya cambió, con este enlace o con otro.
    if datos["h"] != huella(facilitador.password_hash):
        flash("Este enlace ya fue utilizado. Solicita uno nuevo.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirmacion = request.form.get("confirmacion", "")

        if len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "danger")
        elif password != confirmacion:
            flash("Las contraseñas no coinciden.", "danger")
        else:
            facilitador.set_password(password)
            db.session.commit()
            flash("Contraseña establecida. Ya puedes iniciar sesión.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/activar.html", facilitador=facilitador, token=token)
