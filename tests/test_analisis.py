"""Tests del análisis de fortalezas/debilidades con IA.

Cubre las dos capas por separado:
- La AGREGACIÓN PURA (analisis.py): separa acertadas/falladas, ordena las
  preguntas de la más fallada a la menos, y —crítico— el prompt NUNCA lleva
  nombre ni hash del participante (garantía de privacidad, §3.1).
- El WRAPPER (gemini.py): sin API key devuelve None (no toca la red).
- El CABLEADO al cerrar la sesión: sin key cierra igual y no persiste; con un
  generador simulado congela el texto por persona y por grupo; es idempotente
  (no regenera lo ya guardado); y el texto persistido se muestra en los informes.

Los tests de integración NO llaman a la red: se inyecta un generador falso con
monkeypatch, o se deja la API key vacía para forzar la degradación.
"""

from collections import namedtuple

from app import db
from app.models import (
    Alternativa,
    Evaluacion,
    Participante,
    Pregunta,
    Resultado,
    Sesion,
)
from app.utils import gemini
from app.utils.analisis import (
    prompt_persona,
    prompt_sesion,
    resumen_persona,
    resumen_sesion,
)


_Linea = namedtuple("_Linea", "enunciado acerto")


def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


# ------------------------------ Capa pura ------------------------------

def test_resumen_persona_separa_acertadas_y_falladas():
    desglose = [
        _Linea("¿Cuál es el EPP obligatorio?", True),
        _Linea("¿Qué hacer ante un amago de incendio?", False),
        _Linea("¿Cada cuánto se revisa el extintor?", True),
    ]
    r = resumen_persona(desglose, porcentaje=66.7, umbral=60, aprobado=True)

    assert r.acertadas == [
        "¿Cuál es el EPP obligatorio?",
        "¿Cada cuánto se revisa el extintor?",
    ]
    assert r.falladas == ["¿Qué hacer ante un amago de incendio?"]
    assert r.aprobado is True


def test_prompt_persona_no_incluye_nombre_ni_hash():
    # La garantía de privacidad: aunque exista una persona con este nombre y
    # hash, esos datos no se le pasan a la función y no pueden aparecer.
    nombre = "Juana Pérez"
    hash_id = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"

    desglose = [_Linea("¿EPP obligatorio?", True), _Linea("¿Evacuación?", False)]
    r = resumen_persona(desglose, porcentaje=50.0, umbral=60, aprobado=False)
    prompt = prompt_persona(r)

    assert nombre not in prompt
    assert hash_id not in prompt
    # Sí debe llevar el contenido de la evaluación.
    assert "¿EPP obligatorio?" in prompt
    assert "¿Evacuación?" in prompt


def test_resumen_sesion_ordena_de_la_mas_fallada_a_la_menos():
    # Dos personas: P_facil la aciertan ambas; P_dificil ninguna.
    d1 = [_Linea("P_facil", True), _Linea("P_dificil", False)]
    d2 = [_Linea("P_facil", True), _Linea("P_dificil", False)]

    r = resumen_sesion([d1, d2], aprobados=1, reprobados=1, promedio_logro=50.0)

    assert r.total_finalizados == 2
    assert r.aprobados == 1
    assert r.reprobados == 1
    # La más fallada va primero.
    assert r.preguntas[0].enunciado == "P_dificil"
    assert r.preguntas[0].porcentaje_acierto == 0.0
    assert r.preguntas[-1].enunciado == "P_facil"
    assert r.preguntas[-1].porcentaje_acierto == 100.0


def test_prompt_sesion_incluye_las_preguntas_y_los_totales():
    d1 = [_Linea("Pregunta clave", False)]
    r = resumen_sesion([d1], aprobados=0, reprobados=1, promedio_logro=0.0)
    prompt = prompt_sesion(r)

    assert "Pregunta clave" in prompt
    assert "1 aprobados" not in prompt  # (0 aprobados)
    assert "0 aprobados" in prompt


# ------------------------------ Wrapper ------------------------------

def test_gemini_sin_api_key_devuelve_none():
    assert gemini.generar_texto("cualquier prompt", api_key="") is None
    assert gemini.generar_texto("cualquier prompt", api_key=None) is None


def test_gemini_prompt_vacio_devuelve_none():
    assert gemini.generar_texto("", api_key="clave") is None


def _http_error(codigo):
    import urllib.error
    return urllib.error.HTTPError("http://x", codigo, "err", {}, None)


def _respuesta_ok(texto):
    return {"candidates": [{"content": {"parts": [{"text": texto}]}}]}


def test_gemini_reintenta_en_429_y_luego_tiene_exito(monkeypatch):
    # Primera llamada choca con el límite por minuto; la segunda funciona.
    llamadas = []

    def fake(req, timeout):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise _http_error(429)
        return _respuesta_ok("Análisis OK")

    monkeypatch.setattr(gemini, "_llamar_api", fake)
    texto = gemini.generar_texto(
        "prompt", api_key="clave", _sleep=lambda s: None
    )
    assert texto == "Análisis OK"
    assert len(llamadas) == 2  # reintentó una vez


def test_gemini_no_reintenta_en_404(monkeypatch):
    # Un 404 (modelo inexistente) es configuración: no se reintenta.
    llamadas = []

    def fake(req, timeout):
        llamadas.append(1)
        raise _http_error(404)

    monkeypatch.setattr(gemini, "_llamar_api", fake)
    texto = gemini.generar_texto(
        "prompt", api_key="clave", _sleep=lambda s: None
    )
    assert texto is None
    assert len(llamadas) == 1  # NO reintentó


def test_gemini_agota_reintentos_si_429_persiste(monkeypatch):
    llamadas = []

    def fake(req, timeout):
        llamadas.append(1)
        raise _http_error(429)

    monkeypatch.setattr(gemini, "_llamar_api", fake)
    texto = gemini.generar_texto(
        "prompt", api_key="clave", intentos=3, _sleep=lambda s: None
    )
    assert texto is None
    assert len(llamadas) == 3  # intentó las 3 veces y se rindió


# --------------------------- Cableado / DB ---------------------------

def _sesion_con_finalizado(app, facilitador_id, estado="abierta"):
    """Crea evaluación (2 preguntas) + sesión + 1 participante finalizado con su
    foto congelada y su Resultado. Devuelve (eval_id, sesion_id, participante_id).
    """
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo="Prevención de riesgos",
            umbral_aprobacion=60,
        )
        db.session.add(e)
        db.session.flush()

        p1 = Pregunta(evaluacion_id=e.id, enunciado="¿EPP obligatorio?", orden=1)
        p2 = Pregunta(evaluacion_id=e.id, enunciado="¿Vía de evacuación?", orden=2)
        db.session.add_all([p1, p2])
        db.session.flush()
        db.session.add_all([
            Alternativa(pregunta_id=p1.id, texto="Casco", es_correcta=True, orden=1),
            Alternativa(pregunta_id=p1.id, texto="Nada", es_correcta=False, orden=2),
            Alternativa(pregunta_id=p2.id, texto="Salida norte", es_correcta=True, orden=1),
            Alternativa(pregunta_id=p2.id, texto="Ventana", es_correcta=False, orden=2),
        ])

        s = Sesion(
            evaluacion_id=e.id, codigo="ANLSIS", estado=estado, umbral_aprobacion=60,
        )
        db.session.add(s)
        db.session.flush()

        part = Participante(
            sesion_id=s.id, identificador_hash="hash_de_prueba_solo_tests",
            nombre="Persona Test",
        )
        db.session.add(part)
        db.session.flush()

        # Foto congelada: acertó la 1, falló la 2.
        db.session.add_all([
            Respuesta_foto(part.id, 1, "¿EPP obligatorio?", "Casco", "Casco", True),
            Respuesta_foto(part.id, 2, "¿Vía de evacuación?", "Ventana", "Salida norte", False),
        ])
        db.session.add(Resultado(
            participante_id=part.id, puntaje=1, total_preguntas=2, porcentaje=50.0,
            nota=4.0, aprobado=False, evaluacion_titulo="Prevención de riesgos",
            umbral_aprobacion=60,
        ))
        db.session.commit()
        return e.id, s.id, part.id


def Respuesta_foto(participante_id, orden, enunciado, elegida, correcta, acerto):
    from app.models import Respuesta
    return Respuesta(
        participante_id=participante_id,
        enunciado_texto=enunciado,
        elegida_texto=elegida,
        correcta_texto=correcta,
        acerto=acerto,
        orden=orden,
    )


def test_cerrar_sin_api_key_cierra_y_no_persiste_analisis(app, client, facilitador):
    app.config["GEMINI_API_KEY"] = ""  # forzar degradación
    eval_id, sesion_id, part_id = _sesion_con_finalizado(app, facilitador.id)
    _login(client)

    resp = client.post(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        r = db.session.get(Resultado, 1)
        assert s.estado == "cerrada"       # cierra igual
        assert s.analisis_ia is None       # no persiste análisis
        assert r.analisis_ia is None


def test_cerrar_con_generador_persiste_persona_y_grupo(
    app, client, facilitador, monkeypatch
):
    app.config["GEMINI_API_KEY"] = "clave-de-prueba"
    monkeypatch.setattr(
        gemini, "generar_texto",
        lambda prompt, api_key, modelo=None, timeout=30: "Análisis simulado.",
    )
    eval_id, sesion_id, part_id = _sesion_con_finalizado(app, facilitador.id)
    _login(client)

    client.post(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar")

    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        r = (
            db.session.query(Resultado)
            .filter_by(participante_id=part_id).one()
        )
        assert s.analisis_ia == "Análisis simulado."
        assert s.analisis_generado_at is not None
        assert r.analisis_ia == "Análisis simulado."
        assert r.analisis_generado_at is not None


def test_no_regenera_analisis_ya_existente(app, client, facilitador, monkeypatch):
    app.config["GEMINI_API_KEY"] = "clave-de-prueba"
    eval_id, sesion_id, part_id = _sesion_con_finalizado(app, facilitador.id)

    # Pre-cargar un análisis "congelado" en ambos.
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        s.analisis_ia = "ORIGINAL grupo"
        r = db.session.query(Resultado).filter_by(participante_id=part_id).one()
        r.analisis_ia = "ORIGINAL persona"
        db.session.commit()

    # Un generador que, si se llamara, devolvería otra cosa.
    monkeypatch.setattr(
        gemini, "generar_texto",
        lambda prompt, api_key, modelo=None, timeout=30: "NUEVO (no debería pisar)",
    )
    _login(client)
    client.post(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/cerrar")

    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        r = db.session.query(Resultado).filter_by(participante_id=part_id).one()
        assert s.analisis_ia == "ORIGINAL grupo"
        assert r.analisis_ia == "ORIGINAL persona"


def test_analisis_persona_se_muestra_en_informe_individual(app, client, facilitador):
    eval_id, sesion_id, part_id = _sesion_con_finalizado(app, facilitador.id, estado="cerrada")
    with app.app_context():
        r = db.session.query(Resultado).filter_by(participante_id=part_id).one()
        r.analisis_ia = "Domina el EPP pero debe reforzar evacuación."
        db.session.commit()
    _login(client)

    resp = client.get(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/participantes/{part_id}/informe"
    )
    cuerpo = resp.get_data(as_text=True)
    assert "Domina el EPP pero debe reforzar evacuación." in cuerpo
    assert "Sugerido por IA" in cuerpo


def test_analisis_grupo_se_muestra_en_informe_todos(app, client, facilitador):
    eval_id, sesion_id, part_id = _sesion_con_finalizado(app, facilitador.id, estado="cerrada")
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        s.analisis_ia = "El grupo falla en evacuación."
        db.session.commit()
    _login(client)

    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/informe-todos")
    cuerpo = resp.get_data(as_text=True)
    assert "El grupo falla en evacuación." in cuerpo
    assert "Sugerido por IA" in cuerpo


# ------------------------ Backfill por consola (CLI) ------------------------

def test_backfill_genera_para_sesion_cerrada(app, facilitador, monkeypatch):
    app.config["GEMINI_API_KEY"] = "clave-de-prueba"
    monkeypatch.setattr(
        gemini, "generar_texto",
        lambda prompt, api_key, modelo=None, timeout=30: "Texto de backfill.",
    )
    eval_id, sesion_id, part_id = _sesion_con_finalizado(
        app, facilitador.id, estado="cerrada"
    )
    with app.app_context():
        codigo = db.session.get(Sesion, sesion_id).codigo

    result = app.test_cli_runner().invoke(args=["analisis-backfill", codigo])

    assert result.exit_code == 0
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        r = db.session.query(Resultado).filter_by(participante_id=part_id).one()
        assert s.analisis_ia == "Texto de backfill."
        assert r.analisis_ia == "Texto de backfill."


def test_backfill_no_pisa_analisis_existente(app, facilitador, monkeypatch):
    app.config["GEMINI_API_KEY"] = "clave-de-prueba"
    eval_id, sesion_id, part_id = _sesion_con_finalizado(
        app, facilitador.id, estado="cerrada"
    )
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        s.analisis_ia = "ORIGINAL grupo"
        r = db.session.query(Resultado).filter_by(participante_id=part_id).one()
        r.analisis_ia = "ORIGINAL persona"
        db.session.commit()
        codigo = s.codigo

    monkeypatch.setattr(
        gemini, "generar_texto",
        lambda prompt, api_key, modelo=None, timeout=30: "NUEVO (no debe pisar)",
    )
    result = app.test_cli_runner().invoke(args=["analisis-backfill", codigo])

    assert result.exit_code == 0
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        r = db.session.query(Resultado).filter_by(participante_id=part_id).one()
        assert s.analisis_ia == "ORIGINAL grupo"
        assert r.analisis_ia == "ORIGINAL persona"


def test_backfill_codigo_inexistente_sale_con_error(app):
    app.config["GEMINI_API_KEY"] = "clave-de-prueba"
    result = app.test_cli_runner().invoke(args=["analisis-backfill", "NOEXST"])
    assert result.exit_code != 0
    assert "No existe" in result.output


def test_backfill_sin_api_key_avisa_y_no_genera(app, facilitador):
    app.config["GEMINI_API_KEY"] = ""
    eval_id, sesion_id, part_id = _sesion_con_finalizado(
        app, facilitador.id, estado="cerrada"
    )
    with app.app_context():
        codigo = db.session.get(Sesion, sesion_id).codigo

    result = app.test_cli_runner().invoke(args=["analisis-backfill", codigo])

    assert result.exit_code != 0
    assert "GEMINI_API_KEY" in result.output
    with app.app_context():
        s = db.session.get(Sesion, sesion_id)
        assert s.analisis_ia is None


# ------------------------ Espaciado entre llamadas ------------------------

def test_espaciado_pausa_entre_llamadas(app, facilitador, monkeypatch):
    # 1 persona + 1 grupo = 2 llamadas reales => 1 sola pausa entre ambas.
    from app.evaluaciones.routes import generar_analisis_de_sesion

    monkeypatch.setattr(
        gemini, "generar_texto",
        lambda prompt, api_key, modelo=None, timeout=30: "texto",
    )
    esperas = []
    eval_id, sesion_id, part_id = _sesion_con_finalizado(
        app, facilitador.id, estado="cerrada"
    )
    with app.app_context():
        sesion = db.session.get(Sesion, sesion_id)
        generar_analisis_de_sesion(
            sesion, "clave", "modelo",
            espaciado=5.0, _sleep=lambda s: esperas.append(s),
        )

    # No pausa antes de la primera ni después de la última: exactamente una
    # pausa de 5s entre la llamada de la persona y la del grupo.
    assert esperas == [5.0]
