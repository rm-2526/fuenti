"""Rutas publicas del flujo del participante.

Sin auth: el participante no es un Facilitador, no tiene login.
La identidad la lleva el flask.session despues del ingreso.
"""

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import db
from app.models import Participante, Sesion
from app.participante import bp
from app.utils.rut import hash_rut, validar_rut


@bp.route("/<codigo>/ingreso", methods=["GET", "POST"])
def ingreso(codigo):
    sesion = _get_sesion_por_codigo(codigo)

    # Sesion cerrada: no muestra form ni acepta POST. 200 con vista informativa.
    if sesion.estado != "abierta":
        return render_template("participante/sesion_cerrada.html", sesion=sesion)

    if request.method == "POST":
        return _procesar_ingreso(sesion)

    return render_template("participante/ingreso.html", sesion=sesion, rut="")


@bp.route("/<codigo>/responder", methods=["GET"])
def responder(codigo):
    sesion = _get_sesion_por_codigo(codigo)

    # Si la sesion se cerro despues del ingreso, igual mostramos cerrada.
    if sesion.estado != "abierta":
        return render_template("participante/sesion_cerrada.html", sesion=sesion)

    # Validar que la cookie corresponde a un participante de ESTA sesion.
    # Defensa contra cookies cruzadas (alguien ingreso a sesion A, despues
    # abre el link de sesion B y la cookie todavia tiene el id de A).
    participante_id = session.get("participante_id")
    if participante_id is None:
        return redirect(url_for("participante.ingreso", codigo=codigo))

    participante = db.session.get(Participante, participante_id)
    if participante is None or participante.sesion_id != sesion.id:
        session.pop("participante_id", None)
        return redirect(url_for("participante.ingreso", codigo=codigo))

    # Placeholder hasta HC3 Dia 3. En Dia 3 se reemplaza con el form real.
    return render_template(
        "participante/responder_placeholder.html",
        sesion=sesion,
        participante=participante,
    )


# --------------------------- Helpers ---------------------------

def _get_sesion_por_codigo(codigo: str) -> Sesion:
    """404 si no existe sesion con ese codigo."""
    sesion = db.session.query(Sesion).filter_by(codigo=codigo).first()
    if sesion is None:
        abort(404)
    return sesion


def _procesar_ingreso(sesion: Sesion):
    """Procesa el POST del form de ingreso del participante.

    Valida formato del RUT, hashea, busca participante existente o crea
    uno nuevo, deja id en flask.session y redirige al responder.
    """
    rut_input = request.form.get("rut", "").strip()

    if not rut_input:
        flash("Debes ingresar tu RUT.", "danger")
        return render_template("participante/ingreso.html", sesion=sesion, rut="")

    if not validar_rut(rut_input):
        flash("RUT inválido. Revisa el formato (ej: 12.345.678-5).", "danger")
        return render_template(
            "participante/ingreso.html", sesion=sesion, rut=rut_input
        )

    # Hash con salt leido de config (regla 15 del handoff: el caller lee
    # la config y pasa el salt explicito a hash_rut).
    salt = current_app.config["RUT_SALT"]
    identificador_hash = hash_rut(rut_input, salt)

    # Reingreso: si ya existe Participante con este hash en esta sesion,
    # reutilizamos. Caso tipico: se cerro el navegador y volvio.
    participante = (
        db.session.query(Participante)
        .filter_by(sesion_id=sesion.id, identificador_hash=identificador_hash)
        .first()
    )

    if participante is None:
        participante = Participante(
            sesion_id=sesion.id,
            identificador_hash=identificador_hash,
        )
        db.session.add(participante)
        db.session.commit()

    session["participante_id"] = participante.id
    return redirect(url_for("participante.responder", codigo=sesion.codigo))