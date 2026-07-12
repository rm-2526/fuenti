"""Tests del helper puro de reporteria (app/utils/reporte.py).

Sin BD ni app context: se le pasan objetos livianos (SimpleNamespace) con los
mismos atributos que tendrian los objetos reales (Participante, Resultado,
Pregunta, Alternativa).
"""

from types import SimpleNamespace

from app.utils.reporte import (
    ENCABEZADOS_CSV,
    SIN_NOMBRE,
    SIN_RESPUESTA,
    desglose_desde_respuestas,
    foto_de_respuesta,
    filas_csv_sesion,
    filas_informe_sesion,
)


def _part(id, nombre, hash_, resultado):
    return SimpleNamespace(
        id=id, nombre=nombre, identificador_hash=hash_, resultado=resultado
    )


def _res(nota, porcentaje, aprobado):
    return SimpleNamespace(nota=nota, porcentaje=porcentaje, aprobado=aprobado)


# ------------------------- filas_informe_sesion -------------------------

def test_filas_grupo_vacio():
    assert filas_informe_sesion([]) == []


def test_filas_mezcla_finalizado_y_pendiente():
    ps = [
        _part(10, "Ana Soto", "abcdef0123456789", _res(7.0, 100.0, True)),
        _part(11, "Beto Diaz", "zzz", None),  # ingreso pero no finalizo
    ]
    filas = filas_informe_sesion(ps)

    assert filas[0].id == 10
    assert filas[0].orden == 1
    assert filas[0].nombre == "Ana Soto"
    assert filas[0].hash_corto == "abcdef0123"      # primeros 10 caracteres
    assert filas[0].finalizado is True
    assert filas[0].estado == "Finalizado"
    assert filas[0].nota == 7.0
    assert filas[0].aprobado is True

    assert filas[1].orden == 2
    assert filas[1].finalizado is False
    assert filas[1].estado == "Pendiente"
    assert filas[1].nota is None
    assert filas[1].porcentaje is None
    assert filas[1].aprobado is None


def test_filas_nombre_vacio_o_none_muestra_sin_nombre():
    ps = [
        _part(1, None, "h1", None),
        _part(2, "   ", "h2", None),   # solo espacios
    ]
    filas = filas_informe_sesion(ps)
    assert filas[0].nombre == SIN_NOMBRE
    assert filas[1].nombre == SIN_NOMBRE


# ----------------------------- CSV -----------------------------

def test_csv_encabezados():
    assert ENCABEZADOS_CSV[0] == "Orden"
    assert "Nombre" in ENCABEZADOS_CSV
    assert "Aprobado" in ENCABEZADOS_CSV


def test_csv_finalizado_aprobado_y_reprobado():
    ps = [
        _part(1, "Ana", "h1", _res(7.0, 100.0, True)),
        _part(2, "Beto", "h2", _res(2.0, 20.0, False)),
    ]
    filas = filas_csv_sesion(ps)
    assert filas[0] == ["1", "Ana", "h1", "Finalizado", "7.0", "100.0", "Si"]
    assert filas[1][-1] == "No"


def test_csv_pendiente_deja_columnas_vacias():
    ps = [_part(1, "Ana", "h1", None)]
    fila = filas_csv_sesion(ps)[0]
    assert fila[3] == "Pendiente"
    assert fila[4] == ""   # nota
    assert fila[5] == ""   # % de logro
    assert fila[6] == ""   # aprobado


# ----------------------- foto_de_respuesta (snapshot) -----------------------

def _pregunta(id, orden, enunciado, alternativas):
    return SimpleNamespace(
        id=id, orden=orden, enunciado=enunciado, alternativas=alternativas
    )


def _alt(id, texto, es_correcta):
    return SimpleNamespace(id=id, texto=texto, es_correcta=es_correcta)


def test_foto_congela_los_textos_al_elegir_incorrecta():
    a_ok = _alt(1, "4", True)
    a_mal = _alt(2, "5", False)
    p = _pregunta(100, 1, "¿2+2?", [a_ok, a_mal])

    foto = foto_de_respuesta(p, a_mal)   # eligio la incorrecta
    assert foto["enunciado_texto"] == "¿2+2?"
    assert foto["elegida_texto"] == "5"
    assert foto["correcta_texto"] == "4"
    assert foto["acerto"] is False
    assert foto["orden"] == 1


def test_foto_marca_acierto_al_elegir_correcta():
    a_ok = _alt(1, "4", True)
    a_mal = _alt(2, "5", False)
    p = _pregunta(100, 1, "¿2+2?", [a_ok, a_mal])

    foto = foto_de_respuesta(p, a_ok)    # eligio la correcta
    assert foto["acerto"] is True
    assert foto["elegida_texto"] == "4"
    assert foto["correcta_texto"] == "4"


# -------------------- desglose_desde_respuestas (lee la foto) --------------------

def _resp(orden, enunciado, elegida, correcta, acerto):
    """Respuesta liviana con solo la foto congelada (lo que lee el desglose)."""
    return SimpleNamespace(
        orden=orden,
        enunciado_texto=enunciado,
        elegida_texto=elegida,
        correcta_texto=correcta,
        acerto=acerto,
    )


def test_desglose_desde_respuestas_ordena_y_marca():
    # Llegan desordenadas: deben salir por orden ascendente.
    respuestas = [
        _resp(2, "¿Capital de Chile?", "Santiago", "Santiago", True),
        _resp(1, "¿2+2?", "5", "4", False),
    ]
    lineas = desglose_desde_respuestas(respuestas)

    assert [l.orden for l in lineas] == [1, 2]
    assert lineas[0].enunciado == "¿2+2?"
    assert lineas[0].elegida == "5"
    assert lineas[0].correcta == "4"
    assert lineas[0].acerto is False
    assert lineas[1].acerto is True


def test_desglose_desde_respuestas_sin_texto_elegida_muestra_sin_respuesta():
    # Defensa: si por lo que sea no hay texto elegido, se marca sin respuesta.
    lineas = desglose_desde_respuestas([_resp(1, "¿2+2?", None, "4", False)])
    assert lineas[0].elegida == SIN_RESPUESTA
    assert lineas[0].acerto is False
