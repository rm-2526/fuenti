import re

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.evaluaciones import bp
from app.models import Alternativa, Evaluacion, Pregunta


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
    evaluacion = db.session.get(Evaluacion, eval_id)
    if evaluacion is None:
        abort(404)
    if evaluacion.facilitador_id != current_user.id:
        abort(403)
    return render_template("evaluaciones/detalle.html", evaluacion=evaluacion)


@bp.route("/<int:eval_id>/eliminar", methods=["POST"])
@login_required
def eliminar(eval_id):
    evaluacion = db.session.get(Evaluacion, eval_id)
    if evaluacion is None:
        abort(404)
    if evaluacion.facilitador_id != current_user.id:
        abort(403)
    db.session.delete(evaluacion)
    db.session.commit()
    flash(f'Evaluación "{evaluacion.titulo}" eliminada.', "success")
    return redirect(url_for("evaluaciones.listado"))


# --------------------------- Helpers ---------------------------

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