"""Helpers puros de reporteria por participante.

Arman las filas del informe del facilitador (lista por participante y
exportacion CSV) y el desglose pregunta-por-pregunta del informe individual.

Sin BD, sin app context. Misma filosofia que rut.py, calificacion.py y
estadisticas.py: la logica pura vive aca y es testeable sola; la ruta consulta
la base de datos y le pasa objetos ya cargados.

Privacidad: el facilitador nunca ve el RUT. Cada participante se identifica por
su nombre (etiqueta legible) y un prefijo de su hash (identificador tecnico
estable, que ademas sirve para el historial longitudinal entre sesiones).
"""

from dataclasses import dataclass


LARGO_HASH_CORTO = 10
SIN_NOMBRE = "(sin nombre)"
SIN_RESPUESTA = "(sin respuesta)"


@dataclass(frozen=True)
class FilaParticipante:
    id: int                    # id del Participante (para enlazar a su informe)
    orden: int                 # posicion en la lista (por orden de ingreso)
    nombre: str                # etiqueta legible; SIN_NOMBRE si no tiene
    hash_corto: str            # primeros caracteres del hash (identificador tecnico)
    finalizado: bool
    estado: str                # "Finalizado" | "Pendiente"
    nota: float | None         # None si no finalizo
    porcentaje: float | None   # None si no finalizo
    aprobado: bool | None      # None si no finalizo


@dataclass(frozen=True)
class LineaDesglose:
    orden: int
    enunciado: str
    elegida: str        # texto de la alternativa elegida; SIN_RESPUESTA si no
    correcta: str       # texto de la alternativa correcta
    acerto: bool


def _nombre_legible(nombre) -> str:
    """Nombre limpio, o SIN_NOMBRE si viene vacio o None.

    Los participantes que ingresaron ANTES de que el nombre fuera obligatorio
    no tienen nombre; se muestran como SIN_NOMBRE para no dejar la celda vacia.
    """
    if nombre is None:
        return SIN_NOMBRE
    limpio = nombre.strip()
    return limpio if limpio else SIN_NOMBRE


def _hash_corto(identificador_hash) -> str:
    return (identificador_hash or "")[:LARGO_HASH_CORTO]


def filas_informe_sesion(participantes) -> list[FilaParticipante]:
    """Arma una fila por participante, en el orden recibido.

    Cada participante es un objeto con .nombre, .identificador_hash y .resultado
    (None si no finalizo; si finalizo, un objeto con .nota, .porcentaje y
    .aprobado). El caller normalmente los pasa ordenados por ingreso.
    """
    filas = []
    for orden, p in enumerate(participantes, start=1):
        r = p.resultado
        finalizado = r is not None
        filas.append(
            FilaParticipante(
                id=p.id,
                orden=orden,
                nombre=_nombre_legible(p.nombre),
                hash_corto=_hash_corto(p.identificador_hash),
                finalizado=finalizado,
                estado="Finalizado" if finalizado else "Pendiente",
                nota=r.nota if finalizado else None,
                porcentaje=r.porcentaje if finalizado else None,
                aprobado=r.aprobado if finalizado else None,
            )
        )
    return filas


# ----------------------------- Exportacion CSV -----------------------------

ENCABEZADOS_CSV = [
    "Orden",
    "Nombre",
    "Hash",
    "Estado",
    "Nota",
    "% de logro",
    "Aprobado",
]


def _texto_aprobado(aprobado) -> str:
    if aprobado is None:
        return ""
    return "Si" if aprobado else "No"


def filas_csv_sesion(participantes) -> list[list[str]]:
    """Filas de datos para el CSV (sin la cabecera; esa es ENCABEZADOS_CSV).

    Incluye a TODOS los participantes (finalizados y pendientes). Para los
    pendientes, las columnas de nota / % de logro / aprobado van vacias.
    """
    filas = []
    for f in filas_informe_sesion(participantes):
        filas.append(
            [
                str(f.orden),
                f.nombre,
                f.hash_corto,
                f.estado,
                "" if f.nota is None else f"{f.nota:.1f}",
                "" if f.porcentaje is None else f"{f.porcentaje:.1f}",
                _texto_aprobado(f.aprobado),
            ]
        )
    return filas


# -------------------------- Desglose individual --------------------------

def desglose_individual(preguntas, elegidas) -> list[LineaDesglose]:
    """Arma el detalle pregunta-por-pregunta del informe individual.

    Args:
        preguntas: iterable de preguntas ordenadas. Cada una con .enunciado,
            .orden y .alternativas (cada alternativa con .id, .texto,
            .es_correcta).
        elegidas: dict {pregunta.id: alternativa_id_elegida}. Si una pregunta
            no esta en el dict, se marca como sin respuesta.

    Devuelve una linea por pregunta con el texto elegido, el correcto y si
    acerto. No toca la BD.
    """
    lineas = []
    for pregunta in preguntas:
        correcta = next((a for a in pregunta.alternativas if a.es_correcta), None)
        correcta_texto = correcta.texto if correcta is not None else ""

        elegida_id = elegidas.get(pregunta.id)
        elegida = next(
            (a for a in pregunta.alternativas if a.id == elegida_id), None
        )
        elegida_texto = elegida.texto if elegida is not None else SIN_RESPUESTA
        acerto = elegida is not None and elegida.es_correcta

        lineas.append(
            LineaDesglose(
                orden=pregunta.orden,
                enunciado=pregunta.enunciado,
                elegida=elegida_texto,
                correcta=correcta_texto,
                acerto=acerto,
            )
        )
    return lineas
