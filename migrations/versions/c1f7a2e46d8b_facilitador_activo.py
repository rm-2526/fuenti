"""facilitador activo (borrado suave)

Revision ID: c1f7a2e46d8b
Revises: b8e3d5a90c14
Create Date: 2026-07-20 14:30:00.000000

Agrega la bandera `activo` a `facilitador`. Permite desactivar una cuenta (no
puede iniciar sesión) sin borrar sus datos. Los facilitadores existentes quedan
activos (activo = true).

La columna es NOT NULL con default true, así que se agrega en un solo paso: el
default rellena las filas existentes.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1f7a2e46d8b'
down_revision = 'b8e3d5a90c14'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('facilitador', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'activo',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade():
    with op.batch_alter_table('facilitador', schema=None) as batch_op:
        batch_op.drop_column('activo')
