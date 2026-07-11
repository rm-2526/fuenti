"""Helper puro de estadisticas de una sesion: agrega los resultados
individuales en un resumen del grupo.

Sin BD, sin app context. Misma filosofia que rut.py, sesion.py y
calificacion.py: la logica pura vive aca y es testeable sola; el endpoint
consulta la base de datos y le pasa los datos ya listos.

Distingue dos cosas que NO son lo mismo:
- participantes que INGRESARON (entraron con su RUT).
- participantes que FINALIZARON (ya tienen resultado calculado).

Los promedios y la distribucion aprobados/reprobados se calculan solo sobre
los que finalizaron, para que quien ingreso y no termino no altere el promedio.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResumenSesion:
    total_participantes: int      # cuantos ingresaron
    total_finalizados: int        # cuantos tienen resultado
    pendientes: int               # ingresaron pero no finalizaron
    aprobados: int
    reprobados: int
    porcentaje_aprobados: float   # sobre finalizados, 1 decimal
    porcentaje_reprobados: float  # sobre finalizados, 1 decimal
    promedio_nota: float | None   # sobre finalizados, 1 decimal; None si no hay
    promedio_logro: float | None  # promedio de % de logro, 1 decimal; None si no hay


def resumir_resultados(resultados, total_participantes: int) -> ResumenSesion:
    """Agrega una lista de resultados individuales en un resumen del grupo.

    Args:
        resultados: iterable de objetos con atributos .nota (float),
            .porcentaje (float) y .aprobado (bool). En el flujo real son
            objetos Resultado ya cargados; en tests, cualquier objeto liviano
            con esos atributos.
        total_participantes: cuantos participantes ingresaron a la sesion.
            Normalmente >= cantidad de resultados (alguien pudo ingresar y no
            terminar).

    Es defensiva con el borde de grupo vacio (nadie finalizo): promedios None
    y porcentajes 0.0, para no dividir entre cero.
    """
    resultados = list(resultados)
    total_finalizados = len(resultados)
    pendientes = max(total_participantes - total_finalizados, 0)

    aprobados = sum(1 for r in resultados if r.aprobado)
    reprobados = total_finalizados - aprobados

    if total_finalizados == 0:
        return ResumenSesion(
            total_participantes=total_participantes,
            total_finalizados=0,
            pendientes=pendientes,
            aprobados=0,
            reprobados=0,
            porcentaje_aprobados=0.0,
            porcentaje_reprobados=0.0,
            promedio_nota=None,
            promedio_logro=None,
        )

    porcentaje_aprobados = aprobados / total_finalizados * 100
    porcentaje_reprobados = reprobados / total_finalizados * 100
    promedio_nota = sum(r.nota for r in resultados) / total_finalizados
    promedio_logro = sum(r.porcentaje for r in resultados) / total_finalizados

    return ResumenSesion(
        total_participantes=total_participantes,
        total_finalizados=total_finalizados,
        pendientes=pendientes,
        aprobados=aprobados,
        reprobados=reprobados,
        porcentaje_aprobados=round(porcentaje_aprobados, 1),
        porcentaje_reprobados=round(porcentaje_reprobados, 1),
        promedio_nota=round(promedio_nota, 1),
        promedio_logro=round(promedio_logro, 1),
    )
