"""Tests del helper puro de calificacion.

Escala chilena con eje en el umbral: la nota 4.0 cae exactamente en el umbral.
No requieren app context ni BD (el helper es puro).
"""

from app.utils.calificacion import calcular_calificacion


def test_puntaje_en_el_umbral_da_nota_4_y_aprueba():
    c = calcular_calificacion(puntaje=6, total=10, umbral=60)
    assert c.porcentaje == 60.0
    assert c.nota == 4.0
    assert c.aprobado is True


def test_puntaje_perfecto_da_nota_7():
    c = calcular_calificacion(puntaje=10, total=10, umbral=60)
    assert c.porcentaje == 100.0
    assert c.nota == 7.0
    assert c.aprobado is True


def test_puntaje_cero_da_nota_1_y_reprueba():
    c = calcular_calificacion(puntaje=0, total=10, umbral=60)
    assert c.porcentaje == 0.0
    assert c.nota == 1.0
    assert c.aprobado is False


def test_justo_bajo_el_umbral_reprueba():
    # 5/10 = 50% < 60% umbral
    c = calcular_calificacion(puntaje=5, total=10, umbral=60)
    assert c.porcentaje == 50.0
    assert c.aprobado is False
    assert c.nota < 4.0


def test_tramo_inferior_es_lineal():
    # 30% con umbral 60% -> 1.0 + (30/60)*3 = 2.5
    c = calcular_calificacion(puntaje=3, total=10, umbral=60)
    assert c.nota == 2.5
    assert c.aprobado is False


def test_tramo_superior_es_lineal():
    # 80% con umbral 60% -> 4.0 + ((80-60)/40)*3 = 5.5
    c = calcular_calificacion(puntaje=8, total=10, umbral=60)
    assert c.nota == 5.5
    assert c.aprobado is True


def test_nota_redondeada_a_un_decimal():
    # 70% con umbral 60 -> 4.0 + (10/40)*3 = 4.75 -> 4.8
    c = calcular_calificacion(puntaje=7, total=10, umbral=60)
    assert c.nota == 4.8


def test_borde_umbral_100_solo_perfecto_aprueba():
    aprob = calcular_calificacion(puntaje=4, total=4, umbral=100)
    assert aprob.nota == 7.0
    assert aprob.aprobado is True

    reprob = calcular_calificacion(puntaje=3, total=4, umbral=100)
    assert reprob.aprobado is False
    assert reprob.nota < 4.0


def test_borde_umbral_0_todo_aprueba():
    # 0% con umbral 0 cae en el tramo superior con base 4.0
    c = calcular_calificacion(puntaje=0, total=10, umbral=0)
    assert c.aprobado is True
    assert c.nota == 4.0


def test_borde_total_cero_no_explota():
    c = calcular_calificacion(puntaje=0, total=0, umbral=60)
    assert c.porcentaje == 0.0
    assert c.aprobado is False
