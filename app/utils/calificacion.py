"""Helper puro de calificacion: convierte puntaje bruto en porcentaje, nota
y aprobado.

Sin BD, sin app context. Misma filosofia que rut.py y sesion.py: la logica
pura vive aca y es testeable sola; el endpoint maneja la persistencia.

Escala de nota chilena con eje en el umbral (escala de exigencia):
- La nota 4.0 cae EXACTAMENTE en el umbral de aprobacion.
- Dos tramos lineales:
    porcentaje >= umbral  ->  4.0 .. 7.0
    porcentaje <  umbral  ->  1.0 .. 4.0
- 'aprobado' se define sobre el porcentaje (no sobre la nota redondeada)
  para que nunca haya un "3.95 que aprobo".
"""

from dataclasses import dataclass


NOTA_MINIMA = 1.0
NOTA_APROBACION = 4.0
NOTA_MAXIMA = 7.0


@dataclass(frozen=True)
class Calificacion:
    porcentaje: float  # 0.0 - 100.0, redondeado a 2 decimales
    nota: float        # 1.0 - 7.0, redondeado a 1 decimal
    aprobado: bool


def calcular_calificacion(puntaje: int, total: int, umbral: int) -> Calificacion:
    """Calcula porcentaje, nota (escala 1.0-7.0 con eje en el umbral) y aprobado.

    Args:
        puntaje: cantidad de respuestas correctas.
        total: cantidad total de preguntas (>= 1 en el flujo real).
        umbral: porcentaje de aprobacion 0-100 (Evaluacion.umbral_aprobacion).

    La funcion es defensiva con los bordes (total=0, umbral=0, umbral=100)
    para no explotar, aunque en el flujo real total>=1 y 0<=umbral<=100.
    """
    porcentaje = (puntaje / total * 100) if total > 0 else 0.0
    aprobado = porcentaje >= umbral

    if aprobado:
        # Tramo superior: umbral -> 4.0 ; 100% -> 7.0
        rango = 100 - umbral
        if rango <= 0:
            # umbral == 100: solo el 100% aprueba, y vale 7.0
            nota = NOTA_MAXIMA
        else:
            nota = NOTA_APROBACION + (porcentaje - umbral) / rango * (NOTA_MAXIMA - NOTA_APROBACION)
    else:
        # Tramo inferior: 0% -> 1.0 ; umbral -> 4.0
        # (si umbral <= 0 nunca cae aca, porque porcentaje >= 0 >= umbral)
        nota = NOTA_MINIMA + porcentaje / umbral * (NOTA_APROBACION - NOTA_MINIMA)

    return Calificacion(
        porcentaje=round(porcentaje, 2),
        nota=round(nota, 1),
        aprobado=aprobado,
    )
