"""Panel de resumen del historial: una barra por rendicion finalizada.

El panel consolida TODAS las rendiciones de la persona en una sola lista
cronologica, mezclando evaluaciones. Por eso cada barra carga su propio umbral:
comparar largos entre evaluaciones distintas no significa nada, y la marca del
umbral es lo que permite leer cada barra por separado.
"""

from datetime import datetime, timedelta

from app import db
from app.models import Alternativa, Evaluacion, Participante, Pregunta, Resultado, Sesion
from app.utils.reporte import FilaHistorial, GrupoHistorial, barras_resumen


def _fila(fecha, porcentaje, umbral=60, aprobado=True, codigo="ABC123"):
    return FilaHistorial(
        fecha=fecha,
        codigo=codigo,
        porcentaje=porcentaje,
        nota=4.0,
        umbral=umbral,
        aprobado=aprobado,
    )


# ----------------------------- funcion pura -----------------------------


def test_una_barra_por_rendicion_finalizada():
    hoy = datetime(2026, 3, 12)
    grupos = [
        GrupoHistorial("Seguridad", [_fila(hoy, 88.0)]),
        GrupoHistorial("Residuos", [_fila(hoy + timedelta(days=10), 55.0, aprobado=False)]),
    ]

    barras = barras_resumen(grupos)

    assert len(barras) == 2
    assert [b.evaluacion_titulo for b in barras] == ["Seguridad", "Residuos"]


def test_las_rendiciones_sin_resultado_quedan_fuera():
    """Quien ingreso pero no finalizo no tiene rendimiento que graficar. Sigue
    visible como "Pendiente" en la tabla de su evaluacion, que es donde
    corresponde dejar constancia."""
    hoy = datetime(2026, 3, 12)
    pendiente = FilaHistorial(
        fecha=hoy, codigo="ZZZ999", porcentaje=None, nota=None, umbral=60, aprobado=None
    )
    grupos = [GrupoHistorial("Seguridad", [_fila(hoy, 88.0), pendiente])]

    barras = barras_resumen(grupos)

    assert len(barras) == 1
    assert barras[0].porcentaje == 88.0


def test_orden_cronologico_mezclando_evaluaciones():
    """La linea de tiempo es de la PERSONA, no de cada evaluacion por separado."""
    base = datetime(2026, 1, 1)
    grupos = [
        GrupoHistorial("Aaa", [_fila(base + timedelta(days=30), 70.0)]),
        GrupoHistorial("Bbb", [_fila(base, 60.0), _fila(base + timedelta(days=60), 80.0)]),
    ]

    barras = barras_resumen(grupos)

    assert [b.porcentaje for b in barras] == [60.0, 70.0, 80.0]


def test_cada_barra_lleva_su_propio_umbral():
    """El umbral se fija por sesion: el mismo porcentaje puede aprobar en una
    rendicion y reprobar en otra. Si las barras compartieran umbral, el panel
    mentiria sobre las rendiciones antiguas."""
    hoy = datetime(2026, 3, 12)
    grupos = [
        GrupoHistorial(
            "Seguridad",
            [
                _fila(hoy, 65.0, umbral=60, aprobado=True),
                _fila(hoy + timedelta(days=1), 65.0, umbral=70, aprobado=False),
            ],
        )
    ]

    barras = barras_resumen(grupos)

    assert [b.posicion_umbral for b in barras] == [60, 70]
    assert [b.aprobado for b in barras] == [True, False]


def test_el_ancho_se_acota_entre_0_y_100():
    """Un ancho fuera de rango romperia la barra en pantalla."""
    hoy = datetime(2026, 3, 12)
    grupos = [
        GrupoHistorial("A", [_fila(hoy, 140.0)]),
        GrupoHistorial("B", [_fila(hoy + timedelta(days=1), -5.0, aprobado=False)]),
    ]

    barras = barras_resumen(grupos)

    assert barras[0].ancho == 100.0
    assert barras[1].ancho == 0.0


def test_sin_rendiciones_finalizadas_no_hay_barras():
    """El panel entero desaparece: no se dibuja un recuadro vacio."""
    hoy = datetime(2026, 3, 12)
    pendiente = FilaHistorial(
        fecha=hoy, codigo="ZZZ999", porcentaje=None, nota=None, umbral=60, aprobado=None
    )

    assert barras_resumen([GrupoHistorial("Seguridad", [pendiente])]) == []


# ----------------------------- integracion -----------------------------


def _login(client, facilitador):
    return client.post(
        "/login",
        data={"email": facilitador.email, "password": "fuenti2026"},
        follow_redirects=True,
    )


def _persona_con_rendicion(app, facilitador_id, hash_id, finaliza=True):
    """Crea evaluacion + sesion cerrada + participante, con o sin resultado."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo="Seguridad", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()

        p = Pregunta(evaluacion_id=e.id, enunciado="¿2+2?", orden=1, tipo="opcion_multiple")
        db.session.add(p)
        db.session.flush()
        db.session.add(Alternativa(pregunta_id=p.id, texto="4", es_correcta=True, orden=1))
        db.session.add(Alternativa(pregunta_id=p.id, texto="5", es_correcta=False, orden=2))

        s = Sesion(
            evaluacion_id=e.id,
            codigo="RES001",
            estado="cerrada",
            abierta_at=datetime(2026, 3, 12),
            cerrada_at=datetime(2026, 3, 12),
            umbral_aprobacion=60,
        )
        db.session.add(s)
        db.session.flush()

        part = Participante(
            sesion_id=s.id,
            identificador_hash=hash_id,
            nombre="Ana Pérez",
            finalizado_at=datetime(2026, 3, 12) if finaliza else None,
        )
        db.session.add(part)
        db.session.flush()

        if finaliza:
            db.session.add(
                Resultado(
                    participante_id=part.id,
                    puntaje=1,
                    total_preguntas=1,
                    porcentaje=100.0,
                    nota=7.0,
                    aprobado=True,
                    evaluacion_titulo="Seguridad",
                )
            )
        db.session.commit()


def test_el_historial_muestra_el_panel_de_resumen(client, app, facilitador):
    hash_id = "a" * 64
    _persona_con_rendicion(app, facilitador.id, hash_id)
    _login(client, facilitador)

    html = client.get(f"/evaluaciones/participante/{hash_id}/historial").data.decode()

    assert "Resumen de rendiciones" in html
    assert "barra-logro" in html


def test_sin_finalizar_no_aparece_el_panel(client, app, facilitador):
    """La tabla sigue mostrando la sesion como Pendiente, pero sin barra."""
    hash_id = "b" * 64
    _persona_con_rendicion(app, facilitador.id, hash_id, finaliza=False)
    _login(client, facilitador)

    html = client.get(f"/evaluaciones/participante/{hash_id}/historial").data.decode()

    assert "Resumen de rendiciones" not in html
    assert "Pendiente" in html
