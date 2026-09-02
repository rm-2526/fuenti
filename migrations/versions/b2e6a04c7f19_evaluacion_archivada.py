"""evaluacion archivada

Revision ID: b2e6a04c7f19
Revises: a1c5f7e93b6d
Create Date: 2026-09-02 18:00:00.000000

Agrega `evaluacion.archivada` (booleano, por defecto false).

"Eliminar" una evaluación desde la Biblioteca ya no borra su fila ni nada de
lo que cuelga de ella (preguntas, sesiones, participantes, respuestas,
resultados). En su lugar, la marca como archivada. El listado de Biblioteca
(evaluaciones.listado) y el de Iniciar sesión (evaluaciones.iniciar) dejan
de mostrarla; Informes (evaluaciones.informes) NO filtra por esta columna,
así que las sesiones cerradas de una evaluación archivada se siguen viendo
exactamente igual que antes.

Motivo del cambio: el propósito del sistema es generar evidencia del
aprendizaje. Antes de esta migración, "Eliminar evaluación" borraba en
cascada todas sus sesiones y resultados, sin distinguir una evaluación de
prueba vacía de una con participantes reales que ya rindieron.

Nota tecnica sobre las vistas. v_historial_longitudinal hace JOIN contra
'evaluacion' (para exponer facilitador_id). batch_alter_table en SQLite
agrega una columna renombrando la tabla a un nombre temporal y de vuelta, y
SQLite rechaza esa operacion mientras una vista dependa de la tabla. Por eso
esta migracion quita las dos vistas antes de alterar 'evaluacion' y las
vuelve a crear despues, con la MISMA definicion que ya usa app/vistas.py (no
se importa ese modulo aca a proposito: una migracion debe quedar fija en el
tiempo, no depender de codigo de aplicacion que puede cambiar de forma
despues). Es la primera migracion que toca una tabla referenciada por estas
vistas desde que se crearon; cualquier migracion futura sobre 'evaluacion',
'sesion', 'participante' o 'resultado' va a necesitar el mismo tratamiento.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2e6a04c7f19'
down_revision = 'a1c5f7e93b6d'
branch_labels = None
depends_on = None


V_HISTORIAL = """
CREATE VIEW v_historial_longitudinal AS
SELECT p.identificador_hash        AS identificador_hash,
       e.facilitador_id            AS facilitador_id,
       s.id                        AS sesion_id,
       s.codigo                    AS codigo,
       s.cerrada_at                AS cerrada_at,
       res.evaluacion_titulo       AS evaluacion_titulo,
       res.umbral_aprobacion       AS umbral_aprobacion,
       res.puntaje                 AS puntaje,
       res.total_preguntas         AS total_preguntas,
       res.porcentaje              AS porcentaje,
       res.nota                    AS nota,
       res.aprobado                AS aprobado,
       p.nombre                    AS nombre_referencia
FROM participante p
JOIN sesion s       ON s.id = p.sesion_id
JOIN evaluacion e   ON e.id = s.evaluacion_id
JOIN resultado res  ON res.participante_id = p.id
WHERE s.estado = 'cerrada'
"""

V_RESUMEN = """
CREATE VIEW v_resumen_sesion AS
SELECT s.id                                            AS sesion_id,
       s.codigo                                        AS codigo,
       s.estado                                        AS estado,
       s.umbral_aprobacion                             AS umbral_aprobacion,
       COUNT(p.id)                                     AS ingresados,
       COUNT(res.id)                                   AS finalizados,
       ROUND(CAST(AVG(res.nota) AS numeric), 1)        AS nota_promedio,
       ROUND(CAST(AVG(res.porcentaje) AS numeric), 1)  AS logro_promedio,
       SUM(CASE WHEN res.aprobado THEN 1 ELSE 0 END)   AS aprobados
FROM sesion s
LEFT JOIN participante p ON p.sesion_id = s.id
LEFT JOIN resultado res  ON res.participante_id = p.id
GROUP BY s.id, s.codigo, s.estado, s.umbral_aprobacion
"""


def upgrade():
    op.execute("DROP VIEW IF EXISTS v_historial_longitudinal")
    op.execute("DROP VIEW IF EXISTS v_resumen_sesion")

    with op.batch_alter_table('evaluacion', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'archivada',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.execute(V_HISTORIAL)
    op.execute(V_RESUMEN)


def downgrade():
    op.execute("DROP VIEW IF EXISTS v_historial_longitudinal")
    op.execute("DROP VIEW IF EXISTS v_resumen_sesion")

    with op.batch_alter_table('evaluacion', schema=None) as batch_op:
        batch_op.drop_column('archivada')

    op.execute(V_HISTORIAL)
    op.execute(V_RESUMEN)

