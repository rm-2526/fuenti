"""Codigo QR del enlace de una sesion.

Por que en el servidor y no con una libreria JS desde un CDN: generar el QR
cuesta ~6 ms de CPU y viaja dentro del HTML (SVG en linea, cero peticiones
extra). La alternativa por CDN ahorra esos 6 ms pero agrega una peticion a un
dominio de terceros antes de poder dibujar nada. Ademas esta pagina la ve el
FACILITADOR —una persona, un par de veces por sesion—, no los participantes,
asi que la carga de servidor no es un factor.

El QR no tiene ciclo de vida propio: es una imagen del mismo enlace que ya se
muestra al lado. Si la sesion se cierra, el enlace deja de servir y el QR
tambien, sin ninguna expiracion que programar. La plantilla ya lo envuelve en
{% if sesion.estado == "abierta" %}.
"""

import io

import segno


# Nivel de correccion de errores. "m" (~15%) es el estandar: aguanta que el
# codigo se vea algo sucio o torcido sin inflar el tamano del simbolo.
_CORRECCION = "m"

# Pixeles por modulo. Con el largo de URL de Fuenti el simbolo queda de 37x37
# modulos, asi que scale=4 da ~148 px: suficiente para escanear de cerca y sin
# ocupar media pantalla. El tamano final igual lo ajusta el CSS, porque el SVG
# escala sin perder nitidez.
_ESCALA = 4

# Margen blanco alrededor, en modulos. El estandar pide 4; con 2 se ve mas
# compacto y los lectores actuales no tienen problema.
_BORDE = 2


def svg_de_enlace(enlace: str) -> str:
    """
    Devuelve el markup SVG (sin declaracion XML) del QR de `enlace`, listo para
    incrustar dentro del HTML.

    La salida se marca con |safe en la plantilla. Es seguro porque el SVG lo
    genera segno a partir de una URL que arma la propia app con url_for: el
    unico dato variable es el codigo de sesion, que sale de un alfabeto fijo
    (ver app/utils/sesion.py) y no puede contener marcado.
    """
    buffer = io.BytesIO()
    segno.make(enlace, error=_CORRECCION).save(
        buffer,
        kind="svg",
        scale=_ESCALA,
        border=_BORDE,
        xmldecl=False,   # va incrustado en el HTML, no es un archivo aparte
        svgns=False,     # el namespace lo aporta el documento HTML
    )
    return buffer.getvalue().decode("utf-8")
