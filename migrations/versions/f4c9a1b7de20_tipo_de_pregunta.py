"""tipo de pregunta (opcion_multiple / verdadero_falso)

Revision ID: f4c9a1b7de20
Revises: 3a7f21c4bd90
Create Date: 2026-07-20 12:00:00.000000

Agrega la columna `tipo` a `pregunta`. No cambia la calificación (que se hace
por la alternativa es_correcta): solo distingue las preguntas de Verdadero/Falso
para la autoría y la presentación.

La columna termina siendo NOT NULL, pero se agrega en tres pasos para no romper
las preguntas que ya existen:
  1. se crea la columna aceptando NULL,
  2. se marca cada pregunta existente como 'opcion_multiple' (su comportamiento
     actual),
  3. recién ahí se marca NOT NULL.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4c9a1b7de20'
down_revision = '3a7f21c4bd90'
branch_labels = None
depends_on = None


RELLENO = "UPDATE pregunta SET tipo = 'opcion_multiple' WHERE tipo IS NULL"


def upgrade():
    # 1. Columna nueva, por ahora aceptando NULL.
    with op.batch_alter_table('pregunta', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tipo', sa.String(length=20), nullable=True))

    # 2. Relleno: las preguntas que ya existen eran de opción múltiple.
    op.execute(RELLENO)

    # 3. Ahora que no queda ninguna en NULL, se marca obligatoria.
    with op.batch_alter_table('pregunta', schema=None) as batch_op:
        batch_op.alter_column('tipo',
               existing_type=sa.String(length=20),
               nullable=False)


def downgrade():
    with op.batch_alter_table('pregunta', schema=None) as batch_op:
        batch_op.drop_column('tipo')
