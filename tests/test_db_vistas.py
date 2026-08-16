"""Pruebas de las vistas de base de datos (I6).

Lo que se verifica no es que la vista "funcione", sino que diga lo mismo que
decia el codigo Python al que reemplaza. Una vista que agrega distinto que el
modulo de estadisticas seria peor que no tenerla: introduciria dos verdades.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.models import (
    Alternativa,
    Evaluacion,
    Participante,
    Pregunta,
    Resultado,
    Sesion,
)
from app.vistas import historial_de, resumen_de


def _ahora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _evaluacion(facilitador, titulo="Prevencion de riesgos", umbral=60):
    ev = Evaluacion(facilitador_id=facilitador.id, titulo=titulo, umbral_aprobacion=umbral)
    db.session.add(ev)
    db.session.flush()
    pregunta = Pregunta(evaluacion_id=ev.id, enunciado="Enunciado", orden=1)
    db.session.add(pregunta)
    db.session.flush()
    db.session.add(Alternativa(pregunta_id=pregunta.id, texto="A", es_correcta=True, orden=1))
    db.session.add(Alternativa(pregunta_id=pregunta.id, texto="B", es_correcta=False, orden=2))
    db.session.commit()
    return ev


def _sesion(ev, codigo, estado="cerrada", umbral=60):
    abierta = _ahora() - timedelta(hours=2)
    s = Sesion(
        evaluacion_id=ev.id,
        codigo=codigo,
        estado=estado,
        umbral_aprobacion=umbral,
        abierta_at=abierta,
        cerrada_at=abierta + timedelta(hours=1) if estado == "cerrada" else None,
    )
    db.session.add(s)
    db.session.commit()
    return s


def _participacion(sesion, hash_id, nombre, puntaje, total, porcentaje, nota, aprobado):
    p = Participante(
        sesion_id=sesion.id,
        identificador_hash=hash_id,
        nombre=nombre,
        ingreso_at=_ahora() - timedelta(minutes=30),
        finalizado_at=_ahora() - timedelta(minutes=20),
    )
    db.session.add(p)
    db.session.flush()
    db.session.add(
        Resultado(
            participante_id=p.id,
            puntaje=puntaje,
            total_preguntas=total,
            porcentaje=porcentaje,
            nota=nota,
            aprobado=aprobado,
            evaluacion_titulo=sesion.evaluacion.titulo,
            umbral_aprobacion=sesion.umbral_aprobacion,
        )
    )
    db.session.commit()
    return p


def test_las_vistas_existen_tras_create_all(app):
    """Las pruebas levantan el esquema con create_all, no con migraciones.

    Si este test falla, el listener after_create de app/vistas.py no se
    registro y las vistas existirian solo en produccion.
    """
    assert resumen_de(999) is None  # no explota: la vista existe, la sesion no


def test_historial_reune_sesiones_distintas_de_la_misma_persona(app, facilitador):
    hash_id = "a" * 64
    ev1 = _evaluacion(facilitador, "Prevencion de riesgos")
    ev2 = _evaluacion(facilitador, "Datos personales", umbral=70)
    s1 = _sesion(ev1, "AAA111")
    s2 = _sesion(ev2, "BBB222", umbral=70)

    _participacion(s1, hash_id, "Luis Munoz", 8, 10, 80.0, 5.6, True)
    _participacion(s2, hash_id, "L. Munoz", 6, 10, 60.0, 3.7, False)

    filas = historial_de(hash_id, facilitador.id)

    assert len(filas) == 2
    titulos = {f["evaluacion_titulo"] for f in filas}
    assert titulos == {"Prevencion de riesgos", "Datos personales"}
    # El umbral viaja con cada fila justamente porque puede diferir entre
    # sesiones: por eso el historial se compara por porcentaje y no por nota.
    assert {f["umbral_aprobacion"] for f in filas} == {60, 70}


def test_historial_excluye_sesiones_abiertas(app, facilitador):
    hash_id = "b" * 64
    ev = _evaluacion(facilitador)
    abierta = _sesion(ev, "CCC333", estado="abierta")
    _participacion(abierta, hash_id, "Ana Rojas", 9, 10, 90.0, 6.4, True)

    assert historial_de(hash_id, facilitador.id) == []


def test_historial_respeta_la_propiedad_del_facilitador(app, facilitador):
    """V-11: un facilitador no puede ver participaciones de otro."""
    from app.models import Facilitador

    otro = Facilitador(email="otro@fuenti.cl", nombre="Otro")
    otro.set_password("clave-de-prueba")
    db.session.add(otro)
    db.session.commit()

    hash_id = "c" * 64
    ev = _evaluacion(facilitador)
    s = _sesion(ev, "DDD444")
    _participacion(s, hash_id, "Carla Perez", 7, 10, 70.0, 4.5, True)

    assert len(historial_de(hash_id, facilitador.id)) == 1
    assert historial_de(hash_id, otro.id) == []


def test_resumen_coincide_con_el_calculo_en_python(app, facilitador):
    """La vista debe dar lo mismo que agregar las filas en memoria."""
    ev = _evaluacion(facilitador)
    s = _sesion(ev, "EEE555")
    _participacion(s, "d" * 64, "Uno", 8, 10, 80.0, 5.6, True)
    _participacion(s, "e" * 64, "Dos", 5, 10, 50.0, 3.5, False)
    _participacion(s, "f" * 64, "Tres", 10, 10, 100.0, 7.0, True)

    fila = resumen_de(s.id)

    resultados = [p.resultado for p in s.participantes if p.resultado]
    esperado_promedio = round(sum(r.nota for r in resultados) / len(resultados), 1)

    assert fila["ingresados"] == 3
    assert fila["finalizados"] == 3
    assert fila["aprobados"] == 2
    assert float(fila["nota_promedio"]) == pytest.approx(esperado_promedio)
    assert float(fila["logro_promedio"]) == pytest.approx(76.7, abs=0.1)


def test_resumen_incluye_sesion_sin_participantes(app, facilitador):
    """Una sesion recien abierta debe aparecer en el panel con cero, no faltar."""
    ev = _evaluacion(facilitador)
    s = _sesion(ev, "FFF666", estado="abierta")

    fila = resumen_de(s.id)

    assert fila is not None
    assert fila["ingresados"] == 0
    assert fila["finalizados"] == 0
    assert fila["nota_promedio"] is None


def test_resumen_cuenta_ingresados_sin_resultado(app, facilitador):
    """Quien entro pero no envio cuenta como ingresado y no como finalizado."""
    ev = _evaluacion(facilitador)
    s = _sesion(ev, "GGG777", estado="abierta")
    db.session.add(
        Participante(sesion_id=s.id, identificador_hash="0" * 64, nombre="Sin enviar")
    )
    db.session.commit()

    fila = resumen_de(s.id)

    assert fila["ingresados"] == 1
    assert fila["finalizados"] == 0
