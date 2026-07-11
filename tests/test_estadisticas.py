"""Tests del helper puro de estadisticas de sesion (resumir_resultados).

Sin BD, sin app context: se le pasan objetos livianos con .nota, .porcentaje
y .aprobado, igual que test_calificacion.py prueba el calculo de nota solo.

Casos:
- Grupo vacio (nadie finalizo): promedios None, sin dividir entre cero.
- Ingresaron pero nadie finalizo: se cuentan como pendientes.
- Todos aprobados / todos reprobados.
- Mezcla: conteos, porcentajes y promedios.
- Pendientes: ingresaron mas de los que finalizaron.
- Defensa: pendientes nunca es negativo.
"""

from collections import namedtuple

from app.utils.estadisticas import resumir_resultados


# Stand-in liviano de un Resultado: solo los campos que el helper lee.
R = namedtuple("R", ["nota", "porcentaje", "aprobado"])


def test_grupo_vacio_no_divide_entre_cero():
    resumen = resumir_resultados([], total_participantes=0)
    assert resumen.total_participantes == 0
    assert resumen.total_finalizados == 0
    assert resumen.pendientes == 0
    assert resumen.aprobados == 0
    assert resumen.reprobados == 0
    assert resumen.promedio_nota is None
    assert resumen.promedio_logro is None
    assert resumen.porcentaje_aprobados == 0.0
    assert resumen.porcentaje_reprobados == 0.0


def test_ingresaron_pero_nadie_finalizo():
    resumen = resumir_resultados([], total_participantes=3)
    assert resumen.total_participantes == 3
    assert resumen.total_finalizados == 0
    assert resumen.pendientes == 3
    assert resumen.promedio_nota is None


def test_todos_aprobados():
    resultados = [R(7.0, 100.0, True), R(6.0, 80.0, True)]
    resumen = resumir_resultados(resultados, total_participantes=2)
    assert resumen.total_finalizados == 2
    assert resumen.aprobados == 2
    assert resumen.reprobados == 0
    assert resumen.porcentaje_aprobados == 100.0
    assert resumen.porcentaje_reprobados == 0.0
    assert resumen.promedio_nota == 6.5   # (7.0 + 6.0) / 2
    assert resumen.promedio_logro == 90.0  # (100 + 80) / 2


def test_todos_reprobados():
    resultados = [R(2.0, 20.0, False), R(3.0, 40.0, False)]
    resumen = resumir_resultados(resultados, total_participantes=2)
    assert resumen.aprobados == 0
    assert resumen.reprobados == 2
    assert resumen.porcentaje_aprobados == 0.0
    assert resumen.porcentaje_reprobados == 100.0
    assert resumen.promedio_nota == 2.5


def test_mezcla_de_aprobados_y_reprobados():
    resultados = [
        R(7.0, 100.0, True),
        R(4.0, 60.0, True),
        R(2.0, 20.0, False),
    ]
    resumen = resumir_resultados(resultados, total_participantes=3)
    assert resumen.total_finalizados == 3
    assert resumen.aprobados == 2
    assert resumen.reprobados == 1
    # 2/3 = 66.66... -> 66.7 ; 1/3 = 33.33... -> 33.3
    assert resumen.porcentaje_aprobados == 66.7
    assert resumen.porcentaje_reprobados == 33.3
    # (7.0 + 4.0 + 2.0) / 3 = 4.33... -> 4.3
    assert resumen.promedio_nota == 4.3
    # (100 + 60 + 20) / 3 = 60.0
    assert resumen.promedio_logro == 60.0


def test_pendientes_cuando_ingresaron_mas_de_los_que_finalizaron():
    """Alguien ingreso y no termino: se cuenta como pendiente y no entra al
    promedio."""
    resultados = [R(7.0, 100.0, True)]
    resumen = resumir_resultados(resultados, total_participantes=4)
    assert resumen.total_participantes == 4
    assert resumen.total_finalizados == 1
    assert resumen.pendientes == 3
    assert resumen.promedio_nota == 7.0  # solo sobre el que finalizo


def test_pendientes_no_es_negativo():
    """Defensa: si por lo que sea llegan mas resultados que participantes
    declarados, pendientes no baja de cero."""
    resultados = [R(7.0, 100.0, True), R(6.0, 80.0, True)]
    resumen = resumir_resultados(resultados, total_participantes=1)
    assert resumen.pendientes == 0
