"""umbral de aprobacion fijado en la sesion

Revision ID: 3a7f21c4bd90
Revises: 085c74a3cbf0
Create Date: 2026-07-17 20:10:00.000000

El umbral pasa a fijarse AL ABRIR la sesion (tomando el de la evaluacion como
valor por defecto). La calificacion lo lee de la sesion, no de la evaluacion.

La columna termina siendo NOT NULL, pero se agrega en tres pasos para no
romper las sesiones que ya existen:
  1. se crea la columna aceptando NULL,
  2. se rellena cada sesion con el umbral de SU evaluacion (asi el historial
     queda con el umbral que efectivamente se le aplico),
  3. recien ahi se marca NOT NULL.

La columna umbral_aprobacion de `evaluacion` NO se toca: sigue existiendo como
valor por defecto para el formulario de abrir sesion.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a7f21c4bd90'
down_revision = '085c74a3cbf0'
branch_labels = None
depends_on = None


RELLENO = """
UPDATE sesion
   SET umbral_aprobacion = (
       SELECT e.umbral_aprobacion
         FROM evaluacion e
        WHERE e.id = sesion.evaluacion_id
   )
 WHERE umbral_aprobacion IS NULL
"""


def upgrade():
    # 1. Columna nueva, por ahora aceptando NULL.
    with op.batch_alter_table('sesion', schema=None) as batch_op:
        batch_op.add_column(sa.Column('umbral_aprobacion', sa.Integer(), nullable=True))

    # 2. Relleno: cada sesion hereda el umbral de su evaluacion.
    op.execute(RELLENO)

    # 3. Ahora que no queda ninguna en NULL, se marca obligatoria.
    with op.batch_alter_table('sesion', schema=None) as batch_op:
        batch_op.alter_column('umbral_aprobacion',
               existing_type=sa.Integer(),
               nullable=False)


def downgrade():
    with op.batch_alter_table('sesion', schema=None) as batch_op:
        batch_op.drop_column('umbral_aprobacion')
