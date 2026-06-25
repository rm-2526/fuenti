import secrets


# Alfabeto sin caracteres ambiguos: sin 0, 1, O, I, L.
# Pensado para que el codigo se pueda dictar o copiar sin confusiones.
_ALFABETO_CODIGO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_LONGITUD_CODIGO = 6


def generar_codigo_sesion() -> str:
    """Genera un codigo aleatorio de 6 caracteres usando un alfabeto sin
    caracteres ambiguos (sin 0, 1, O, I, L).

    No verifica unicidad contra la BD: el caller (blueprint) es responsable
    de reintentar si hay colision. Misma logica que con hash_rut: la funcion
    queda pura y testeable sin app context.
    """
    return "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(_LONGITUD_CODIGO))