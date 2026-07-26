"""Wrapper mínimo de la API de Gemini (Google AI Studio).

Es la ÚNICA parte del análisis que toca la red. Todo lo demás (agregación y
prompts) vive en app/utils/analisis.py y es puro y testeable. Acá adentro:

- Usa solo la librería estándar (urllib), para no sumar dependencias al proyecto
  —misma línea que el resto (segno es la única lib "de más")—.
- Degrada a None ante CUALQUIER problema (sin API key, timeout, error HTTP,
  respuesta con formato inesperado). El caller trata None como "sin análisis" y
  el informe se muestra igual con los números. Nunca lanza hacia arriba: cerrar
  la sesión no puede fallar porque la IA falle.

PRIVACIDAD: este módulo manda el prompt tal cual se lo pasan. La garantía de que
el prompt no lleva nombre ni hash está en analisis.py, que es quien lo arma.
"""

import json
import urllib.parse
import urllib.request
import urllib.error

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Tier gratis: Flash/Flash-Lite (los modelos Pro salieron del gratis en 2026).
# Se puede pisar con la variable de entorno GEMINI_MODEL sin tocar código.
MODELO_POR_DEFECTO = "gemini-2.5-flash"


def generar_texto(
    prompt: str,
    api_key: str | None,
    modelo: str = MODELO_POR_DEFECTO,
    timeout: int = 30,
) -> str | None:
    """Pide a Gemini una respuesta de texto para 'prompt'. None si algo falla.

    No lanza excepciones: cualquier problema se traduce en None.
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

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        import logging
        cuerpo = e.read().decode("utf-8", "replace")
        logging.getLogger("gemini").warning(
            "GEMINI HTTPError %s: %s", e.code, cuerpo[:800]
        )
        return None
    except Exception as e:
        import logging
        logging.getLogger("gemini").warning("GEMINI error: %r", e)
        return None

    return _extraer_texto(datos)


def _extraer_texto(datos) -> str | None:
    """Saca el texto del primer candidato. None si el formato no es el esperado."""
    try:
        partes = datos["candidates"][0]["content"]["parts"]
        texto = "".join(p.get("text", "") for p in partes).strip()
    except (KeyError, IndexError, TypeError):
        import logging
        logging.getLogger("gemini").warning("GEMINI respuesta sin texto: %r", datos)
        return None
    return texto or None
