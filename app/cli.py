"""Comandos de consola (flask ...) para tareas de mantenimiento.

Se registran en create_app con registrar_cli(app). Hoy hay uno:

    flask analisis-backfill <CODIGO>

que genera el análisis de IA de una sesión YA cerrada. Sirve para sesiones que
se cerraron antes de tener la feature (o sin la API key configurada). A
diferencia del cierre —que genera en silencio para no bloquearse— este comando
reporta exactamente qué hizo.
"""

import click
from flask import current_app
from flask.cli import with_appcontext

from app import db
from app.models import Sesion
from app.utils import gemini


def registrar_cli(app):
    app.cli.add_command(analisis_backfill)


@click.command("analisis-backfill")
@click.argument("codigo")
@with_appcontext
def analisis_backfill(codigo):
    """Genera el análisis de IA de la sesión con ese CODIGO.

    Idempotente: no pisa análisis ya generados; solo rellena los que faltan.
    Pensado para sesiones cerradas. Requiere GEMINI_API_KEY en el entorno.
    """
    # Import diferido: evita ciclos al cargar la app (routes importa mucho).
    from app.evaluaciones.routes import generar_analisis_de_sesion

    sesion = db.session.query(Sesion).filter_by(codigo=codigo).first()
    if sesion is None:
        click.echo(f"No existe una sesión con código '{codigo}'.")
        raise SystemExit(1)

    if sesion.estado != "cerrada":
        click.echo(
            f"Aviso: la sesión '{codigo}' está {sesion.estado}, no cerrada. "
            "Se genera igual, pero lo normal es correr esto sobre cerradas."
        )

    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        click.echo(
            "No hay GEMINI_API_KEY configurada; no se puede generar. "
            "Setea la variable de entorno y reintenta."
        )
        raise SystemExit(1)

    modelo = current_app.config.get("GEMINI_MODEL", gemini.MODELO_POR_DEFECTO)

    try:
        res = generar_analisis_de_sesion(sesion, api_key, modelo)
        db.session.commit()
    except Exception as e:  # noqa: BLE001 - queremos ver la causa en consola
        db.session.rollback()
        click.echo(f"Error al generar: {e!r}")
        raise SystemExit(1)

    if res.finalizados == 0:
        click.echo(
            f"La sesión '{codigo}' no tiene participantes finalizados; "
            "no hay nada que analizar."
        )
        return

    if res.grupo_generado:
        grupo_txt = "generado"
    elif res.grupo_omitido:
        grupo_txt = "ya existía (no se pisa)"
    else:
        grupo_txt = "no generado"

    click.echo(f"Sesión '{codigo}':")
    click.echo(f"  Finalizados: {res.finalizados}")
    click.echo(
        f"  Análisis por persona generados: {res.personas_generadas} "
        f"(omitidos por ya tener: {res.personas_omitidas})"
    )
    click.echo(f"  Análisis del grupo: {grupo_txt}")
    if res.fallos:
        click.echo(
            f"  Atención: {res.fallos} llamada(s) al modelo volvieron vacías. "
            "Revisa la API key, el modelo (GEMINI_MODEL) o la cuota diaria."
        )
