from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, ForeignKey, UniqueConstraint, Index
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


class Pregunta(db.Model):
    __tablename__ = "pregunta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluacion_id: Mapped[int] = mapped_column(ForeignKey("evaluacion.id"), nullable=False)
    enunciado: Mapped[str] = mapped_column(Text, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    evaluacion: Mapped["Evaluacion"] = relationship(back_populates="preguntas")
    alternativas: Mapped[list["Alternativa"]] = relationship(
        back_populates="pregunta", cascade="all, delete-orphan"
    )
    respuestas: Mapped[list["Respuesta"]] = relationship(back_populates="pregunta")


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

    evaluacion: Mapped["Evaluacion"] = relationship(back_populates="sesiones")
    participantes: Mapped[list["Participante"]] = relationship(
        back_populates="sesion", cascade="all, delete-orphan"
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

    participante: Mapped["Participante"] = relationship(back_populates="resultado")