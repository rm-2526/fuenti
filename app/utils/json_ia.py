"""Lectura tolerante del JSON que devuelve un asistente de IA.

Por que existe este modulo:

El facilitador copia la respuesta de ChatGPT / Claude / Gemini y la pega en el
formulario de importacion. Ese texto casi nunca es JSON limpio, y el motivo mas
comun no es que la IA se equivoque, sino la forma en que la interfaz de chat
renderiza el texto:

- Si el modelo escribe el JSON como texto suelto (no dentro de un bloque de
  codigo), tiende a escapar los simbolos que Markdown/LaTeX interpretarian:
  devuelve \\[ y \\] en vez de [ y ], y a veces \\" en vez de ". En JSON esa
  barra invertida no es valida y json.loads falla.
- Al copiar desde el chat viajan tambien las tres comillas invertidas del bloque
  de codigo, la palabra "json" de la primera linea, alguna frase de cortesia
  antes o despues, espacios duros (U+00A0) y comillas tipograficas.

En vez de exigirle al facilitador que limpie el texto a mano, la app lo limpia:
`leer_json_ia` intenta parsear, y si falla aplica reparaciones acumulativas de a
una, reintentando despues de cada una. Cada reparacion solo se da por buena si
el texto resultante PARSEA; una reparacion que rompe el texto no puede colarse
como resultado, porque el intento simplemente sigue fallando.

El modulo es puro (sin Flask, sin BD), igual que calificacion.py o rut.py, y se
testea solo.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LecturaJson:
    """Resultado de leer un texto pegado.

    datos:   el objeto ya parseado (None si no se pudo leer).
    texto:   el texto que conviene devolver al textarea. Si hubo reparaciones es
             el JSON ya normalizado, para que el facilitador vea con que se
             trabajo; si no hubo, es su texto tal cual.
    ajustes: descripciones cortas de lo que se corrigio, para avisarle.
    error:   mensaje en español listo para flash, o None si se pudo leer.
    """

    datos: Any = None
    texto: str = ""
    ajustes: tuple = ()
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def leer_json_ia(texto: str) -> LecturaJson:
    """Parsea `texto` como JSON tolerando la basura tipica de un chat de IA."""
    candidato = texto or ""

    ok, datos, err = _cargar(candidato)
    if ok:
        return _resultado(datos, candidato, [])

    aplicados = []
    for etiqueta, reparar in _REPARACIONES:
        reparado = reparar(candidato)
        if reparado == candidato:
            continue
        candidato = reparado
        aplicados.append(etiqueta)
        ok, datos, error_nuevo = _cargar(candidato)
        if ok:
            return _resultado(datos, candidato, aplicados)
        err = error_nuevo

    # Ultimo recurso: la IA devolvio un dict de Python (comillas simples,
    # True/False/None). literal_eval es seguro: solo evalua literales.
    datos = _via_literal_eval(candidato)
    if datos is not None:
        aplicados.append("se convirtió la sintaxis de Python a JSON")
        return _resultado(datos, candidato, aplicados)

    return LecturaJson(
        texto=texto or "",
        ajustes=tuple(aplicados),
        error=_mensaje_error(err, candidato),
    )


# -------------------- parseo y resultado --------------------

def _cargar(texto):
    """json.loads envuelto: (ok, datos, excepcion)."""
    try:
        return True, json.loads(texto), None
    except ValueError as exc:  # JSONDecodeError hereda de ValueError
        return False, None, exc


def _resultado(datos, texto, aplicados):
    """Arma la LecturaJson final: desdobla el JSON doblemente codificado y, si
    hubo reparaciones, devuelve el texto ya normalizado."""
    datos, extra = _desdoblar(datos)
    # Una misma correccion puede intentarse por dos caminos (por ejemplo, la
    # sintaxis de Python). Al facilitador se le nombra una sola vez.
    aplicados = list(dict.fromkeys(list(aplicados) + extra))

    if aplicados and isinstance(datos, (dict, list)):
        texto = json.dumps(datos, ensure_ascii=False, indent=2)

    return LecturaJson(datos=datos, texto=texto, ajustes=tuple(aplicados))


def _desdoblar(datos):
    """Si el JSON resulto ser un texto que a su vez contiene JSON, lo abre.

    Pasa cuando alguien copia el JSON ya serializado dentro de otro campo, o
    cuando el modelo devuelve la respuesta entre comillas.
    """
    ajustes = []
    for _ in range(3):  # tope defensivo: nunca hay mas de un nivel en la practica
        if not isinstance(datos, str):
            break
        ok, interno, _ = _cargar(datos)
        if not ok or not isinstance(interno, (dict, list)):
            break
        datos = interno
        ajustes.append("se abrió el JSON que venía dentro de un texto")
    return datos, ajustes


# -------------------- reparaciones --------------------

# Caracteres que se cuelan al copiar desde un navegador y que JSON no acepta
# donde deberia haber un espacio normal.
_INVISIBLES = {
    "\ufeff": "",   # BOM
    "\u200b": "",   # espacio de ancho cero
    "\u200c": "",
    "\u200d": "",
    "\u2060": "",
    "\u00a0": " ",  # espacio duro
    "\u202f": " ",
    "\u2007": " ",
    "\u2009": " ",
}


def _normalizar_invisibles(texto):
    t = texto.replace("\r\n", "\n").replace("\r", "\n")
    for original, reemplazo in _INVISIBLES.items():
        t = t.replace(original, reemplazo)
    return t


_LINEA_CERCA = re.compile(r"^[ \t]*```[A-Za-z0-9_+-]*[ \t]*$", re.MULTILINE)
_BLOQUE = re.compile(
    r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\n(.*?)(?:\n[ \t]*```|\Z)", re.DOTALL
)


def _extraer_bloque_codigo(texto):
    """Se queda con el contenido del bloque ```...``` que contiene el JSON.

    Si hay varios bloques, gana el primero que empiece en { o en [. Si las
    comillas invertidas quedaron sueltas (respuesta cortada, por ejemplo), al
    menos se borran las lineas de cerca.
    """
    if "```" not in texto:
        return texto

    for coincidencia in _BLOQUE.finditer(texto):
        cuerpo = coincidencia.group(1).strip()
        if cuerpo.startswith(("{", "[")):
            return cuerpo

    return _LINEA_CERCA.sub("", texto)


# Los unicos escapes que JSON admite despues de una barra invertida.
_ESCAPES_VALIDOS = set('"\\/bfnrt')
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")


def _quitar_escapes_invalidos(texto):
    """Borra las barras invertidas que Markdown/LaTeX agrega y JSON rechaza.

    Convierte \\[ en [ , \\_ en _ , \\* en * , etc. Deja intactos los escapes
    que JSON si entiende (\\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX), asi que un
    salto de linea o una comilla escapada legitimamente no se tocan.
    """
    salida = []
    i = 0
    n = len(texto)
    while i < n:
        caracter = texto[i]
        if caracter != "\\":
            salida.append(caracter)
            i += 1
            continue

        siguiente = texto[i + 1] if i + 1 < n else ""
        if siguiente in _ESCAPES_VALIDOS and siguiente:
            salida.append(caracter)
            salida.append(siguiente)
            i += 2
            continue
        if siguiente == "u" and _HEX4.fullmatch(texto[i + 2:i + 6] or ""):
            salida.append(texto[i:i + 6])
            i += 6
            continue

        # Escape de Markdown (o barra suelta al final): se descarta la barra y
        # se conserva el caracter, que se procesa en la vuelta siguiente.
        i += 1

    return "".join(salida)


def _desescapar_comillas(texto):
    """Caso "todo el JSON viene escapado": {\\"preguntas\\": [...]}.

    Solo actua si TODAS las comillas del texto estan escapadas; si hay una
    mezcla, la comilla escapada es parte de un enunciado y no se toca.
    """
    escapadas = texto.count('\\"')
    if escapadas and texto.count('"') == escapadas:
        return texto.replace('\\"', '"')
    return texto


# En JSON toda comilla de apertura viene despues de { [ , o : y toda comilla de
# cierre va antes de : , } o ]. Por eso se pueden enderezar las comillas
# tipograficas que hacen de delimitador sin tocar las que estan dentro de un
# enunciado (esas nunca quedan pegadas a un simbolo de estructura).
_COMILLA_ABRE = re.compile(r'(^\s*|[\{\[,:]\s*)[\u201c\u201d\u201e\u201f\u00ab\u2039]')
_COMILLA_CIERRA = re.compile(r'[\u201c\u201d\u201f\u00bb\u203a](\s*[:,\}\]]|\s*$)')


def _comillas_rectas(texto):
    t = _COMILLA_ABRE.sub(lambda m: m.group(1) + '"', texto)
    return _COMILLA_CIERRA.sub(lambda m: '"' + m.group(1), t)


def _quitar_comas_finales(texto):
    """Borra la coma que queda antes de } o de ] (JSON no la admite).

    Recorre el texto sabiendo cuando esta dentro de una cadena, para no borrar
    una coma que forme parte de un enunciado.
    """
    salida = []
    en_cadena = False
    i = 0
    n = len(texto)
    while i < n:
        caracter = texto[i]

        if en_cadena:
            salida.append(caracter)
            if caracter == "\\" and i + 1 < n:
                salida.append(texto[i + 1])
                i += 2
                continue
            if caracter == '"':
                en_cadena = False
            i += 1
            continue

        if caracter == '"':
            en_cadena = True
            salida.append(caracter)
            i += 1
            continue

        if caracter == ",":
            j = i + 1
            while j < n and texto[j] in " \t\n":
                j += 1
            if j < n and texto[j] in "}]":
                i += 1  # coma sobrante: se descarta
                continue

        salida.append(caracter)
        i += 1

    return "".join(salida)


_LITERAL_PYTHON = re.compile(r"([:\[,]\s*)(True|False|None)\b")
_EQUIVALENTE_JSON = {"True": "true", "False": "false", "None": "null"}


def _literales_python(texto):
    return _LITERAL_PYTHON.sub(
        lambda m: m.group(1) + _EQUIVALENTE_JSON[m.group(2)], texto
    )


def _recortar_al_json(texto):
    """Descarta lo que haya antes y despues del JSON ("Aquí tienes...", etc.)."""
    posiciones = [p for p in (texto.find("{"), texto.find("[")) if p != -1]
    if not posiciones:
        return texto
    inicio = min(posiciones)

    fin = _fin_balanceado(texto, inicio)
    if fin is None:
        cierre = "}" if texto[inicio] == "{" else "]"
        fin = texto.rfind(cierre)
        if fin < inicio:
            return texto

    return texto[inicio:fin + 1]


def _fin_balanceado(texto, inicio):
    """Indice del cierre que equilibra la llave/corchete que abre en `inicio`."""
    pares = {"{": "}", "[": "]"}
    pila = []
    en_cadena = False
    i = inicio
    n = len(texto)

    while i < n:
        caracter = texto[i]
        if en_cadena:
            if caracter == "\\":
                i += 2
                continue
            if caracter == '"':
                en_cadena = False
        elif caracter == '"':
            en_cadena = True
        elif caracter in pares:
            pila.append(pares[caracter])
        elif caracter in "}]":
            if not pila or caracter != pila.pop():
                return None
            if not pila:
                return i
        i += 1

    return None


def _via_literal_eval(texto):
    """Interpreta un dict/list de Python ('clave': True) como estructura.

    ast.literal_eval NO ejecuta codigo: solo acepta literales. Se devuelve None
    si no se puede, o si el resultado no es un objeto ni una lista.
    """
    convertido = re.sub(r"([:\[,]\s*)true\b", r"\1True", texto)
    convertido = re.sub(r"([:\[,]\s*)false\b", r"\1False", convertido)
    convertido = re.sub(r"([:\[,]\s*)null\b", r"\1None", convertido)
    try:
        datos = ast.literal_eval(convertido.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return datos if isinstance(datos, (dict, list)) else None


# El orden importa: primero se saca el envoltorio del chat (invisibles, bloque
# de codigo, escapes de Markdown) y recien despues se recorta y se afinan los
# detalles de sintaxis, ya sobre un texto limpio.
_REPARACIONES = (
    ("se quitaron espacios y caracteres invisibles", _normalizar_invisibles),
    ("se extrajo el bloque de código ```json", _extraer_bloque_codigo),
    ("se quitaron las barras invertidas de más (\\[ , \\_)", _quitar_escapes_invalidos),
    ("se desescaparon las comillas", _desescapar_comillas),
    ("se descartó el texto que rodeaba al JSON", _recortar_al_json),
    ("se enderezaron las comillas tipográficas", _comillas_rectas),
    ("se quitaron comas sobrantes antes de } o ]", _quitar_comas_finales),
    ("se convirtió la sintaxis de Python a JSON", _literales_python),
)


# -------------------- mensaje de error --------------------

# json.JSONDecodeError habla en ingles y con jerga. Se traduce a algo que le
# sirva a quien pego el texto, no a quien programa.
_TRADUCCIONES = (
    (
        "Expecting property name enclosed in double quotes",
        "se esperaba el nombre de un campo entre comillas dobles",
    ),
    ("Expecting ',' delimiter", "falta una coma entre dos elementos"),
    ("Expecting ':' delimiter", "falta el «:» entre un campo y su valor"),
    (
        "Expecting value",
        "se esperaba un valor (revisa si hay una coma de más o una comilla sin cerrar)",
    ),
    ("Unterminated string", "hay un texto entre comillas que nunca se cierra"),
    ("Invalid \\escape", "hay una barra invertida (\\) mal usada"),
    ("Invalid control character", "hay un carácter de control dentro de un texto"),
    ("Extra data", "hay texto de más después del JSON"),
    ("Expecting object or array", "el contenido no empieza con { ni con ["),
)


def _mensaje_error(exc, texto):
    """Arma el aviso que se muestra: que pasa, donde, y con que fragmento."""
    base = "El texto pegado no es un JSON válido"

    detalle = ""
    mensaje_original = getattr(exc, "msg", "") or str(exc or "")
    for patron, traduccion in _TRADUCCIONES:
        if patron in mensaje_original:
            detalle = traduccion
            break

    ubicacion = ""
    linea = getattr(exc, "lineno", None)
    columna = getattr(exc, "colno", None)
    if linea and columna:
        ubicacion = f" (línea {linea}, columna {columna})"

    partes = [base]
    if detalle:
        partes.append(f": {detalle}{ubicacion}.")
    elif ubicacion:
        partes.append(f"{ubicacion}.")
    else:
        partes.append(".")

    fragmento = _fragmento(texto, getattr(exc, "pos", None))
    if fragmento:
        partes.append(f" Cerca de: «{fragmento}».")

    partes.append(
        " Pega la respuesta de la IA completa, incluida la línea ```json: "
        "el resto lo limpiamos nosotros."
    )
    return "".join(partes)


def _fragmento(texto, posicion, contexto=35):
    """Trozo de una linea alrededor del punto del error, para ubicarse rapido."""
    if not texto or posicion is None:
        return ""
    inicio = max(0, posicion - contexto)
    fin = min(len(texto), posicion + contexto)
    trozo = re.sub(r"\s+", " ", texto[inicio:fin]).strip()
    if not trozo:
        return ""
    if inicio > 0:
        trozo = "…" + trozo
    if fin < len(texto):
        trozo = trozo + "…"
    return trozo
