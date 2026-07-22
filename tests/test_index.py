"""Tests de la portada.

La portada es la unica pagina que ve alguien que llega sin link directo, y
tiene dos puertas distintas: el participante que trae un codigo y el
facilitador que viene a entrar a su panel. Estos tests cuidan que las dos
sigan ahi, y que el atajo del codigo no se desarme en silencio.
"""

from app.utils.sesion import _ALFABETO_CODIGO, _LONGITUD_CODIGO


def test_la_portada_responde(client):
    resp = client.get("/")

    assert resp.status_code == 200


def test_la_portada_ya_no_dice_hola_fuenti(client):
    """Se reemplazo el placeholder. Si vuelve, algo se revirtio."""
    html = client.get("/").data.decode("utf-8")

    assert "Hola Fuenti" not in html


def test_la_portada_ofrece_las_dos_puertas(client):
    """Participante con codigo y facilitador con cuenta."""
    html = client.get("/").data.decode("utf-8")

    assert 'id="form-codigo"' in html   # puerta del participante
    assert "/login" in html             # puerta del facilitador


def test_el_formulario_de_codigo_apunta_al_ingreso_real(client):
    """El atajo arma la URL de participante.ingreso con url_for, no a mano.
    Si el blueprint cambia de prefijo, esto tiene que seguir calzando."""
    html = client.get("/").data.decode("utf-8")

    assert "/sesion/__CODIGO__/ingreso" in html


def test_el_ejemplo_de_codigo_usa_el_alfabeto_real(client):
    """El codigo de ejemplo no puede llevar caracteres que el generador nunca
    produce (0, 1, O, I, L): seria ensenarle a leer mal a quien lo dicta."""
    html = client.get("/").data.decode("utf-8")

    inicio = html.index('placeholder="') + len('placeholder="')
    ejemplo = html[inicio:html.index('"', inicio)]

    assert len(ejemplo) == _LONGITUD_CODIGO
    for caracter in ejemplo:
        assert caracter in _ALFABETO_CODIGO, caracter


def test_la_portada_no_pide_login(client):
    """Es publica: nadie llega con cuenta la primera vez."""
    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 200


def test_facilitador_conectado_ve_el_acceso_al_panel(client, facilitador):
    """Con la cuenta iniciada, la portada ofrece el panel en vez de 'Iniciar
    sesion': mandarlo a loguearse de nuevo seria un callejon."""
    client.post(
        "/login",
        data={"email": facilitador.email, "password": "fuenti2026"},
        follow_redirects=True,
    )

    html = client.get("/").data.decode("utf-8")

    assert "/dashboard" in html
