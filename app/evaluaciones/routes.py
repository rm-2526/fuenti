import csv
import io
import json
import re
import time
import unicodedata
from collections import namedtuple
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
from app.utils.qr import svg_de_enlace
from app.utils.estadisticas import resumir_resultados
from app.utils import gemini
from app.utils.analisis import (
    prompt_persona,
    prompt_sesion,
    resumen_persona,
    resumen_sesion,
)
from app.utils.reporte import (
    ENCABEZADOS_CSV,
    ENCABEZADOS_CSV_HISTORIAL,
    agrupar_historial,
    agrupar_personas,
    barras_resumen,
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


@bp.route("/<int:eval_id>/exportar.json")
@login_required
def exportar(eval_id):
    """Descarga una evaluacion propia como archivo JSON.

    El archivo NO incluye dueño ni ids internos: es portable y se puede
    importar en cualquier cuenta (queda a nombre de quien lo importe).
    """
    evaluacion = _get_evaluacion_propia(eval_id)
    contenido = json.dumps(
        _evaluacion_a_dict(evaluacion), ensure_ascii=False, indent=2
    )
    nombre = _slug(evaluacion.titulo) or "evaluacion"
    return Response(
        contenido,
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}.json"'
        },
    )


# Tope de tamano del JSON de importacion (2 MB). Una evaluacion de texto jamas
# se acerca a esto; el limite solo evita procesar un texto enorme pegado.
_MAX_IMPORT_BYTES = 2_000_000


@bp.route("/importar", methods=["GET", "POST"])
@login_required
def importar():
    """Crea una evaluacion nueva (a nombre del usuario actual) desde un JSON.

    El facilitador pega el JSON de las preguntas en un cuadro de texto e ingresa
    titulo y umbral en el formulario. Importar SIEMPRE agrega: nunca reemplaza ni
    edita una evaluacion existente, aunque el titulo coincida. La validacion es la
    misma que la creacion manual (reusa _validar e _insertar_preguntas); ademas
    valida la forma del JSON.
    """
    if request.method == "GET":
        return render_template(
            "evaluaciones/importar.html",
            titulo="",
            umbral="60",
            json_texto="",
            vista_previa=None,
        )

    # El titulo y el umbral los define el facilitador aqui; el JSON pegado solo
    # aporta las preguntas. Si algo falla, se re-muestran (incluido el texto
    # pegado) para no re-escribirlos. Dos acciones: "previsualizar" (muestra el
    # desglose sin crear nada) e "importar" (crea la evaluacion).
    accion = request.form.get("accion", "importar")
    titulo = request.form.get("titulo", "").strip()
    umbral_str = request.form.get("umbral", "").strip()
    json_texto = request.form.get("json", "")

    def _re_render(vista_previa=None):
        return render_template(
            "evaluaciones/importar.html",
            titulo=titulo,
            umbral=umbral_str,
            json_texto=json_texto,
            vista_previa=vista_previa,
        )

    if not json_texto.strip():
        flash("Debes pegar el JSON con las preguntas.", "danger")
        return _re_render()

    if len(json_texto) > _MAX_IMPORT_BYTES:
        flash("El texto pegado es demasiado largo.", "danger")
        return _re_render()

    try:
        data = json.loads(json_texto)
    except json.JSONDecodeError:
        flash(
            "El texto pegado no es un JSON válido. Revisa que tenga el formato "
            "indicado más abajo.",
            "danger",
        )
        return _re_render()

    # La validacion corre SIEMPRE, tanto en vista previa como al importar. Asi
    # "Importar" nunca crea algo distinto de lo que se acaba de previsualizar.
    preguntas, errores = _json_a_preguntas(data)
    errores = errores + _validar(titulo, umbral_str, preguntas)

    if errores:
        for e in errores:
            flash(e, "danger")
        return _re_render()

    # JSON valido. En vista previa mostramos el desglose SIN tocar la base.
    if accion == "previsualizar":
        flash(
            "Vista previa: revisa las preguntas y pulsa Importar para crear la "
            "evaluación.",
            "info",
        )
        return _re_render(vista_previa=_vista_previa(preguntas))

    evaluacion = Evaluacion(
        facilitador_id=current_user.id,
        titulo=titulo,
        umbral_aprobacion=int(umbral_str),
    )
    db.session.add(evaluacion)
    db.session.flush()

    _insertar_preguntas(evaluacion.id, preguntas)

    db.session.commit()
    flash(f'Evaluación "{titulo}" importada.', "success")
    return redirect(url_for("evaluaciones.listado"))


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

    resumen = _resumen_de_sesion(sesion)
    participantes = filas_informe_sesion(_participantes_ordenados(sesion))

    # El enlace de invitacion y su QR solo tienen sentido con la sesion
    # abierta: una sesion cerrada no acepta ingresos. Se calculan aca (y no en
    # la plantilla) para que esta solo pinte, pero SOLO si van a mostrarse: no
    # tiene sentido generar un QR que nadie va a ver.
    #
    # Esta pantalla YA NO redirige a informe_todos cuando la sesion esta
    # cerrada. Antes lo hacia, con el argumento de que "los resultados viven
    # en la matriz". El problema: cerrar_sesion redirige aqui mismo, asi que
    # esa redireccion automatica encadenaba cerrar -> detalle_sesion ->
    # informe_todos SIN que el facilitador hiciera clic en nada, y
    # informe_todos es quien genera (de forma perezosa) el analisis narrativo
    # del grupo. El facilitador terminaba esperando esa llamada igual, solo
    # que en la segunda redireccion en lugar de en el POST de cierre, y sin
    # ver la animacion de carga (que depende de un clic real en un enlace
    # .js-cargando, no de una redireccion del servidor).
    #
    # Ahora, al cerrar, esta misma pantalla se re-renderiza con el resumen y
    # la tabla de participantes -sin analisis narrativo, que no hace ninguna
    # llamada de red- y el enlace "Resultados por pregunta" (mas abajo en la
    # plantilla) es la UNICA puerta hacia informe_todos. Esa si es una accion
    # deliberada del facilitador, y ahi la animacion de "..." tiene sentido.
    if sesion.estado == "abierta":
        enlace_ingreso = url_for(
            "participante.ingreso", codigo=sesion.codigo, _external=True
        )
        qr_ingreso = svg_de_enlace(enlace_ingreso)
    else:
        enlace_ingreso = None
        qr_ingreso = None

    return render_template(
        "evaluaciones/detalle_sesion.html",
        evaluacion=evaluacion,
        sesion=sesion,
        resumen=resumen,
        participantes=participantes,
        enlace_ingreso=enlace_ingreso,
        qr_ingreso=qr_ingreso,
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

    # El análisis narrativo de esta persona se genera aquí la primera vez, no
    # al cerrar la sesión. Ver _analisis_persona_perezoso para el porqué.
    _analisis_persona_perezoso(sesion, participante, desglose)

    return render_template(
        "evaluaciones/informe_individual.html",
        evaluacion=evaluacion,
        sesion=sesion,
        participante=participante,
        resultado=participante.resultado,
        desglose=desglose,
        # De dónde vino el usuario, para que "Volver" apunte al lugar correcto.
        # Solo "historial" cambia el botón; cualquier otro valor (o ninguno)
        # mantiene el comportamiento por defecto: volver a la sesión.
        volver=request.args.get("volver"),
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
        es_vf = pregunta.tipo == "verdadero_falso"
        for alt in pregunta.alternativas:
            # V/F muestra V/F; opción múltiple, A/B/C… La letra de una V/F sale
            # del TEXTO y no del orden, porque desde que se puede dejar "Falso"
            # en primer lugar la posición ya no dice cuál es cuál.
            if es_vf:
                letra = "F" if _normalizar_vf(alt.texto) == "Falso" else "V"
            else:
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

    # El análisis narrativo del GRUPO se genera aquí, la primera vez que se
    # abre este informe, y no al cerrar la sesión. Ver el comentario en
    # cerrar_sesion para el porqué; ver _generar_analisis_ia para la
    # idempotencia (no vuelve a llamar al modelo si sesion.analisis_ia ya
    # tiene contenido).
    _generar_analisis_ia(sesion)

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
        barras=barras_resumen(grupos),
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
        # El análisis narrativo del GRUPO ya NO se genera aquí. Cerrar debe
        # quedar como una operación puramente de base de datos: un cambio de
        # estado y un commit, sin ninguna llamada de red de por medio. La
        # llamada a Gemini se traslada a la primera apertura del informe de
        # sesión (ver informe_todos), con el mismo patrón perezoso que ya
        # tenía el análisis individual (_analisis_persona_perezoso). Motivo:
        # una petición HTTP de cierre no debe depender del tiempo de
        # respuesta de un servicio externo, que es variable y, en el peor
        # caso, puede exceder el plazo del servidor.
        flash("Sesión cerrada. No aceptará nuevos ingresos.", "success")

    return redirect(
        url_for("evaluaciones.detalle_sesion", eval_id=eval_id, sesion_id=sesion_id)
    )


def _generar_analisis_ia(sesion: Sesion) -> None:
    """Genera SOLO el análisis del GRUPO, la primera vez que se abre el
    informe de sesión (informe_todos). Es el equivalente, a nivel de sesión,
    de _analisis_persona_perezoso: una llamada por informe abierto, no una
    llamada por participante encadenada dentro de otra petición.

    Historia de por qué no vive en el cierre. Hasta la prueba de
    cargabilidad, el cierre generaba el análisis de cada participante Y el
    del grupo en la misma petición. Con treinta personas eran treinta y una
    llamadas encadenadas: más de dos minutos de ejecución, que el servidor
    WSGI corta mucho antes (SIGKILL o 500), aunque la sesión sí quedara
    cerrada. La solución de esa vez fue sacar el análisis individual del
    cierre; la de ahora es sacar también el del grupo, porque incluso una
    sola llamada a un servicio externo es tiempo variable dentro de una
    operación (cerrar) que debe sentirse instantánea para quien está frente a
    un grupo esperando. Cerrar hoy es solo un cambio de estado y un commit.

    Degrada en silencio: sin API key no hace nada; cualquier error se traga
    para que abrir el informe nunca falle por culpa de la IA (el informe se
    ve igual, solo sin el bloque de análisis). Es idempotente
    (generar_analisis_de_sesion solo genera si sesion.analisis_ia está en
    NULL), así que si una llamada falla, la siguiente vez que se abra este
    mismo informe se reintenta sola, sin acción del facilitador.

    El backfill por consola usa el mismo núcleo (generar_analisis_de_sesion)
    con incluir_personas=True y SÍ reporta lo que hizo.
    """
    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        return
    modelo = current_app.config.get("GEMINI_MODEL", gemini.MODELO_POR_DEFECTO)
    espaciado = current_app.config.get("GEMINI_ESPACIADO_SEG", 0.0)
    try:
        generar_analisis_de_sesion(
            sesion, api_key, modelo, espaciado=espaciado, incluir_personas=False
        )
        db.session.commit()
    except Exception:
        # Nunca dejar la sesión a medio cerrar por un problema de la IA.
        db.session.rollback()


def _analisis_persona_perezoso(sesion, participante, desglose) -> None:
    """Genera el análisis individual la PRIMERA vez que se abre su informe.

    Es la contraparte de la decisión explicada en _generar_analisis_ia: una
    llamada por informe abierto, en lugar de treinta encadenadas al cerrar.
    El facilitador revisa los informes de a uno, así que el costo queda
    repartido y ninguna petición acumula la espera de todas las demás.

    Idempotente: solo genera si 'analisis_ia' está en NULL, de modo que abrir
    el informe dos veces no vuelve a llamar al modelo ni pisa lo ya congelado.
    Degrada en silencio: sin clave, o si el servicio falla, el informe se
    muestra igual y simplemente no aparece el recuadro de análisis.
    """
    resultado = participante.resultado
    if resultado is None or resultado.analisis_ia:
        return
    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        return
    modelo = current_app.config.get("GEMINI_MODEL", gemini.MODELO_POR_DEFECTO)
    try:
        resumen_grupo = _resumen_de_sesion(sesion)
        datos = resumen_persona(
            desglose,
            porcentaje=resultado.porcentaje,
            umbral=resultado.umbral_aprobacion,
            aprobado=resultado.aprobado,
            promedio_logro_grupo=resumen_grupo.promedio_logro,
        )
        texto = gemini.generar_texto(prompt_persona(datos), api_key, modelo)
        if texto:
            resultado.analisis_ia = texto
            resultado.analisis_generado_at = ahora_utc()
            db.session.commit()
    except Exception:
        # El informe vale por sí mismo: un fallo de la IA no lo impide.
        db.session.rollback()


# Resultado de una corrida de generación, para poder reportarlo (lo usa el CLI).
ResultadoAnalisis = namedtuple(
    "ResultadoAnalisis",
    "finalizados personas_generadas personas_omitidas "
    "grupo_generado grupo_omitido fallos",
)


def generar_analisis_de_sesion(
    sesion, api_key, modelo, espaciado: float = 0.0, _sleep=time.sleep,
    incluir_personas: bool = True,
) -> "ResultadoAnalisis":
    """Núcleo de generación del análisis de IA (grupo + por persona).

    Compartido entre el cierre de sesión y el backfill por consola. Es
    idempotente: solo genera donde 'analisis_ia' está en NULL, así que volver a
    correrlo no pisa lo ya congelado. NO hace commit (lo hace quien llama) y NO
    atrapa excepciones (quien llama decide). Devuelve cuántos análisis generó,
    cuántos omitió por ya tenerlos y cuántas llamadas al modelo volvieron vacías.

    'espaciado' son los segundos de pausa ENTRE llamadas reales al modelo, para
    no pasarse del límite por minuto (RPM) del tier gratis. No pausa antes de la
    primera ni después de la última, ni gasta pausas en participantes omitidos.
    El backoff de gemini.py sigue actuando como red de seguridad por si igual
    aparece un 429. '_sleep' se inyecta para poder testear sin esperar de verdad.

    'incluir_personas' distingue a los dos llamadores. El backfill por consola
    lo deja en True y genera todo lo que falte. La apertura del informe de
    sesión (_generar_analisis_ia) lo pone en False y genera solo el grupo,
    porque encadenar una llamada por participante dentro de esa misma
    petición excedería el plazo del servidor cuando el grupo es grande. El
    análisis individual se genera aparte, al abrir cada informe individual
    (_analisis_persona_perezoso), repartido en el tiempo en vez de encadenado.

    PRIVACIDAD: a analisis.py solo se le pasan textos de preguntas, aciertos y
    números; el nombre y el hash del participante no salen nunca hacia el modelo.
    """
    finalizados = [p for p in sesion.participantes if p.resultado is not None]
    if not finalizados:
        return ResultadoAnalisis(0, 0, 0, False, False, 0)

    resumen_grupo = _resumen_de_sesion(sesion)
    desgloses = [desglose_desde_respuestas(p.respuestas) for p in finalizados]

    personas_generadas = 0
    personas_omitidas = 0
    fallos = 0

    # Espacia las llamadas: pausa 'espaciado' segundos antes de cada llamada
    # salvo la primera. Así el ritmo total no supera el RPM del tier gratis.
    _primera = [True]

    def _espaciar():
        if _primera[0]:
            _primera[0] = False
        elif espaciado:
            _sleep(espaciado)

    # --- Por persona (omitido cuando llama el cierre de sesión) ---
    for participante, desglose in zip(
        finalizados if incluir_personas else [], desgloses
    ):
        resultado = participante.resultado
        if resultado.analisis_ia:
            personas_omitidas += 1
            continue
        datos = resumen_persona(
            desglose,
            porcentaje=resultado.porcentaje,
            umbral=resultado.umbral_aprobacion,
            aprobado=resultado.aprobado,
            promedio_logro_grupo=resumen_grupo.promedio_logro,
        )
        _espaciar()
        texto = gemini.generar_texto(prompt_persona(datos), api_key, modelo)
        if texto:
            resultado.analisis_ia = texto
            resultado.analisis_generado_at = ahora_utc()
            personas_generadas += 1
        else:
            fallos += 1

    # --- Del grupo ---
    grupo_generado = False
    grupo_omitido = bool(sesion.analisis_ia)
    if not grupo_omitido:
        datos_sesion = resumen_sesion(
            desgloses,
            aprobados=resumen_grupo.aprobados,
            reprobados=resumen_grupo.reprobados,
            promedio_logro=resumen_grupo.promedio_logro,
        )
        _espaciar()
        texto = gemini.generar_texto(prompt_sesion(datos_sesion), api_key, modelo)
        if texto:
            sesion.analisis_ia = texto
            sesion.analisis_generado_at = ahora_utc()
            grupo_generado = True
        else:
            fallos += 1

    return ResultadoAnalisis(
        finalizados=len(finalizados),
        personas_generadas=personas_generadas,
        personas_omitidas=personas_omitidas,
        grupo_generado=grupo_generado,
        grupo_omitido=grupo_omitido,
        fallos=fallos,
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


# Textos canonicos de una pregunta Verdadero/Falso. La app NUNCA guarda otra
# cosa en una alternativa V/F: o es "Verdadero" o es "Falso".
_CANONICOS_VF = {"verdadero": "Verdadero", "falso": "Falso"}


def _normalizar_vf(texto):
    """Mapea el texto de una alternativa V/F a su forma canonica.

    Devuelve "Verdadero", "Falso", o None si el texto no se reconoce. Ignora
    mayusculas, espacios y tildes, para que "  verdadero " o "FALSO" tambien
    sirvan (util al importar JSON escrito a mano o generado por una IA).
    """
    base = (
        unicodedata.normalize("NFKD", (texto or "").strip())
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return _CANONICOS_VF.get(base)


def _textos_vf(alternativas):
    """Decide el texto definitivo de cada alternativa de una pregunta V/F.

    `alternativas` es la lista [(j, texto)] ya parseada. Devuelve {j: texto}.

    Si las dos alternativas traen textos reconocibles y distintos ("Verdadero" y
    "Falso", en cualquier orden), se RESPETA ese orden: asi el facilitador puede
    dejar "Falso" en primer lugar y la primera opcion no es siempre la verdadera.

    En cualquier otro caso (textos vacios, "V"/"F", basura de un POST manipulado)
    se cae al comportamiento historico: la primera es "Verdadero" y la segunda
    "Falso". Por eso la app nunca guarda un texto raro en una V/F, venga de donde
    venga, y las evaluaciones anteriores se comportan exactamente igual que antes.
    """
    canonicos = [(j, _normalizar_vf(t)) for j, t in alternativas]
    valores = [c for _, c in canonicos]
    if len(valores) == 2 and None not in valores and valores[0] != valores[1]:
        return dict(canonicos)
    return {
        j: ("Verdadero" if pos == 1 else "Falso")
        for pos, (j, _) in enumerate(alternativas, start=1)
    }


def _insertar_preguntas(evaluacion_id, preguntas):
    """Crea las Pregunta/Alternativa de una evaluacion a partir de la lista ya
    parseada y validada. Compartido por crear, editar e importar.

    `preguntas` es la salida de _parsear_preguntas: lista de dicts con
    {enunciado, correcta, alternativas: [(j, texto)]}.
    """
    for orden_p, p in enumerate(preguntas, start=1):
        tipo = p.get("tipo", "opcion_multiple")
        pregunta = Pregunta(
            evaluacion_id=evaluacion_id,
            enunciado=p["enunciado"],
            orden=orden_p,
            tipo=tipo,
        )
        db.session.add(pregunta)
        db.session.flush()

        # En Verdadero/Falso el texto no se guarda tal cual: pasa por _textos_vf,
        # que respeta el orden elegido si viene explicito y si no lo fija por
        # posicion. La alternativa correcta la sigue marcando el indice elegido.
        textos_vf = _textos_vf(p["alternativas"]) if tipo == "verdadero_falso" else None

        correcta_idx = int(p["correcta"])
        for orden_a, (j, texto) in enumerate(p["alternativas"], start=1):
            if textos_vf is not None:
                texto = textos_vf[j]
            alternativa = Alternativa(
                pregunta_id=pregunta.id,
                texto=texto,
                es_correcta=(j == correcta_idx),
                orden=orden_a,
            )
            db.session.add(alternativa)


def _slug(texto: str) -> str:
    """Convierte un titulo en un nombre de archivo seguro (ascii, sin espacios)."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:60]


def _evaluacion_a_dict(evaluacion) -> dict:
    """Serializa una evaluacion al formato JSON de exportacion.

    No incluye ids internos ni el dueno: el archivo es portable. El orden de
    preguntas y alternativas se respeta, asi que una V/F que quedo con "Falso"
    en primer lugar se exporta e importa de vuelta en ese mismo orden.
    """
    return {
        "formato": "fuenti.evaluacion",
        "version": 1,
        "titulo": evaluacion.titulo,
        "umbral_aprobacion": evaluacion.umbral_aprobacion,
        "preguntas": [
            {
                "enunciado": p.enunciado,
                "tipo": p.tipo,
                "alternativas": [
                    {"texto": a.texto, "es_correcta": a.es_correcta}
                    for a in sorted(p.alternativas, key=lambda a: a.orden)
                ],
            }
            for p in sorted(evaluacion.preguntas, key=lambda p: p.orden)
        ],
    }


def _json_a_preguntas(data):
    """Extrae y valida la FORMA de las preguntas del JSON: (preguntas, errores),
    en la estructura interna que consumen _validar e _insertar_preguntas.

    El titulo y el umbral NO salen del archivo: los ingresa el facilitador en el
    formulario de importacion. Si el archivo trae 'titulo' o 'umbral_aprobacion'
    (por ejemplo, uno exportado desde la app), simplemente se ignoran. Las reglas
    de dominio (rangos, conteos) las aplica _validar despues, igual que en la
    creacion manual.
    """
    if not isinstance(data, dict):
        return [], ["El archivo debe contener un objeto JSON en la raíz."]

    errores = []

    preguntas_json = data.get("preguntas")
    if not isinstance(preguntas_json, list):
        return [], ["El archivo debe tener una lista llamada 'preguntas'."]

    preguntas = []
    for idx, p in enumerate(preguntas_json, start=1):
        if not isinstance(p, dict):
            errores.append(f"La pregunta {idx} debe ser un objeto JSON.")
            continue

        enunciado = p.get("enunciado", "")
        if not isinstance(enunciado, str):
            errores.append(f"La pregunta {idx}: 'enunciado' debe ser texto.")
            enunciado = ""

        tipo = p.get("tipo", "opcion_multiple")
        if not isinstance(tipo, str) or not tipo.strip():
            tipo = "opcion_multiple"
        tipo = tipo.strip()

        alts_json = p.get("alternativas")
        if not isinstance(alts_json, list):
            errores.append(f"La pregunta {idx}: 'alternativas' debe ser una lista.")
            alts_json = []

        pares = []  # (texto, es_correcta)
        for k, a in enumerate(alts_json, start=1):
            if not isinstance(a, dict):
                errores.append(
                    f"La pregunta {idx}, alternativa {k}: debe ser un objeto JSON."
                )
                continue
            texto = a.get("texto", "")
            if not isinstance(texto, str):
                errores.append(
                    f"La pregunta {idx}, alternativa {k}: 'texto' debe ser texto."
                )
                texto = ""
            es_correcta = a.get("es_correcta", False)
            if not isinstance(es_correcta, bool):
                errores.append(
                    f"La pregunta {idx}, alternativa {k}: "
                    "'es_correcta' debe ser true o false."
                )
                es_correcta = False
            pares.append((texto.strip(), es_correcta))

        # En opcion multiple, las alternativas sin texto se descartan (igual que
        # en el formulario). En V/F no se descartan: deben venir las 2, y su
        # texto SI importa, porque decide el orden ("Falso" puede ir primero).
        # Lo que no se reconozca lo normaliza _textos_vf al insertar.
        if tipo == "opcion_multiple":
            pares = [(t, c) for (t, c) in pares if t]

        alternativas = [(j, t) for j, (t, c) in enumerate(pares)]
        correctas = [j for j, (t, c) in enumerate(pares) if c]

        if len(correctas) == 1:
            correcta = str(correctas[0])
        elif not correctas:
            errores.append(
                f"La pregunta {idx}: debe haber exactamente una alternativa con "
                "es_correcta=true (no hay ninguna)."
            )
            correcta = ""
        else:
            errores.append(
                f"La pregunta {idx}: debe haber exactamente una alternativa con "
                f"es_correcta=true (hay {len(correctas)})."
            )
            correcta = ""

        preguntas.append(
            {
                "enunciado": enunciado.strip(),
                "tipo": tipo,
                "correcta": correcta,
                "alternativas": alternativas,
            }
        )

    return preguntas, errores


def _vista_previa(preguntas):
    """Arma el desglose legible para la vista previa a partir de las preguntas ya
    parseadas y validadas. Muestra los textos TAL COMO quedaran al crear: para
    las V/F pasa por _textos_vf (el mismo helper que usa _insertar_preguntas), de
    modo que la previa refleja el orden real, incluido "Falso" en primer lugar.
    """
    etiquetas = {
        "opcion_multiple": "Opción múltiple",
        "verdadero_falso": "Verdadero / Falso",
    }
    vista = []
    for p in preguntas:
        es_vf = p["tipo"] == "verdadero_falso"
        textos_vf = _textos_vf(p["alternativas"]) if es_vf else None
        alternativas = []
        for j, texto in p["alternativas"]:
            display = textos_vf[j] if textos_vf is not None else texto
            alternativas.append(
                {"texto": display, "correcta": str(j) == str(p["correcta"])}
            )
        vista.append(
            {
                "enunciado": p["enunciado"],
                "tipo_label": etiquetas.get(p["tipo"], p["tipo"]),
                "alternativas": alternativas,
            }
        )
    return vista


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
                "tipo": p.tipo,
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
                # Tipo de pregunta; por defecto opción múltiple (compatible con
                # formularios y tests que no envían el campo).
                "tipo": form.get(f"pregunta_{idx}_tipo", "opcion_multiple").strip()
                or "opcion_multiple",
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

        tipo = p.get("tipo", "opcion_multiple")
        if tipo not in ("opcion_multiple", "verdadero_falso"):
            errores.append(f"La pregunta {idx} tiene un tipo no válido.")

        n_alts = len(p["alternativas"])
        if tipo == "verdadero_falso":
            if n_alts != 2:
                errores.append(
                    f"La pregunta {idx} (Verdadero/Falso) debe tener "
                    "exactamente 2 alternativas."
                )
        else:
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