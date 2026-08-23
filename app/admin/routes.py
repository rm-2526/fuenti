"""Panel de administración: gestión de facilitadores.

Solo accesible por facilitadores con es_admin=True. El primer administrador se
crea/promueve con scripts/seed_facilitador.py --admin (no por este panel, ya que
requeriría un admin previo).

Invariante de credenciales. El panel NO permite fijar ni cambiar contraseñas de
nadie. Al crear una cuenta se le asigna una clave aleatoria que nadie conoce, y
el titular establece la suya a través de un enlace de activación firmado
(app/utils/activacion.py). Mientras esto fue opcional era una buena práctica que
dependía de que el administrador la eligiera cada vez; al retirar el campo pasa
a ser una propiedad del sistema.

Lo que esto garantiza, y lo que no. No impide que un administrador se apodere de
una cuenta ajena: puede emitir un enlace y usarlo. Lo que impide es que lo haga
sin dejar rastro, porque al establecer una clave nueva la anterior deja de
funcionar y el titular lo advierte en su siguiente ingreso. La toma de control
deja de ser silenciosa.

Excepción documentada: scripts/seed_facilitador.py sí fija contraseñas, porque
es el arranque del sistema y exige acceso al servidor o a la base.
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

    Absoluta (_external=True) porque el enlace viaja fuera de la aplicación: se
    copia y se envía por correo, mensajería o se entrega en persona.
    """
    return url_for(
        "auth.activar",
        token=generar_token(f.id, f.password_hash, current_app.config["SECRET_KEY"]),
        _external=True,
    )


def _validar_nuevo_facilitador(email, nombre):
    errores = []
    if not email or "@" not in email:
        errores.append("El correo no es válido.")
    if not nombre:
        errores.append("El nombre es obligatorio.")
    return errores


@bp.route("/facilitadores", methods=["GET", "POST"])
@admin_required
def facilitadores():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nombre = request.form.get("nombre", "").strip()
        es_admin = request.form.get("es_admin") == "on"
        # La contraseña no se lee del formulario a propósito: aunque alguien la
        # envíe a mano, se ignora.

        errores = _validar_nuevo_facilitador(email, nombre)

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
            # Clave aleatoria que nadie conoce ni necesita conocer: la cuenta
            # solo se abre por el enlace de activación. No se guarda en ningún
            # lado ni se muestra.
            nuevo.set_password(secrets.token_urlsafe(32))
            db.session.add(nuevo)
            try:
                db.session.commit()
                flash(
                    f"Facilitador \"{email}\" creado. Envíale este enlace para "
                    f"que establezca su contraseña: {_enlace_activacion(nuevo)}",
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
    """Emite un enlace de activación para una cuenta existente.

    Es la única vía frente a una contraseña olvidada. NO cambia la clave
    vigente: si el titular nunca usa el enlace, la que tenía sigue sirviendo.
    """
    f = _get_facilitador(fid)

    if not f.activo:
        flash(
            "La cuenta está desactivada. Reactívala antes de emitir el enlace.",
            "danger",
        )
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
        # Tampoco aquí se lee la contraseña: el cambio de clave pasa siempre por
        # el enlace de activación.

        errores = []
        if not email or "@" not in email:
            errores.append("El correo no es válido.")
        if not nombre:
            errores.append("El nombre es obligatorio.")

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
