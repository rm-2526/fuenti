"""Tests de la eliminación de una sesión SIN participantes.

No es un botón nuevo suelto: reemplaza al de "Cerrar sesión" en la propia
pantalla de la sesión, cuando todavía no ingresó nadie. Ver el docstring de
evaluaciones.eliminar_sesion para el porqué.
"""

from app import db
from app.models import Evaluacion, Facilitador, Participante, Pregunta, Sesion
from app.utils.rut import hash_rut


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=True
    )


def _crear_eval(app, facilitador_id, titulo="Eval eliminar"):
    with app.app_context():
        e = Evaluacion(facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=60)
        db.session.add(e)
        db.session.flush()
        p = Pregunta(evaluacion_id=e.id, enunciado="¿2+2?", orden=1)
        db.session.add(p)
        db.session.commit()
        return e.id


def _abrir(client, eval_id):
    return client.post(
        f"/evaluaciones/{eval_id}/sesiones/abrir", data={}, follow_redirects=False
    )


def _agregar_participante(app, sesion_id, rut="45.278.361-4"):
    with app.app_context():
        salt = app.config["RUT_SALT"]
        p = Participante(sesion_id=sesion_id, identificador_hash=hash_rut(rut, salt))
        db.session.add(p)
        db.session.commit()
        return p.id


# ------------------------------- Vista (botón) -------------------------------


def test_sesion_abierta_vacia_muestra_boton_eliminar(app, client, facilitador):
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    _abrir(client, eval_id)
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id

    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}")
    body = resp.data.decode()
    assert "Eliminar sesión (sin participantes)" in body
    # No basta con buscar el texto "Cerrar sesión": el navbar tiene su propio
    # enlace de "Cerrar sesión" para el logout, que no tiene nada que ver con
    # este botón. Se busca la acción del formulario, que es inequívoca.
    assert f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar" not in body
    assert f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/eliminar" in body


def test_sesion_abierta_con_participantes_muestra_boton_cerrar(app, client, facilitador):
    """En cuanto hay al menos un participante, el botón vuelve a ser
    'Cerrar sesión': la eliminación deja de ofrecerse como camino normal."""
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    _abrir(client, eval_id)
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id
    _agregar_participante(app, sesion_id)

    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}")
    body = resp.data.decode()
    assert f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar" in body
    assert f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/eliminar" not in body
    assert "Eliminar sesión (sin participantes)" not in body


# ------------------------------- La acción -------------------------------


def test_eliminar_sesion_vacia_la_borra_y_redirige_a_iniciar(app, client, facilitador):
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    _abrir(client, eval_id)
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id

    resp = client.post(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/eliminar",
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert resp.request.path == "/evaluaciones/iniciar"
    assert "eliminada".encode() in resp.data
    with app.app_context():
        assert db.session.get(Sesion, sesion_id) is None


def test_eliminar_sesion_con_participantes_se_rechaza(app, client, facilitador):
    """Defensa en el servidor: aunque alguien fuerce el POST directamente (o
    haya entrado un participante entre que cargó la página y envió el
    formulario), una sesión con participantes NO se borra por esta vía."""
    eval_id = _crear_eval(app, facilitador.id)
    _login(client)
    _abrir(client, eval_id)
    with app.app_context():
        sesion_id = db.session.query(Sesion).filter_by(evaluacion_id=eval_id).one().id
    _agregar_participante(app, sesion_id)

    resp = client.post(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/eliminar",
        follow_redirects=True,
    )

    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Sesion, sesion_id) is not None
        assert (
            db.session.scalar(
                db.select(db.func.count())
                .select_from(Participante)
                .where(Participante.sesion_id == sesion_id)
            )
            == 1
        )


def test_eliminar_sesion_de_otro_facilitador_da_403(app, client, facilitador):
    """Mismo guard de propiedad que el resto de las rutas de evaluaciones."""
    with app.app_context():
        otro = Facilitador(email="otro2@fuenti.cl", nombre="Otro", aprobado=True)
        otro.set_password("clave1234")
        db.session.add(otro)
        db.session.commit()
        otro_id = otro.id
    eval_id = _crear_eval(app, otro_id, titulo="Ajena")
    with app.app_context():
        s = Sesion(evaluacion_id=eval_id, codigo="AJENA1", estado="abierta", umbral_aprobacion=60)
        db.session.add(s)
        db.session.commit()
        sesion_id = s.id

    _login(client)  # el facilitador del fixture, NO el dueño
    resp = client.post(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/eliminar")
    assert resp.status_code == 403
