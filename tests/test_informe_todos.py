"""Tests de la matriz de resultados de la sesion (informe_todos).

Cubre:
- El helper puro construir_matriz: celdas (letra + acierto), % de acierto por
  pregunta, nota por fila, y preguntas no respondidas.
- La ruta: login, guardas (403 dueno / 404 sesion), y el contenido de la matriz
  (filas de finalizados, exclusion de pendientes, encabezados Qn y leyenda).
"""

from types import SimpleNamespace

from app import db
from app.models import (
    Alternativa,
    Evaluacion,
    Facilitador,
    Participante,
    Pregunta,
    Respuesta,
    Resultado,
    Sesion,
)


# ------------------------------ helpers ------------------------------

def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _crear_facilitador(app, email, nombre="Otro Facilitador", password="clave1234"):
    with app.app_context():
        f = Facilitador(email=email, nombre=nombre)
        f.set_password(password)
        db.session.add(f)
        db.session.commit()
        return f.id


def _crear_evaluacion_2preguntas(app, facilitador_id, titulo="Induccion", umbral=60):
    """Evaluacion con 2 preguntas; cada una con alternativa A (correcta, orden 1)
    y B (incorrecta, orden 2). Devuelve los textos para construir respuestas."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=umbral
        )
        db.session.add(e)
        db.session.flush()
        preguntas = []
        for orden, enunciado in [(1, "¿2 + 2?"), (2, "¿Color del casco?")]:
            q = Pregunta(evaluacion_id=e.id, enunciado=enunciado, orden=orden)
            db.session.add(q)
            db.session.flush()
            a = Alternativa(pregunta_id=q.id, texto=f"correcta-{orden}", es_correcta=True, orden=1)
            b = Alternativa(pregunta_id=q.id, texto=f"mala-{orden}", es_correcta=False, orden=2)
            db.session.add_all([a, b])
            preguntas.append(
                {
                    "orden": orden,
                    "enunciado": enunciado,
                    "correcta_texto": a.texto,
                    "mala_texto": b.texto,
                }
            )
        db.session.commit()
        return {"eval_id": e.id, "preguntas": preguntas}


def _crear_sesion(app, evaluacion_id, codigo, estado="cerrada", umbral=60):
    with app.app_context():
        s = Sesion(
            evaluacion_id=evaluacion_id, codigo=codigo, estado=estado, umbral_aprobacion=umbral
        )
        db.session.add(s)
        db.session.commit()
        return s.id


def _persona(app, sesion_id, nombre, respuestas, finalizado=True, nota=6.0, porcentaje=80.0):
    """respuestas: lista de dict {orden, elegida_texto, correcta_texto, acerto}."""
    with app.app_context():
        p = Participante(
            sesion_id=sesion_id, identificador_hash=f"hash_{nombre}", nombre=nombre
        )
        db.session.add(p)
        db.session.flush()
        for r in respuestas:
            db.session.add(
                Respuesta(
                    participante_id=p.id,
                    enunciado_texto="",
                    elegida_texto=r["elegida_texto"],
                    correcta_texto=r["correcta_texto"],
                    acerto=r["acerto"],
                    orden=r["orden"],
                )
            )
        if finalizado:
            db.session.add(
                Resultado(
                    participante_id=p.id,
                    puntaje=1,
                    total_preguntas=len(respuestas) or 1,
                    porcentaje=porcentaje,
                    nota=nota,
                    aprobado=porcentaje >= 60,
                )
            )
        db.session.commit()
        return p.id


def _url(eval_id, sesion_id):
    return f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/informe-todos"


# ===================== helper puro: construir_matriz =====================

def test_construir_matriz_celdas_porcentajes_y_no_respondidas():
    from app.utils.reporte import construir_matriz

    def _resp(orden, elegida, acerto):
        return SimpleNamespace(orden=orden, elegida_texto=elegida, acerto=acerto)

    ana = SimpleNamespace(
        nombre="Ana", identificador_hash="hashana0001",
        respuestas=[_resp(1, "4", True), _resp(2, "rojo", False)],
        resultado=SimpleNamespace(nota=5.5, porcentaje=50.0),
    )
    beto = SimpleNamespace(
        nombre="Beto", identificador_hash="hashbeto002",
        respuestas=[_resp(1, "4", True)],  # no respondio Q2
        resultado=SimpleNamespace(nota=7.0, porcentaje=100.0),
    )

    columnas_meta = [(1, "Dos mas dos", "A"), (2, "Color", "A")]
    letra_de = lambda orden, texto: {"4": "A", "rojo": "B"}.get(texto, "路".replace("路", "\u00b7"))

    m = construir_matriz([ana, beto], columnas_meta, letra_de)

    assert [c.orden for c in m.columnas] == [1, 2]
    # Q1: los dos acertaron -> 100%. Q2: solo Ana respondio y fallo -> 0%.
    assert m.columnas[0].pct_acierto == 100
    assert m.columnas[1].pct_acierto == 0

    fila_ana = m.filas[0]
    assert fila_ana.celdas[0].letra == "A" and fila_ana.celdas[0].acerto is True
    assert fila_ana.celdas[1].letra == "B" and fila_ana.celdas[1].acerto is False
    assert fila_ana.nota == 5.5

    fila_beto = m.filas[1]
    # Q2 sin responder: celda vacia, acerto None (no cuenta para el %).
    assert fila_beto.celdas[1].acerto is None


# ===================== ruta: informe_todos (matriz) =====================

def test_informe_todos_requiere_login(client, app):
    resp = client.get(_url(1, 1))
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_informe_todos_403_si_no_es_dueno(client, facilitador, app):
    otro_id = _crear_facilitador(app, "otro@fuenti.cl")
    data = _crear_evaluacion_2preguntas(app, otro_id)
    s = _crear_sesion(app, data["eval_id"], "AJENA1")

    _login(client)  # facilitador del fixture, no es el dueno
    assert client.get(_url(data["eval_id"], s)).status_code == 403


def test_informe_todos_404_si_sesion_no_es_de_esa_evaluacion(client, facilitador, app):
    data = _crear_evaluacion_2preguntas(app, facilitador.id)
    otra = _crear_evaluacion_2preguntas(app, facilitador.id, titulo="Otra")
    s_otra = _crear_sesion(app, otra["eval_id"], "OTRA01")

    _login(client)
    assert client.get(_url(data["eval_id"], s_otra)).status_code == 404


def test_informe_todos_matriz_filas_columnas_y_leyenda(client, facilitador, app):
    data = _crear_evaluacion_2preguntas(app, facilitador.id)
    s = _crear_sesion(app, data["eval_id"], "HSES01")
    p1, p2 = data["preguntas"][0], data["preguntas"][1]

    _persona(app, s, "Ana Soto", [
        {"orden": 1, "elegida_texto": p1["correcta_texto"], "correcta_texto": p1["correcta_texto"], "acerto": True},
        {"orden": 2, "elegida_texto": p2["mala_texto"], "correcta_texto": p2["correcta_texto"], "acerto": False},
    ], nota=5.5, porcentaje=50.0)
    _persona(app, s, "Beto Diaz", [
        {"orden": 1, "elegida_texto": p1["correcta_texto"], "correcta_texto": p1["correcta_texto"], "acerto": True},
        {"orden": 2, "elegida_texto": p2["correcta_texto"], "correcta_texto": p2["correcta_texto"], "acerto": True},
    ], nota=7.0, porcentaje=100.0)
    _persona(app, s, "Carla Pendiente", [], finalizado=False)

    _login(client)
    cuerpo = client.get(_url(data["eval_id"], s)).get_data(as_text=True)

    assert "Ana Soto" in cuerpo
    assert "Beto Diaz" in cuerpo
    assert "Carla Pendiente" not in cuerpo    # pendiente: no va
    assert "P1" in cuerpo and "P2" in cuerpo  # encabezados de columna
    assert "¿2 + 2?" in cuerpo                # la leyenda trae el enunciado
    assert "% de acierto" in cuerpo           # fila de resumen por pregunta
    assert "\u2713" in cuerpo and "\u2717" in cuerpo  # aciertos y errores marcados
    assert "A \u2713" in cuerpo               # Ana eligio A (correcta) en Q1


def test_informe_todos_sin_finalizados_muestra_aviso(client, facilitador, app):
    data = _crear_evaluacion_2preguntas(app, facilitador.id)
    s = _crear_sesion(app, data["eval_id"], "VACIA1")
    _persona(app, s, "Solo Pendiente", [], finalizado=False)

    _login(client)
    cuerpo = client.get(_url(data["eval_id"], s)).get_data(as_text=True)
    assert "no hay" in cuerpo.lower()
    assert "Solo Pendiente" not in cuerpo
