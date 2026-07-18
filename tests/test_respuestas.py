"""Tests del flujo de respuesta del participante: responder + resultado.

Cubre el cierre de OE2 (responde -> recibe resultado) y OE4 (sesion cerrada
no acepta el POST de respuestas).

Casos:
- Respuesta correcta calcula bien y persiste Respuesta + Resultado.
- Respuesta incorrecta reprueba.
- Sesion cerrada bloquea el POST (cierre de OE4).
- Preguntas sin responder: rechazo con flash, sin persistir.
- Participante con Resultado: GET y POST de responder redirigen al resultado.
- Resultado sin haber respondido redirige al cuestionario.
- El resultado se puede ver aunque la sesion se cierre despues.
- No se puede responder una sesion ajena (cookie cruzada).
- Alternativa que no pertenece a la pregunta: 400 (anti-tampering).
"""

from app import db
from app.models import (
    Alternativa,
    Evaluacion,
    Participante,
    Pregunta,
    Resultado,
    Respuesta,
    Sesion,
)


RUT_VALIDO = "11.111.111-1"


def _crear_eval(app, facilitador_id, n_preguntas=2, umbral=60):
    """Crea una evaluacion con n preguntas, cada una con 2 alternativas
    (orden 1 = correcta, orden 2 = incorrecta).

    Devuelve (eval_id, [(pregunta_id, alt_correcta_id, alt_incorrecta_id), ...]).
    """
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id,
            titulo="Eval respuestas",
            umbral_aprobacion=umbral,
        )
        db.session.add(e)
        db.session.flush()
        eval_id = e.id

        info = []
        for i in range(1, n_preguntas + 1):
            p = Pregunta(evaluacion_id=eval_id, enunciado=f"Pregunta {i}", orden=i)
            db.session.add(p)
            db.session.flush()
            correcta = Alternativa(
                pregunta_id=p.id, texto="correcta", es_correcta=True, orden=1
            )
            incorrecta = Alternativa(
                pregunta_id=p.id, texto="incorrecta", es_correcta=False, orden=2
            )
            db.session.add_all([correcta, incorrecta])
            db.session.flush()
            info.append((p.id, correcta.id, incorrecta.id))

        db.session.commit()
        return eval_id, info


def _abrir_sesion(app, eval_id, codigo="RESP34", estado="abierta", umbral=60):
    with app.app_context():
        s = Sesion(
            evaluacion_id=eval_id,
            codigo=codigo,
            estado=estado,
            umbral_aprobacion=umbral,
        )
        db.session.add(s)
        db.session.commit()
        return s.id


def _ingresar(client, codigo, rut=RUT_VALIDO, nombre="Juan Perez"):
    """Ingresa al participante (setea la cookie participante_id)."""
    return client.post(
        f"/sesion/{codigo}/ingreso", data={"rut": rut, "nombre": nombre}
    )


# ====================== Respuesta: calculo y persistencia ======================

def test_respuesta_correcta_calcula_y_persiste(client, facilitador, app):
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=2, umbral=60)
    sesion_id = _abrir_sesion(app, eval_id, codigo="RESP34")
    _ingresar(client, "RESP34")

    # Responde las 2 correctas -> 100% -> nota 7.0, aprobado
    data = {f"pregunta_{pid}": correcta for (pid, correcta, _) in info}
    resp = client.post("/sesion/RESP34/responder", data=data, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/RESP34/resultado")

    with app.app_context():
        participante = db.session.query(Participante).filter_by(sesion_id=sesion_id).one()
        assert db.session.query(Respuesta).filter_by(participante_id=participante.id).count() == 2
        r = participante.resultado
        assert r is not None
        assert r.puntaje == 2
        assert r.total_preguntas == 2
        assert r.porcentaje == 100.0
        assert r.nota == 7.0
        assert r.aprobado is True
        assert participante.finalizado_at is not None


def test_finalizar_guarda_la_foto_congelada(client, facilitador, app):
    """Al finalizar, cada Respuesta guarda su copia (enunciado, elegida,
    correcta, acerto, orden) y el Resultado guarda titulo y umbral aplicados.
    Asi el resultado queda autocontenido y no depende de la evaluacion viva.
    """
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=2, umbral=60)
    sesion_id = _abrir_sesion(app, eval_id, codigo="FOTO34")
    _ingresar(client, "FOTO34")

    # Pregunta 1 correcta, pregunta 2 incorrecta.
    (pid1, correcta1, _), (pid2, _, incorrecta2) = info
    data = {f"pregunta_{pid1}": correcta1, f"pregunta_{pid2}": incorrecta2}
    client.post("/sesion/FOTO34/responder", data=data)

    with app.app_context():
        participante = db.session.query(Participante).filter_by(sesion_id=sesion_id).one()
        respuestas = {
            r.orden: r
            for r in db.session.query(Respuesta).filter_by(
                participante_id=participante.id
            )
        }

        # Pregunta 1 (orden 1): eligio la correcta.
        r1 = respuestas[1]
        assert r1.enunciado_texto == "Pregunta 1"
        assert r1.elegida_texto == "correcta"
        assert r1.correcta_texto == "correcta"
        assert r1.acerto is True

        # Pregunta 2 (orden 2): eligio la incorrecta.
        r2 = respuestas[2]
        assert r2.enunciado_texto == "Pregunta 2"
        assert r2.elegida_texto == "incorrecta"
        assert r2.correcta_texto == "correcta"
        assert r2.acerto is False

        # El resultado guarda el encabezado congelado.
        assert participante.resultado.evaluacion_titulo == "Eval respuestas"
        assert participante.resultado.umbral_aprobacion == 60


def test_respuesta_incorrecta_reprueba(client, facilitador, app):
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=2, umbral=60)
    sesion_id = _abrir_sesion(app, eval_id, codigo="BADD34")
    _ingresar(client, "BADD34")

    # Responde las 2 incorrectas -> 0% -> nota 1.0, reprobado
    data = {f"pregunta_{pid}": incorrecta for (pid, _, incorrecta) in info}
    client.post("/sesion/BADD34/responder", data=data)

    with app.app_context():
        participante = db.session.query(Participante).filter_by(sesion_id=sesion_id).one()
        r = participante.resultado
        assert r.puntaje == 0
        assert r.nota == 1.0
        assert r.aprobado is False


def test_resultado_muestra_la_nota(client, facilitador, app):
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=2, umbral=60)
    _abrir_sesion(app, eval_id, codigo="VER234")
    _ingresar(client, "VER234")

    data = {f"pregunta_{pid}": correcta for (pid, correcta, _) in info}
    client.post("/sesion/VER234/responder", data=data)

    resp = client.get("/sesion/VER234/resultado")
    assert resp.status_code == 200
    assert b"7.0" in resp.data
    assert "Aprobado".encode("utf-8") in resp.data


# ====================== OE4: sesion cerrada bloquea el POST ======================

def test_sesion_cerrada_bloquea_post_de_respuestas(client, facilitador, app):
    """Cierre de OE4: aunque el participante ingreso con la sesion abierta y
    despues el facilitador la cierra, el POST de respuestas no se acepta y no
    se crea Resultado."""
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=2, umbral=60)
    sesion_id = _abrir_sesion(app, eval_id, codigo="CERR34")
    _ingresar(client, "CERR34")

    # El facilitador cierra la sesion
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        s.estado = "cerrada"
        db.session.commit()

    data = {f"pregunta_{pid}": correcta for (pid, correcta, _) in info}
    resp = client.post("/sesion/CERR34/responder", data=data)

    assert resp.status_code == 200
    assert "cerrada".encode("utf-8") in resp.data.lower()

    with app.app_context():
        assert db.session.query(Resultado).count() == 0
        assert db.session.query(Respuesta).count() == 0


# ====================== Validacion: preguntas sin responder ======================

def test_preguntas_sin_responder_rechaza_sin_persistir(client, facilitador, app):
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=2, umbral=60)
    _abrir_sesion(app, eval_id, codigo="GAPS34")
    _ingresar(client, "GAPS34")

    # Responde solo la primera pregunta
    primer_pid, primera_correcta, _ = info[0]
    data = {f"pregunta_{primer_pid}": primera_correcta}
    resp = client.post("/sesion/GAPS34/responder", data=data)

    assert resp.status_code == 200
    assert "todas las preguntas".encode("utf-8") in resp.data

    with app.app_context():
        assert db.session.query(Resultado).count() == 0
        assert db.session.query(Respuesta).count() == 0


# ====================== Reentrada con Resultado ya calculado ======================

def test_get_responder_con_resultado_redirige_a_resultado(client, facilitador, app):
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=1, umbral=60)
    _abrir_sesion(app, eval_id, codigo="REDU34")
    _ingresar(client, "REDU34")

    data = {f"pregunta_{pid}": correcta for (pid, correcta, _) in info}
    client.post("/sesion/REDU34/responder", data=data)

    resp = client.get("/sesion/REDU34/responder", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/REDU34/resultado")


def test_post_responder_con_resultado_no_recalcula(client, facilitador, app):
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=1, umbral=60)
    sesion_id = _abrir_sesion(app, eval_id, codigo="TWCE34")
    _ingresar(client, "TWCE34")

    # Primera vez: correcta
    pid, correcta, incorrecta = info[0]
    client.post("/sesion/TWCE34/responder", data={f"pregunta_{pid}": correcta})

    # Segundo POST, ahora con la incorrecta: no debe recalcular ni duplicar
    resp = client.post(
        "/sesion/TWCE34/responder",
        data={f"pregunta_{pid}": incorrecta},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/TWCE34/resultado")

    with app.app_context():
        assert db.session.query(Resultado).count() == 1
        participante = db.session.query(Participante).filter_by(sesion_id=sesion_id).one()
        # Sigue reflejando la primera respuesta (correcta), no la segunda.
        assert participante.resultado.puntaje == 1
        assert db.session.query(Respuesta).filter_by(participante_id=participante.id).count() == 1


# ====================== Resultado: guardas de acceso ======================

def test_resultado_sin_haber_respondido_redirige_a_responder(client, facilitador, app):
    eval_id, _ = _crear_eval(app, facilitador.id, n_preguntas=1, umbral=60)
    _abrir_sesion(app, eval_id, codigo="NADA34")
    _ingresar(client, "NADA34")

    resp = client.get("/sesion/NADA34/resultado", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/NADA34/responder")


def test_resultado_visible_aunque_sesion_cerrada(client, facilitador, app):
    """Si el facilitador cierra la sesion despues, el participante igual ve su
    resultado (resultado NO se bloquea por sesion cerrada)."""
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=1, umbral=60)
    sesion_id = _abrir_sesion(app, eval_id, codigo="SEEN34")
    _ingresar(client, "SEEN34")

    data = {f"pregunta_{pid}": correcta for (pid, correcta, _) in info}
    client.post("/sesion/SEEN34/responder", data=data)

    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        s.estado = "cerrada"
        db.session.commit()

    resp = client.get("/sesion/SEEN34/resultado")
    assert resp.status_code == 200
    assert b"7.0" in resp.data


# ====================== Defensas ======================

def test_no_puede_responder_sesion_ajena(client, facilitador, app):
    """Ingresa a sesion A y trata de postear respuestas a sesion B con la
    cookie de A: se lo redirige al ingreso de B y no se crea Resultado."""
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=1, umbral=60)
    _abrir_sesion(app, eval_id, codigo="SESA34")
    _abrir_sesion(app, eval_id, codigo="SESB34")

    _ingresar(client, "SESA34")

    pid, correcta, _ = info[0]
    resp = client.post(
        "/sesion/SESB34/responder",
        data={f"pregunta_{pid}": correcta},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sesion/SESB34/ingreso")

    with app.app_context():
        assert db.session.query(Resultado).count() == 0


def test_alternativa_de_otra_pregunta_es_rechazada(client, facilitador, app):
    """Anti-tampering: si el POST manda una alternativa que no pertenece a la
    pregunta, se rechaza con 400 y no se persiste."""
    eval_id, info = _crear_eval(app, facilitador.id, n_preguntas=2, umbral=60)
    _abrir_sesion(app, eval_id, codigo="TAMP34")
    _ingresar(client, "TAMP34")

    pid_1, correcta_1, _ = info[0]
    _, correcta_2, _ = info[1]
    # A la pregunta 1 le mando la alternativa correcta de la pregunta 2.
    data = {f"pregunta_{pid_1}": correcta_2, f"pregunta_{info[1][0]}": correcta_2}
    resp = client.post("/sesion/TAMP34/responder", data=data)

    assert resp.status_code == 400
    with app.app_context():
        assert db.session.query(Resultado).count() == 0
