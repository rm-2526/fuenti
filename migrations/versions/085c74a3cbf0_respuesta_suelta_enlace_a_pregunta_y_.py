"""respuesta suelta enlace a pregunta y alternativa al editar

Revision ID: 085c74a3cbf0
Revises: 11df109c6a14
Create Date: 2026-07-12 16:49:02.455410

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '085c74a3cbf0'
down_revision = '11df109c6a14'
branch_labels = None
depends_on = None


def upgrade():
    # Editar evaluaciones: la respuesta puede soltar su enlace a pregunta y
    # alternativa (quedar en NULL) sin perder su foto congelada.
    with op.batch_alter_table('respuesta', schema=None) as batch_op:
        batch_op.alter_column('pregunta_id',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.alter_column('alternativa_id',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade():
    with op.batch_alter_table('respuesta', schema=None) as batch_op:
        batch_op.alter_column('alternativa_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.alter_column('pregunta_id',
               existing_type=sa.INTEGER(),
               nullable=False)
