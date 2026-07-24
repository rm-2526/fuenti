"""Tests del tipo de pregunta Verdadero/Falso.

Cubre autoría (creación por POST), integridad (los textos se guardan como
Verdadero/Falso aunque el POST venga manipulado), validación (exactamente 2
alternativas), round-trip de edición, y la presentación en la matriz (letras
V/F en vez de A/B). La calificación NO cambia (se corrige por es_correcta), así
que no se prueba aparte.
"""

from app import db
from app.models import (
    Alternativa,
    Evaluacion,
    Participante,
    Pregunta,
    Respuesta,
    Resultado,
    Sesion,
)


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=True
    )


# ----------------------------- Autoría (POST) -----------------------------

def test_crear_pregunta_vf_guarda_tipo_y_alternativas(client, facilitador, app):
    _login(client)
    data = {
        "titulo": "Seguridad",
        "umbral": "60",
        "pregunta_0_enunciado": "El casco es obligatorio.",
        "pregunta_0_tipo": "verdadero_falso",
        "pregunta_0_correcta": "0",  # Verdadero (índice 0) es la correcta
        "pregunta_0_alternativa_0_texto": "Verdadero",
        "pregunta_0_alternativa_1_texto": "Falso",
    }
    resp = client.post("/evaluaciones/nueva", data=data, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        q = (
            db.session.query(Pregunta)
            .filter_by(enunciado="El casco es obligatorio.")
            .one()
        )
        assert q.tipo == "verdadero_falso"
        alts = sorted(q.alternativas, key=lambda a: a.orden)
        assert [a.texto for a in alts] == ["Verdadero", "Falso"]
        assert alts[0].es_correcta is True   # Verdadero
        assert alts[1].es_correcta is False  # Falso


def test_pregunta_opcion_multiple_sin_tipo_queda_opcion_multiple(client, facilitador, app):
    """Compatibilidad: un POST sin el campo tipo (o de opción múltiple normal)
    guarda tipo='opcion_multiple'."""
    _login(client)
    data = {
        "titulo": "Clásica",
        "umbral": "60",
        "pregunta_0_enunciado": "¿2 + 2?",
        "pregunta_0_correcta": "0",
        "pregunta_0_alternativa_0_texto": "4",
        "pregunta_0_alternativa_1_texto": "5",
    }
    resp = client.post("/evaluaciones/nueva", data=data, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        q = db.session.query(Pregunta).filter_by(enunciado="¿2 + 2?").one()
        assert q.tipo == "opcion_multiple"


def test_crear_vf_normaliza_textos_manipulados(client, facilitador, app):
    """Aunque el POST envíe textos falsos, se guardan Verdadero/Falso por orden;
    la alternativa marcada sigue siendo la correcta."""
    _login(client)
    data = {
        "titulo": "Anti-tampering",
        "umbral": "60",
        "pregunta_0_enunciado": "Afirmación.",
        "pregunta_0_tipo": "verdadero_falso",
        "pregunta_0_correcta": "1",   # la segunda (Falso) es la correcta
        "pregunta_0_alternativa_0_texto": "hola",   # basura
        "pregunta_0_alternativa_1_texto": "chao",   # basura
    }
    resp = client.post("/evaluaciones/nueva", data=data, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        q = db.session.query(Pregunta).filter_by(enunciado="Afirmación.").one()
        alts = sorted(q.alternativas, key=lambda a: a.orden)
        assert [a.texto for a in alts] == ["Verdadero", "Falso"]
        assert alts[0].es_correcta is False  # Verdadero
        assert alts[1].es_correcta is True   # Falso (índice 1, el marcado)


def test_vf_con_tres_alternativas_falla(client, facilitador, app):
    _login(client)
    data = {
        "titulo": "Mal armada",
        "umbral": "60",
        "pregunta_0_enunciado": "Afirmación.",
        "pregunta_0_tipo": "verdadero_falso",
        "pregunta_0_correcta": "0",
        "pregunta_0_alternativa_0_texto": "Verdadero",
        "pregunta_0_alternativa_1_texto": "Falso",
        "pregunta_0_alternativa_2_texto": "Quizás",
    }
    resp = client.post("/evaluaciones/nueva", data=data)  # sin follow: re-render
    assert resp.status_code == 200
    assert "exactamente 2 alternativas" in resp.get_data(as_text=True)
    with app.app_context():
        assert (
            db.session.query(Evaluacion).filter_by(titulo="Mal armada").first() is None
        )


# ----------------------------- Edición -----------------------------

def _crear_eval_vf(app, facilitador_id, titulo="Edit VF", enunciado="Afirmación."):
    with app.app_context():
        e = Evaluacion(facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=60)
        db.session.add(e)
        db.session.flush()
        q = Pregunta(
            evaluacion_id=e.id, enunciado=enunciado, orden=1, tipo="verdadero_falso"
        )
        db.session.add(q)
        db.session.flush()
        db.session.add_all([
            Alternativa(pregunta_id=q.id, texto="Verdadero", es_correcta=True, orden=1),
            Alternativa(pregunta_id=q.id, texto="Falso", es_correcta=False, orden=2),
        ])
        db.session.commit()
        return e.id


def test_editar_precarga_y_conserva_tipo_vf(client, facilitador, app):
    eval_id = _crear_eval_vf(app, facilitador.id)

    _login(client)
    # GET editar: el formulario trae el tipo oculto y las alternativas readonly.
    cuerpo = client.get(f"/evaluaciones/{eval_id}/editar").get_data(as_text=True)
    assert 'name="pregunta_0_tipo" value="verdadero_falso"' in cuerpo
    assert "readonly" in cuerpo
    assert "Verdadero" in cuerpo and "Falso" in cuerpo

    # POST editar conservando el tipo -> sigue siendo verdadero_falso.
    data = {
        "titulo": "Edit VF",
        "umbral": "60",
        "pregunta_0_enunciado": "Afirmación editada.",
        "pregunta_0_tipo": "verdadero_falso",
        "pregunta_0_correcta": "0",
        "pregunta_0_alternativa_0_texto": "Verdadero",
        "pregunta_0_alternativa_1_texto": "Falso",
    }
    resp = client.post(
        f"/evaluaciones/{eval_id}/editar", data=data, follow_redirects=True
    )
    assert resp.status_code == 200
    with app.app_context():
        q = db.session.query(Pregunta).filter_by(evaluacion_id=eval_id).one()
        assert q.tipo == "verdadero_falso"
        assert q.enunciado == "Afirmación editada."


# ----------------------------- Matriz -----------------------------

def test_matriz_muestra_letras_vf(client, facilitador, app):
    """En la matriz, una pregunta V/F muestra V/F (no A/B)."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador.id, titulo="Matriz VF", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()
        q = Pregunta(
            evaluacion_id=e.id, enunciado="El casco es obligatorio.",
            orden=1, tipo="verdadero_falso",
        )
        db.session.add(q)
        db.session.flush()
        db.session.add_all([
            Alternativa(pregunta_id=q.id, texto="Verdadero", es_correcta=True, orden=1),
            Alternativa(pregunta_id=q.id, texto="Falso", es_correcta=False, orden=2),
        ])
        s = Sesion(
            evaluacion_id=e.id, codigo="VFSES", estado="cerrada", umbral_aprobacion=60
        )
        db.session.add(s)
        db.session.flush()
        p = Participante(sesion_id=s.id, identificador_hash="hash_vf", nombre="Ana Soto")
        db.session.add(p)
        db.session.flush()
        db.session.add(Respuesta(
            participante_id=p.id, enunciado_texto="El casco es obligatorio.",
            elegida_texto="Verdadero", correcta_texto="Verdadero", acerto=True, orden=1,
        ))
        db.session.add(Resultado(
            participante_id=p.id, puntaje=1, total_preguntas=1,
            porcentaje=100.0, nota=7.0, aprobado=True,
        ))
        db.session.commit()
        eval_id, sesion_id = e.id, s.id

    _login(client)
    cuerpo = client.get(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/informe-todos"
    ).get_data(as_text=True)

    # La celda lleva la letra sola (el ✓/✗ se quito: el color y el subrayado
    # distinguen acierto de error). Lo que se verifica aqui es CUAL letra.
    assert 'cell-ok">V<' in cuerpo      # celda: V (Verdadero), acertada
    assert "correcta: V" in cuerpo      # encabezado marca la correcta como V
    assert 'cell-ok">A<' not in cuerpo  # NO se usa la letra A para una V/F


# ----------------------- Orden elegible de la V/F -----------------------
# El facilitador puede intercambiar Verdadero y Falso para que la primera opcion
# no sea siempre la verdadera. El boton "Intercambiar" del formulario permuta los
# textos y el radio marcado; el backend guarda ese orden tal cual.

def test_crear_vf_con_falso_primero_guarda_ese_orden(client, facilitador, app):
    _login(client)
    data = {
        "titulo": "VF invertida",
        "umbral": "60",
        "pregunta_0_enunciado": "La Luna es una estrella.",
        "pregunta_0_tipo": "verdadero_falso",
        "pregunta_0_correcta": "0",             # la primera, que ahora es Falso
        "pregunta_0_alternativa_0_texto": "Falso",
        "pregunta_0_alternativa_1_texto": "Verdadero",
    }
    resp = client.post("/evaluaciones/nueva", data=data, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        q = (
            db.session.query(Pregunta)
            .filter_by(enunciado="La Luna es una estrella.")
            .one()
        )
        alts = sorted(q.alternativas, key=lambda a: a.orden)
        assert [a.texto for a in alts] == ["Falso", "Verdadero"]
        assert alts[0].es_correcta is True    # Falso
        assert alts[1].es_correcta is False   # Verdadero


def test_editar_precarga_conserva_el_orden_invertido(client, facilitador, app):
    """Al editar, el formulario vuelve a mostrar Falso primero (no lo reordena)."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador.id, titulo="Editar invertida", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()
        q = Pregunta(
            evaluacion_id=e.id, enunciado="Afirmación.", orden=1, tipo="verdadero_falso"
        )
        db.session.add(q)
        db.session.flush()
        db.session.add_all([
            Alternativa(pregunta_id=q.id, texto="Falso", es_correcta=True, orden=1),
            Alternativa(pregunta_id=q.id, texto="Verdadero", es_correcta=False, orden=2),
        ])
        db.session.commit()
        eval_id = e.id

    _login(client)
    cuerpo = client.get(f"/evaluaciones/{eval_id}/editar").get_data(as_text=True)
    assert 'value="Falso"' in cuerpo
    assert cuerpo.index('value="Falso"') < cuerpo.index('value="Verdadero"')
    assert "btn-intercambiar-vf" in cuerpo   # el botón de intercambio está


def test_matriz_usa_el_texto_y_no_la_posicion(client, facilitador, app):
    """Con "Falso" en primer lugar, la matriz debe mostrar F (no V): la letra
    sale del texto de la alternativa, no de su orden."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador.id, titulo="Matriz invertida", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()
        q = Pregunta(
            evaluacion_id=e.id, enunciado="La Luna es una estrella.",
            orden=1, tipo="verdadero_falso",
        )
        db.session.add(q)
        db.session.flush()
        db.session.add_all([
            Alternativa(pregunta_id=q.id, texto="Falso", es_correcta=True, orden=1),
            Alternativa(pregunta_id=q.id, texto="Verdadero", es_correcta=False, orden=2),
        ])
        s = Sesion(
            evaluacion_id=e.id, codigo="VFINV", estado="cerrada", umbral_aprobacion=60
        )
        db.session.add(s)
        db.session.flush()
        p = Participante(sesion_id=s.id, identificador_hash="hash_inv", nombre="Ana Soto")
        db.session.add(p)
        db.session.flush()
        db.session.add(Respuesta(
            participante_id=p.id, enunciado_texto="La Luna es una estrella.",
            elegida_texto="Falso", correcta_texto="Falso", acerto=True, orden=1,
        ))
        db.session.add(Resultado(
            participante_id=p.id, puntaje=1, total_preguntas=1,
            porcentaje=100.0, nota=7.0, aprobado=True,
        ))
        db.session.commit()
        eval_id, sesion_id = e.id, s.id

    _login(client)
    cuerpo = client.get(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/informe-todos"
    ).get_data(as_text=True)

    assert 'cell-ok">F<' in cuerpo    # respondió Falso, que estaba primera
    assert "correcta: F" in cuerpo    # y la correcta es F, no V
    assert 'cell-ok">V<' not in cuerpo
