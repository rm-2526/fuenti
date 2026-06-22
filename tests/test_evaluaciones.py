"""Tests del CRUD de evaluaciones (OE1)."""

from app import db
from app.models import Alternativa, Evaluacion, Facilitador, Pregunta


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _payload_valido(titulo="Eval de prueba", umbral="60"):
    """Payload mínimo: 1 pregunta, 2 alternativas, la primera correcta."""
    return {
        "titulo": titulo,
        "umbral": umbral,
        "pregunta_0_enunciado": "¿Cuánto es 2 + 2?",
        "pregunta_0_correcta": "0",
        "pregunta_0_alternativa_0_texto": "4",
        "pregunta_0_alternativa_1_texto": "5",
    }


# -------------------- Acceso --------------------

def test_listado_sin_auth_redirige_a_login(client):
    resp = client.get("/evaluaciones/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_listado_vacio_con_auth(client, facilitador):
    _login(client)
    resp = client.get("/evaluaciones/")
    assert resp.status_code == 200
    assert "No tienes evaluaciones".encode("utf-8") in resp.data


# -------------------- Creación válida --------------------

def test_crear_evaluacion_valida(client, facilitador, app):
    _login(client)
    resp = client.post("/evaluaciones/nueva", data=_payload_valido(), follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        evals = db.session.query(Evaluacion).all()
        assert len(evals) == 1
        e = evals[0]
        assert e.titulo == "Eval de prueba"
        assert e.umbral_aprobacion == 60
        assert len(e.preguntas) == 1
        p = e.preguntas[0]
        assert p.enunciado == "¿Cuánto es 2 + 2?"
        assert len(p.alternativas) == 2
        correctas = [a for a in p.alternativas if a.es_correcta]
        assert len(correctas) == 1
        assert correctas[0].texto == "4"


def test_crear_evaluacion_multiples_preguntas_y_alternativas(client, facilitador, app):
    _login(client)
    data = {
        "titulo": "Eval múltiple",
        "umbral": "70",
        # Pregunta 0: 3 alternativas, correcta = índice 2
        "pregunta_0_enunciado": "Capital de Chile",
        "pregunta_0_correcta": "2",
        "pregunta_0_alternativa_0_texto": "Lima",
        "pregunta_0_alternativa_1_texto": "Buenos Aires",
        "pregunta_0_alternativa_2_texto": "Santiago",
        # Pregunta 1: 4 alternativas con un hueco en índice (simula quitar alt 1)
        "pregunta_1_enunciado": "Año de la independencia",
        "pregunta_1_correcta": "0",
        "pregunta_1_alternativa_0_texto": "1810",
        "pregunta_1_alternativa_2_texto": "1818",
        "pregunta_1_alternativa_3_texto": "1820",
    }
    resp = client.post("/evaluaciones/nueva", data=data, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        e = db.session.query(Evaluacion).one()
        assert len(e.preguntas) == 2
        p0 = [p for p in e.preguntas if p.orden == 1][0]
        p1 = [p for p in e.preguntas if p.orden == 2][0]
        assert len(p0.alternativas) == 3
        assert len(p1.alternativas) == 3  # el hueco no debe contar
        assert [a for a in p0.alternativas if a.es_correcta][0].texto == "Santiago"
        assert [a for a in p1.alternativas if a.es_correcta][0].texto == "1810"


# -------------------- Validaciones --------------------

def test_crear_sin_titulo_falla(client, facilitador, app):
    _login(client)
    data = _payload_valido(titulo="")
    resp = client.post("/evaluaciones/nueva", data=data)
    assert resp.status_code == 200
    assert "obligatorio".encode("utf-8") in resp.data
    with app.app_context():
        assert db.session.query(Evaluacion).count() == 0


def test_crear_umbral_fuera_de_rango_falla(client, facilitador, app):
    _login(client)
    data = _payload_valido(umbral="150")
    resp = client.post("/evaluaciones/nueva", data=data)
    assert resp.status_code == 200
    assert "umbral".encode("utf-8") in resp.data.lower() or b"Umbral" in resp.data
    with app.app_context():
        assert db.session.query(Evaluacion).count() == 0


def test_crear_sin_preguntas_falla(client, facilitador, app):
    _login(client)
    resp = client.post("/evaluaciones/nueva", data={"titulo": "X", "umbral": "60"})
    assert resp.status_code == 200
    assert "al menos una pregunta".encode("utf-8") in resp.data
    with app.app_context():
        assert db.session.query(Evaluacion).count() == 0


def test_crear_pregunta_con_una_sola_alternativa_falla(client, facilitador, app):
    _login(client)
    data = {
        "titulo": "X",
        "umbral": "60",
        "pregunta_0_enunciado": "¿?",
        "pregunta_0_correcta": "0",
        "pregunta_0_alternativa_0_texto": "única",
    }
    resp = client.post("/evaluaciones/nueva", data=data)
    assert resp.status_code == 200
    assert "al menos 2 alternativas".encode("utf-8") in resp.data
    with app.app_context():
        assert db.session.query(Evaluacion).count() == 0


def test_crear_sin_marcar_correcta_falla(client, facilitador, app):
    _login(client)
    data = {
        "titulo": "X",
        "umbral": "60",
        "pregunta_0_enunciado": "¿?",
        # falta pregunta_0_correcta
        "pregunta_0_alternativa_0_texto": "A",
        "pregunta_0_alternativa_1_texto": "B",
    }
    resp = client.post("/evaluaciones/nueva", data=data)
    assert resp.status_code == 200
    assert "alternativa correcta".encode("utf-8") in resp.data
    with app.app_context():
        assert db.session.query(Evaluacion).count() == 0


# -------------------- Aislamiento por facilitador --------------------

def test_listado_solo_muestra_evaluaciones_propias(client, facilitador, app):
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        otro.set_password("clave123")
        db.session.add(otro)
        db.session.flush()
        e_ajena = Evaluacion(
            facilitador_id=otro.id,
            titulo="Evaluación ajena",
            umbral_aprobacion=60,
        )
        db.session.add(e_ajena)
        db.session.commit()

    _login(client)
    client.post("/evaluaciones/nueva", data=_payload_valido(titulo="Mi eval"), follow_redirects=True)

    resp = client.get("/evaluaciones/")
    assert resp.status_code == 200
    assert b"Mi eval" in resp.data
    assert "Evaluación ajena".encode("utf-8") not in resp.data


def test_detalle_de_evaluacion_ajena_es_403(client, facilitador, app):
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        otro.set_password("clave123")
        db.session.add(otro)
        db.session.flush()
        e_ajena = Evaluacion(
            facilitador_id=otro.id,
            titulo="Ajena",
            umbral_aprobacion=60,
        )
        db.session.add(e_ajena)
        db.session.commit()
        eval_id_ajena = e_ajena.id

    _login(client)
    resp = client.get(f"/evaluaciones/{eval_id_ajena}")
    assert resp.status_code == 403


# -------------------- Eliminar --------------------

def test_eliminar_propia_funciona(client, facilitador, app):
    _login(client)
    client.post("/evaluaciones/nueva", data=_payload_valido(), follow_redirects=True)

    with app.app_context():
        e = db.session.query(Evaluacion).one()
        eval_id = e.id

    resp = client.post(f"/evaluaciones/{eval_id}/eliminar", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.query(Evaluacion).count() == 0
        # Cascada verificada: no quedaron preguntas ni alternativas
        assert db.session.query(Pregunta).count() == 0
        assert db.session.query(Alternativa).count() == 0


def test_eliminar_ajena_es_403(client, facilitador, app):
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        otro.set_password("clave123")
        db.session.add(otro)
        db.session.flush()
        e_ajena = Evaluacion(
            facilitador_id=otro.id,
            titulo="Ajena",
            umbral_aprobacion=60,
        )
        db.session.add(e_ajena)
        db.session.commit()
        eval_id_ajena = e_ajena.id

    _login(client)
    resp = client.post(f"/evaluaciones/{eval_id_ajena}/eliminar")
    assert resp.status_code == 403

    with app.app_context():
        assert db.session.get(Evaluacion, eval_id_ajena) is not None