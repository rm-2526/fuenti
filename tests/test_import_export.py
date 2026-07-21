"""Tests de importación y exportación de evaluaciones en formato JSON.

Cubren: control de acceso (login y dueño), exportación (estructura del JSON,
ida y vuelta), e importación (creación a nombre del usuario, validación de la
forma del JSON y reuso de las reglas de dominio de la creación manual).
"""

import io
import json

from app import db
from app.models import Alternativa, Evaluacion, Facilitador, Pregunta


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _crear_evaluacion(facilitador_id, titulo="Eval de prueba", umbral=60):
    """Crea directamente en la base una evaluación con una opción múltiple y
    una Verdadero/Falso, para tener algo que exportar."""
    ev = Evaluacion(facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=umbral)
    db.session.add(ev)
    db.session.flush()

    p1 = Pregunta(evaluacion_id=ev.id, enunciado="¿2+2?", orden=1, tipo="opcion_multiple")
    db.session.add(p1)
    db.session.flush()
    db.session.add_all([
        Alternativa(pregunta_id=p1.id, texto="4", es_correcta=True, orden=1),
        Alternativa(pregunta_id=p1.id, texto="5", es_correcta=False, orden=2),
    ])

    p2 = Pregunta(evaluacion_id=ev.id, enunciado="El cielo es verde.", orden=2, tipo="verdadero_falso")
    db.session.add(p2)
    db.session.flush()
    db.session.add_all([
        Alternativa(pregunta_id=p2.id, texto="Verdadero", es_correcta=False, orden=1),
        Alternativa(pregunta_id=p2.id, texto="Falso", es_correcta=True, orden=2),
    ])
    db.session.commit()
    return ev


def _json_valido(titulo="Importada", umbral=60):
    return {
        "formato": "fuenti.evaluacion",
        "version": 1,
        "titulo": titulo,
        "umbral_aprobacion": umbral,
        "preguntas": [
            {
                "enunciado": "¿Capital de Chile?",
                "tipo": "opcion_multiple",
                "alternativas": [
                    {"texto": "Santiago", "es_correcta": True},
                    {"texto": "Lima", "es_correcta": False},
                ],
            },
            {
                "enunciado": "El agua hierve a 100°C a nivel del mar.",
                "tipo": "verdadero_falso",
                "alternativas": [
                    {"texto": "Verdadero", "es_correcta": True},
                    {"texto": "Falso", "es_correcta": False},
                ],
            },
        ],
    }


def _subir(client, data, filename="eval.json"):
    """POST del archivo a /importar. `data` es un dict (se serializa a JSON) o
    un str/bytes crudo (para probar JSON malformado)."""
    if isinstance(data, dict):
        contenido = json.dumps(data).encode("utf-8")
    elif isinstance(data, str):
        contenido = data.encode("utf-8")
    else:
        contenido = data
    return client.post(
        "/evaluaciones/importar",
        data={"archivo": (io.BytesIO(contenido), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


# -------------------- Acceso --------------------

def test_exportar_sin_auth_redirige_a_login(client, facilitador):
    ev = _crear_evaluacion(facilitador.id)
    resp = client.get(f"/evaluaciones/{ev.id}/exportar.json", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_importar_sin_auth_redirige_a_login(client):
    resp = client.get("/evaluaciones/importar", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_exportar_evaluacion_ajena_es_403(client, app, facilitador):
    _login(client)
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        otro.set_password("otro12345")
        db.session.add(otro)
        db.session.commit()
        ev_ajena = _crear_evaluacion(otro.id, titulo="Ajena")
        eid = ev_ajena.id
    resp = client.get(f"/evaluaciones/{eid}/exportar.json")
    assert resp.status_code == 403


# -------------------- Exportar --------------------

def test_exportar_estructura_json(client, app, facilitador):
    _login(client)
    with app.app_context():
        ev = _crear_evaluacion(facilitador.id, titulo="Mi Eval", umbral=70)
        eid = ev.id
    resp = client.get(f"/evaluaciones/{eid}/exportar.json")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert "attachment" in resp.headers.get("Content-Disposition", "")

    data = json.loads(resp.get_data(as_text=True))
    assert data["formato"] == "fuenti.evaluacion"
    assert data["titulo"] == "Mi Eval"
    assert data["umbral_aprobacion"] == 70
    assert len(data["preguntas"]) == 2
    p1 = data["preguntas"][0]
    assert p1["tipo"] == "opcion_multiple"
    correctas = [a for a in p1["alternativas"] if a["es_correcta"]]
    assert len(correctas) == 1 and correctas[0]["texto"] == "4"


# -------------------- Importar (camino feliz) --------------------

def test_importar_crea_evaluacion_a_mi_nombre(client, app, facilitador):
    _login(client)
    resp = _subir(client, _json_valido(titulo="Nueva importada"))
    assert resp.status_code == 200

    with app.app_context():
        evs = Evaluacion.query.filter_by(titulo="Nueva importada").all()
        assert len(evs) == 1
        ev = evs[0]
        assert ev.facilitador_id == facilitador.id
        assert ev.umbral_aprobacion == 60
        assert len(ev.preguntas) == 2
        vf = next(p for p in ev.preguntas if p.tipo == "verdadero_falso")
        textos = sorted(a.texto for a in vf.alternativas)
        assert textos == ["Falso", "Verdadero"]


def test_importar_ignora_dueno_del_archivo(client, app, facilitador):
    """Aunque el archivo traiga un facilitador_id, la evaluación queda a nombre
    del usuario autenticado."""
    _login(client)
    data = _json_valido(titulo="Con dueño falso")
    data["facilitador_id"] = 9999  # debe ignorarse
    resp = _subir(client, data)
    assert resp.status_code == 200
    with app.app_context():
        ev = Evaluacion.query.filter_by(titulo="Con dueño falso").first()
        assert ev is not None
        assert ev.facilitador_id == facilitador.id


def test_ida_y_vuelta_exportar_importar(client, app, facilitador):
    """Exportar una evaluación y volver a importar ese mismo archivo produce una
    segunda evaluación con el mismo contenido."""
    _login(client)
    with app.app_context():
        ev = _crear_evaluacion(facilitador.id, titulo="Round Trip")
        eid = ev.id
    exportado = client.get(f"/evaluaciones/{eid}/exportar.json").get_data()

    resp = _subir(client, exportado)
    assert resp.status_code == 200
    with app.app_context():
        evs = Evaluacion.query.filter_by(titulo="Round Trip").all()
        assert len(evs) == 2  # la original + la importada
        for e in evs:
            assert len(e.preguntas) == 2


def test_importar_duplicado_no_reemplaza(client, app, facilitador):
    _login(client)
    _subir(client, _json_valido(titulo="Igual"))
    _subir(client, _json_valido(titulo="Igual"))
    with app.app_context():
        assert Evaluacion.query.filter_by(titulo="Igual").count() == 2


# -------------------- Importar (validación) --------------------

def test_importar_sin_archivo_falla(client, facilitador):
    _login(client)
    resp = client.post(
        "/evaluaciones/importar",
        data={},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "elegir un archivo".encode("utf-8") in resp.data


def test_importar_json_malformado_falla(client, app, facilitador):
    _login(client)
    resp = _subir(client, "{esto no es json valido")
    assert b"no es un JSON" in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_raiz_no_objeto_falla(client, app, facilitador):
    _login(client)
    resp = _subir(client, "[1, 2, 3]")
    assert "objeto JSON".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_umbral_no_entero_falla(client, app, facilitador):
    _login(client)
    data = _json_valido()
    data["umbral_aprobacion"] = "sesenta"
    resp = _subir(client, data)
    assert b"umbral_aprobacion" in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_dos_correctas_falla(client, app, facilitador):
    _login(client)
    data = _json_valido()
    data["preguntas"][0]["alternativas"][1]["es_correcta"] = True  # 2 correctas
    resp = _subir(client, data)
    assert "exactamente una".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_sin_correcta_falla(client, app, facilitador):
    _login(client)
    data = _json_valido()
    for a in data["preguntas"][0]["alternativas"]:
        a["es_correcta"] = False
    resp = _subir(client, data)
    assert "es_correcta=true".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_opcion_multiple_una_alternativa_falla(client, app, facilitador):
    _login(client)
    data = _json_valido()
    data["preguntas"][0]["alternativas"] = [
        {"texto": "Única", "es_correcta": True}
    ]
    resp = _subir(client, data)
    assert "al menos 2 alternativas".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_sin_preguntas_falla(client, app, facilitador):
    _login(client)
    data = _json_valido()
    data["preguntas"] = []
    resp = _subir(client, data)
    assert "al menos una pregunta".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


# -------------------- Biblioteca (botones) --------------------

def test_biblioteca_muestra_botones_importar_exportar(client, app, facilitador):
    _login(client)
    with app.app_context():
        _crear_evaluacion(facilitador.id, titulo="Para exportar")
    resp = client.get("/evaluaciones/")
    assert resp.status_code == 200
    assert b"Importar" in resp.data
    assert b"Exportar" in resp.data
