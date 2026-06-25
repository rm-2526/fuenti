"""Tests del helper puro de generacion de codigos de sesion."""

from app.utils.sesion import generar_codigo_sesion


_ALFABETO_ESPERADO = set("23456789ABCDEFGHJKMNPQRSTUVWXYZ")


def test_codigo_tiene_longitud_correcta():
    assert len(generar_codigo_sesion()) == 6


def test_codigo_solo_usa_alfabeto_seguro():
    """Verifica que no aparezcan caracteres ambiguos (0, 1, O, I, L)
    ni caracteres fuera del alfabeto definido."""
    codigo = generar_codigo_sesion()
    for char in codigo:
        assert char in _ALFABETO_ESPERADO, f"Caracter inesperado: {char!r}"


def test_codigo_no_contiene_caracteres_ambiguos():
    """Test explicito de la propiedad principal del alfabeto: queremos
    que dictar el codigo por chat o telefono no genere confusiones."""
    codigo = generar_codigo_sesion()
    for char in "01OIL":
        assert char not in codigo


def test_genera_codigos_validos_en_serie():
    """Genera 50 codigos y verifica que todos cumplan el contrato.
    No es un test de unicidad estricta (eso se prueba contra la BD),
    pero detecta bugs tipo 'no estoy llamando secrets.choice bien'."""
    for _ in range(50):
        codigo = generar_codigo_sesion()
        assert len(codigo) == 6
        assert all(c in _ALFABETO_ESPERADO for c in codigo)