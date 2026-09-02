"""solicitud de eliminacion de datos

Revision ID: a1c5f7e93b6d
Revises: e5b1c8d7f302
Create Date: 2026-09-02 12:00:00.000000

Crea `solicitud_eliminacion`, la tabla que respalda la página pública
/privacidad: una persona escribe su RUT, el sistema calcula el mismo hash
que usa `participante.identificador_hash` y registra una solicitud
pendiente. Un administrador la aprueba (borra físicamente todas las
participaciones con ese hash, en cualquier evaluación) o la rechaza.

No toca ninguna tabla existente: es puramente aditiva.

`identificador_hash` NO lleva UNIQUE a propósito: la misma persona podría
solicitar la eliminación más de una vez (por ejemplo, si la primera vez fue
rechazada, o si vuelve a participar después de una eliminación aprobada).
Se indexa igual, porque es la columna por la que se busca coincidencia.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c5f7e93b6d'
down_revision = 'e5b1c8d7f302'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'solicitud_eliminacion',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('identificador_hash', sa.String(length=64), nullable=False),
        sa.Column('contacto', sa.String(length=255), nullable=True),
        sa.Column(
            'estado',
            sa.String(length=20),
            nullable=False,
            server_default='pendiente',
        ),
        sa.Column('solicitado_at', sa.DateTime(), nullable=False),
        sa.Column('resuelta_at', sa.DateTime(), nullable=True),
        sa.Column('resuelta_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['resuelta_por_id'], ['facilitador.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'aprobada', 'rechazada')",
            name='ck_solicitud_eliminacion_estado',
        ),
    )
    with op.batch_alter_table('solicitud_eliminacion', schema=None) as batch_op:
        batch_op.create_index(
            'ix_solicitud_eliminacion_hash', ['identificador_hash'], unique=False
        )


def downgrade():
    with op.batch_alter_table('solicitud_eliminacion', schema=None) as batch_op:
        batch_op.drop_index('ix_solicitud_eliminacion_hash')
    op.drop_table('solicitud_eliminacion')
