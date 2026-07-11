import re

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import db
from app.evaluaciones import bp
from app.models import Alternativa, Evaluacion, Pregunta, Sesion
from app.utils.sesion import generar_codigo_sesion
from app.utils.estadisticas import resumir_resultados
from app.models import ahora_utc


# Maximo de reintentos para generar un codigo de sesion unico.
# Con 32^6 combinaciones, una colision es practicamente imposible.
# Si pasa 5 veces seguidas, es mas probable que sea bug que mala suerte.
_MAX_REINTENTOS_CODIGO = 5


@bp.route("/")
@login_required
def listado():
    evaluaciones = (
        db.session.query(Evaluacion)
        .filter_by(facilitador_id=current_user.id)
        .order_by(Evaluacion.created_at.desc())
        .all()
    )
    return render_template("evaluaciones/listado.html", evaluaciones=evaluaciones)


@bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    if request.method == "POST":
        return _crear_evaluacion()
    return render_template(
        "evaluaciones/nueva.html",
        titulo="",
        umbral="60",
        preguntas_form=None,
    )


@bp.route("/<int:eval_id>")
@login_required
def detalle(eval_id):
    evaluacion = _get_evaluacion_propia(eval_id)
    sesiones = sorted(
        evaluacion.sesiones, key=lambda s: s.abierta_at, reverse=True
    )
    return render_template(
        "evaluaciones/detalle.html",
        evaluacion=evaluacion,
        sesiones=sesiones,
    )


@bp.route("/<int:eval_id>/eliminar", methods=["POST"])
@login_required
def eliminar(eval_id):
    evaluacion = _get_evaluacion_propia(eval_id)
    db.session.delete(evaluacion)
    db.session.commit()
    flash(f'Evaluación "{evaluacion.titulo}" eliminada.', "success")
    return redirect(url_for("evaluaciones.listado"))


# --------------------------- Sesiones (facilitador) ---------------------------

@bp.route("/<int:eval_id>/sesiones/abrir", methods=["POST"])
@login_required
def abrir_sesion(eval_id):
    evaluacion = _get_evaluacion_propia(eval_id)

    # Validacion de negocio: no se puede abrir una sesion para una evaluacion
    # sin preguntas (el participante no tendria nada que responder).
    if not evaluacion.preguntas:
        flash(
            "No se puede abrir una sesión: la evaluación no tiene preguntas.",
            "danger",
        )
        return redirect(url_for("evaluaciones.detalle", eval_id=eval_id))

    sesion = _crear_sesion_con_codigo_unico(evaluacion.id)
    flash(f"Sesión abierta. Código: {sesion.codigo}", "success")
    return redirect(
        url_for("evaluaciones.detalle_sesion", eval_id=eval_id, sesion_id=sesion.id)
    )


@bp.route("/<int:eval_id>/sesiones/<int:sesion_id>")
@login_required
def detalle_sesion(eval_id, sesion_id):
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)
    resumen = _resumen_de_sesion(sesion)
    return render_template(
        "evaluaciones/detalle_sesion.html",
        evaluacion=evaluacion,
        sesion=sesion,
        resumen=resumen,
    )


@bp.route("/<int:eval_id>/sesiones/<int:sesion_id>/cerrar", methods=["POST"])
@login_required
def cerrar_sesion(eval_id, sesion_id):
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)

    # Idempotente: cerrar una sesion ya cerrada no es error.
    if sesion.estado == "cerrada":
        flash("La sesión ya estaba cerrada.", "info")
    else:
        sesion.estado = "cerrada"
        sesion.cerrada_at = ahora_utc()
        db.session.commit()
        flash("Sesión cerrada. No aceptará nuevos ingresos.", "success")

    return redirect(
        url_for("evaluaciones.detalle_sesion", eval_id=eval_id, sesion_id=sesion_id)
    )


# --------------------------- Helpers ---------------------------

def _get_evaluacion_propia(eval_id: int) -> Evaluacion:
    """404 si no existe, 403 si no es del facilitador autenticado."""
    evaluacion = db.session.get(Evaluacion, eval_id)
    if evaluacion is None:
        abort(404)
    if evaluacion.facilitador_id != current_user.id:
        abort(403)
    return evaluacion


def _resumen_de_sesion(sesion: Sesion):
    """Arma el resumen agregado de la sesion para el panel del facilitador.

    Consulta los participantes y sus resultados y delega el calculo puro a
    resumir_resultados (que no toca la BD). El caller pasa el resumen a la
    plantilla.
    """
    participantes = sesion.participantes
    resultados = [p.resultado for p in participantes if p.resultado is not None]
    return resumir_resultados(resultados, total_participantes=len(participantes))


def _get_sesion_de_evaluacion(evaluacion: Evaluacion, sesion_id: int) -> Sesion:
    """404 si la sesion no pertenece a esa evaluacion.
    El chequeo de duenio ya esta hecho por _get_evaluacion_propia.
    """
    sesion = db.session.get(Sesion, sesion_id)
    if sesion is None or sesion.evaluacion_id != evaluacion.id:
        abort(404)
    return sesion


def _crear_sesion_con_codigo_unico(evaluacion_id: int) -> Sesion:
    """Crea una Sesion con codigo unico, reintentando si hay colision.

    La unicidad la garantiza la BD (unique constraint en sesion.codigo).
    Si IntegrityError despues de _MAX_REINTENTOS_CODIGO intentos, levanta
    RuntimeError: en ese caso es mas probable un bug que mala suerte.
    """
    for _ in range(_MAX_REINTENTOS_CODIGO):
        codigo = generar_codigo_sesion()
        sesion = Sesion(evaluacion_id=evaluacion_id, codigo=codigo)
        db.session.add(sesion)
        try:
            db.session.commit()
            return sesion
        except IntegrityError:
            db.session.rollback()
            continue
    raise RuntimeError(
        f"No se pudo generar un código único tras {_MAX_REINTENTOS_CODIGO} intentos."
    )


def _crear_evaluacion():
    """Procesa el POST de /evaluaciones/nueva.

    Lee los campos `titulo`, `umbral` y los grupos
    `pregunta_<i>_enunciado`, `pregunta_<i>_correcta`,
    `pregunta_<i>_alternativa_<j>_texto`.

    Los índices i, j no necesitan ser consecutivos
    (el JS no renumera al eliminar).
    """
    titulo = request.form.get("titulo", "").strip()
    umbral_str = request.form.get("umbral", "").strip()
    preguntas = _parsear_preguntas(request.form)
    errores = _validar(titulo, umbral_str, preguntas)

    if errores:
        for e in errores:
            flash(e, "danger")
        return render_template(
            "evaluaciones/nueva.html",
            titulo=titulo,
            umbral=umbral_str,
            preguntas_form=preguntas,
        )

    # Guardado en una sola transacción
    evaluacion = Evaluacion(
        facilitador_id=current_user.id,
        titulo=titulo,
        umbral_aprobacion=int(umbral_str),
    )
    db.session.add(evaluacion)
    db.session.flush()  # obtenemos evaluacion.id sin commitear todavía

    for orden_p, p in enumerate(preguntas, start=1):
        pregunta = Pregunta(
            evaluacion_id=evaluacion.id,
            enunciado=p["enunciado"],
            orden=orden_p,
        )
        db.session.add(pregunta)
        db.session.flush()

        correcta_idx = int(p["correcta"])
        for orden_a, (j, texto) in enumerate(p["alternativas"], start=1):
            alternativa = Alternativa(
                pregunta_id=pregunta.id,
                texto=texto,
                es_correcta=(j == correcta_idx),
                orden=orden_a,
            )
            db.session.add(alternativa)

    db.session.commit()
    flash(f'Evaluación "{titulo}" creada.', "success")
    return redirect(url_for("evaluaciones.listado"))


def _parsear_preguntas(form):
    """Devuelve una lista de dicts: [{enunciado, correcta, alternativas: [(j, texto)]}, ...]
    Ordenadas por índice ascendente. Tolerante a huecos en los índices.
    """
    preguntas_dict = {}

    # Primera pasada: encontrar las preguntas
    for key, value in form.items():
        m = re.fullmatch(r"pregunta_(\d+)_enunciado", key)
        if m:
            idx = int(m.group(1))
            preguntas_dict[idx] = {
                "enunciado": value.strip(),
                "correcta": form.get(f"pregunta_{idx}_correcta", "").strip(),
                "alternativas": [],
            }

    # Segunda pasada: alternativas
    alternativas_dict = {}  # {pregunta_idx: {alt_idx: texto}}
    for key, value in form.items():
        m = re.fullmatch(r"pregunta_(\d+)_alternativa_(\d+)_texto", key)
        if m:
            p_idx, a_idx = int(m.group(1)), int(m.group(2))
            if p_idx in preguntas_dict:
                alternativas_dict.setdefault(p_idx, {})[a_idx] = value.strip()

    for p_idx, alts in alternativas_dict.items():
        # Solo conservamos las que tienen texto no vacío,
        # pero ordenadas por índice original
        preguntas_dict[p_idx]["alternativas"] = [
            (a_idx, texto)
            for a_idx, texto in sorted(alts.items())
            if texto
        ]

    return [preguntas_dict[k] for k in sorted(preguntas_dict.keys())]


def _validar(titulo, umbral_str, preguntas):
    errores = []

    if not titulo:
        errores.append("El título es obligatorio.")
    elif len(titulo) > 255:
        errores.append("El título no puede tener más de 255 caracteres.")

    try:
        umbral = int(umbral_str)
        if not 0 <= umbral <= 100:
            errores.append("El umbral debe estar entre 0 y 100.")
    except (ValueError, TypeError):
        errores.append("El umbral debe ser un número entero.")

    if not preguntas:
        errores.append("Debe haber al menos una pregunta.")

    for idx, p in enumerate(preguntas, start=1):
        if not p["enunciado"]:
            errores.append(f"La pregunta {idx} no tiene enunciado.")
        n_alts = len(p["alternativas"])
        if n_alts < 2:
            errores.append(f"La pregunta {idx} debe tener al menos 2 alternativas con texto.")
        if n_alts > 6:
            errores.append(f"La pregunta {idx} no puede tener más de 6 alternativas.")

        try:
            correcta_idx = int(p["correcta"])
            indices_validos = [j for j, _ in p["alternativas"]]
            if correcta_idx not in indices_validos:
                errores.append(
                    f"La pregunta {idx}: la alternativa correcta marcada "
                    "no corresponde a ninguna alternativa con texto."
                )
        except (ValueError, TypeError):
            errores.append(f"La pregunta {idx}: debes marcar la alternativa correcta.")

    return errores