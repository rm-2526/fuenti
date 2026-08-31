"""facilitador aprobado y organizacion (solicitud de acceso)

Revision ID: e5b1c8d7f302
Revises: a7d3e91b52c4
Create Date: 2026-08-31 18:00:00.000000

Agrega a `facilitador` la bandera `aprobado` y el campo `organizacion`.

`aprobado` NO reemplaza a `activo`: responden preguntas distintas. `aprobado`
dice si un administrador dio el visto bueno alguna vez; `activo` dice si la
cuenta puede operar ahora. Separarlos deja que `activo` conserve exactamente el
significado que ya tenia, de modo que ninguna consulta existente cambia (incluida
la salvaguarda del ultimo administrador activo).

Las cuentas existentes quedan aprobadas (aprobado = true): todas fueron creadas
por un administrador desde el panel, que es justamente el acto de aprobacion.
Por eso la columna es NOT NULL con default true y se agrega en un solo paso.

`organizacion` es nullable porque las cuentas creadas desde el panel no la
declaran: solo la aportan las solicitudes publicas.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5b1c8d7f302'
down_revision = 'a7d3e91b52c4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('facilitador', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'aprobado',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column('organizacion', sa.String(length=255), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('facilitador', schema=None) as batch_op:
        batch_op.drop_column('organizacion')
        batch_op.drop_column('aprobado')
