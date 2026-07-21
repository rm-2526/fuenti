"""Panel de administración: gestión de facilitadores.

Solo accesible por facilitadores con es_admin=True. El primer administrador se
crea/promueve con scripts/seed_facilitador.py --admin (no por este panel, ya que
requeriría un admin previo).
"""
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import db
from app.admin import bp
from app.models import Facilitador


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


def _validar_nuevo_facilitador(email, nombre, password):
    errores = []
    if not email or "@" not in email:
        errores.append("El correo no es válido.")
    if not nombre:
        errores.append("El nombre es obligatorio.")
    if len(password) < 8:
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
            nuevo.set_password(password)
            db.session.add(nuevo)
            try:
                db.session.commit()
                flash(f"Facilitador \"{email}\" creado.", "success")
            except IntegrityError:
                # Carrera improbable: alguien insertó el mismo correo en paralelo.
                db.session.rollback()
                flash("Ya existe un facilitador con ese correo.", "danger")
            return redirect(url_for("admin.facilitadores"))

    lista = db.session.scalars(
        db.select(Facilitador).order_by(Facilitador.created_at)
    ).all()
    return render_template("admin/facilitadores.html", facilitadores=lista)
