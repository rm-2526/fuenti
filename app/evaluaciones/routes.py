import csv
import io
import re
from dataclasses import asdict

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import db, hora_local
from app.evaluaciones import bp
from app.models import Alternativa, Evaluacion, Participante, Pregunta, Resultado, Sesion
from app.utils.sesion import generar_codigo_sesion
from app.utils.estadisticas import resumir_resultados
from app.utils.reporte import (
    ENCABEZADOS_CSV,
    ENCABEZADOS_CSV_HISTORIAL,
    agrupar_historial,
    agrupar_personas,
    construir_matriz,
    desglose_desde_respuestas,
    filas_csv_historial,
    filas_csv_matriz,
    filas_csv_sesion,
    filas_informe_sesion,
)
from app.models import ahora_utc
from app.utils.rut import hash_rut, validar_rut


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

@bp.route("/participantes")
@login_required
def informes_por_participante():
    """Vista 'Por participante' de Informes: lista de personas que han rendido
    (finalizado) al menos una sesión en evaluaciones de este facilitador.

    Acepta dos filtros opcionales por query string:
      - ?nombre=<texto>  : coincidencia parcial, sin distinguir mayúsculas.
      - ?rut=<rut>       : RUT completo; se valida, se hashea y se busca el
                           hash exacto. No hay búsqueda parcial por RUT porque
                           el RUT no se almacena, solo su hash.
    Los dos filtros se pueden combinar. Si el RUT es inválido, se avisa y no
    se aplica ese filtro.
    """
    nombre_q = request.args.get("nombre", "").strip()
    rut_q = request.args.get("rut", "").strip()

    consulta = (
        db.session.query(Participante)
        .join(Sesion, Participante.sesion_id == Sesion.id)
        .join(Evaluacion, Sesion.evaluacion_id == Evaluacion.id)
        .join(Resultado, Resultado.participante_id == Participante.id)
        .filter(
            Evaluacion.facilitador_id == current_user.id,
            Sesion.estado == "cerrada",
        )
    )

    # Filtro por nombre: parcial, insensible a mayúsculas.
    if nombre_q:
        consulta = consulta.filter(Participante.nombre.ilike(f"%{nombre_q}%"))

    # Filtro por RUT: exacto vía hash. Mismo pepper y misma función que el
    # ingreso, así el hash calculado acá coincide con el guardado.
    rut_invalido = False
    if rut_q:
        if validar_rut(rut_q):
            salt = current_app.config["RUT_SALT"]
            hash_buscado = hash_rut(rut_q, salt)
            consulta = consulta.filter(
                Participante.identificador_hash == hash_buscado
            )
        else:
            rut_invalido = True

    participantes = consulta.all()
    personas = agrupar_personas(participantes)

    if rut_invalido:
        flash("El RUT ingresado no es válido. Se ignoró ese filtro.", "warning")

    return render_template(
        "evaluaciones/informes_participantes.html",
        personas=personas,
        nombre_q=nombre_q,
        rut_q=rut_q,
    )


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
    # Se vuelve a Iniciar, que es desde donde se abren las sesiones.
    if not evaluacion.preguntas:
        flash(
            "No se puede abrir una sesión: la evaluación no tiene preguntas.",
            "danger",
        )
        return redirect(url_for("evaluaciones.iniciar"))

    # Umbral de esta sesion: viene del formulario de Iniciar, pre-cargado con
    # el de la evaluacion. Si el campo no viene (o viene vacio), se usa el de
    # la evaluacion como valor por defecto.
    umbral_str = request.form.get("umbral", "").strip()
    if umbral_str == "":
        umbral = evaluacion.umbral_aprobacion
    else:
        try:
            umbral = int(umbral_str)
        except ValueError:
            flash("El umbral debe ser un número entero.", "danger")
            return redirect(url_for("evaluaciones.iniciar"))
        if not 0 <= umbral <= 100:
            flash("El umbral debe estar entre 0 y 100.", "danger")
            return redirect(url_for("evaluaciones.iniciar"))

    sesion = _crear_sesion_con_codigo_unico(evaluacion.id, umbral)
    flash(f"Sesión abierta. Código: {sesion.codigo}", "success")
    return redirect(
        url_for("evaluaciones.detalle_sesion", eval_id=eval_id, sesion_id=sesion.id)
    )


@bp.route("/<int:eval_id>/sesiones/<int:sesion_id>")
@login_required
def detalle_sesion(eval_id, sesion_id):
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)
    # Una sesión cerrada ya no se opera: sus resultados viven en la matriz
    # (informe_todos). Esta pantalla queda para la sesión en vivo (abierta), que
    # es cuando se necesita el link para invitar, el refresco y cerrar.
    if sesion.estado != "abierta":
        return redirect(
            url_for("evaluaciones.informe_todos", eval_id=eval_id, sesion_id=sesion_id)
        )
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


def _matriz_de_sesion(evaluacion, sesion):
    """Construye la matriz de resultados de la sesión (o None si nadie finalizó).

    La letra de cada alternativa sale de su orden en la evaluación (1=A, 2=B…);
    la celda toma el texto elegido de la foto congelada y lo mapea a esa letra.
    Se comparte entre la vista (HTML) y su exportación a CSV para que muestren
    exactamente lo mismo.
    """
    finalizados = [p for p in _participantes_ordenados(sesion) if p.resultado]
    if not finalizados:
        return None

    letras = {}
    columnas_meta = []
    for pregunta in sorted(evaluacion.preguntas, key=lambda q: q.orden):
        mapa = {}
        correcta_letra = "·"
        for alt in pregunta.alternativas:
            letra = chr(64 + alt.orden)  # 1 -> A, 2 -> B, …
            mapa[alt.texto] = letra
            if alt.es_correcta:
                correcta_letra = letra
        letras[pregunta.orden] = mapa
        columnas_meta.append((pregunta.orden, pregunta.enunciado, correcta_letra))

    def letra_de(orden, texto):
        return letras.get(orden, {}).get(texto, "·")

    return construir_matriz(finalizados, columnas_meta, letra_de)


@bp.route("/<int:eval_id>/sesiones/<int:sesion_id>/informe-todos")
@login_required
def informe_todos(eval_id, sesion_id):
    """Informe de la sesión en matriz: participantes en filas, preguntas en
    columnas. Cada celda muestra la alternativa elegida (letra) y si acertó; con
    el % de logro y la nota por persona, y el % de acierto por pregunta. Queda
    lista para imprimir o guardar como un único PDF (en horizontal).

    Solo incluye a quienes finalizaron. Mismos guards que el resto: 403 si no es
    el facilitador dueño, 404 si la sesión no es de esa evaluación.
    """
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)

    matriz = _matriz_de_sesion(evaluacion, sesion)

    return render_template(
        "evaluaciones/informe_todos.html",
        evaluacion=evaluacion,
        sesion=sesion,
        matriz=matriz,
        resumen=_resumen_de_sesion(sesion),
    )


@bp.route("/<int:eval_id>/sesiones/<int:sesion_id>/resultados.csv")
@login_required
def exportar_matriz_csv(eval_id, sesion_id):
    """Descarga la matriz de resultados como CSV, con las mismas columnas que la
    tabla en pantalla (personas en filas, P1..Pn, % de logro, nota, estado) más
    el % de acierto por pregunta y la leyenda. Mismos guards; 404 si nadie
    finalizó. Lleva BOM para que Excel muestre bien los acentos y los ✓/✗.
    """
    evaluacion = _get_evaluacion_propia(eval_id)
    sesion = _get_sesion_de_evaluacion(evaluacion, sesion_id)

    matriz = _matriz_de_sesion(evaluacion, sesion)
    if matriz is None:
        abort(404)

    buffer = io.StringIO()
    buffer.write("\ufeff")
    csv.writer(buffer).writerows(filas_csv_matriz(matriz))

    nombre_archivo = f"resultados_{sesion.codigo}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


def _participantes_historial(hash_id):
    """Instancias (Participante) de una persona en sesiones CERRADAS de
    evaluaciones del facilitador actual. Lista vacía si no hay ninguna.

    Comparte el filtro de dueño con el resto de Informes: cada facilitador ve
    solo lo suyo. La usan tanto el historial en pantalla como su exportación.
    """
    return (
        db.session.query(Participante)
        .join(Sesion, Participante.sesion_id == Sesion.id)
        .join(Evaluacion, Sesion.evaluacion_id == Evaluacion.id)
        .filter(
            Participante.identificador_hash == hash_id,
            Evaluacion.facilitador_id == current_user.id,
            Sesion.estado == "cerrada",
        )
        .all()
    )


def _nombre_reciente(participantes):
    """El nombre puede variar entre sesiones (o faltar); se toma el más reciente
    no vacío como etiqueta. La identidad la da el hash, no el nombre."""
    for p in sorted(participantes, key=lambda p: p.ingreso_at, reverse=True):
        if p.nombre and p.nombre.strip():
            return p.nombre.strip()
    return None


@bp.route("/participante/<hash_id>/historial")
@login_required
def historial_participante(hash_id):
    """Historial longitudinal de una persona: todas sus sesiones (solo de las
    evaluaciones de ESTE facilitador), agrupadas por evaluación y ordenadas
    cronológicamente dentro de cada una.

    La persona se identifica por su identificador_hash (el hash del RUT). No se
    guarda ni se muestra el RUT: el hash es la llave estable entre sesiones.
    """
    participantes = _participantes_historial(hash_id)
    if not participantes:
        abort(404)

    contexto = [
        (p.sesion.evaluacion.titulo, p.sesion, p.resultado) for p in participantes
    ]
    grupos = agrupar_historial(contexto)

    return render_template(
        "evaluaciones/historial_participante.html",
        nombre=_nombre_reciente(participantes),
        hash_id=hash_id,
        hash_corto=hash_id[:10],
        grupos=grupos,
    )


@bp.route("/participante/<hash_id>/historial/export.csv")
@login_required
def exportar_historial_csv(hash_id):
    """Descarga el historial de la persona como CSV: una fila por sesión rendida,
    agrupada por evaluación (la evaluación es la primera columna).

    Mismos guards que el historial en pantalla (login + dueño): si no hay
    sesiones cerradas de este facilitador para ese hash, responde 404. Se le
    antepone un BOM para que Excel muestre bien los acentos.
    """
    participantes = _participantes_historial(hash_id)
    if not participantes:
        abort(404)

    contexto = [
        (p.sesion.evaluacion.titulo, p.sesion, p.resultado) for p in participantes
    ]
    grupos = agrupar_historial(contexto)

    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM: ayuda a Excel a leer UTF-8 (acentos)
    escritor = csv.writer(buffer)
    escritor.writerow(ENCABEZADOS_CSV_HISTORIAL)
    escritor.writerows(filas_csv_historial(grupos, formatear_fecha=hora_local))

    nombre_archivo = f"historial_{hash_id[:10]}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
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


def _crear_sesion_con_codigo_unico(evaluacion_id: int, umbral: int) -> Sesion:
    """Crea una Sesion con codigo unico, reintentando si hay colision.

    `umbral` queda fijado en la sesion al abrirla y no se edita despues.

    La unicidad la garantiza la BD (unique constraint en sesion.codigo).
    Si IntegrityError despues de _MAX_REINTENTOS_CODIGO intentos, levanta
    RuntimeError: en ese caso es mas probable un bug que mala suerte.
    """
    for _ in range(_MAX_REINTENTOS_CODIGO):
        codigo = generar_codigo_sesion()
        sesion = Sesion(
            evaluacion_id=evaluacion_id, codigo=codigo, umbral_aprobacion=umbral
        )
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