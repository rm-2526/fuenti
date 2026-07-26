"""Análisis de fortalezas y debilidades a partir de la foto congelada.

Dos capas separadas a propósito (misma filosofía que estadisticas.py y
reporte.py):

1. AGREGACIÓN PURA (este módulo): cuenta aciertos y errores desde la foto
   congelada y arma un resumen estructurado + el PROMPT para el modelo. Sin BD,
   sin red, sin IA. Es lo testeable y lo reproducible.
2. NARRATIVA (app/utils/gemini.py): toma el prompt que sale de acá y le pide a
   Gemini un texto. Es lo único impuro; degrada a None si falla.

PRIVACIDAD (regla dura, alineada con §3.1): el prompt que produce este módulo
NUNCA incluye el nombre ni el identificador_hash del participante. El modelo no
los necesita para describir fortalezas y debilidades, y el tier gratis de Gemini
puede usar los prompts para entrenar. Las funciones de acá ni siquiera reciben
esos datos: solo textos de preguntas, aciertos, porcentaje, umbral y stats del
grupo. El nombre se pega en la plantilla, del lado de Fuenti.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResumenAnalisisPersona:
    """Desempeño individual ya reducido a lo que necesita el prompt.

    Solo contenido de la evaluación y números; sin identidad de la persona.
    """
    porcentaje: float
    umbral: int | None
    aprobado: bool
    acertadas: list[str]          # enunciados respondidos correctamente
    falladas: list[str]           # enunciados respondidos incorrectamente
    promedio_logro_grupo: float | None  # para contextualizar; None si no aplica


@dataclass(frozen=True)
class PreguntaSesion:
    enunciado: str
    aciertos: int
    total: int
    porcentaje_acierto: float     # 0-100, 1 decimal


@dataclass(frozen=True)
class ResumenAnalisisSesion:
    """Desempeño del grupo ya reducido a lo que necesita el prompt."""
    total_finalizados: int
    aprobados: int
    reprobados: int
    promedio_logro: float | None
    # Preguntas ordenadas de la MÁS fallada a la menos fallada por el grupo.
    preguntas: list[PreguntaSesion]


def resumen_persona(
    desglose,
    porcentaje: float,
    umbral: int | None,
    aprobado: bool,
    promedio_logro_grupo: float | None = None,
) -> ResumenAnalisisPersona:
    """Reduce el desglose pregunta-por-pregunta de una persona a un resumen.

    Args:
        desglose: iterable de objetos con .enunciado (str) y .acerto (bool). En
            el flujo real son LineaDesglose (app.utils.reporte); en tests,
            cualquier objeto liviano con esos atributos.
        porcentaje: % de logro del participante.
        umbral: umbral de aprobación aplicado (de la foto congelada); puede ser
            None si un resultado antiguo no lo guardó.
        aprobado: si aprobó.
        promedio_logro_grupo: promedio de % de logro del grupo, para contexto.

    Puro: no toca la BD ni la red. No recibe ni el nombre ni el hash.
    """
    acertadas = [l.enunciado for l in desglose if l.acerto]
    falladas = [l.enunciado for l in desglose if not l.acerto]
    return ResumenAnalisisPersona(
        porcentaje=porcentaje,
        umbral=umbral,
        aprobado=aprobado,
        acertadas=acertadas,
        falladas=falladas,
        promedio_logro_grupo=promedio_logro_grupo,
    )


def resumen_sesion(
    desgloses,
    aprobados: int = 0,
    reprobados: int = 0,
    promedio_logro: float | None = None,
) -> ResumenAnalisisSesion:
    """Agrega los desgloses de todos los finalizados en un resumen del grupo.

    Args:
        desgloses: iterable de desgloses individuales; cada uno es un iterable
            de objetos con .enunciado (str) y .acerto (bool). El orden de las
            preguntas se toma del primer desglose que las contiene.
        aprobados, reprobados, promedio_logro: números del grupo que la ruta ya
            calculó con resumir_resultados (estadisticas.py); se pasan tal cual
            para no recalcularlos ni tocar la BD desde acá.

    Cuenta, por enunciado, cuántos acertaron sobre cuántos lo respondieron, y
    ordena de la más fallada a la menos fallada (a igualdad, alfabético por
    enunciado, para que el orden sea estable). Puro.
    """
    orden = []                 # preserva el orden de aparición de los enunciados
    aciertos: dict[str, int] = {}
    totales: dict[str, int] = {}
    total_finalizados = 0

    for desglose in desgloses:
        total_finalizados += 1
        for l in desglose:
            if l.enunciado not in totales:
                orden.append(l.enunciado)
                totales[l.enunciado] = 0
                aciertos[l.enunciado] = 0
            totales[l.enunciado] += 1
            if l.acerto:
                aciertos[l.enunciado] += 1

    preguntas = []
    for enunciado in orden:
        total = totales[enunciado]
        ok = aciertos[enunciado]
        pct = round(ok / total * 100, 1) if total else 0.0
        preguntas.append(
            PreguntaSesion(
                enunciado=enunciado,
                aciertos=ok,
                total=total,
                porcentaje_acierto=pct,
            )
        )

    # Más fallada primero: menor % de acierto primero; desempate alfabético.
    preguntas.sort(key=lambda p: (p.porcentaje_acierto, p.enunciado))

    return ResumenAnalisisSesion(
        total_finalizados=total_finalizados,
        aprobados=aprobados,
        reprobados=reprobados,
        promedio_logro=promedio_logro,
        preguntas=preguntas,
    )


def _lista(enunciados) -> str:
    if not enunciados:
        return "  (ninguna)"
    return "\n".join(f"  - {e}" for e in enunciados)


def prompt_persona(resumen: ResumenAnalisisPersona) -> str:
    """Arma el prompt para el análisis individual. Texto plano, español.

    No incluye nombre ni hash: solo desempeño y contenido de la evaluación.
    """
    umbral_txt = f"{resumen.umbral}%" if resumen.umbral is not None else "no registrado"
    estado = "aprobó" if resumen.aprobado else "reprobó"
    contexto_grupo = ""
    if resumen.promedio_logro_grupo is not None:
        contexto_grupo = (
            f"\nEl promedio de logro del grupo fue "
            f"{resumen.promedio_logro_grupo}%."
        )

    return (
        "Eres un evaluador pedagógico. A partir del siguiente desempeño en una "
        "evaluación de capacitación, redacta un análisis breve (2 a 4 frases) de "
        "las fortalezas y debilidades de la persona y cierra con una "
        "recomendación concreta de estudio. Escribe en español, en tercera "
        "persona, en texto plano (sin viñetas ni markdown) y sin inventar datos "
        "que no aparezcan aquí.\n\n"
        f"Porcentaje de logro: {resumen.porcentaje}% "
        f"(umbral de aprobación: {umbral_txt}). La persona {estado}."
        f"{contexto_grupo}\n\n"
        "Preguntas respondidas correctamente:\n"
        f"{_lista(resumen.acertadas)}\n\n"
        "Preguntas respondidas incorrectamente:\n"
        f"{_lista(resumen.falladas)}\n"
    )


def prompt_sesion(resumen: ResumenAnalisisSesion) -> str:
    """Arma el prompt para el análisis del grupo. Texto plano, español."""
    promedio_txt = (
        f"{resumen.promedio_logro}%"
        if resumen.promedio_logro is not None
        else "no disponible"
    )
    lineas = [
        f"  - {p.enunciado} — {p.porcentaje_acierto}% de acierto "
        f"({p.aciertos}/{p.total})"
        for p in resumen.preguntas
    ]
    detalle = "\n".join(lineas) if lineas else "  (sin preguntas)"

    return (
        "Eres un evaluador pedagógico. A partir del desempeño AGREGADO de un "
        "grupo en una evaluación de capacitación, redacta un análisis breve (2 a "
        "4 frases): qué temas domina el grupo, qué preguntas concentran los "
        "errores y una recomendación de refuerzo para la próxima sesión. Escribe "
        "en español, en texto plano (sin viñetas ni markdown) y sin inventar "
        "datos que no aparezcan aquí.\n\n"
        f"Participantes que finalizaron: {resumen.total_finalizados} "
        f"({resumen.aprobados} aprobados, {resumen.reprobados} reprobados). "
        f"Promedio de logro: {promedio_txt}.\n\n"
        "Preguntas ordenadas de la más fallada a la menos fallada:\n"
        f"{detalle}\n"
    )
