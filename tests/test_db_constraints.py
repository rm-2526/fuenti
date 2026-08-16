"""Pruebas de las restricciones declarativas del esquema (I6).

Estas pruebas no pasan por el controlador a proposito: escriben directo contra
la base. Esa es justamente la via que las restricciones tienen que cubrir, la
que queda abierta cuando el bug esta en el codigo de aplicacion o cuando alguien
corre un script de mantencion a mano.

Si una de estas pruebas falla con 'IntegrityError no fue lanzado', significa que
la restriccion no llego a la base: en produccion, que la migracion no se aplico;
en local, que falta en __table_args__.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import Evaluacion, Participante, Pregunta, Resultado, Sesion


def _ahora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _evaluacion(facilitador, umbral=60):
    ev = Evaluacion(
        facilitador_id=facilitador.id, titulo="Evaluacion", umbral_aprobacion=umbral
    )
    db.session.add(ev)
    db.session.commit()
    return ev


def _sesion(ev, codigo="ZZZ999"):
    s = Sesion(
        evaluacion_id=ev.id,
        codigo=codigo,
        estado="abierta",
        umbral_aprobacion=60,
        abierta_at=_ahora(),
    )
    db.session.add(s)
    db.session.commit()
    return s


def _participante(sesion, hash_id="1" * 64):
    p = Participante(sesion_id=sesion.id, identificador_hash=hash_id, nombre="Prueba")
    db.session.add(p)
    db.session.commit()
    return p


# ---------------------------------------------------------------------------
# Umbral y tipo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("umbral", [-1, 101, 150])
def test_umbral_de_evaluacion_fuera_de_rango(app, facilitador, umbral):
    db.session.add(
        Evaluacion(
            facilitador_id=facilitador.id, titulo="Mala", umbral_aprobacion=umbral
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_tipo_de_pregunta_no_soportado(app, facilitador):
    ev = _evaluacion(facilitador)
    db.session.add(
        Pregunta(
            evaluacion_id=ev.id, enunciado="Desarrolle", orden=1, tipo="desarrollo"
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_estado_de_sesion_no_contemplado(app, facilitador):
    """El diagrama de estados tiene dos estados. No hay un tercero."""
    ev = _evaluacion(facilitador)
    db.session.add(
        Sesion(
            evaluacion_id=ev.id,
            codigo="PAUSA1",
            estado="pausada",
            umbral_aprobacion=60,
            abierta_at=_ahora(),
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# Coherencia temporal
# ---------------------------------------------------------------------------

def test_cierre_anterior_a_la_apertura(app, facilitador):
    ev = _evaluacion(facilitador)
    ahora = _ahora()
    db.session.add(
        Sesion(
            evaluacion_id=ev.id,
            codigo="TIEMP1",
            estado="cerrada",
            umbral_aprobacion=60,
            abierta_at=ahora,
            cerrada_at=ahora - timedelta(hours=1),
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_finalizacion_anterior_al_ingreso(app, facilitador):
    s = _sesion(_evaluacion(facilitador))
    ahora = _ahora()
    db.session.add(
        Participante(
            sesion_id=s.id,
            identificador_hash="2" * 64,
            nombre="Viajero del tiempo",
            ingreso_at=ahora,
            finalizado_at=ahora - timedelta(minutes=5),
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# Calificacion: el dato con valor probatorio
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nota", [0.9, 7.1, 12.0])
def test_nota_fuera_de_la_escala_chilena(app, facilitador, nota):
    p = _participante(_sesion(_evaluacion(facilitador)))
    db.session.add(
        Resultado(
            participante_id=p.id,
            puntaje=5,
            total_preguntas=10,
            porcentaje=50.0,
            nota=nota,
            aprobado=False,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_puntaje_mayor_que_el_total_de_preguntas(app, facilitador):
    """11 aciertos sobre 10 preguntas es aritmeticamente imposible."""
    p = _participante(_sesion(_evaluacion(facilitador)))
    db.session.add(
        Resultado(
            participante_id=p.id,
            puntaje=11,
            total_preguntas=10,
            porcentaje=100.0,
            nota=7.0,
            aprobado=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_porcentaje_fuera_de_rango(app, facilitador):
    p = _participante(_sesion(_evaluacion(facilitador)))
    db.session.add(
        Resultado(
            participante_id=p.id,
            puntaje=10,
            total_preguntas=10,
            porcentaje=120.0,
            nota=7.0,
            aprobado=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_resultado_valido_se_persiste(app, facilitador):
    """Contraprueba: las restricciones no deben bloquear lo legitimo."""
    p = _participante(_sesion(_evaluacion(facilitador)))
    db.session.add(
        Resultado(
            participante_id=p.id,
            puntaje=8,
            total_preguntas=10,
            porcentaje=80.0,
            nota=5.6,
            aprobado=True,
            evaluacion_titulo="Evaluacion",
            umbral_aprobacion=60,
        )
    )
    db.session.commit()

    assert db.session.get(Resultado, 1).nota == 5.6


def test_umbral_nulo_en_resultado_antiguo_es_valido(app, facilitador):
    """Los resultados anteriores a la migracion del umbral no lo tienen."""
    p = _participante(_sesion(_evaluacion(facilitador)))
    db.session.add(
        Resultado(
            participante_id=p.id,
            puntaje=6,
            total_preguntas=10,
            porcentaje=60.0,
            nota=4.0,
            aprobado=True,
            umbral_aprobacion=None,
        )
    )
    db.session.commit()

    assert db.session.get(Resultado, 1).umbral_aprobacion is None
