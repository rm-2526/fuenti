"""Enlaces de activación y restablecimiento de contraseña.

Por qué existe. Hasta aquí el administrador definía la contraseña inicial del
facilitador, de modo que la conocía. Eso impide la separación de credenciales:
quien administra el sistema puede entrar como cualquier facilitador y operar sus
evaluaciones sin dejar rastro de suplantación. Este módulo permite que el
titular establezca su propia clave a través de un enlace firmado, y de paso
resuelve el olvido de contraseña, que antes obligaba al administrador a
reemplazarla (volviendo a conocerla).

Un solo mecanismo, dos flujos. Activación inicial y restablecimiento son la
misma operación: un enlace con vencimiento que habilita fijar una contraseña.
Cambia el punto de entrada, no la máquina.

Un solo uso sin persistencia. El token lleva dentro la "huella" del
password_hash vigente: sus últimos caracteres. Al fijar la contraseña nueva el
hash cambia, la huella deja de coincidir y el token queda muerto. Eso evita una
tabla de tokens emitidos y su purga posterior. El costo es que un enlace se
invalida también si la contraseña cambia por otra vía, lo que es el
comportamiento deseado.

Sin dependencias nuevas. itsdangerous ya viene con Flask (firma la cookie de
sesión) y la clave es la SECRET_KEY que el proyecto ya declara. Ojo con eso:
rotar SECRET_KEY invalida los enlaces pendientes además de cerrar las sesiones
abiertas.

Módulo puro: recibe el secreto como parámetro y no importa Flask ni el ORM, de
modo que se verifica sin contexto de aplicación como el resto de app/utils/.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Namespace de la firma. Aísla estos tokens de cualquier otro uso futuro del
# mismo SECRET_KEY: un token de activación no vale como token de otra cosa.
SAL = "fuenti-activacion"

# Vencimiento del enlace, en segundos. Siete días: suficiente para que una
# invitación sobreviva a un fin de semana largo sin quedar viva para siempre.
ACTIVACION_MAX_AGE = 7 * 24 * 3600

# Cuántos caracteres finales del hash se guardan como huella. 16 basta para que
# la colisión sea irrelevante y mantiene el token corto. No revela la
# contraseña: el hash PBKDF2 ya es irreversible, y esto es solo un fragmento.
LARGO_HUELLA = 16


def _serializador(secreto):
    return URLSafeTimedSerializer(secreto, salt=SAL)


def huella(password_hash):
    """Fragmento del hash que actúa como marca de un solo uso."""
    return password_hash[-LARGO_HUELLA:]


def generar_token(facilitador_id, password_hash, secreto):
    """Devuelve un token firmado para el facilitador indicado.

    El token queda atado al hash vigente al momento de emitirlo.
    """
    carga = {"id": facilitador_id, "h": huella(password_hash)}
    return _serializador(secreto).dumps(carga)


def leer_token(token, secreto, max_age=ACTIVACION_MAX_AGE):
    """Devuelve la carga del token, o None si es inválido, ajeno o vencido.

    No consulta la base: solo verifica firma y vigencia. La comparación de la
    huella contra el hash actual la hace quien llame, porque requiere leer al
    facilitador.
    """
    try:
        carga = _serializador(secreto).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None

    # Defensa ante un token bien firmado pero con estructura inesperada.
    if not isinstance(carga, dict) or "id" not in carga or "h" not in carga:
        return None
    return carga
