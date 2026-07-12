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
    desglose_individual,
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


# ----------------------- desglose_individual -----------------------

def _pregunta(id, orden, enunciado, alternativas):
    return SimpleNamespace(
        id=id, orden=orden, enunciado=enunciado, alternativas=alternativas
    )


def _alt(id, texto, es_correcta):
    return SimpleNamespace(id=id, texto=texto, es_correcta=es_correcta)


def test_desglose_marca_acierto_y_error():
    a_ok = _alt(1, "4", True)
    a_mal = _alt(2, "5", False)
    p = _pregunta(100, 1, "¿2+2?", [a_ok, a_mal])

    # Eligio la incorrecta
    linea = desglose_individual([p], {100: 2})[0]
    assert linea.orden == 1
    assert linea.enunciado == "¿2+2?"
    assert linea.elegida == "5"
    assert linea.correcta == "4"
    assert linea.acerto is False

    # Eligio la correcta
    linea = desglose_individual([p], {100: 1})[0]
    assert linea.acerto is True


def test_desglose_pregunta_sin_respuesta():
    a_ok = _alt(1, "4", True)
    p = _pregunta(100, 1, "¿2+2?", [a_ok])

    linea = desglose_individual([p], {})[0]   # no la respondio
    assert linea.elegida == SIN_RESPUESTA
    assert linea.acerto is False
    assert linea.correcta == "4"
