"""Tests del CRUD de evaluaciones (OE1)."""

from app import db
from app.models import (
    Alternativa,
    Evaluacion,
    Facilitador,
    Participante,
    Pregunta,
    Respuesta,
    Sesion,
)


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

# ==================== Editar evaluación ====================

def _crear_eval_directa(app, facilitador_id, titulo="Editable", umbral=60):
    """Crea directamente en BD una evaluacion con 1 pregunta ('¿2+2?') y 2
    alternativas ('4' correcta, '5' incorrecta). Devuelve el id.
    """
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=umbral
        )
        db.session.add(e)
        db.session.flush()
        p = Pregunta(evaluacion_id=e.id, enunciado="¿2+2?", orden=1)
        db.session.add(p)
        db.session.flush()
        db.session.add(Alternativa(pregunta_id=p.id, texto="4", es_correcta=True, orden=1))
        db.session.add(Alternativa(pregunta_id=p.id, texto="5", es_correcta=False, orden=2))
        db.session.commit()
        return e.id


def test_editar_sin_auth_redirige_a_login(client, facilitador, app):
    eval_id = _crear_eval_directa(app, facilitador.id)
    resp = client.get(f"/evaluaciones/{eval_id}/editar", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_get_editar_precarga_los_datos(client, facilitador, app):
    eval_id = _crear_eval_directa(app, facilitador.id, titulo="Mi Eval")
    _login(client)
    resp = client.get(f"/evaluaciones/{eval_id}/editar")
    assert resp.status_code == 200
    assert "Editar evaluación".encode("utf-8") in resp.data
    assert "Mi Eval".encode("utf-8") in resp.data       # titulo pre-cargado
    assert "¿2+2?".encode("utf-8") in resp.data          # enunciado pre-cargado
    assert b'value="4"' in resp.data                     # alternativa pre-cargada


def test_editar_cambia_titulo_umbral_y_preguntas(client, facilitador, app):
    eval_id = _crear_eval_directa(app, facilitador.id, titulo="Viejo")
    _login(client)
    data = {
        "titulo": "Nuevo",
        "umbral": "80",
        "pregunta_0_enunciado": "¿Capital de Chile?",
        "pregunta_0_correcta": "1",
        "pregunta_0_alternativa_0_texto": "Lima",
        "pregunta_0_alternativa_1_texto": "Santiago",
        # segunda pregunta agregada
        "pregunta_1_enunciado": "¿2x3?",
        "pregunta_1_correcta": "0",
        "pregunta_1_alternativa_0_texto": "6",
        "pregunta_1_alternativa_1_texto": "5",
    }
    resp = client.post(f"/evaluaciones/{eval_id}/editar", data=data, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        ev = db.session.get(Evaluacion, eval_id)
        assert ev.titulo == "Nuevo"
        assert ev.umbral_aprobacion == 80
        enunciados = sorted(p.enunciado for p in ev.preguntas)
        assert "¿Capital de Chile?" in enunciados
        assert "¿2x3?" in enunciados
        assert "¿2+2?" not in enunciados      # el viejo se reemplazo
        # la correcta de la 1a pregunta quedo en "Santiago"
        p_cap = next(p for p in ev.preguntas if "Capital" in p.enunciado)
        correcta = next(a for a in p_cap.alternativas if a.es_correcta)
        assert correcta.texto == "Santiago"


def test_editar_invalido_no_cambia_nada(client, facilitador, app):
    eval_id = _crear_eval_directa(app, facilitador.id, titulo="Intacto")
    _login(client)
    data = {
        "titulo": "",   # invalido: titulo vacio
        "umbral": "60",
        "pregunta_0_enunciado": "x",
        "pregunta_0_correcta": "0",
        "pregunta_0_alternativa_0_texto": "a",
        "pregunta_0_alternativa_1_texto": "b",
    }
    resp = client.post(f"/evaluaciones/{eval_id}/editar", data=data)
    assert resp.status_code == 200
    assert "título es obligatorio".encode("utf-8") in resp.data
    with app.app_context():
        assert db.session.get(Evaluacion, eval_id).titulo == "Intacto"


def test_no_editar_evaluacion_ajena(client, facilitador, app):
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        otro.set_password("clave123")
        db.session.add(otro)
        db.session.commit()
        otro_id = otro.id
    eval_ajena = _crear_eval_directa(app, otro_id, titulo="Ajena")

    _login(client)   # entra como el facilitador principal
    resp = client.get(f"/evaluaciones/{eval_ajena}/editar")
    assert resp.status_code == 403


def test_no_editar_con_sesion_abierta(client, facilitador, app):
    eval_id = _crear_eval_directa(app, facilitador.id, titulo="Bloqueada")
    with app.app_context():
        db.session.add(Sesion(evaluacion_id=eval_id, codigo="OPEN99", estado="abierta"))
        db.session.commit()

    _login(client)
    resp = client.post(
        f"/evaluaciones/{eval_id}/editar",
        data={
            "titulo": "Cambiado",
            "umbral": "60",
            "pregunta_0_enunciado": "x",
            "pregunta_0_correcta": "0",
            "pregunta_0_alternativa_0_texto": "a",
            "pregunta_0_alternativa_1_texto": "b",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "sesión abierta".encode("utf-8") in resp.data
    with app.app_context():
        # No cambio: sigue con el titulo original.
        assert db.session.get(Evaluacion, eval_id).titulo == "Bloqueada"


def test_editar_evaluacion_ya_respondida_suelta_enlace_y_conserva_foto(
    client, facilitador, app
):
    """Editar una evaluacion ya rendida: la respuesta vieja SUELTA el enlace a
    la pregunta/alternativa borradas (quedan en NULL) pero CONSERVA su foto
    congelada. Y las preguntas nuevas quedan activas.
    """
    eval_id = _crear_eval_directa(app, facilitador.id, titulo="Suma")
    with app.app_context():
        s = Sesion(evaluacion_id=eval_id, codigo="EDT999", estado="abierta")
        db.session.add(s)
        db.session.commit()
        sesion_id = s.id
        p = db.session.query(Pregunta).filter_by(evaluacion_id=eval_id).first()
        pid = p.id
        alt5 = next(a.id for a in p.alternativas if a.texto == "5")

    # El participante responde (elige "5", la incorrecta).
    client.post("/sesion/EDT999/ingreso", data={"rut": "11.111.111-1", "nombre": "Ana"})
    client.post("/sesion/EDT999/responder", data={f"pregunta_{pid}": alt5})

    # Se cierra la sesion para poder editar.
    with app.app_context():
        db.session.get(Sesion, sesion_id).estado = "cerrada"
        db.session.commit()

    # Se edita: enunciado y alternativas totalmente distintos.
    _login(client)
    resp = client.post(
        f"/evaluaciones/{eval_id}/editar",
        data={
            "titulo": "Suma editada",
            "umbral": "70",
            "pregunta_0_enunciado": "¿10+10?",
            "pregunta_0_correcta": "0",
            "pregunta_0_alternativa_0_texto": "20",
            "pregunta_0_alternativa_1_texto": "30",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        ev = db.session.get(Evaluacion, eval_id)
        assert ev.titulo == "Suma editada"
        assert ev.umbral_aprobacion == 70
        # Nueva pregunta activa.
        assert len(ev.preguntas) == 1
        assert ev.preguntas[0].enunciado == "¿10+10?"

        # La respuesta vieja: solto el enlace pero conserva su foto congelada.
        r = db.session.query(Respuesta).first()
        assert r is not None
        assert r.pregunta_id is None
        assert r.alternativa_id is None
        assert r.enunciado_texto == "¿2+2?"
        assert r.elegida_texto == "5"
        assert r.correcta_texto == "4"


# ==================== Iniciar evaluación (lanzamiento) ====================

def _crear_eval_vacia(app, facilitador_id, titulo="Vacia"):
    """Crea una evaluacion SIN preguntas. Devuelve el id."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.commit()
        return e.id


def test_iniciar_sin_auth_redirige_a_login(client):
    resp = client.get("/evaluaciones/iniciar", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_iniciar_con_preguntas_muestra_boton_activo(client, facilitador, app):
    _crear_eval_directa(app, facilitador.id, titulo="Lista para lanzar")
    _login(client)
    resp = client.get("/evaluaciones/iniciar")
    assert resp.status_code == 200
    assert "Lista para lanzar".encode("utf-8") in resp.data
    assert "Abrir sesión".encode("utf-8") in resp.data
    assert b"disabled" not in resp.data


def test_iniciar_sin_preguntas_boton_deshabilitado(client, facilitador, app):
    _crear_eval_vacia(app, facilitador.id, titulo="Sin preguntas")
    _login(client)
    resp = client.get("/evaluaciones/iniciar")
    assert resp.status_code == 200
    assert "Sin preguntas".encode("utf-8") in resp.data
    assert b"disabled" in resp.data
    assert "Agrega preguntas primero".encode("utf-8") in resp.data


def test_iniciar_solo_muestra_propias(client, facilitador, app):
    with app.app_context():
        otro = Facilitador(email="otro2@fuenti.cl", nombre="Otro2")
        otro.set_password("clave123")
        db.session.add(otro)
        db.session.commit()
        otro_id = otro.id
    _crear_eval_directa(app, otro_id, titulo="De otro")
    _crear_eval_directa(app, facilitador.id, titulo="Mia propia")

    _login(client)
    resp = client.get("/evaluaciones/iniciar")
    assert "Mia propia".encode("utf-8") in resp.data
    assert "De otro".encode("utf-8") not in resp.data


def test_abrir_sesion_desde_iniciar_crea_sesion(client, facilitador, app):
    eval_id = _crear_eval_directa(app, facilitador.id, titulo="Para lanzar")
    _login(client)
    resp = client.post(
        f"/evaluaciones/{eval_id}/sesiones/abrir", follow_redirects=False
    )
    assert resp.status_code in (302, 303)   # redirige a la sesion recien creada
    with app.app_context():
        s = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).first()
        assert s is not None
        assert s.estado == "abierta"
