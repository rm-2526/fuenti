"""Rutas publicas del flujo del participante.

Sin auth: el participante no es un Facilitador, no tiene login.
La identidad la lleva flask.session["participante_id"] (cookie firmada por
Flask) despues del ingreso.
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
from app.models import Participante, Respuesta, Resultado, Sesion, ahora_utc
from app.participante import bp
from app.utils.calificacion import calcular_calificacion
from app.utils.reporte import foto_de_respuesta
from app.utils.rut import hash_rut, validar_rut


@bp.route("/<codigo>/ingreso", methods=["GET", "POST"])
def ingreso(codigo):
    sesion = _get_sesion_por_codigo(codigo)

    # Sesion cerrada: no muestra form ni acepta POST. 200 con vista informativa.
    if sesion.estado != "abierta":
        return render_template("participante/sesion_cerrada.html", sesion=sesion)

    if request.method == "POST":
        return _procesar_ingreso(sesion)

    return render_template("participante/ingreso.html", sesion=sesion, rut="", nombre="")


@bp.route("/<codigo>/responder", methods=["GET", "POST"])
def responder(codigo):
    sesion = _get_sesion_por_codigo(codigo)

    # Sesion cerrada bloquea GET y POST. Este chequeo, aplicado al POST, es el
    # que cierra el ultimo componente de OE4: una sesion cerrada no acepta
    # respuestas aunque alguien arme el POST a mano.
    if sesion.estado != "abierta":
        return render_template("participante/sesion_cerrada.html", sesion=sesion)

    # Defensa contra cookie cruzada: el participante debe ser de ESTA sesion.
    participante = _participante_de_sesion(sesion)
    if participante is None:
        return redirect(url_for("participante.ingreso", codigo=codigo))

    # Ya respondio: no puede responder dos veces, lo mandamos a su resultado.
    if participante.resultado is not None:
        return redirect(url_for("participante.resultado", codigo=codigo))

    preguntas = _preguntas_ordenadas(sesion)

    if request.method == "POST":
        return _procesar_respuestas(sesion, participante, preguntas)

    return render_template(
        "participante/responder.html",
        sesion=sesion,
        preguntas=preguntas,
        seleccion={},
    )


@bp.route("/<codigo>/resultado", methods=["GET"])
def resultado(codigo):
    sesion = _get_sesion_por_codigo(codigo)

    # OJO: aca NO se bloquea por sesion cerrada. Si el facilitador cierra la
    # sesion despues de que el participante termino, igual debe poder ver su nota.
    participante = _participante_de_sesion(sesion)
    if participante is None:
        return redirect(url_for("participante.ingreso", codigo=codigo))

    # Todavia no respondio: lo mandamos al cuestionario.
    if participante.resultado is None:
        return redirect(url_for("participante.responder", codigo=codigo))

    return render_template(
        "participante/resultado.html",
        sesion=sesion,
        resultado=participante.resultado,
    )


# --------------------------- Helpers ---------------------------

def _get_sesion_por_codigo(codigo: str) -> Sesion:
    """404 si no existe sesion con ese codigo."""
    sesion = db.session.query(Sesion).filter_by(codigo=codigo).first()
    if sesion is None:
        abort(404)
    return sesion


def _participante_de_sesion(sesion: Sesion) -> Participante | None:
    """Devuelve el Participante de ESTA sesion segun la cookie, o None.

    Defensa contra cookie cruzada: si la cookie tiene un participante de otra
    sesion (o de ninguna), la limpia y devuelve None. El caller redirige al
    ingreso.
    """
    participante_id = session.get("participante_id")
    if participante_id is None:
        return None

    participante = db.session.get(Participante, participante_id)
    if participante is None or participante.sesion_id != sesion.id:
        session.pop("participante_id", None)
        return None

    return participante


def _preguntas_ordenadas(sesion: Sesion) -> list:
    """Preguntas de la evaluacion de la sesion, ordenadas por su campo orden."""
    return sorted(sesion.evaluacion.preguntas, key=lambda p: p.orden)


def _procesar_ingreso(sesion: Sesion):
    """Procesa el POST del form de ingreso del participante.

    Valida formato del RUT, hashea, busca participante existente o crea
    uno nuevo, deja id en flask.session y redirige al responder.
    """
    rut_input = request.form.get("rut", "").strip()
    nombre_input = request.form.get("nombre", "").strip()

    # Nombre y apellido es obligatorio: es la etiqueta legible del informe del
    # facilitador (los reportes para terceros -RRHH u otros- necesitan leer
    # nombres). El RUT igual se hashea; el nombre no reemplaza esa proteccion.
    if not nombre_input:
        flash("Debes ingresar tu nombre y apellido.", "danger")
        return render_template(
            "participante/ingreso.html", sesion=sesion, rut=rut_input, nombre=""
        )

    if not rut_input:
        flash("Debes ingresar tu RUT.", "danger")
        return render_template(
            "participante/ingreso.html", sesion=sesion, rut="", nombre=nombre_input
        )

    if not validar_rut(rut_input):
        flash("RUT inválido. Revisa el formato (ej: 12.345.678-5).", "danger")
        return render_template(
            "participante/ingreso.html",
            sesion=sesion,
            rut=rut_input,
            nombre=nombre_input,
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
            nombre=nombre_input,
        )
        db.session.add(participante)
        db.session.commit()
    elif participante.nombre != nombre_input:
        # Reingreso: si corrigio su nombre, lo actualizamos (no crea otro).
        participante.nombre = nombre_input
        db.session.commit()

    session["participante_id"] = participante.id
    return redirect(url_for("participante.responder", codigo=sesion.codigo))


def _procesar_respuestas(sesion: Sesion, participante: Participante, preguntas: list):
    """Procesa el POST del cuestionario.

    Lee una alternativa por pregunta (input name="pregunta_<id>"), valida que
    esten todas respondidas y que cada alternativa elegida pertenezca a su
    pregunta, persiste una Respuesta por pregunta, calcula el Resultado y
    redirige al resultado.
    """
    # Recolectar la seleccion cruda (str) por pregunta.
    seleccion = {}
    for p in preguntas:
        val = request.form.get(f"pregunta_{p.id}", "").strip()
        if val:
            seleccion[p.id] = val

    # Validacion: todas las preguntas respondidas. Si falta alguna, re-render
    # con lo que ya habia marcado (no se persiste nada parcial).
    faltantes = [p for p in preguntas if p.id not in seleccion]
    if faltantes:
        flash("Debes responder todas las preguntas antes de enviar.", "danger")
        return render_template(
            "participante/responder.html",
            sesion=sesion,
            preguntas=preguntas,
            seleccion=seleccion,
        )

    puntaje = 0
    respuestas_a_crear = []
    for p in preguntas:
        try:
            alt_id = int(seleccion[p.id])
        except ValueError:
            abort(400)

        # Defensa anti-tampering: la alternativa elegida debe pertenecer a
        # ESTA pregunta.
        alternativa = next((a for a in p.alternativas if a.id == alt_id), None)
        if alternativa is None:
            abort(400)

        if alternativa.es_correcta:
            puntaje += 1

        # Congelamos la copia del contenido en la propia respuesta: asi el
        # resultado queda autocontenido y no depende de la evaluacion viva.
        foto = foto_de_respuesta(p, alternativa)
        respuestas_a_crear.append(
            Respuesta(
                participante_id=participante.id,
                pregunta_id=p.id,
                alternativa_id=alternativa.id,
                **foto,
            )
        )

    calificacion = calcular_calificacion(
        puntaje=puntaje,
        total=len(preguntas),
        umbral=sesion.evaluacion.umbral_aprobacion,
    )

    for r in respuestas_a_crear:
        db.session.add(r)
    db.session.add(
        Resultado(
            participante_id=participante.id,
            puntaje=puntaje,
            total_preguntas=len(preguntas),
            porcentaje=calificacion.porcentaje,
            nota=calificacion.nota,
            aprobado=calificacion.aprobado,
            # Foto congelada del encabezado: titulo y umbral aplicados.
            evaluacion_titulo=sesion.evaluacion.titulo,
            umbral_aprobacion=sesion.evaluacion.umbral_aprobacion,
        )
    )
    participante.finalizado_at = ahora_utc()
    db.session.commit()

    return redirect(url_for("participante.resultado", codigo=sesion.codigo))
