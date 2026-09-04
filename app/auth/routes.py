import secrets

from flask import current_app, render_template, redirect, url_for, request, flash
from sqlalchemy.exc import IntegrityError
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse

from app import db, limiter
from app.auth import bp
from app.models import Facilitador
from app.utils.activacion import ACTIVACION_MAX_AGE, huella, leer_token


@bp.route("/login", methods=["GET", "POST"])
# Solo el POST se limita: si se limitara tambien el GET, alguien que
# simplemente recarga la pantalla de login se autobloquearia. Frena la fuerza
# bruta, que ademas de un riesgo de credenciales es un riesgo de disponibilidad:
# check_password corre PBKDF2 con muchas iteraciones, asi que cada intento
# consume CPU de un unico worker.
@limiter.limit("5 per minute; 30 per hour", methods=["POST"])
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

        # Va ANTES de `activo` porque son estados distintos y el mensaje debe
        # decir la verdad: a quien todavia no fue aprobado no se le puede decir
        # que su cuenta esta desactivada, porque nunca la tuvo. En la practica
        # esta rama casi no se alcanza (una solicitud pendiente tiene una clave
        # aleatoria que nadie conoce, asi que antes falla check_password), pero
        # el estado no debe depender de esa coincidencia.
        if not facilitador.aprobado:
            flash(
                "Tu solicitud de acceso todavía está en revisión.",
                "info",
            )
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


@bp.route("/solicitud", methods=["GET", "POST"])
# Nadie solicita legitimamente tres cuentas por hora desde la misma IP. El
# riesgo aca no es de acceso —una solicitud no da acceso a nada— sino de
# saturacion: cada envio crea una fila que un administrador tiene que revisar a
# mano, y llenar ese panel de basura lo vuelve inutilizable.
@limiter.limit("3 per hour; 10 per day", methods=["POST"])
def solicitud():
    """Solicitud publica de una cuenta de facilitador.

    No crea acceso: crea un registro pendiente que un administrador aprueba o
    rechaza. La cuenta nace con `aprobado=False` y una clave aleatoria que nadie
    conoce, de modo que aunque alguien adivinara la existencia del registro no
    tendria como entrar. El acceso real solo aparece al aprobar, y por la misma
    via de siempre: el enlace de activacion firmado.

    La respuesta es la MISMA exista o no ya ese correo. Si dijera "ya hay una
    solicitud con ese correo", el formulario se convertiria en un detector de
    quien tiene cuenta en el sistema.
    """
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        # Trampa para bots ("honeypot"), igual que en /privacidad: el campo
        # 'website' esta fuera de pantalla y fuera del orden de tabulacion, asi
        # que solo lo rellena un programa. Se responde con el mismo mensaje de
        # exito de siempre y sin crear la solicitud, para no ensenarle al autor
        # del bot que el campo existe. Coherente con la regla que ya rige esta
        # ruta: la respuesta es identica exista o no ya ese correo.
        if request.form.get("website"):
            flash(
                "Recibimos tu solicitud. Si corresponde, recibirás un enlace "
                "para activar tu cuenta.",
                "success",
            )
            return redirect(url_for("auth.login"))

        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        organizacion = request.form.get("organizacion", "").strip()

        errores = []
        if not nombre:
            errores.append("El nombre es obligatorio.")
        if not email or "@" not in email:
            errores.append("El correo no es válido.")
        if not organizacion:
            errores.append("La organización es obligatoria.")

        if errores:
            for e in errores:
                flash(e, "danger")
            return render_template(
                "auth/solicitud.html",
                nombre=nombre,
                email=email,
                organizacion=organizacion,
            )

        existe = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == email)
        )
        if existe is None:
            solicitante = Facilitador(
                email=email,
                nombre=nombre,
                organizacion=organizacion[:255],
                es_admin=False,
                aprobado=False,
            )
            # Misma invariante que el panel: el sistema nunca fija una clave que
            # alguien conozca. Si la solicitud se aprueba, el titular establece
            # la suya con el enlace de activacion.
            solicitante.set_password(secrets.token_urlsafe(32))
            db.session.add(solicitante)
            try:
                db.session.commit()
            except IntegrityError:
                # Carrera: dos solicitudes con el mismo correo a la vez. La
                # respuesta al usuario no cambia.
                db.session.rollback()

        flash(
            "Recibimos tu solicitud. Si corresponde, recibirás un enlace para "
            "activar tu cuenta.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/solicitud.html", nombre="", email="", organizacion=""
    )


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
