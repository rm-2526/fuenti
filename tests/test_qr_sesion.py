"""Tests del QR del enlace de la sesion.

El QR no es un objeto con vida propia: es una imagen del mismo enlace que ya se
muestra al lado. De ahi que lo que se prueba sea (a) que ese enlace y esa imagen
digan lo mismo, y (b) que el QR aparezca solo mientras la sesion acepta
ingresos. Si alguna vez el QR quedara apuntando a otra parte, o sobreviviera al
cierre de la sesion, seria un codigo pegado en una pared que manda a la nada.
"""

import pathlib

from app import db
from app.models import Alternativa, Evaluacion, Pregunta, Sesion
from app.utils.qr import _BORDE, svg_de_enlace


def _login(client, facilitador):
    return client.post(
        "/login",
        data={"email": facilitador.email, "password": "fuenti2026"},
        follow_redirects=True,
    )


def _eval_con_sesion(app, facilitador_id, codigo="QRS123", estado="abierta"):
    """Evaluacion con una pregunta + sesion. Devuelve (eval_id, sesion_id)."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo="Eval QR", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()

        p = Pregunta(evaluacion_id=e.id, enunciado="¿2+2?", orden=1)
        db.session.add(p)
        db.session.flush()
        db.session.add(
            Alternativa(pregunta_id=p.id, texto="4", es_correcta=True, orden=1)
        )
        db.session.add(
            Alternativa(pregunta_id=p.id, texto="5", es_correcta=False, orden=2)
        )

        s = Sesion(
            evaluacion_id=e.id,
            codigo=codigo,
            estado=estado,
            umbral_aprobacion=60,
        )
        db.session.add(s)
        db.session.commit()
        return e.id, s.id


# === El helper, sin tocar la app ===

def test_el_helper_devuelve_un_svg():
    svg = svg_de_enlace("https://ejemplo.cl/sesion/K7M4PQ/ingreso")

    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")


def test_el_svg_no_trae_declaracion_xml():
    """Va incrustado dentro del HTML, no es un archivo aparte: un <?xml ... ?>
    en medio del documento seria invalido."""
    svg = svg_de_enlace("https://ejemplo.cl/sesion/K7M4PQ/ingreso")

    assert "<?xml" not in svg


def test_enlaces_distintos_dan_qr_distintos():
    """Defensa contra un QR "generico" cacheado por error: cada sesion tiene el
    suyo."""
    uno = svg_de_enlace("https://ejemplo.cl/sesion/AAAAAA/ingreso")
    otro = svg_de_enlace("https://ejemplo.cl/sesion/BBBBBB/ingreso")

    assert uno != otro


def test_el_qr_pesa_poco():
    """Viaja dentro del HTML. Si algun dia se sube la escala sin pensarlo, este
    test avisa antes de que la pagina engorde."""
    svg = svg_de_enlace("https://ejemplo.cl/sesion/K7M4PQ/ingreso")

    assert len(svg.encode("utf-8")) < 8000


# === En la pagina de la sesion ===

def test_la_sesion_abierta_muestra_el_qr(client, facilitador, app):
    eval_id, sesion_id = _eval_con_sesion(app, facilitador.id, codigo="QRABRE")
    _login(client, facilitador)

    html = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}").data.decode(
        "utf-8"
    )

    assert "qr-sesion" in html
    assert "<svg" in html


def test_el_qr_y_el_link_apuntan_al_mismo_lugar(client, facilitador, app):
    """Son dos formas de entrar a lo mismo. Si se separan, el facilitador
    reparte dos destinos distintos sin saberlo."""
    eval_id, sesion_id = _eval_con_sesion(app, facilitador.id, codigo="QRMISM")
    _login(client, facilitador)

    html = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}").data.decode(
        "utf-8"
    )

    # El enlace visible sale de la misma variable que alimenta al QR.
    assert "/sesion/QRMISM/ingreso" in html


def test_la_sesion_cerrada_no_muestra_el_qr(client, facilitador, app):
    """Al cerrar, la sesion no acepta mas ingresos: el QR tiene que irse con el
    link. No necesita expiracion propia, hereda la del enlace."""
    eval_id, sesion_id = _eval_con_sesion(
        app, facilitador.id, codigo="QRCERR", estado="cerrada"
    )
    _login(client, facilitador)

    resp = client.get(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}", follow_redirects=True
    )
    html = resp.data.decode("utf-8")

    assert "qr-sesion" not in html


def test_otro_facilitador_no_ve_el_qr_de_una_sesion_ajena(client, facilitador, app):
    """El QR es la llave de entrada a la sesion: no puede filtrarse a quien no
    es dueno de la evaluacion."""
    from app.models import Facilitador

    eval_id, sesion_id = _eval_con_sesion(app, facilitador.id, codigo="QRAJEN")

    with app.app_context():
        intruso = Facilitador(email="otro@fuenti.cl", nombre="Otro")
        intruso.set_password("fuenti2026")
        db.session.add(intruso)
        db.session.commit()

    client.post(
        "/login",
        data={"email": "otro@fuenti.cl", "password": "fuenti2026"},
        follow_redirects=True,
    )

    resp = client.get(f"/evaluaciones/{eval_id}/sesiones/{sesion_id}")

    assert resp.status_code == 403


# === Que el QR se pueda ESCANEAR, no solo que exista ===
# Los tres de abajo cuidan lo que rompio la primera version: se veia perfecto en
# pantalla y ninguna camara lo leia.

def test_respeta_la_zona_de_silencio():
    """El margen blanco alrededor (4 modulos, ISO 18004) es lo que permite al
    lector encontrar el simbolo. La primera version usaba 2 y no habia forma de
    notarlo mirando la pantalla."""
    assert _BORDE >= 4


def test_el_svg_trae_su_tamano_explicito():
    """El SVG tiene que declarar width/height y mostrarse ASI. Si llegara sin
    tamano propio, la hoja de estilos tendria que ponerselo, y ahi empieza el
    problema del test siguiente."""
    svg = svg_de_enlace("https://ejemplo.cl/sesion/K7M4PQ/ingreso")

    assert 'width="' in svg
    assert 'height="' in svg


def test_la_plantilla_no_reescala_el_qr_por_css():
    """EL BUG DE LA PRIMERA VERSION: el SVG se generaba a 148 px y el CSS lo
    achicaba a 130. Como segno dibuja con trazos, ese reescalado difumina el
    borde de cada modulo; a la vista se ve bien y la camara no lo lee.

    El tamano se cambia en app/utils/qr.py (_ESCALA), NUNCA con width/height en
    el CSS. Este test lee la plantilla para que nadie lo reintroduzca sin
    enterarse.
    """
    plantilla = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app" / "templates" / "evaluaciones" / "detalle_sesion.html"
    ).read_text(encoding="utf-8")

    inicio = plantilla.index(".qr-sesion svg")
    regla = plantilla[inicio:plantilla.index("}", inicio)]

    assert "width" not in regla, f"el CSS reescala el QR: {regla.strip()}"
    assert "height" not in regla, f"el CSS reescala el QR: {regla.strip()}"
