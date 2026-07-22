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


# ---------------------------------------------------------------------------
# RUT bloqueados como identidad de un participante
# ---------------------------------------------------------------------------
# Modulo 11 es un digito de control, no un registro: verifica que el DV calce,
# no que el RUT exista ni que sea de quien lo escribio. Todos los de esta lista
# PASAN modulo 11; se rechazan por decision de producto, porque son los que se
# tipean cuando alguien quiere saltarse el formulario, y un RUT falso no queda
# como un dato malo: queda como una PERSONA que no existe en el historial
# longitudinal (la identidad es el hash del RUT).
#
# La lista va normalizada (sin puntos ni guion, K mayuscula) porque se compara
# contra normalizar_rut(). Agregar o quitar uno es una linea.
#
# Riesgo asumido, documentado a proposito. El Registro Civil asigna el RUN a
# personas naturales en forma secuencial desde el 1, y va bastante mas arriba de
# los 20 millones, asi que tres de estos caen DENTRO del rango efectivamente
# asignado y podrian pertenecer a una persona real y viva:
#   - 11111111-1  (cuerpo ~11 millones)
#   - 12345678-5  (cuerpo ~12 millones)
#   - 22222222-2  (cuerpo ~22 millones)
# Si esa persona llega a una sesion, no puede ingresar y el facilitador no tiene
# como anularlo. Se acepta el costo: la probabilidad es minima y la alternativa
# —dejar entrar identidades fantasma— ensucia en silencio lo que mas importa.
# Los otros cuatro son estructuralmente seguros: 0-0 no es una persona, 1-9 esta
# en el piso historico del rango, y 33333333-3 / 99999999-9 estan por encima de
# lo asignado a personas naturales (99.999.999 es, de hecho, el rango que usan
# los generadores de RUT de prueba justamente porque no le corresponde a nadie).
# Ojo: 33333333-3 sera un RUT real algun dia, cuando la numeracion llegue ahi.
RUTS_BLOQUEADOS = frozenset(
    {
        "00",          # 0-0
        "19",          # 1-9
        "111111111",   # 11.111.111-1
        "222222222",   # 22.222.222-2
        "333333333",   # 33.333.333-3
        "123456785",   # 12.345.678-5
        "999999999",   # 99.999.999-9
        "444444460",   # 44.444.446-0: placeholder que el SII usa para receptor
                       # extranjero sin RUT chileno. No lo pediste; se puede
                       # borrar esta linea sin tocar nada mas.
    }
)


def es_rut_bloqueado(rut: str) -> bool:
    """
    True si el RUT esta en la lista de RUT no aceptados como identidad de un
    participante. Acepta el RUT con o sin formato.

    Deliberadamente SEPARADA de validar_rut(): validar_rut responde "el DV
    calza", que es una propiedad aritmetica y no cambia. Esto responde "lo
    aceptamos como persona", que es politica de producto y va a cambiar. Mantener
    las dos preguntas aparte deja intactos los tests de validar_rut y hace obvio,
    al leer el codigo, cual de las dos rechazo el ingreso.

    No decide sola: el caller chequea primero validar_rut (formato) y despues
    esta (politica), para poder dar dos mensajes distintos.
    """
    try:
        return normalizar_rut(rut) in RUTS_BLOQUEADOS
    except TypeError:
        return False


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