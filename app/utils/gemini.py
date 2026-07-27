"""Wrapper mínimo de la API de Gemini (Google AI Studio).

Es la ÚNICA parte del análisis que toca la red. Todo lo demás (agregación y
prompts) vive en app/utils/analisis.py y es puro y testeable. Acá adentro:

- Usa solo la librería estándar (urllib), para no sumar dependencias al proyecto
  —misma línea que el resto (segno es la única lib "de más")—.
- Degrada a None ante CUALQUIER problema (sin API key, timeout, error HTTP,
  respuesta con formato inesperado). El caller trata None como "sin análisis" y
  el informe se muestra igual con los números. Nunca lanza hacia arriba.
- REINTENTA con espera creciente (backoff) SOLO cuando el problema es de ritmo o
  transitorio: HTTP 429 (te pasaste del límite por minuto), HTTP 503 (servicio
  ocupado) y cortes de red. Los errores de configuración (404 de modelo, 400/403
  de key) NO se reintentan: esperar no los arregla, así que devuelve None de una.

PRIVACIDAD: este módulo manda el prompt tal cual se lo pasan. La garantía de que
el prompt no lleva nombre ni hash está en analisis.py, que es quien lo arma.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Tier gratis: Flash/Flash-Lite (los modelos Pro salieron del gratis en 2026).
# 'gemini-flash-latest' es un alias que Google mantiene apuntando al Flash
# vigente, así no hay que cambiar código cada vez que jubilan un ID de modelo.
# Se puede pisar con la variable de entorno GEMINI_MODEL sin tocar código.
MODELO_POR_DEFECTO = "gemini-flash-latest"

# Códigos HTTP que SÍ vale la pena reintentar: límite por minuto y servicio
# ocupado. Son transitorios; con una espera corta suelen resolverse. El resto
# (400, 401, 403, 404…) es configuración y no se reintenta.
_CODIGOS_REINTENTABLES = frozenset({429, 503})

# Reintentos y espera por defecto. Con 3 intentos y base 2s, las esperas son
# 2s y 4s (6s en el peor caso por llamada). Suficiente para el límite por minuto
# del tier gratis sin alargar demasiado el cierre de sesión.
INTENTOS_POR_DEFECTO = 3
ESPERA_BASE_POR_DEFECTO = 2.0


def generar_texto(
    prompt: str,
    api_key: "str | None",
    modelo: str = MODELO_POR_DEFECTO,
    timeout: int = 30,
    intentos: int = INTENTOS_POR_DEFECTO,
    espera_base: float = ESPERA_BASE_POR_DEFECTO,
    _sleep=time.sleep,
) -> "str | None":
    """Pide a Gemini una respuesta de texto para 'prompt'. None si algo falla.

    No lanza excepciones: cualquier problema se traduce en None. Reintenta con
    backoff ante 429/503 y cortes de red, hasta 'intentos' veces.

    _sleep se inyecta para poder testear el backoff sin esperar de verdad.
    """
    if not api_key or not prompt:
        return None

    url = _ENDPOINT.format(model=modelo) + "?" + urllib.parse.urlencode(
        {"key": api_key}
    )
    cuerpo = json.dumps(
        {"contents": [{"parts": [{"text": prompt}]}]}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=cuerpo,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    for intento in range(intentos):
        es_ultimo = intento == intentos - 1
        try:
            datos = _llamar_api(req, timeout)
        except urllib.error.HTTPError as e:
            # Solo reintenta ritmo/servicio ocupado; lo demás es configuración.
            if e.code in _CODIGOS_REINTENTABLES and not es_ultimo:
                _sleep(espera_base * (2 ** intento))
                continue
            return None
        except urllib.error.URLError:
            # Corte o timeout de red: transitorio, se reintenta.
            if not es_ultimo:
                _sleep(espera_base * (2 ** intento))
                continue
            return None
        except Exception:
            # Cualquier otra cosa (JSON inválido, etc.): no reintentar.
            return None
        return _extraer_texto(datos)

    return None


def _llamar_api(req, timeout):
    """Hace la llamada HTTP y devuelve el JSON parseado. Aislada para testear:
    los tests pueden simular 429 y luego éxito reemplazando esta función.
    """
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extraer_texto(datos) -> "str | None":
    """Saca el texto del primer candidato. None si el formato no es el esperado."""
    try:
        partes = datos["candidates"][0]["content"]["parts"]
        texto = "".join(p.get("text", "") for p in partes).strip()
    except (KeyError, IndexError, TypeError):
        return None
    return texto or None
