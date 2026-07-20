"""Tests del bloque longitudinal (OE4, criterio 5).

Cubre las tres rutas nuevas de reporteria longitudinal:
- Historial por persona: /evaluaciones/participante/<hash_id>/historial
- Lista "Por participante":         /evaluaciones/participantes
- Buscador (nombre parcial + RUT completo via hash) en esa misma lista.

Se prueba lo que da valor de defensa:
- El historial agrupa por evaluacion y ordena cronologicamente.
- Solo aparecen sesiones CERRADAS y personas que FINALIZARON al menos una.
- La busqueda por RUT completo encuentra por hash (trazabilidad sin guardar RUT).
- Cada facilitador ve solo lo suyo (aislamiento).
"""

from datetime import datetime

from app import db
from app.models import Evaluacion, Facilitador, Participante, Resultado, Sesion
from app.utils.rut import hash_rut


RUT_A = "11.111.111-1"        # valido
RUT_B = "12.345.678-5"        # valido, otra persona
RUT_INVALIDO = "11.111.111-2"  # DV incorrecto


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


def _crear_evaluacion(app, facilitador_id, titulo, umbral=60):
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=umbral
        )
        db.session.add(e)
        db.session.commit()
        return e.id


def _crear_sesion(app, evaluacion_id, codigo, estado="cerrada", umbral=60):
    with app.app_context():
        s = Sesion(
            evaluacion_id=evaluacion_id,
            codigo=codigo,
            estado=estado,
            umbral_aprobacion=umbral,
        )
        db.session.add(s)
        db.session.commit()
        return s.id


def _agregar_persona(
    app, sesion_id, identificador_hash, nombre=None,
    finalizado=True, porcentaje=80.0, nota=6.0, aprobado=True,
):
    """Inserta un Participante con el hash dado. Si finalizado=True, le crea su
    Resultado (asi cuenta como sesion rendida)."""
    with app.app_context():
        p = Participante(
            sesion_id=sesion_id, identificador_hash=identificador_hash, nombre=nombre
        )
        db.session.add(p)
        db.session.flush()
        if finalizado:
            db.session.add(
                Resultado(
                    participante_id=p.id,
                    puntaje=1,
                    total_preguntas=1,
                    porcentaje=porcentaje,
                    nota=nota,
                    aprobado=aprobado,
                )
            )
        db.session.commit()
        return p.id


def _hash_de(app, rut):
    """Hash del RUT con el mismo pepper que usa la app (el default de tests)."""
    with app.app_context():
        return hash_rut(rut, app.config["RUT_SALT"])


# =================== Historial: funcion de agrupacion ===================

def test_agrupar_historial_agrupa_por_evaluacion_y_ordena_cronologico():
    """Nucleo del argumento de rigor: se agrupa por evaluacion y, dentro de
    cada una, de la sesion mas antigua a la mas nueva."""
    from types import SimpleNamespace

    from app.utils.reporte import agrupar_historial

    def _sesion(codigo, fecha):
        return SimpleNamespace(
            id=1, evaluacion_id=1,
            codigo=codigo, cerrada_at=fecha, abierta_at=fecha, umbral_aprobacion=60,
        )

    def _res(porcentaje):
        return SimpleNamespace(
            participante_id=1, porcentaje=porcentaje, nota=5.0, aprobado=True
        )

    antigua = datetime(2026, 1, 1)
    nueva = datetime(2026, 3, 1)
    # Llegan desordenadas y mezcladas entre dos evaluaciones.
    contexto = [
        ("Induccion", _sesion("NUEVA", nueva), _res(90.0)),
        ("Induccion", _sesion("ANTIGUA", antigua), _res(50.0)),
        ("Certificacion", _sesion("CERT1", antigua), _res(70.0)),
    ]
    grupos = agrupar_historial(contexto)

    # Dos grupos, ordenados por titulo.
    assert [g.evaluacion_titulo for g in grupos] == ["Certificacion", "Induccion"]
    # Dentro de Induccion, cronologico: la antigua antes que la nueva.
    induccion = next(g for g in grupos if g.evaluacion_titulo == "Induccion")
    assert [f.codigo for f in induccion.filas] == ["ANTIGUA", "NUEVA"]


def test_agrupar_historial_expone_llaves_del_informe_individual():
    """Cada fila FINALIZADA trae eval_id/sesion_id/participante_id (para enlazar
    a su informe individual). Una fila sin resultado no trae participante_id: no
    hay informe que mostrar, así que la fila no debe ofrecer link."""
    from types import SimpleNamespace

    from app.utils.reporte import agrupar_historial

    fecha = datetime(2026, 1, 1)
    sesion_fin = SimpleNamespace(
        id=7, evaluacion_id=3, codigo="FIN",
        cerrada_at=fecha, abierta_at=fecha, umbral_aprobacion=60,
    )
    sesion_pend = SimpleNamespace(
        id=8, evaluacion_id=3, codigo="PEND",
        cerrada_at=fecha, abierta_at=fecha, umbral_aprobacion=60,
    )
    res = SimpleNamespace(participante_id=42, porcentaje=90.0, nota=6.0, aprobado=True)

    contexto = [
        ("Induccion", sesion_fin, res),
        ("Induccion", sesion_pend, None),   # ingresó pero no finalizó
    ]
    por_codigo = {f.codigo: f for f in agrupar_historial(contexto)[0].filas}

    fin = por_codigo["FIN"]
    assert (fin.eval_id, fin.sesion_id, fin.participante_id) == (3, 7, 42)

    pend = por_codigo["PEND"]
    assert pend.participante_id is None          # sin informe -> sin link
    assert (pend.eval_id, pend.sesion_id) == (3, 8)


# ===================== Historial: ruta =====================

def test_historial_requiere_login(client, app):
    resp = client.get("/evaluaciones/participante/loquesea/historial")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_historial_404_si_no_existe_ese_hash(client, facilitador, app):
    _login(client)
    resp = client.get("/evaluaciones/participante/hash_inexistente/historial")
    assert resp.status_code == 404


def test_historial_solo_muestra_sesiones_cerradas(client, facilitador, app):
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s_cerrada = _crear_sesion(app, eval_id, "CERRAD", estado="cerrada")
    s_abierta = _crear_sesion(app, eval_id, "ABIERT", estado="abierta")
    h = "hash_persona_uno"
    _agregar_persona(app, s_cerrada, h, nombre="Ana Soto")
    _agregar_persona(app, s_abierta, h, nombre="Ana Soto")

    _login(client)
    resp = client.get(f"/evaluaciones/participante/{h}/historial")
    assert resp.status_code == 200
    cuerpo = resp.get_data(as_text=True)
    assert "CERRAD" in cuerpo       # la sesion cerrada aparece
    assert "ABIERT" not in cuerpo   # la abierta, no


def test_historial_aislado_por_facilitador(client, facilitador, app):
    """La persona rindio una sesion cerrada, pero de OTRO facilitador. El del
    fixture no debe poder ver ese historial."""
    otro_id = _crear_facilitador(app, "otro@fuenti.cl")
    eval_otro = _crear_evaluacion(app, otro_id, "Ajena")
    s = _crear_sesion(app, eval_otro, "AJENA1", estado="cerrada")
    _agregar_persona(app, s, "hash_ajeno", nombre="Persona Ajena")

    _login(client)  # facilitador del fixture, dueno de nada de lo anterior
    resp = client.get("/evaluaciones/participante/hash_ajeno/historial")
    assert resp.status_code == 404


def test_historial_enlaza_al_informe_individual_de_sesiones_finalizadas(
    client, facilitador, app
):
    """Cada sesión donde la persona FINALIZÓ enlaza a su informe individual;
    una sesión cerrada donde no finalizó (Pendiente) aparece pero SIN link."""
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s_fin = _crear_sesion(app, eval_id, "FINSES", estado="cerrada")
    s_pend = _crear_sesion(app, eval_id, "PENSES", estado="cerrada")
    h = "hash_persona"
    pid_fin = _agregar_persona(app, s_fin, h, nombre="Ana Soto", finalizado=True)
    pid_pend = _agregar_persona(app, s_pend, h, nombre="Ana Soto", finalizado=False)

    _login(client)
    cuerpo = client.get(
        f"/evaluaciones/participante/{h}/historial"
    ).get_data(as_text=True)

    url_fin = f"/evaluaciones/{eval_id}/sesiones/{s_fin}/participantes/{pid_fin}/informe"
    url_pend = f"/evaluaciones/{eval_id}/sesiones/{s_pend}/participantes/{pid_pend}/informe"
    assert "PENSES" in cuerpo        # la fila pendiente existe en la tabla…
    assert url_fin in cuerpo         # …la finalizada enlaza a su informe…
    assert url_pend not in cuerpo    # …y la pendiente no ofrece link.


# ============ Lista "Por participante" + buscador ============

def test_lista_requiere_login(client, app):
    resp = client.get("/evaluaciones/participantes")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_lista_muestra_solo_finalizados(client, facilitador, app):
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s = _crear_sesion(app, eval_id, "SESIO1", estado="cerrada")
    _agregar_persona(app, s, "hash_fin", nombre="Ana Finaliza", finalizado=True)
    _agregar_persona(app, s, "hash_nofin", nombre="Beto Pendiente", finalizado=False)

    _login(client)
    cuerpo = client.get("/evaluaciones/participantes").get_data(as_text=True)
    assert "Ana Finaliza" in cuerpo
    assert "Beto Pendiente" not in cuerpo


def test_lista_agrupa_por_hash_una_fila_por_persona(client, facilitador, app):
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s1 = _crear_sesion(app, eval_id, "SES1", estado="cerrada")
    s2 = _crear_sesion(app, eval_id, "SES2", estado="cerrada")
    h = "hash_repetida"
    _agregar_persona(app, s1, h, nombre="Ana Soto")
    _agregar_persona(app, s2, h, nombre="Ana Soto")

    _login(client)
    cuerpo = client.get("/evaluaciones/participantes").get_data(as_text=True)
    # Dos sesiones del mismo hash colapsan en una sola fila.
    assert cuerpo.count("Ana Soto") == 1


def test_buscador_por_nombre_parcial_insensible(client, facilitador, app):
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s = _crear_sesion(app, eval_id, "SESN", estado="cerrada")
    _agregar_persona(app, s, "h1", nombre="Ana Soto")
    _agregar_persona(app, s, "h2", nombre="Carla Diaz")

    _login(client)
    # minuscula y parcial: debe caer Ana, no Carla.
    cuerpo = client.get("/evaluaciones/participantes?nombre=ana").get_data(as_text=True)
    assert "Ana Soto" in cuerpo
    assert "Carla Diaz" not in cuerpo


def test_buscador_por_rut_completo_encuentra_por_hash(client, facilitador, app):
    """De punta a punta: solo se guarda el hash; buscar por RUT completo lo
    recalcula y cae la persona exacta."""
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s = _crear_sesion(app, eval_id, "SESR", estado="cerrada")
    _agregar_persona(app, s, _hash_de(app, RUT_A), nombre="Persona A")
    _agregar_persona(app, s, _hash_de(app, RUT_B), nombre="Persona B")

    _login(client)
    cuerpo = client.get(f"/evaluaciones/participantes?rut={RUT_A}").get_data(as_text=True)
    assert "Persona A" in cuerpo
    assert "Persona B" not in cuerpo


def test_buscador_rut_invalido_avisa_y_no_filtra(client, facilitador, app):
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s = _crear_sesion(app, eval_id, "SESI", estado="cerrada")
    _agregar_persona(app, s, "h1", nombre="Ana Soto")

    _login(client)
    cuerpo = client.get(
        f"/evaluaciones/participantes?rut={RUT_INVALIDO}"
    ).get_data(as_text=True)
    assert "Ana Soto" in cuerpo        # no se filtro
    assert "no es válido" in cuerpo    # se avisa del RUT invalido


def test_buscador_nombre_y_rut_se_combinan(client, facilitador, app):
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s = _crear_sesion(app, eval_id, "SESC", estado="cerrada")
    _agregar_persona(app, s, _hash_de(app, RUT_A), nombre="Ana Soto")

    _login(client)
    # nombre correcto + RUT correcto -> aparece
    ok = client.get(
        f"/evaluaciones/participantes?nombre=ana&rut={RUT_A}"
    ).get_data(as_text=True)
    assert "Ana Soto" in ok
    # nombre que no calza con ese RUT -> el AND la descarta
    no = client.get(
        f"/evaluaciones/participantes?nombre=zzz&rut={RUT_A}"
    ).get_data(as_text=True)
    assert "Ana Soto" not in no


def test_lista_aislada_por_facilitador(client, facilitador, app):
    otro_id = _crear_facilitador(app, "otro@fuenti.cl")
    eval_otro = _crear_evaluacion(app, otro_id, "Ajena")
    s = _crear_sesion(app, eval_otro, "AJENO", estado="cerrada")
    _agregar_persona(app, s, "hash_ajeno", nombre="Persona Ajena")

    _login(client)  # facilitador del fixture
    cuerpo = client.get("/evaluaciones/participantes").get_data(as_text=True)
    assert "Persona Ajena" not in cuerpo
