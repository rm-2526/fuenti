"""Vistas de base de datos (I6).

Por que existen. Hasta I5 toda operacion de datos se resolvia en Python: el
panel de la sesion contaba participantes y promediaba notas en memoria, y el
historial longitudinal se armaba con un join escrito en el blueprint. Eso
funciona, pero paga dos costos: trae filas completas por la red en cada sondeo
(cada 10 s, contra una base gestionada que cobra transferencia) y deja la
definicion de "que es el historial de una persona" repartida entre el codigo de
consulta y el de reporteria.

Estas dos vistas mueven esa agregacion al motor. No agregan reglas de negocio
nuevas: son la MISMA consulta, expresada una sola vez y del lado de la base.

Portabilidad (RNF-12). Ambas son SQL estandar y corren igual en SQLite y en
PostgreSQL. Los dos puntos donde los motores difieren y que estan resueltos aca:

  - ROUND(x, n) en PostgreSQL no acepta double precision, solo numeric, y
    Resultado.nota es Float. Por eso va CAST(... AS numeric) alrededor del
    AVG(), que SQLite acepta sin ruido (le da afinidad numerica).
  - El booleano: SQLite lo guarda como 0/1 y PostgreSQL como boolean real. Por
    eso el conteo de aprobados usa CASE WHEN res.aprobado THEN 1 ELSE 0 END,
    que es verdadero en los dos, en vez de comparar contra 1 o contra TRUE.

Como se crean. En un solo lugar (SQL_VISTAS) y desde dos caminos:

  - En produccion, la migracion de Alembic las ejecuta.
  - En los tests, que levantan el esquema con db.create_all() y no con
    migraciones, un listener 'after_create' sobre la metadata las crea tambien.

Sin ese listener las vistas existirian en produccion y no en las pruebas, que es
exactamente la clase de divergencia que este proyecto trata de no tener.

Las vistas NO se mapean como modelos del ORM a proposito: db.create_all() las
trataria como tablas e intentaria crearlas, y el autogenerate de Alembic se
confundiria. Se consultan con SQL explicito a traves de los helpers de abajo.
"""

from sqlalchemy import event, text

from app.models import db


# ---------------------------------------------------------------------------
# Definiciones
# ---------------------------------------------------------------------------

# OE4: reune las participaciones de una misma persona a traves de sesiones y
# evaluaciones distintas. Dos decisiones que vienen del diseno, no del SQL:
#   - Lee de la foto congelada (res.evaluacion_titulo, res.umbral_aprobacion),
#     no de la evaluacion viva, para que editar la evaluacion no altere el
#     historial ya emitido.
#   - Expone facilitador_id para que el filtro de propiedad (V-11) se aplique
#     dentro de la consulta y no despues, en memoria.
# Solo sesiones cerradas: una sesion abierta todavia puede cambiar.
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

# Alimenta el panel de monitoreo y el encabezado del informe de sesion.
# Devuelve UNA fila por sesion donde antes se traian N filas de participante.
# LEFT JOIN para que una sesion recien abierta (sin nadie dentro) siga
# apareciendo con ingresados = 0 en vez de desaparecer del panel.
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

SQL_VISTAS = {
    "v_historial_longitudinal": V_HISTORIAL,
    "v_resumen_sesion": V_RESUMEN,
}


# ---------------------------------------------------------------------------
# Creacion y borrado
# ---------------------------------------------------------------------------

def crear_vistas(conn):
    """Crea las vistas. Idempotente: borra antes de crear."""
    for nombre, sentencia in SQL_VISTAS.items():
        conn.execute(text(f"DROP VIEW IF EXISTS {nombre}"))
        conn.execute(text(sentencia))


def eliminar_vistas(conn):
    for nombre in SQL_VISTAS:
        conn.execute(text(f"DROP VIEW IF EXISTS {nombre}"))


@event.listens_for(db.metadata, "after_create")
def _crear_vistas_tras_create_all(target, connection, **kw):
    """db.create_all() arma las tablas; esto agrega las vistas encima.

    Es lo que hace que los tests vean el mismo esquema que produccion.
    """
    crear_vistas(connection)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def historial_de(identificador_hash, facilitador_id):
    """Trayectoria de una persona, restringida a lo que este facilitador posee.

    Devuelve filas ordenadas de la mas reciente a la mas antigua. La comparacion
    entre sesiones se hace por 'porcentaje' y no por 'nota': dos sesiones de la
    misma evaluacion pueden haber fijado umbrales distintos, asi que sus notas
    no son comparables entre si.
    """
    return db.session.execute(
        text(
            """
            SELECT * FROM v_historial_longitudinal
            WHERE identificador_hash = :h AND facilitador_id = :f
            ORDER BY cerrada_at DESC
            """
        ),
        {"h": identificador_hash, "f": facilitador_id},
    ).mappings().all()


def resumen_de(sesion_id):
    """Agregados de una sesion en una sola fila. None si la sesion no existe."""
    return db.session.execute(
        text("SELECT * FROM v_resumen_sesion WHERE sesion_id = :s"),
        {"s": sesion_id},
    ).mappings().first()
