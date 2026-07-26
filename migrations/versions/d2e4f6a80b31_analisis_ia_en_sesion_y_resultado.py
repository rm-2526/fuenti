"""análisis de IA en sesion y resultado

Revision ID: d2e4f6a80b31
Revises: c1f7a2e46d8b
Create Date: 2026-07-26 12:00:00.000000

Agrega el texto de análisis de IA (fortalezas/debilidades) y su fecha de
generación, tanto por SESIÓN (análisis del grupo) como por RESULTADO (análisis
de la persona). Ambas columnas son nullable: si no hay API key o la llamada al
modelo falla, quedan en NULL y el informe se muestra igual con los números.

Son columnas nuevas sobre tablas existentes; nullable, sin default, sin tocar
filas previas.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2e4f6a80b31'
down_revision = 'c1f7a2e46d8b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sesion', schema=None) as batch_op:
        batch_op.add_column(sa.Column('analisis_ia', sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column('analisis_generado_at', sa.DateTime(), nullable=True)
        )

    with op.batch_alter_table('resultado', schema=None) as batch_op:
        batch_op.add_column(sa.Column('analisis_ia', sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column('analisis_generado_at', sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('resultado', schema=None) as batch_op:
        batch_op.drop_column('analisis_generado_at')
        batch_op.drop_column('analisis_ia')

    with op.batch_alter_table('sesion', schema=None) as batch_op:
        batch_op.drop_column('analisis_generado_at')
        batch_op.drop_column('analisis_ia')
