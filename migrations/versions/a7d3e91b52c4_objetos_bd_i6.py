"""Objetos de base de datos: vistas de reporteria y restricciones CHECK (I6)

Hasta aca la base de datos era solo almacenamiento: guardaba filas y el rango de
cada valor se validaba unicamente en Python. Esta migracion agrega las dos cosas
que faltaban para que la base participe de la logica del sistema:

  1. Dos vistas que resuelven en el motor la agregacion del panel de sesion y la
     consolidacion del historial longitudinal, definidas una sola vez en
     app/vistas.py.
  2. Restricciones CHECK que declaran en el esquema los invariantes que hasta
     ahora solo vivian en el controlador.

Sobre SQLite. Agregar un CHECK a una tabla que ya existe obliga a reconstruirla:
SQLite no tiene ALTER TABLE ADD CONSTRAINT. batch_alter_table hace ese baile
(crea tabla nueva, copia, renombra) de forma transparente, y en PostgreSQL emite
el ALTER TABLE directo. Por eso todo el bloque va en modo batch aunque en
produccion no haga falta.

Cuidado con los datos existentes. Si alguna fila ya viola un CHECK, la migracion
falla al aplicarse, que es el comportamiento correcto: significa que hay datos
malos que hay que revisar antes, no una restriccion que haya que relajar.

Revision ID: a7d3e91b52c4
Revises: d2e4f6a80b31
"""

from alembic import op

from app.vistas import crear_vistas, eliminar_vistas


revision = "a7d3e91b52c4"
down_revision = "d2e4f6a80b31"
branch_labels = None
depends_on = None


# (tabla, nombre de la restriccion, condicion)
CHECKS = [
    ("evaluacion", "ck_evaluacion_umbral", "umbral_aprobacion BETWEEN 0 AND 100"),
    ("pregunta", "ck_pregunta_tipo", "tipo IN ('opcion_multiple', 'verdadero_falso')"),
    ("sesion", "ck_sesion_estado", "estado IN ('abierta', 'cerrada')"),
    ("sesion", "ck_sesion_umbral", "umbral_aprobacion BETWEEN 0 AND 100"),
    ("sesion", "ck_sesion_cierre", "cerrada_at IS NULL OR cerrada_at >= abierta_at"),
    (
        "participante",
        "ck_participante_fin",
        "finalizado_at IS NULL OR finalizado_at >= ingreso_at",
    ),
    ("resultado", "ck_resultado_nota", "nota BETWEEN 1.0 AND 7.0"),
    ("resultado", "ck_resultado_pct", "porcentaje BETWEEN 0 AND 100"),
    (
        "resultado",
        "ck_resultado_puntaje",
        "puntaje >= 0 AND puntaje <= total_preguntas",
    ),
    (
        "resultado",
        "ck_resultado_umbral",
        "umbral_aprobacion IS NULL OR umbral_aprobacion BETWEEN 0 AND 100",
    ),
]


def upgrade():
    for tabla, nombre, condicion in CHECKS:
        with op.batch_alter_table(tabla) as batch:
            batch.create_check_constraint(nombre, condicion)

    crear_vistas(op.get_bind())


def downgrade():
    eliminar_vistas(op.get_bind())

    for tabla, nombre, _ in reversed(CHECKS):
        with op.batch_alter_table(tabla) as batch:
            batch.drop_constraint(nombre, type_="check")
