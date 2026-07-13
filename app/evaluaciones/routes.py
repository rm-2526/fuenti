import csv
import io
import re
from dataclasses import asdict

from flask import (
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import db
from app.evaluaciones import bp
from app.models import Alternativa, Evaluacion, Participante, Pregunta, Sesion
from app.utils.sesion import generar_codigo_sesion
from app.utils.estadisticas import resumir_resultados
from app.utils.reporte import (
    ENCABEZADOS_CSV,
    desglose_desde_respuestas,
    filas_csv_sesion,
    filas_informe_sesion,
)
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


@bp.route("/iniciar")
@login_required
def iniciar():
    """Pagina de lanzamiento: lista las evaluaciones del facilitador para abrir
    una sesion. Reusa la ruta abrir_sesion; las evaluaciones sin preguntas
    aparecen con el boton deshabilitado.
    """
    evaluaciones = (
        db.session.query(Evaluacion)
        .filter_by(facilitador_id=current_user.id)
        .order_by(Evaluacion.created_at.desc())
        .all()
    )
    return render_template("evaluaciones/iniciar.html", evaluaciones=evaluaciones)


@bp.route("/informes")
@login_required
def informes():
    """Informes: sesiones CERRADAS del facilitador, agrupadas por evaluacion.
    Cada sesion enlaza a su pantalla de resultados (detalle_sesion). Las
    sesiones abiertas no aparecen aca (se gestionan desde Iniciar).
    """
    evaluaciones = (
        db.session.query(Evaluacion)
        .filter_by(facilitador_id=current_user.id)
        .order_by(Evaluacion.created_at.desc())
        .all()
    )
    grupos = []
    for e in evaluaciones:
        cerradas = sorted(
            (s for s in e.sesiones if s.estado == "cerrada"),
            key=lambda s: s.cerrada_at or s.abierta_at,
            reverse=True,
        )
        if cerradas:
            grupos.append((e, cerradas))
    return render_template("evaluaciones/informes.html", grupos=grupos)


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
    return render_template(
        "evaluaciones/detalle.html",
        evaluacion=evaluacion,
    )


@bp.route("/<int:eval_id>/editar", methods=["GET", "POST"])
@login_required
def editar(eval_id):
    evaluacion = _get_evaluacion_propia(eval_id)

    # No se puede editar mientras haya una sesion abierta: cambiar las preguntas
    # en vivo ensuciaria esa sesion (unos responderian una version y otros otra).
    # El facilitador debe cerrar la sesion primero.
    if _tiene_sesion_abierta(evaluacion):
        flash(
            "No se puede editar mientras haya una sesión abierta. "
            "Ciérrala primero y vuelve a intentar.",
            "danger",
        )
        return redirect(url_for("evaluaciones.detalle", eval_id=eval_id))

    if request.method == "POST":
        return _actualizar_evaluacion(evaluacion)

    return render_template(
        "evaluaciones/nueva.html",
        titulo=evaluacion.titulo,
        umbral=str(evaluacion.umbral_aprobacion),
        preguntas_form=_preguntas_form_desde_evaluacion(evaluacion),
        titulo_pagina="Editar evaluación",
        boton_guardar="Guardar cambios",
        cancelar_url=url_for("evaluaciones.detalle", eval_id=eval_id),
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
    participantes = filas_informe_sesion(_participantes_ordenados(sesion))
    return render_template(
        "evaluaciones/detalle_sesion.html",
        evaluacion=evaluacion,
        sesion=sesion,
        resumen=resumen,
        participantes=participantes,
    )


@bp.route("/<int:eval_id>/sesiones/<int:sesion_id>/resumen")
@login_required
def resumen_sesion_json(eval_id, sesion_id):
    """Devuelve el resumen agregado de la sesion en formato JSON.

    Lo consume el refresco automatico (polling) del panel: cada pocos segundos
    el navegador pide esta URL y actualiza los numeros sin recargar la pagina.
    Misma proteccion que el detalle de sesion: solo el facilitador dueno de la
    evaluacion (si no, 403). Incluye el estado de la sesion para que el
    navegador sepa cuando dejar de sondear (sesion cerrada -> no hay mas
    resultados nuevos).
    """
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)
    datos = asdict(_resumen_de_sesion(sesion))
    datos["estado"] = sesion.estado
    return jsonify(datos)


@bp.route(
    "/<int:eval_id>/sesiones/<int:sesion_id>/participantes/<int:participante_id>/informe"
)
@login_required
def informe_individual(eval_id, sesion_id, participante_id):
    """Informe individual de un participante: su calificacion y el detalle
    pregunta-por-pregunta (que eligio, cual era la correcta, si acerto).

    Misma proteccion que el resto: solo el facilitador dueno (si no, 403) y 404
    si el participante no pertenece a esa sesion. La pagina esta estilada para
    imprimir: el facilitador puede usar 'Imprimir -> Guardar como PDF'.
    """
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)
    participante = _get_participante_de_sesion(sesion, participante_id)

    # El desglose se arma desde la FOTO congelada guardada en cada respuesta,
    # no desde la evaluacion viva: asi editar la evaluacion despues no altera
    # el informe de una sesion ya rendida.
    desglose = desglose_desde_respuestas(participante.respuestas)

    return render_template(
        "evaluaciones/informe_individual.html",
        evaluacion=evaluacion,
        sesion=sesion,
        participante=participante,
        resultado=participante.resultado,
        desglose=desglose,
    )


@bp.route("/<int:eval_id>/sesiones/<int:sesion_id>/export.csv")
@login_required
def exportar_csv(eval_id, sesion_id):
    """Descarga la sesion como CSV (una fila por participante).

    CSV = tabla de datos que se abre en Excel. Se le antepone un BOM para que
    Excel muestre bien los acentos. Mismos guards de dueno/login que el detalle.
    """
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)

    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM: ayuda a Excel a leer UTF-8 (acentos)
    escritor = csv.writer(buffer)
    escritor.writerow(ENCABEZADOS_CSV)
    escritor.writerows(filas_csv_sesion(_participantes_ordenados(sesion)))

    nombre_archivo = f"sesion_{sesion.codigo}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
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


def _get_participante_de_sesion(sesion: Sesion, participante_id: int) -> Participante:
    """404 si el participante no pertenece a esa sesion.
    El chequeo de duenio ya esta hecho por _get_evaluacion_propia.
    """
    participante = db.session.get(Participante, participante_id)
    if participante is None or participante.sesion_id != sesion.id:
        abort(404)
    return participante


def _participantes_ordenados(sesion: Sesion) -> list:
    """Participantes de la sesion ordenados por su ingreso (orden estable para
    la lista y el CSV: el #1 es el primero que entro)."""
    return sorted(sesion.participantes, key=lambda p: p.ingreso_at)


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

    _insertar_preguntas(evaluacion.id, preguntas)

    db.session.commit()
    flash(f'Evaluación "{titulo}" creada.', "success")
    return redirect(url_for("evaluaciones.listado"))


def _insertar_preguntas(evaluacion_id, preguntas):
    """Crea las Pregunta/Alternativa de una evaluacion a partir de la lista ya
    parseada y validada. Compartido por crear y editar.

    `preguntas` es la salida de _parsear_preguntas: lista de dicts con
    {enunciado, correcta, alternativas: [(j, texto)]}.
    """
    for orden_p, p in enumerate(preguntas, start=1):
        pregunta = Pregunta(
            evaluacion_id=evaluacion_id,
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


def _tiene_sesion_abierta(evaluacion) -> bool:
    """True si la evaluacion tiene al menos una sesion en estado 'abierta'."""
    return any(s.estado == "abierta" for s in evaluacion.sesiones)


def _preguntas_form_desde_evaluacion(evaluacion):
    """Arma la estructura que espera el formulario (la misma forma que produce
    _parsear_preguntas) a partir de las preguntas guardadas, para pre-cargar la
    edicion: lista de {enunciado, correcta, alternativas: [(j, texto)]}.

    Los indices j van 0,1,2... (igual que al crear), para que el JS que agrega
    alternativas calcule bien el siguiente indice y no choque.
    """
    form = []
    for p in sorted(evaluacion.preguntas, key=lambda p: p.orden):
        alts = sorted(p.alternativas, key=lambda a: a.orden)
        correcta_pos = next(
            (i for i, a in enumerate(alts) if a.es_correcta), None
        )
        form.append(
            {
                "enunciado": p.enunciado,
                "correcta": str(correcta_pos) if correcta_pos is not None else "",
                "alternativas": [(i, a.texto) for i, a in enumerate(alts)],
            }
        )
    return form


def _actualizar_evaluacion(evaluacion):
    """Procesa el POST de /evaluaciones/<id>/editar.

    Reusa el parseo y la validacion de la creacion. Si es valido, actualiza
    titulo/umbral y REEMPLAZA el set de preguntas (borra las viejas y re-crea
    desde el formulario). Es seguro porque los resultados ya tienen su foto
    congelada: al borrar una pregunta ya respondida, sus respuestas sueltan el
    enlace (pregunta_id/alternativa_id -> NULL) pero conservan la copia.
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
            titulo_pagina="Editar evaluación",
            boton_guardar="Guardar cambios",
            cancelar_url=url_for("evaluaciones.detalle", eval_id=evaluacion.id),
        )

    evaluacion.titulo = titulo
    evaluacion.umbral_aprobacion = int(umbral_str)

    # Reemplazo del set de preguntas. Al borrar cada pregunta, sus alternativas
    # se borran en cascada y las respuestas asociadas sueltan el enlace (quedan
    # en NULL) conservando su foto congelada.
    for pregunta in list(evaluacion.preguntas):
        db.session.delete(pregunta)
    db.session.flush()

    _insertar_preguntas(evaluacion.id, preguntas)

    db.session.commit()
    flash(f'Evaluación "{titulo}" actualizada.', "success")
    return redirect(url_for("evaluaciones.detalle", eval_id=evaluacion.id))


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