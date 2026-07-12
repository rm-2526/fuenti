"""foto congelada en respuesta y resultado

Revision ID: 11df109c6a14
Revises: 26ac2f417cf6
Create Date: 2026-07-12 15:59:01.624316

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '11df109c6a14'
down_revision = '26ac2f417cf6'
branch_labels = None
depends_on = None


def upgrade():
    # Foto congelada (snapshot): columnas nuevas para que respuesta y resultado
    # queden autocontenidos y no dependan de la evaluacion viva.
    with op.batch_alter_table('respuesta', schema=None) as batch_op:
        batch_op.add_column(sa.Column('enunciado_texto', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('elegida_texto', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('correcta_texto', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('acerto', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('orden', sa.Integer(), nullable=True))

    with op.batch_alter_table('resultado', schema=None) as batch_op:
        batch_op.add_column(sa.Column('evaluacion_titulo', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('umbral_aprobacion', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    with op.batch_alter_table('resultado', schema=None) as batch_op:
        batch_op.drop_column('umbral_aprobacion')
        batch_op.drop_column('evaluacion_titulo')

    with op.batch_alter_table('respuesta', schema=None) as batch_op:
        batch_op.drop_column('orden')
        batch_op.drop_column('acerto')
        batch_op.drop_column('correcta_texto')
        batch_op.drop_column('elegida_texto')
        batch_op.drop_column('enunciado_texto')
