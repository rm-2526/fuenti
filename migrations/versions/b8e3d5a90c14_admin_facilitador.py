"""facilitador administrador (es_admin)

Revision ID: b8e3d5a90c14
Revises: f4c9a1b7de20
Create Date: 2026-07-20 13:30:00.000000

Agrega la bandera `es_admin` a `facilitador`. Los facilitadores que ya existen
quedan como NO administradores (es_admin = false); al primer administrador se lo
promueve aparte con el script scripts/seed_facilitador.py --admin.

La columna es NOT NULL con default false, así que se agrega en un solo paso: el
default rellena las filas existentes sin dejar ninguna en NULL.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8e3d5a90c14'
down_revision = 'f4c9a1b7de20'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('facilitador', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'es_admin',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table('facilitador', schema=None) as batch_op:
        batch_op.drop_column('es_admin')
