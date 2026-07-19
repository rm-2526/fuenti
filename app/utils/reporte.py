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


# -------------------------- Foto congelada (snapshot) --------------------------

def foto_de_respuesta(pregunta, alternativa_elegida) -> dict:
    """Congela (copia) los datos de una respuesta al momento de responder.

    Devuelve un dict con los textos que se guardan en la Respuesta para que el
    resultado no dependa despues de la evaluacion viva. El caller lo usa asi:
    Respuesta(participante_id=..., pregunta_id=..., alternativa_id=..., **foto).

    Args:
        pregunta: la Pregunta respondida, con .enunciado, .orden y
            .alternativas (cada una con .texto y .es_correcta).
        alternativa_elegida: la Alternativa que marco el participante, con
            .texto y .es_correcta.

    Pura: no toca la BD, solo lee atributos de los objetos que recibe.
    """
    correcta = next((a for a in pregunta.alternativas if a.es_correcta), None)
    return {
        "enunciado_texto": pregunta.enunciado,
        "elegida_texto": alternativa_elegida.texto,
        "correcta_texto": correcta.texto if correcta is not None else "",
        "acerto": bool(alternativa_elegida.es_correcta),
        "orden": pregunta.orden,
    }


# -------------------------- Desglose individual --------------------------

def desglose_desde_respuestas(respuestas) -> list[LineaDesglose]:
    """Arma el detalle pregunta-por-pregunta del informe individual leyendo la
    FOTO congelada guardada en cada Respuesta (no la evaluacion viva).

    Args:
        respuestas: iterable de Respuesta. Cada una con la foto guardada:
            .enunciado_texto, .elegida_texto, .correcta_texto, .acerto y .orden.

    Ordena por el campo .orden guardado. Pura: no toca la BD. Como el resultado
    quedo autocontenido, editar la evaluacion despues no altera este desglose.
    """
    def _orden(r):
        return r.orden if r.orden is not None else 0

    lineas = []
    for r in sorted(respuestas, key=_orden):
        lineas.append(
            LineaDesglose(
                orden=_orden(r),
                enunciado=r.enunciado_texto or "",
                elegida=r.elegida_texto or SIN_RESPUESTA,
                correcta=r.correcta_texto or "",
                acerto=bool(r.acerto),
            )
        )
    return lineas

# ----------------------------- Historial por persona -----------------------------

@dataclass(frozen=True)
class FilaHistorial:
    """Una sesión rendida por la persona, dentro de un grupo de evaluación."""
    fecha: object          # datetime de cierre de la sesión (para mostrar)
    codigo: str            # código de la sesión
    porcentaje: float | None
    nota: float | None
    umbral: int
    aprobado: bool | None


@dataclass(frozen=True)
class GrupoHistorial:
    """Todas las sesiones de la persona en UNA evaluación, orden cronológico."""
    evaluacion_titulo: str
    filas: list           # list[FilaHistorial], de la más antigua a la más nueva


def agrupar_historial(resultados_con_contexto) -> list[GrupoHistorial]:
    """Agrupa el historial de una persona por evaluación.

    `resultados_con_contexto` es una lista de tuplas
    (evaluacion_titulo, sesion, resultado), donde resultado puede ser None si
    la persona ingresó pero no finalizó esa sesión.

    Devuelve una lista de GrupoHistorial, un grupo por evaluación (ordenados
    por título), y dentro de cada grupo las sesiones de la más antigua a la más
    nueva. La comparación válida es DENTRO de un grupo (misma evaluación): por
    eso se separan, para no invitar a comparar % de logro entre evaluaciones
    distintas, que no significan lo mismo.
    """
    grupos: dict[str, list] = {}
    for evaluacion_titulo, sesion, resultado in resultados_con_contexto:
        fila = FilaHistorial(
            fecha=sesion.cerrada_at or sesion.abierta_at,
            codigo=sesion.codigo,
            porcentaje=resultado.porcentaje if resultado else None,
            nota=resultado.nota if resultado else None,
            umbral=sesion.umbral_aprobacion,
            aprobado=resultado.aprobado if resultado else None,
        )
        grupos.setdefault(evaluacion_titulo, []).append(fila)

    resultado_final = []
    for titulo in sorted(grupos.keys()):
        filas = sorted(grupos[titulo], key=lambda f: f.fecha)
        resultado_final.append(GrupoHistorial(evaluacion_titulo=titulo, filas=filas))
    return resultado_final


# Cabecera del CSV del historial. La evaluación va primera para que el CSV
# conserve la agrupación al ordenarlo en Excel.
ENCABEZADOS_CSV_HISTORIAL = [
    "Evaluación",
    "Fecha",
    "Código",
    "% de logro",
    "Nota",
    "Umbral",
    "Resultado",
]


def _texto_resultado(aprobado) -> str:
    if aprobado is None:
        return "Pendiente"
    return "Aprobado" if aprobado else "Reprobado"


def filas_csv_historial(grupos, formatear_fecha=str) -> list[list[str]]:
    """Aplana el historial agrupado en filas para el CSV (sin la cabecera).

    `grupos` es una lista de GrupoHistorial. Se genera una fila por sesión
    rendida, con la evaluación como primera columna. Para las pendientes (sin
    resultado) las columnas de % / nota van vacías y el resultado dice
    "Pendiente", igual que en la tabla en pantalla.

    `formatear_fecha` recibe el datetime de la fila y devuelve el texto a
    mostrar. Por defecto es str; la ruta le pasa hora_local para que salga en
    hora de Chile. Se recibe por argumento para que este helper siga siendo
    puro (sin depender de la app) y fácil de testear.
    """
    filas = []
    for grupo in grupos:
        for f in grupo.filas:
            filas.append(
                [
                    grupo.evaluacion_titulo,
                    formatear_fecha(f.fecha),
                    f.codigo,
                    "" if f.porcentaje is None else f"{f.porcentaje:.1f}",
                    "" if f.nota is None else f"{f.nota:.1f}",
                    f"{f.umbral}",
                    _texto_resultado(f.aprobado),
                ]
            )
    return filas


# ----------------------------- Lista por participante -----------------------------

@dataclass(frozen=True)
class FilaPersona:
    """Una persona en la lista 'Por participante'. Agrupa todas sus sesiones
    (identificadas por el mismo hash) en una sola fila."""
    hash_id: str           # identificador_hash completo (para enlazar al historial)
    hash_corto: str        # primeros caracteres, para mostrar
    nombre: str            # etiqueta legible; SIN_NOMBRE si no tiene
    n_sesiones: int        # cuántas sesiones finalizadas tiene


def agrupar_personas(participantes) -> list[FilaPersona]:
    """Agrupa instancias de Participante por su identificador_hash, para que
    cada persona aparezca UNA vez aunque haya rendido varias sesiones.

    `participantes` es una lista de objetos Participante (cada uno con
    .identificador_hash, .nombre, .ingreso_at). El caller ya filtró a quienes
    tienen al menos un resultado. Se cuenta cuántas instancias (sesiones) tiene
    cada hash. El nombre mostrado es el más reciente no vacío, porque puede
    variar entre sesiones; la identidad la da el hash, no el nombre.

    Devuelve la lista ordenada por nombre (los sin nombre al final).
    """
    por_hash: dict[str, list] = {}
    for p in participantes:
        por_hash.setdefault(p.identificador_hash, []).append(p)

    filas = []
    for hash_id, instancias in por_hash.items():
        mas_reciente_primero = sorted(
            instancias, key=lambda p: p.ingreso_at, reverse=True
        )
        nombre = SIN_NOMBRE
        for p in mas_reciente_primero:
            if p.nombre and p.nombre.strip():
                nombre = p.nombre.strip()
                break
        filas.append(
            FilaPersona(
                hash_id=hash_id,
                hash_corto=_hash_corto(hash_id),
                nombre=nombre,
                n_sesiones=len(instancias),
            )
        )

    # Orden: por nombre alfabético; los "(sin nombre)" al final.
    filas.sort(key=lambda f: (f.nombre == SIN_NOMBRE, f.nombre.lower()))
    return filas

# ----------------------------- Matriz de la sesión -----------------------------
# Vista tipo "libreta de notas": participantes en filas, preguntas en columnas.
# Cada celda muestra la letra de la alternativa elegida y si acertó. Deja ver de
# un vistazo qué preguntas costaron (columna) y a quién le fue mal (fila).

@dataclass(frozen=True)
class CeldaMatriz:
    letra: str            # letra de la alternativa elegida (A, B, …) o "·"
    acerto: "bool | None"  # None = no respondió esa pregunta


@dataclass(frozen=True)
class FilaMatriz:
    participante_id: int
    nombre: str
    hash_corto: str
    celdas: list          # CeldaMatriz por columna, en el orden de las columnas
    nota: "float | None"
    porcentaje: "float | None"
    aprobado: "bool | None"


@dataclass(frozen=True)
class ColumnaMatriz:
    orden: int
    enunciado: str
    correcta_letra: str
    pct_acierto: "int | None"  # % de quienes respondieron que acertaron


@dataclass(frozen=True)
class Matriz:
    columnas: list        # ColumnaMatriz
    filas: list           # FilaMatriz


def construir_matriz(participantes, columnas_meta, letra_de):
    """Arma la matriz de la sesión.

    Args:
        participantes: participantes FINALIZADOS (con .resultado), en el orden
            en que se quieren las filas. Cada uno con .respuestas (foto: .orden,
            .elegida_texto, .acerto), .nombre, .identificador_hash, .resultado.
        columnas_meta: lista de (orden, enunciado, correcta_letra), una por
            pregunta, en el orden de las columnas.
        letra_de: callable (orden, texto_elegido) -> letra ("A", "B", … o "·").

    Devuelve una Matriz con columnas (incluye % de acierto por pregunta) y filas
    (incluye nota y % de logro de cada persona). Pura: no toca la BD.
    """
    ordenes = [orden for (orden, _enunciado, _correcta) in columnas_meta]
    aciertos = {orden: 0 for orden in ordenes}
    respondidas = {orden: 0 for orden in ordenes}

    filas = []
    for p in participantes:
        por_orden = {r.orden: r for r in p.respuestas}
        celdas = []
        for (orden, _enunciado, _correcta) in columnas_meta:
            r = por_orden.get(orden)
            if r is None:
                celdas.append(CeldaMatriz(letra="", acerto=None))
                continue
            celdas.append(CeldaMatriz(letra=letra_de(orden, r.elegida_texto), acerto=r.acerto))
            respondidas[orden] += 1
            if r.acerto:
                aciertos[orden] += 1
        res = p.resultado
        filas.append(
            FilaMatriz(
                participante_id=p.id,
                nombre=p.nombre.strip() if (p.nombre and p.nombre.strip()) else SIN_NOMBRE,
                hash_corto=_hash_corto(p.identificador_hash),
                celdas=celdas,
                nota=res.nota if res else None,
                porcentaje=res.porcentaje if res else None,
                aprobado=res.aprobado if res else None,
            )
        )

    columnas = []
    for (orden, enunciado, correcta_letra) in columnas_meta:
        pct = (
            round(100 * aciertos[orden] / respondidas[orden])
            if respondidas[orden]
            else None
        )
        columnas.append(
            ColumnaMatriz(
                orden=orden,
                enunciado=enunciado,
                correcta_letra=correcta_letra,
                pct_acierto=pct,
            )
        )

    return Matriz(columnas=columnas, filas=filas)
