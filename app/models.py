from datetime import datetime, timezone
from sqlalchemy import (
    Integer, String, Text, Boolean, DateTime, Float, ForeignKey,
    UniqueConstraint, Index, CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from app import db


def ahora_utc():
    return datetime.now(timezone.utc)


class Facilitador(UserMixin, db.Model):
    __tablename__ = "facilitador"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    # Administrador: puede acceder al panel de gestión de facilitadores. Los
    # facilitadores normales solo operan sus propias evaluaciones.
    es_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Activo: un facilitador desactivado no puede iniciar sesión y su sesión
    # existente se corta, pero se conserva TODO lo suyo (evaluaciones, sesiones,
    # informes). Es un "borrado suave" reversible: no destruye datos.
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Aprobado: responde una pregunta DISTINTA de `activo`. `aprobado` dice si un
    # administrador dio el visto bueno alguna vez; `activo` dice si la cuenta
    # puede operar ahora. Son independientes a proposito:
    #   aprobado=False              -> solicitud pendiente de revision
    #   aprobado=True, activo=True  -> cuenta operativa
    #   aprobado=True, activo=False -> cuenta dada de baja
    # Sobrecargar `activo` para las dos cosas mezclaria en el mismo listado a
    # quien nunca fue usuario con quien dejo de serlo, y el mensaje de login
    # ("esta cuenta esta desactivada") le diria a un solicitante que tuvo una
    # cuenta y se la quitaron.
    aprobado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Organizacion declarada al solicitar acceso. Es la unica informacion con
    # que el administrador decide aprobar o rechazar, asi que se guarda tal como
    # la escribio el solicitante. Nula en las cuentas creadas desde el panel.
    organizacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=ahora_utc
    )

    evaluaciones: Mapped[list["Evaluacion"]] = relationship(
        back_populates="facilitador", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Evaluacion(db.Model):
    __tablename__ = "evaluacion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facilitador_id: Mapped[int] = mapped_column(ForeignKey("facilitador.id"), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    umbral_aprobacion: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)

    facilitador: Mapped["Facilitador"] = relationship(back_populates="evaluaciones")
    preguntas: Mapped[list["Pregunta"]] = relationship(
        back_populates="evaluacion", cascade="all, delete-orphan"
    )
    sesiones: Mapped[list["Sesion"]] = relationship(
        back_populates="evaluacion", cascade="all, delete-orphan"
    )

    # El rango del umbral ya se valida en el formulario. Declararlo tambien aca
    # cierra la via de escritura directa: un bug en el controlador o un script
    # de mantencion no puede dejar una evaluacion con umbral 150.
    __table_args__ = (
        CheckConstraint(
            "umbral_aprobacion BETWEEN 0 AND 100", name="ck_evaluacion_umbral"
        ),
    )


class Pregunta(db.Model):
    __tablename__ = "pregunta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluacion_id: Mapped[int] = mapped_column(ForeignKey("evaluacion.id"), nullable=False)
    enunciado: Mapped[str] = mapped_column(Text, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    # Tipo de pregunta: "opcion_multiple" (2-6 alternativas de texto libre) o
    # "verdadero_falso" (exactamente 2 alternativas fijas: Verdadero/Falso). No
    # cambia cómo se califica —ambas se corrigen por la alternativa es_correcta—;
    # solo afecta la autoría (V/F trae las alternativas ya puestas) y la
    # presentación (la matriz muestra V/F en vez de A/B).
    tipo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="opcion_multiple"
    )

    evaluacion: Mapped["Evaluacion"] = relationship(back_populates="preguntas")
    alternativas: Mapped[list["Alternativa"]] = relationship(
        back_populates="pregunta", cascade="all, delete-orphan"
    )
    respuestas: Mapped[list["Respuesta"]] = relationship(back_populates="pregunta")

    __table_args__ = (
        CheckConstraint(
            "tipo IN ('opcion_multiple', 'verdadero_falso')", name="ck_pregunta_tipo"
        ),
    )


class Alternativa(db.Model):
    __tablename__ = "alternativa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pregunta_id: Mapped[int] = mapped_column(ForeignKey("pregunta.id"), nullable=False)
    texto: Mapped[str] = mapped_column(String(500), nullable=False)
    es_correcta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=A, 2=B, 3=C, 4=D

    pregunta: Mapped["Pregunta"] = relationship(back_populates="alternativas")
    respuestas: Mapped[list["Respuesta"]] = relationship(back_populates="alternativa")


class Sesion(db.Model):
    __tablename__ = "sesion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluacion_id: Mapped[int] = mapped_column(ForeignKey("evaluacion.id"), nullable=False)
    codigo: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta")
    # Umbral de aprobacion (0-100) FIJADO AL ABRIR la sesion. Se toma de la
    # evaluacion como valor por defecto, pero el facilitador puede cambiarlo
    # al abrir: la misma evaluacion puede exigir 50 en un diagnostico y 70 en
    # una certificacion, sin editar la evaluacion (y sin mezclar versiones).
    # Una vez abierta la sesion NO se edita: la nota que se le prometio a un
    # participante no puede cambiar despues. La calificacion lee este valor,
    # no el de la evaluacion.
    # Ojo: dos sesiones de la misma evaluacion pueden tener umbrales distintos,
    # asi que sus NOTAS no son comparables entre si. El seguimiento longitudinal
    # se compara por porcentaje de logro, que no depende del umbral.
    umbral_aprobacion: Mapped[int] = mapped_column(Integer, nullable=False)
    abierta_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Análisis de IA del GRUPO (congelado al cerrar la sesión) ---
    # Texto narrativo de fortalezas/debilidades del grupo, generado UNA sola vez
    # al cerrar la sesión y guardado tal cual (igual que la foto congelada: no se
    # regenera al abrir el informe). Nullable: si no hay API key o la llamada
    # falla, queda en NULL y el informe se muestra sin este bloque.
    analisis_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    analisis_generado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    evaluacion: Mapped["Evaluacion"] = relationship(back_populates="sesiones")
    participantes: Mapped[list["Participante"]] = relationship(
        back_populates="sesion", cascade="all, delete-orphan"
    )

    # Los estados son los del diagrama de estados: no hay un tercero, y el
    # cierre es irreversible. El CHECK cubre el primer invariante; el segundo
    # (no volver de cerrada a abierta) es una transicion y no un valor, asi que
    # sigue viviendo en el controlador.
    __table_args__ = (
        CheckConstraint("estado IN ('abierta', 'cerrada')", name="ck_sesion_estado"),
        CheckConstraint(
            "umbral_aprobacion BETWEEN 0 AND 100", name="ck_sesion_umbral"
        ),
        CheckConstraint(
            "cerrada_at IS NULL OR cerrada_at >= abierta_at", name="ck_sesion_cierre"
        ),
    )


class Participante(db.Model):
    __tablename__ = "participante"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sesion_id: Mapped[int] = mapped_column(ForeignKey("sesion.id"), nullable=False)
    identificador_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ingreso_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    finalizado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sesion: Mapped["Sesion"] = relationship(back_populates="participantes")
    respuestas: Mapped[list["Respuesta"]] = relationship(
        back_populates="participante", cascade="all, delete-orphan"
    )
    resultado: Mapped["Resultado | None"] = relationship(
        back_populates="participante", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("sesion_id", "identificador_hash", name="uq_participante_sesion_hash"),
        Index("ix_participante_identificador_hash", "identificador_hash"),
        CheckConstraint(
            "finalizado_at IS NULL OR finalizado_at >= ingreso_at",
            name="ck_participante_fin",
        ),
    )


class Respuesta(db.Model):
    __tablename__ = "respuesta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participante_id: Mapped[int] = mapped_column(ForeignKey("participante.id"), nullable=False)
    # pregunta_id / alternativa_id son opcionales (nullable): si la evaluacion se
    # edita y una pregunta o alternativa se borra, la respuesta suelta el enlace
    # (queda en NULL) pero CONSERVA su foto congelada. Asi editar una evaluacion
    # ya rendida no rompe el historial.
    pregunta_id: Mapped[int | None] = mapped_column(ForeignKey("pregunta.id"), nullable=True)
    alternativa_id: Mapped[int | None] = mapped_column(ForeignKey("alternativa.id"), nullable=True)
    enviada_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)

    # --- Foto congelada (snapshot) ---
    # Copia del contenido tal como estaba al momento de responder. Deja la
    # respuesta autocontenida: el informe individual se arma con estos textos,
    # no leyendo la evaluacion viva. Asi se puede editar la evaluacion despues
    # sin alterar los resultados de sesiones ya rendidas.
    # Nullable por compatibilidad (columnas agregadas a una tabla existente);
    # el flujo de finalizacion siempre las rellena.
    enunciado_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    elegida_texto: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correcta_texto: Mapped[str | None] = mapped_column(String(500), nullable=True)
    acerto: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    orden: Mapped[int | None] = mapped_column(Integer, nullable=True)

    participante: Mapped["Participante"] = relationship(back_populates="respuestas")
    pregunta: Mapped["Pregunta"] = relationship(back_populates="respuestas")
    alternativa: Mapped["Alternativa"] = relationship(back_populates="respuestas")

    __table_args__ = (
        UniqueConstraint("participante_id", "pregunta_id", name="uq_respuesta_participante_pregunta"),
    )


class Resultado(db.Model):
    __tablename__ = "resultado"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participante_id: Mapped[int] = mapped_column(
        ForeignKey("participante.id"), unique=True, nullable=False
    )
    puntaje: Mapped[int] = mapped_column(Integer, nullable=False)
    total_preguntas: Mapped[int] = mapped_column(Integer, nullable=False)
    porcentaje: Mapped[float] = mapped_column(Float, nullable=False)
    nota: Mapped[float] = mapped_column(Float, nullable=False)  # escala 1.0-7.0
    aprobado: Mapped[bool] = mapped_column(Boolean, nullable=False)
    calculado_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)

    # --- Foto congelada (snapshot) del encabezado ---
    # Titulo de la evaluacion y umbral aplicados al momento de calcular. Dejan
    # el informe autocontenido tambien en su encabezado: si despues se edita el
    # titulo o el umbral de la evaluacion, el resultado viejo sigue mostrando
    # lo que efectivamente se aplico. Nullable por compatibilidad.
    evaluacion_titulo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    umbral_aprobacion: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Análisis de IA de la PERSONA (congelado al cerrar la sesión) ---
    # Texto narrativo de fortalezas/debilidades del participante, generado UNA
    # sola vez al cerrar la sesión. Mismas reglas que el de Sesion: nullable, no
    # se regenera, y el nombre/hash NUNCA se le mandan al modelo (ver analisis.py).
    analisis_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    analisis_generado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    participante: Mapped["Participante"] = relationship(back_populates="resultado")

    # La calificacion es el dato con valor probatorio del sistema: es lo que se
    # le entrega a la organizacion. Estos CHECK son la ultima linea que impide
    # persistir un informe aritmeticamente imposible.
    # umbral_aprobacion admite NULL: la columna se agrego a una tabla que ya
    # tenia filas (migracion 3a7f21c4bd90), asi que los resultados anteriores a
    # esa fecha no lo tienen.
    __table_args__ = (
        CheckConstraint("nota BETWEEN 1.0 AND 7.0", name="ck_resultado_nota"),
        CheckConstraint("porcentaje BETWEEN 0 AND 100", name="ck_resultado_pct"),
        CheckConstraint(
            "puntaje >= 0 AND puntaje <= total_preguntas", name="ck_resultado_puntaje"
        ),
        CheckConstraint(
            "umbral_aprobacion IS NULL OR umbral_aprobacion BETWEEN 0 AND 100",
            name="ck_resultado_umbral",
        ),
    )


class SolicitudEliminacion(db.Model):
    """Solicitud pública de eliminación de los datos de un participante.

    Nace desde la página pública /privacidad: la persona escribe su RUT, el
    sistema calcula el mismo hash que usa Participante.identificador_hash
    (ver app/utils/rut.py) y registra la solicitud. El RUT en texto plano
    NUNCA se guarda, ni siquiera aquí: solo su hash, igual que en el resto
    del sistema.

    Aprobar la solicitud borra TODAS las filas de Participante con ese hash,
    en cualquier evaluación y de cualquier facilitador (arrastra Respuesta y
    Resultado por la cascada ya declarada en Participante). Por eso vive en
    el panel de administración y no en el de cada facilitador: el
    consentimiento es de la persona titular del dato, no de quien dictó la
    capacitación, y su alcance cruza cuentas.

    Limite conocido: como el sistema no le pide correo a un participante para
    rendir, no hay forma de verificar aquí que quien solicita la eliminación
    es efectivamente esa persona. Es el mismo modelo de confianza que ya
    rige el ingreso por RUT (quien lo escribe se asume su titular); `contacto`
    es la unica mitigacion, y es opcional.
    """
    __tablename__ = "solicitud_eliminacion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identificador_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Opcional: correo o telefono para que un administrador contacte a quien
    # solicita, si tiene dudas antes de aprobar. No se exige porque en ningun
    # otro punto del sistema se le pide correo a un participante.
    contacto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 'pendiente' -> 'aprobada' (se borraron los datos) o 'rechazada' (no se
    # tocó nada). Es una transición única y sin vuelta, igual que el cierre
    # de una sesión: no hay un cuarto estado ni un camino de regreso.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    solicitado_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    resuelta_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Quien la resolvio, para auditoria. Nullable: nunca se borra al borrar al
    # administrador (no hay ON DELETE CASCADE aca), asi que si esa cuenta se
    # da de baja el registro historico de la solicitud se conserva igual.
    resuelta_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("facilitador.id"), nullable=True
    )

    resuelta_por: Mapped["Facilitador | None"] = relationship()

    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'aprobada', 'rechazada')",
            name="ck_solicitud_eliminacion_estado",
        ),
        Index("ix_solicitud_eliminacion_hash", "identificador_hash"),
    )