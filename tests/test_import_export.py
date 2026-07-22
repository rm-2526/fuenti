"""Tests de importación y exportación de evaluaciones en formato JSON.

En la importación, el título y el umbral los ingresa el facilitador en el
formulario; el JSON de las preguntas se pega en un cuadro de texto. La
validación reutiliza las mismas reglas que la creación manual (_validar e
_insertar_preguntas).
"""

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
    """Crea en la base una evaluación con una opción múltiple y una V/F,
    para tener algo que exportar."""
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


def _preguntas():
    """Dos preguntas válidas: una opción múltiple y una V/F."""
    return [
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
    ]


def _cuerpo(preguntas=None):
    return {"preguntas": _preguntas() if preguntas is None else preguntas}


def _subir(client, data, titulo="Importada", umbral="60"):
    """POST del formulario de importación, pegando el JSON en el campo de texto.
    `data` puede ser un dict (se serializa), un str o bytes (para probar
    contenidos malformados o un archivo exportado)."""
    if isinstance(data, dict):
        json_texto = json.dumps(data)
    elif isinstance(data, bytes):
        json_texto = data.decode("utf-8")
    else:
        json_texto = data
    return client.post(
        "/evaluaciones/importar",
        data={"titulo": titulo, "umbral": umbral, "json": json_texto,
              "accion": "importar"},
        follow_redirects=True,
    )


def _previsualizar(client, data, titulo="Prev", umbral="60"):
    """POST con la acción de vista previa (no debe crear nada)."""
    if isinstance(data, dict):
        json_texto = json.dumps(data)
    elif isinstance(data, bytes):
        json_texto = data.decode("utf-8")
    else:
        json_texto = data
    return client.post(
        "/evaluaciones/importar",
        data={"titulo": titulo, "umbral": umbral, "json": json_texto,
              "accion": "previsualizar"},
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
    correctas = [a for a in p1["alternativas"] if a["es_correcta"]]
    assert len(correctas) == 1 and correctas[0]["texto"] == "4"


# -------------------- Importar (camino feliz) --------------------

def test_importar_usa_titulo_y_umbral_del_formulario(client, app, facilitador):
    _login(client)
    resp = _subir(client, _cuerpo(), titulo="Desde el form", umbral="75")
    assert resp.status_code == 200
    with app.app_context():
        ev = Evaluacion.query.filter_by(titulo="Desde el form").first()
        assert ev is not None
        assert ev.facilitador_id == facilitador.id
        assert ev.umbral_aprobacion == 75
        assert len(ev.preguntas) == 2
        vf = next(p for p in ev.preguntas if p.tipo == "verdadero_falso")
        assert sorted(a.texto for a in vf.alternativas) == ["Falso", "Verdadero"]


def test_importar_ignora_titulo_y_umbral_del_cuerpo(client, app, facilitador):
    """Aunque el archivo traiga título/umbral (p. ej. uno exportado), mandan los
    del formulario."""
    _login(client)
    data = _cuerpo()
    data["titulo"] = "IGNORAR"
    data["umbral_aprobacion"] = 5
    data["facilitador_id"] = 9999
    resp = _subir(client, data, titulo="El que vale", umbral="80")
    assert resp.status_code == 200
    with app.app_context():
        assert Evaluacion.query.filter_by(titulo="IGNORAR").first() is None
        ev = Evaluacion.query.filter_by(titulo="El que vale").first()
        assert ev is not None
        assert ev.umbral_aprobacion == 80
        assert ev.facilitador_id == facilitador.id


def test_ida_y_vuelta_exportar_importar(client, app, facilitador):
    """Un archivo exportado (que trae título/umbral extra) se importa sin
    problema; el título de la nueva sale del formulario."""
    _login(client)
    with app.app_context():
        ev = _crear_evaluacion(facilitador.id, titulo="Original")
        eid = ev.id
    exportado = client.get(f"/evaluaciones/{eid}/exportar.json").get_data()

    resp = _subir(client, exportado, titulo="Copia importada", umbral="60")
    assert resp.status_code == 200
    with app.app_context():
        assert Evaluacion.query.filter_by(titulo="Original").count() == 1
        copia = Evaluacion.query.filter_by(titulo="Copia importada").first()
        assert copia is not None
        assert len(copia.preguntas) == 2


def test_importar_duplicado_no_reemplaza(client, app, facilitador):
    _login(client)
    _subir(client, _cuerpo(), titulo="Igual")
    _subir(client, _cuerpo(), titulo="Igual")
    with app.app_context():
        assert Evaluacion.query.filter_by(titulo="Igual").count() == 2


# -------------------- Importar (validación) --------------------

def test_importar_sin_json_falla(client, facilitador):
    _login(client)
    resp = client.post(
        "/evaluaciones/importar",
        data={"titulo": "X", "umbral": "60", "json": "   "},
        follow_redirects=True,
    )
    assert "pegar el JSON".encode("utf-8") in resp.data


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


def test_importar_sin_lista_preguntas_falla(client, app, facilitador):
    _login(client)
    resp = _subir(client, {"otra_cosa": 1})
    assert "lista llamada".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_sin_titulo_falla(client, app, facilitador):
    _login(client)
    resp = _subir(client, _cuerpo(), titulo="")
    assert "título es obligatorio".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_umbral_no_entero_falla(client, app, facilitador):
    _login(client)
    resp = _subir(client, _cuerpo(), umbral="sesenta")
    assert "umbral debe ser un número entero".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_umbral_fuera_de_rango_falla(client, app, facilitador):
    _login(client)
    resp = _subir(client, _cuerpo(), umbral="150")
    assert "umbral debe estar entre 0 y 100".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_error_conserva_titulo_y_texto(client, facilitador):
    """Si algo falla, el título tecleado y el JSON pegado se re-muestran."""
    _login(client)
    resp = _subir(client, "json roto pero identificable", titulo="No lo pierdas")
    cuerpo = resp.get_data(as_text=True)
    assert 'value="No lo pierdas"' in cuerpo
    assert "json roto pero identificable" in cuerpo


def test_importar_dos_correctas_falla(client, app, facilitador):
    _login(client)
    data = _cuerpo()
    data["preguntas"][0]["alternativas"][1]["es_correcta"] = True
    resp = _subir(client, data)
    assert "exactamente una".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_sin_correcta_falla(client, app, facilitador):
    _login(client)
    data = _cuerpo()
    for a in data["preguntas"][0]["alternativas"]:
        a["es_correcta"] = False
    resp = _subir(client, data)
    assert "es_correcta=true".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_opcion_multiple_una_alternativa_falla(client, app, facilitador):
    _login(client)
    data = _cuerpo()
    data["preguntas"][0]["alternativas"] = [{"texto": "Única", "es_correcta": True}]
    resp = _subir(client, data)
    assert "al menos 2 alternativas".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_importar_preguntas_vacias_falla(client, app, facilitador):
    _login(client)
    resp = _subir(client, {"preguntas": []})
    assert "al menos una pregunta".encode("utf-8") in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


# -------------------- Vista previa --------------------

def test_vista_previa_valida_muestra_y_no_crea(client, app, facilitador):
    _login(client)
    resp = _previsualizar(client, _cuerpo())
    cuerpo = resp.get_data(as_text=True)
    assert "Vista previa" in cuerpo
    assert "¿Capital de Chile?" in cuerpo
    assert "Santiago" in cuerpo
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_vista_previa_marca_la_correcta(client, facilitador):
    _login(client)
    cuerpo = _previsualizar(client, _cuerpo()).get_data(as_text=True)
    assert "✔" in cuerpo  # la correcta se muestra marcada


def test_vista_previa_normaliza_vf(client, facilitador):
    """La V/F se muestra como Verdadero/Falso aunque el JSON traiga otros textos."""
    _login(client)
    data = {"preguntas": [{
        "enunciado": "¿Cierto?",
        "tipo": "verdadero_falso",
        "alternativas": [
            {"texto": "sí", "es_correcta": True},
            {"texto": "no", "es_correcta": False},
        ],
    }]}
    cuerpo = _previsualizar(client, data).get_data(as_text=True)
    assert "Verdadero" in cuerpo and "Falso" in cuerpo


def test_vista_previa_invalida_no_crea(client, app, facilitador):
    _login(client)
    resp = _previsualizar(client, "{ json roto")
    assert b"no es un JSON" in resp.data
    with app.app_context():
        assert Evaluacion.query.count() == 0


def test_vista_previa_error_de_validacion_no_crea(client, app, facilitador):
    _login(client)
    resp = _previsualizar(client, _cuerpo(), titulo="")
    assert "título es obligatorio".encode("utf-8") in resp.data
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
