"""Panel de administración: gestión de facilitadores.

Solo accesible por facilitadores con es_admin=True. El primer administrador se
crea/promueve con scripts/seed_facilitador.py --admin (no por este panel, ya que
requeriría un admin previo).

Sobre la contraseña inicial. Es OPCIONAL al crear. Si se deja en blanco, la
cuenta nace con una clave aleatoria que nadie conoce y el panel entrega un
enlace de activación para que el titular fije la suya: así el administrador
no queda en posesión de las credenciales ajenas. Se mantiene la posibilidad de
escribirla porque hay escenarios sin canal para hacer llegar el enlace, y
porque los flujos ya existentes la envían.
"""
import secrets
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import db
from app.admin import bp
from app.models import Facilitador
from app.utils.activacion import generar_token


def admin_required(view):
    """Exige sesión iniciada Y rol admin. A los no-admin les responde 403; a los
    anónimos, login_required los manda a la pantalla de login."""

    @wraps(view)
    @login_required
    def envuelta(*args, **kwargs):
        if not current_user.es_admin:
            abort(403)
        return view(*args, **kwargs)

    return envuelta


def _enlace_activacion(f):
    """URL absoluta para que f establezca su contraseña.

    Absoluta (_external=True) porque el enlace viaja fuera de la aplicación:
    se copia y se envía por correo, mensajería o se entrega en persona.
    """
    return url_for(
        "auth.activar",
        token=generar_token(f.id, f.password_hash, current_app.config["SECRET_KEY"]),
        _external=True,
    )


def _validar_nuevo_facilitador(email, nombre, password):
    errores = []
    if not email or "@" not in email:
        errores.append("El correo no es válido.")
    if not nombre:
        errores.append("El nombre es obligatorio.")
    # Contraseña opcional: en blanco = se emite enlace de activación. Si viene
    # con texto, debe cumplir el mínimo.
    if password and len(password) < 8:
        errores.append("La contraseña debe tener al menos 8 caracteres.")
    return errores


@bp.route("/facilitadores", methods=["GET", "POST"])
@admin_required
def facilitadores():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nombre = request.form.get("nombre", "").strip()
        password = request.form.get("password", "")
        es_admin = request.form.get("es_admin") == "on"

        errores = _validar_nuevo_facilitador(email, nombre, password)

        # Chequeo de duplicado antes de intentar insertar (mensaje claro).
        if not errores:
            existe = db.session.scalar(
                db.select(Facilitador).where(Facilitador.email == email)
            )
            if existe is not None:
                errores.append("Ya existe un facilitador con ese correo.")

        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            nuevo = Facilitador(email=email, nombre=nombre, es_admin=es_admin)
            if password:
                nuevo.set_password(password)
            else:
                # Clave aleatoria que nadie conoce ni necesita conocer: la
                # cuenta solo se abre por el enlace de activación.
                nuevo.set_password(secrets.token_urlsafe(32))
            db.session.add(nuevo)
            try:
                db.session.commit()
                if password:
                    flash(f"Facilitador \"{email}\" creado.", "success")
                else:
                    flash(
                        f"Facilitador \"{email}\" creado. Envíale este enlace "
                        f"para que establezca su contraseña: "
                        f"{_enlace_activacion(nuevo)}",
                        "success",
                    )
            except IntegrityError:
                # Carrera improbable: alguien insertó el mismo correo en paralelo.
                db.session.rollback()
                flash("Ya existe un facilitador con ese correo.", "danger")
            return redirect(url_for("admin.facilitadores"))

    lista = db.session.scalars(
        db.select(Facilitador).order_by(Facilitador.created_at)
    ).all()
    return render_template("admin/facilitadores.html", facilitadores=lista)


def _get_facilitador(fid):
    f = db.session.get(Facilitador, fid)
    if f is None:
        abort(404)
    return f


def _admins_activos_count():
    return db.session.scalar(
        db.select(db.func.count())
        .select_from(Facilitador)
        .where(Facilitador.es_admin.is_(True), Facilitador.activo.is_(True))
    )


def _es_ultimo_admin_activo(f):
    """True si f es un admin activo y es el único que queda."""
    return f.es_admin and f.activo and _admins_activos_count() <= 1


@bp.route("/facilitadores/<int:fid>/enlace", methods=["POST"])
@admin_required
def enlace_activacion(fid):
    """Regenera el enlace de activación de una cuenta existente.

    Es la vía para una contraseña olvidada. NO cambia la clave vigente: si el
    titular nunca usa el enlace, la que tenía sigue funcionando. El cambio
    tampoco es silencioso, porque al usarse invalida la contraseña anterior.
    """
    f = _get_facilitador(fid)

    if not f.activo:
        flash("La cuenta está desactivada. Reactívala antes de enviar el enlace.", "danger")
    else:
        flash(
            f"Enlace de activación para \"{f.email}\": {_enlace_activacion(f)}",
            "info",
        )
    return redirect(url_for("admin.facilitadores"))


@bp.route("/facilitadores/<int:fid>/editar", methods=["GET", "POST"])
@admin_required
def editar_facilitador(fid):
    f = _get_facilitador(fid)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        es_admin = request.form.get("es_admin") == "on"
        password = request.form.get("password", "")

        errores = []
        if not email or "@" not in email:
            errores.append("El correo no es válido.")
        if not nombre:
            errores.append("El nombre es obligatorio.")
        # La contraseña es opcional al editar: en blanco = no se cambia. Si viene
        # con texto, debe cumplir el mínimo.
        if password and len(password) < 8:
            errores.append("La contraseña debe tener al menos 8 caracteres.")

        # Correo único: puede ser el mismo de f, pero no el de OTRO facilitador.
        if not errores:
            otro = db.session.scalar(
                db.select(Facilitador).where(
                    Facilitador.email == email, Facilitador.id != f.id
                )
            )
            if otro is not None:
                errores.append("Ya existe otro facilitador con ese correo.")

        # No dejar al sistema sin administradores: no se puede quitar el rol admin
        # al último admin activo.
        if not es_admin and _es_ultimo_admin_activo(f):
            errores.append(
                "No puedes quitar el rol de administrador al último admin activo."
            )

        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            f.nombre = nombre
            f.email = email
            f.es_admin = es_admin
            if password:  # solo si se escribió una nueva
                f.set_password(password)
            db.session.commit()
            flash("Facilitador actualizado.", "success")
            return redirect(url_for("admin.facilitadores"))

    return render_template("admin/editar_facilitador.html", facilitador=f)


@bp.route("/facilitadores/<int:fid>/estado", methods=["POST"])
@admin_required
def cambiar_estado(fid):
    f = _get_facilitador(fid)

    if f.activo:  # se está intentando DESACTIVAR
        if f.id == current_user.id:
            flash("No puedes desactivar tu propia cuenta.", "danger")
            return redirect(url_for("admin.facilitadores"))
        if _es_ultimo_admin_activo(f):
            flash("No puedes desactivar al último administrador activo.", "danger")
            return redirect(url_for("admin.facilitadores"))
        f.activo = False
        db.session.commit()
        flash(
            f"Facilitador \"{f.email}\" desactivado. Sus datos se conservan.",
            "success",
        )
    else:  # REACTIVAR (siempre permitido)
        f.activo = True
        db.session.commit()
        flash(f"Facilitador \"{f.email}\" reactivado.", "success")

    return redirect(url_for("admin.facilitadores"))
