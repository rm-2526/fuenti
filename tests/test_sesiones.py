"""Tests del flujo de sesiones: facilitador abre/cierra, participante ingresa.

Cubre:
- Facilitador puede abrir y cerrar sesiones de sus evaluaciones.
- Aislamiento: facilitador no puede tocar sesiones de evaluaciones ajenas.
- Participante ingresa con RUT valido, se crea Participante con hash.
- Defensas: sesion cerrada rechaza, codigo inexistente 404, RUT invalido rechaza.
- Reingreso: mismo RUT en misma sesion no duplica Participante.
"""

from app import db
from app.models import Evaluacion, Facilitador, Participante, Pregunta, Alternativa, Sesion
from app.utils.rut import hash_rut


RUT_VALIDO = "11.111.111-1"
RUT_VALIDO_NORMALIZADO = "111111111"
RUT_INVALIDO = "11.111.111-2"  # DV incorrecto


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _crear_evaluacion_con_pregunta(app, facilitador_id, titulo="Eval test"):
    """Crea una evaluacion con 1 pregunta y 2 alternativas. Devuelve el id."""
    with app.app_context():
        e = Evaluacion(facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=60)
        db.session.add(e)
        db.session.flush()
        p = Pregunta(evaluacion_id=e.id, enunciado="¿2+2?", orden=1)
        db.session.add(p)
        db.session.flush()
        db.session.add(Alternativa(pregunta_id=p.id, texto="4", es_correcta=True, orden=1))
        db.session.add(Alternativa(pregunta_id=p.id, texto="5", es_correcta=False, orden=2))
        db.session.commit()
        return e.id


def _crear_sesion_directa(app, evaluacion_id, codigo="TESTCD", estado="abierta"):
    """Crea una Sesion en BD sin pasar por el endpoint. Devuelve el id."""
    with app.app_context():
        s = Sesion(evaluacion_id=evaluacion_id, codigo=codigo, estado=estado)
        db.session.add(s)
        db.session.commit()
        return s.id


# ====================== Facilitador: abrir sesion ======================

def test_facilitador_abre_sesion_de_evaluacion_propia(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _login(client)

    resp = client.post(f"/evaluaciones/{eval_id}/sesiones/abrir", follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        sesiones = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).all()
        assert len(sesiones) == 1
        s = sesiones[0]
        assert s.estado == "abierta"
        assert s.cerrada_at is None
        assert len(s.codigo) == 6
        # Redirige al detalle de esa sesion
        assert resp.headers["Location"].endswith(f"/sesiones/{s.id}")


def test_facilitador_no_puede_abrir_sesion_de_eval_sin_preguntas(client, facilitador, app):
    """Validacion de negocio: una evaluacion sin preguntas no puede recibir
    participantes, asi que abrir sesion debe rechazarse."""
    with app.app_context():
        e = Evaluacion(facilitador_id=facilitador.id, titulo="Sin preguntas", umbral_aprobacion=60)
        db.session.add(e)
        db.session.commit()
        eval_id = e.id

    _login(client)
    resp = client.post(
        f"/evaluaciones/{eval_id}/sesiones/abrir", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "no tiene preguntas".encode("utf-8") in resp.data

    with app.app_context():
        assert db.session.query(Sesion).count() == 0


def test_facilitador_no_puede_abrir_sesion_de_eval_ajena(client, facilitador, app):
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        otro.set_password("clave123")
        db.session.add(otro)
        db.session.flush()
        eval_id = _crear_evaluacion_con_pregunta(app, otro.id, titulo="Ajena")

    _login(client)
    resp = client.post(f"/evaluaciones/{eval_id}/sesiones/abrir")
    assert resp.status_code == 403

    with app.app_context():
        assert db.session.query(Sesion).count() == 0


# ====================== Facilitador: cerrar sesion ======================

def test_facilitador_cierra_sesion_propia(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    sesion_id = _crear_sesion_directa(app, eval_id, codigo="ABC234")

    _login(client)
    resp = client.post(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar", follow_redirects=False
    )
    assert resp.status_code == 302

    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        assert s.estado == "cerrada"
        assert s.cerrada_at is not None


def test_cerrar_sesion_ya_cerrada_es_idempotente(client, facilitador, app):
    """Doble click en cerrar no debe fallar: solo informa que ya estaba cerrada."""
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    sesion_id = _crear_sesion_directa(app, eval_id, codigo="XYZ234", estado="cerrada")

    _login(client)
    resp = client.post(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "ya estaba cerrada".encode("utf-8") in resp.data


def test_facilitador_no_puede_cerrar_sesion_ajena(client, facilitador, app):
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        otro.set_password("clave123")
        db.session.add(otro)
        db.session.flush()
        eval_id_ajena = _crear_evaluacion_con_pregunta(app, otro.id, titulo="Ajena")
        sesion_id_ajena = _crear_sesion_directa(app, eval_id_ajena, codigo="AJN234")

    _login(client)
    resp = client.post(
        f"/evaluaciones/{eval_id_ajena}/sesiones/{sesion_id_ajena}/cerrar"
    )
    assert resp.status_code == 403

    with app.app_context():
        s = db.session.get(Sesion, sesion_id_ajena)
        assert s.estado == "abierta"  # no cambio


# ====================== Facilitador: ver sesion ======================

def test_facilitador_ve_detalle_de_sesion_propia(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    sesion_id = _crear_sesion_directa(app, eval_id, codigo="VIS234")

    _login(client)
    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}")
    assert resp.status_code == 200
    assert b"VIS234" in resp.data


def test_sesion_de_otra_evaluacion_es_404(client, facilitador, app):
    """Si el sesion_id existe pero pertenece a otra evaluacion del MISMO
    facilitador, igual debe ser 404 (URL incorrecta)."""
    eval_a = _crear_evaluacion_con_pregunta(app, facilitador.id, titulo="A")
    eval_b = _crear_evaluacion_con_pregunta(app, facilitador.id, titulo="B")
    sesion_de_b = _crear_sesion_directa(app, eval_b, codigo="BSS234")

    _login(client)
    # Pido la sesion de B pero como si fuera de A
    resp = client.get(f"/evaluaciones/{eval_a}/sesiones/{sesion_de_b}")
    assert resp.status_code == 404


# ====================== Participante: ingreso ======================

def test_get_ingreso_de_sesion_abierta_renderiza_form(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id, titulo="Mi Eval")
    _crear_sesion_directa(app, eval_id, codigo="ABRT34")

    resp = client.get("/sesion/ABRT34/ingreso")
    assert resp.status_code == 200
    assert b"Mi Eval" in resp.data
    assert b"ABRT34" in resp.data


def test_post_ingreso_con_rut_valido_crea_participante(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    sesion_id = _crear_sesion_directa(app, eval_id, codigo="ING234")

    resp = client.post(
        "/sesion/ING234/ingreso", data={"rut": RUT_VALIDO}, follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/ING234/responder")

    with app.app_context():
        participantes = db.session.query(Participante).filter_by(sesion_id=sesion_id).all()
        assert len(participantes) == 1
        # El hash es del RUT normalizado + salt de config
        from flask import current_app
        salt = app.config["RUT_SALT"]
        assert participantes[0].identificador_hash == hash_rut(RUT_VALIDO, salt)


def test_post_ingreso_con_rut_invalido_no_crea_participante(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _crear_sesion_directa(app, eval_id, codigo="INV234")

    resp = client.post("/sesion/INV234/ingreso", data={"rut": RUT_INVALIDO})
    assert resp.status_code == 200
    assert "inv\u00e1lido".encode("utf-8") in resp.data.lower() or b"invalido" in resp.data.lower()

    with app.app_context():
        assert db.session.query(Participante).count() == 0


def test_post_ingreso_con_rut_vacio_no_crea_participante(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _crear_sesion_directa(app, eval_id, codigo="VAC234")

    resp = client.post("/sesion/VAC234/ingreso", data={"rut": ""})
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.query(Participante).count() == 0


# ====================== Participante: reingreso ======================

def test_reingreso_mismo_rut_no_duplica_participante(client, facilitador, app):
    """Caso: se cierra el navegador y vuelve a entrar. Mismo hash en misma
    sesion → reutilizamos el Participante existente."""
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    sesion_id = _crear_sesion_directa(app, eval_id, codigo="REI234")

    # Primer ingreso
    client.post("/sesion/REI234/ingreso", data={"rut": RUT_VALIDO})
    # Borrar la cookie de sesion del cliente (simula nueva visita)
    with client.session_transaction() as sess:
        sess.clear()
    # Segundo ingreso con el mismo RUT
    client.post("/sesion/REI234/ingreso", data={"rut": RUT_VALIDO})

    with app.app_context():
        participantes = db.session.query(Participante).filter_by(sesion_id=sesion_id).all()
        assert len(participantes) == 1


# ====================== Defensas: sesion cerrada / codigo inexistente ======================

def test_get_ingreso_de_sesion_cerrada_muestra_aviso(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _crear_sesion_directa(app, eval_id, codigo="CER234", estado="cerrada")

    resp = client.get("/sesion/CER234/ingreso")
    assert resp.status_code == 200
    assert "cerrada".encode("utf-8") in resp.data.lower()
    # El form de RUT no debe estar presente
    assert b'name="rut"' not in resp.data


def test_post_ingreso_a_sesion_cerrada_no_crea_participante(client, facilitador, app):
    """Defensa: aunque alguien arme el POST a mano contra una sesion cerrada,
    no se crea Participante. Esto cierra el componente 'sesiones cerradas
    no aceptan respuestas' de OE4."""
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _crear_sesion_directa(app, eval_id, codigo="CRP234", estado="cerrada")

    resp = client.post("/sesion/CRP234/ingreso", data={"rut": RUT_VALIDO})
    assert resp.status_code == 200
    assert "cerrada".encode("utf-8") in resp.data.lower()

    with app.app_context():
        assert db.session.query(Participante).count() == 0


def test_ingreso_con_codigo_inexistente_es_404(client):
    resp = client.get("/sesion/NOEXIS/ingreso")
    assert resp.status_code == 404


def test_post_ingreso_con_codigo_inexistente_es_404(client):
    resp = client.post("/sesion/NOEXIS/ingreso", data={"rut": RUT_VALIDO})
    assert resp.status_code == 404


# ====================== Responder (placeholder) ======================

def test_responder_sin_ingreso_previo_redirige_a_ingreso(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _crear_sesion_directa(app, eval_id, codigo="RSP234")

    resp = client.get("/sesion/RSP234/responder", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/RSP234/ingreso")


def test_responder_con_ingreso_valido_muestra_cuestionario(client, facilitador, app):
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _crear_sesion_directa(app, eval_id, codigo="RPV234")

    client.post("/sesion/RPV234/ingreso", data={"rut": RUT_VALIDO})
    resp = client.get("/sesion/RPV234/responder")
    assert resp.status_code == 200
    # El form real renderiza el enunciado de la pregunta y radios por pregunta.
    assert "\u00bf2+2?".encode("utf-8") in resp.data
    assert b'type="radio"' in resp.data


def test_cookie_cruzada_entre_sesiones_redirige_a_ingreso(client, facilitador, app):
    """Defensa: si el participante ingreso a sesion A y despues abre el link
    de sesion B, la cookie con participante_id de A NO debe darle acceso a B.
    Lo redirigimos al ingreso de B."""
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    _crear_sesion_directa(app, eval_id, codigo="SESA34")
    _crear_sesion_directa(app, eval_id, codigo="SESB34")

    # Ingreso a sesion A
    client.post("/sesion/SESA34/ingreso", data={"rut": RUT_VALIDO})

    # Intento entrar a responder de sesion B con la cookie de A
    resp = client.get("/sesion/SESB34/responder", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/SESB34/ingreso")


def test_responder_de_sesion_cerrada_muestra_aviso(client, facilitador, app):
    """Si la sesion se cierra despues del ingreso, el responder tambien debe
    bloquear (defensa en profundidad)."""
    eval_id = _crear_evaluacion_con_pregunta(app, facilitador.id)
    sesion_id = _crear_sesion_directa(app, eval_id, codigo="CRD234")

    # Ingreso mientras estaba abierta
    client.post("/sesion/CRD234/ingreso", data={"rut": RUT_VALIDO})

    # El facilitador cierra la sesion
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        s.estado = "cerrada"
        db.session.commit()

    # El participante intenta acceder a responder
    resp = client.get("/sesion/CRD234/responder")
    assert resp.status_code == 200
    assert "cerrada".encode("utf-8") in resp.data.lower()