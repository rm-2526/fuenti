"""Tests del umbral fijado al abrir la sesion, y del volver segun estado.

Regla de negocio: el umbral se fija AL ABRIR la sesion (por defecto el de la
evaluacion, editable en ese momento) y NO se edita despues. La calificacion lo
lee de la sesion, no de la evaluacion, asi que editar la evaluacion mas tarde
no altera lo que ya se midio.
"""

from app import db
from app.models import (
    Alternativa,
    Evaluacion,
    Participante,
    Pregunta,
    Resultado,
    Sesion,
)


RUT_VALIDO = "15.432.198-5"


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _crear_eval(app, facilitador_id, titulo="Eval umbral", umbral=60):
    """Evaluacion con 1 pregunta y 2 alternativas (la correcta es '4')."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=umbral
        )
        db.session.add(e)
        db.session.flush()
        p = Pregunta(evaluacion_id=e.id, enunciado="¿2+2?", orden=1)
        db.session.add(p)
        db.session.flush()
        db.session.add(
            Alternativa(pregunta_id=p.id, texto="4", es_correcta=True, orden=1)
        )
        db.session.add(
            Alternativa(pregunta_id=p.id, texto="5", es_correcta=False, orden=2)
        )
        db.session.commit()
        return e.id


def _abrir(client, eval_id, data=None):
    return client.post(
        f"/evaluaciones/{eval_id}/sesiones/abrir",
        data=data if data is not None else {},
        follow_redirects=False,
    )


def _umbral_de_la_unica_sesion(app, eval_id):
    with app.app_context():
        s = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one()
        return s.umbral_aprobacion


# --------------------------- Fijar el umbral al abrir ---------------------------


def test_abrir_sin_umbral_usa_el_de_la_evaluacion(client, facilitador, app):
    """Si el formulario no manda umbral, la sesion hereda el de la evaluacion."""
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    resp = _abrir(client, eval_id)
    assert resp.status_code == 302
    assert _umbral_de_la_unica_sesion(app, eval_id) == 60


def test_abrir_con_umbral_propio_lo_guarda_en_la_sesion(client, facilitador, app):
    """El facilitador puede exigir otra cosa solo para esta sesion."""
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    resp = _abrir(client, eval_id, {"umbral": "75"})
    assert resp.status_code == 302
    assert _umbral_de_la_unica_sesion(app, eval_id) == 75


def test_abrir_con_umbral_propio_no_toca_la_evaluacion(client, facilitador, app):
    """Cambiar el umbral al abrir NO edita la evaluacion (sigue siendo el defecto)."""
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    _abrir(client, eval_id, {"umbral": "75"})
    with app.app_context():
        assert db.session.get(Evaluacion, eval_id).umbral_aprobacion == 60


def test_dos_sesiones_pueden_tener_umbrales_distintos(client, facilitador, app):
    """La misma evaluacion: diagnostico exigente al 50, certificacion al 80."""
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    _abrir(client, eval_id, {"umbral": "50"})
    _abrir(client, eval_id, {"umbral": "80"})
    with app.app_context():
        umbrales = sorted(
            s.umbral_aprobacion
            for s in db.session.query(Sesion).filter_by(evaluacion_id=eval_id).all()
        )
    assert umbrales == [50, 80]


def test_abrir_con_umbral_fuera_de_rango_no_crea_sesion(client, facilitador, app):
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    resp = _abrir(client, eval_id, {"umbral": "150"})
    assert resp.status_code == 302
    assert "/evaluaciones/iniciar" in resp.headers["Location"]
    with app.app_context():
        assert db.session.query(Sesion).filter_by(evaluacion_id=eval_id).count() == 0


def test_abrir_con_umbral_no_numerico_no_crea_sesion(client, facilitador, app):
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    resp = _abrir(client, eval_id, {"umbral": "mucho"})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.query(Sesion).filter_by(evaluacion_id=eval_id).count() == 0


def test_abrir_sin_preguntas_avisa_y_vuelve_a_iniciar(client, facilitador, app):
    """El aviso deja al facilitador en Iniciar, no en el detalle de la evaluacion."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador.id, titulo="Vacia", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.commit()
        eval_id = e.id

    _login(client)
    resp = _abrir(client, eval_id)
    assert resp.status_code == 302
    assert "/evaluaciones/iniciar" in resp.headers["Location"]


# --------------------------- La nota usa el umbral de la sesion ---------------------------


def test_la_nota_usa_el_umbral_de_la_sesion_no_el_de_la_evaluacion(
    client, facilitador, app
):
    """Evaluacion al 60, sesion abierta al 100: responder bien da 7.0 igual,
    pero el resultado congela el umbral 100 (el de la sesion)."""
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    _abrir(client, eval_id, {"umbral": "100"})

    with app.app_context():
        sesion = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one()
        codigo = sesion.codigo

    # El participante responde TODO bien.
    client_p = client
    client_p.get(f"/sesion/{codigo}/ingreso")
    client_p.post(
        f"/sesion/{codigo}/ingreso", data={"rut": RUT_VALIDO, "nombre": "Ana"}
    )
    with app.app_context():
        p = db.session.query(Pregunta).filter_by(evaluacion_id=eval_id).one()
        correcta = next(a for a in p.alternativas if a.es_correcta)
        pid, aid = p.id, correcta.id
    client_p.post(f"/sesion/{codigo}/responder", data={f"pregunta_{pid}": str(aid)})

    with app.app_context():
        r = db.session.query(Resultado).one()
        assert r.porcentaje == 100.0
        assert r.nota == 7.0
        assert r.aprobado is True
        # Foto congelada: el umbral aplicado es el de la SESION.
        assert r.umbral_aprobacion == 100


def test_umbral_de_la_sesion_decide_la_aprobacion(client, facilitador, app):
    """Mismo 0% de logro: con umbral 0 aprueba, y ese umbral viene de la sesion."""
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    _abrir(client, eval_id, {"umbral": "0"})

    with app.app_context():
        codigo = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().codigo

    client.post(f"/sesion/{codigo}/ingreso", data={"rut": RUT_VALIDO, "nombre": "Ana"})
    with app.app_context():
        p = db.session.query(Pregunta).filter_by(evaluacion_id=eval_id).one()
        incorrecta = next(a for a in p.alternativas if not a.es_correcta)
        pid, aid = p.id, incorrecta.id
    client.post(f"/sesion/{codigo}/responder", data={f"pregunta_{pid}": str(aid)})

    with app.app_context():
        r = db.session.query(Resultado).one()
        assert r.porcentaje == 0.0
        assert r.aprobado is True  # umbral 0: todos aprueban
        assert r.umbral_aprobacion == 0


# --------------------------- Pantallas ---------------------------


def test_iniciar_muestra_el_umbral_de_la_evaluacion_precargado(
    client, facilitador, app
):
    _crear_eval(app, facilitador.id, umbral=72)
    _login(client)
    resp = client.get("/evaluaciones/iniciar")
    html = resp.get_data(as_text=True)
    assert 'name="umbral"' in html
    assert 'value="72"' in html


def test_panel_muestra_el_umbral_aplicado(client, facilitador, app):
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    _abrir(client, eval_id, {"umbral": "85"})
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id

    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}")
    assert "85%" in resp.get_data(as_text=True)


def test_sesion_abierta_ofrece_volver_a_iniciar(client, facilitador, app):
    """Dice solo "Volver": "Volver a Iniciar evaluación" se leía como
    "iniciarla de nuevo" ("volver a" + infinitivo = repetir la acción)."""
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    _abrir(client, eval_id)
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id

    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}")
    html = resp.get_data(as_text=True)
    assert "/evaluaciones/iniciar" in html
    assert "← Volver" in html
    # No debe sugerir que se vuelve a iniciar la evaluacion.
    assert "Volver a Iniciar" not in html


def test_sesion_cerrada_redirige_a_resultados(client, facilitador, app):
    """Una sesión cerrada ya no se opera: al entrar a su detalle se redirige a la
    matriz de resultados (informe_todos). detalle_sesion queda para la abierta."""
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    _abrir(client, eval_id)
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id

    client.post(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar")
    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}")
    assert resp.status_code == 302
    assert "informe-todos" in resp.headers["Location"]


def test_informes_muestra_el_umbral_de_cada_sesion(client, facilitador, app):
    eval_id = _crear_eval(app, facilitador.id, umbral=60)
    _login(client)
    _abrir(client, eval_id, {"umbral": "90"})
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id
    client.post(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar")

    resp = client.get("/evaluaciones/informes")
    assert "90%" in resp.get_data(as_text=True)
