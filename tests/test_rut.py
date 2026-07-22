import pytest
from app.utils.rut import (
    RUTS_BLOQUEADOS,
    es_rut_bloqueado,
    hash_rut,
    normalizar_rut,
    validar_rut,
)


# Salt fijo para tests. No depende de la config de Flask para que estos
# tests sean unitarios puros (no requieren app context).
SALT_TEST = "salt-de-prueba-fijo"


# === Normalización ===

def test_normalizar_quita_puntos_y_guion():
    assert normalizar_rut("11.111.111-1") == "111111111"


def test_normalizar_pasa_k_a_mayuscula():
    assert normalizar_rut("17012345-k") == "17012345K"


def test_normalizar_quita_espacios():
    assert normalizar_rut(" 12345678-5 ") == "123456785"


# === Validación ===

def test_validar_rut_correcto_sin_formato():
    assert validar_rut("111111111") is True


def test_validar_rut_correcto_con_formato():
    assert validar_rut("11.111.111-1") is True


def test_validar_rut_con_dv_k():
    assert validar_rut("17.012.345-K") is True


def test_validar_rut_con_dv_incorrecto():
    assert validar_rut("11.111.111-2") is False


def test_validar_rut_con_letras_en_cuerpo():
    assert validar_rut("ABCDEFGH-1") is False


def test_validar_rut_vacio():
    assert validar_rut("") is False


# === Hash ===

def test_hash_es_deterministico_aunque_cambie_el_formato():
    h1 = hash_rut("11.111.111-1", SALT_TEST)
    h2 = hash_rut("111111111", SALT_TEST)
    assert h1 == h2


def test_hash_de_ruts_distintos_es_distinto():
    h1 = hash_rut("11.111.111-1", SALT_TEST)
    h2 = hash_rut("12.345.678-5", SALT_TEST)
    assert h1 != h2


def test_hash_de_rut_invalido_lanza_error():
    with pytest.raises(ValueError):
        hash_rut("11.111.111-2", SALT_TEST)


def test_hash_tiene_64_caracteres_hex():
    h = hash_rut("11.111.111-1", SALT_TEST)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_con_distintos_salts_da_distintos_resultados():
    """El mismo RUT con dos salts distintos debe producir hashes distintos.
    Esto garantiza que el salt efectivamente entra en el calculo."""
    h1 = hash_rut("11.111.111-1", "salt-uno")
    h2 = hash_rut("11.111.111-1", "salt-dos")
    assert h1 != h2


def test_hash_con_salt_vacio_lanza_error():
    """Defensa: si en algun deploy se olvida setear RUT_SALT y queda string vacio,
    queremos que reviente, no que silenciosamente hashee sin salt."""
    with pytest.raises(ValueError):
        hash_rut("11.111.111-1", "")

# === RUT bloqueados ===
# Ojo con la division de trabajo: validar_rut responde "el DV calza" y
# es_rut_bloqueado responde "lo aceptamos como persona". Son preguntas
# distintas y por eso viven en funciones distintas.

def test_los_bloqueados_pasan_modulo_11():
    """Si alguno NO pasara modulo 11, sobraria en la lista: validar_rut ya lo
    estaria rechazando antes y la entrada seria puro ruido."""
    for rut in RUTS_BLOQUEADOS:
        assert validar_rut(rut) is True, rut


def test_bloqueado_reconoce_los_de_la_lista():
    for rut in ["11.111.111-1", "22.222.222-2", "33.333.333-3",
                "12.345.678-5", "1-9", "0-0", "99.999.999-9"]:
        assert es_rut_bloqueado(rut) is True, rut


def test_bloqueado_ignora_el_formato():
    """Con puntos, sin puntos o con espacios: es el mismo RUT."""
    assert es_rut_bloqueado("11111111-1") is True
    assert es_rut_bloqueado("111111111") is True
    assert es_rut_bloqueado("  11.111.111-1  ") is True


def test_un_rut_normal_no_esta_bloqueado():
    assert es_rut_bloqueado("15.432.198-5") is False


def test_bloqueado_no_revienta_con_basura():
    assert es_rut_bloqueado("") is False
    assert es_rut_bloqueado(None) is False


def test_validar_rut_no_sabe_de_la_lista():
    """validar_rut sigue siendo aritmetica pura: el bloqueo es politica y no
    debe filtrarse hacia adentro de ella. Este test es el que se pone rojo si
    alguien 'simplifica' metiendo la lista dentro de validar_rut."""
    assert validar_rut("11.111.111-1") is True


def test_hash_rut_sigue_hasheando_un_bloqueado():
    """hash_rut no filtra por politica: su contrato es 'RUT bien formado'. Quien
    decide si se acepta la identidad es la ruta de ingreso, no el hasher."""
    assert len(hash_rut("11.111.111-1", SALT_TEST)) == 64
