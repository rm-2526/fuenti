import hashlib


def normalizar_rut(rut: str) -> str:
    """
    Normaliza un RUT removiendo puntos, guion y espacios.
    Convierte el dígito verificador K a mayúscula.

    Ejemplo: "11.111.111-1" -> "111111111"
             "12345678-k"   -> "12345678K"
    """
    if not isinstance(rut, str):
        raise TypeError("El RUT debe ser un string")
    limpio = rut.replace(".", "").replace("-", "").replace(" ", "")
    return limpio.upper()


def validar_rut(rut: str) -> bool:
    """
    Valida un RUT chileno usando el algoritmo módulo 11.
    Acepta el RUT con o sin formato. Devuelve True si es válido.
    """
    try:
        rut_norm = normalizar_rut(rut)
    except TypeError:
        return False

    # Debe tener al menos 2 caracteres (1 dígito de cuerpo + DV)
    if len(rut_norm) < 2:
        return False

    cuerpo = rut_norm[:-1]
    dv = rut_norm[-1]

    # El cuerpo debe ser solo dígitos
    if not cuerpo.isdigit():
        return False

    # El DV debe ser un dígito o K
    if not (dv.isdigit() or dv == "K"):
        return False

    # Algoritmo módulo 11
    suma = 0
    multiplicador = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador
        multiplicador += 1
        if multiplicador > 7:
            multiplicador = 2

    resto = suma % 11
    dv_calculado = 11 - resto

    if dv_calculado == 11:
        dv_esperado = "0"
    elif dv_calculado == 10:
        dv_esperado = "K"
    else:
        dv_esperado = str(dv_calculado)

    return dv == dv_esperado


def hash_rut(rut: str, salt: str) -> str:
    """
    Devuelve el hash SHA-256 del RUT normalizado concatenado con un salt,
    en hexadecimal. Lanza ValueError si el RUT no es valido.

    El salt se pasa explicitamente por argumento (no se lee de config aqui)
    para que la funcion sea pura y facil de testear. Los callers (blueprints,
    scripts) son responsables de leer el salt desde current_app.config["RUT_SALT"]
    y pasarlo aca.
    """
    if not validar_rut(rut):
        raise ValueError(f"RUT invalido: {rut}")

    if not isinstance(salt, str) or salt == "":
        raise ValueError("El salt debe ser un string no vacio")

    rut_norm = normalizar_rut(rut)
    return hashlib.sha256((salt + rut_norm).encode("utf-8")).hexdigest()