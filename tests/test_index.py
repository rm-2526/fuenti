"""Tests de la portada.

La portada es publica y apunta a un solo lado: el facilitador. El participante
NO llega por aca —recibe el enlace directo de su sesion—, y ese es justamente
el detalle que estos tests cuidan, porque es una decision facil de deshacer sin
darse cuenta al agregar una seccion nueva.
"""


def test_la_portada_responde(client):
    resp = client.get("/")

    assert resp.status_code == 200


def test_la_portada_es_publica(client):
    """Nadie llega con cuenta la primera vez: no puede redirigir al login."""
    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 200


def test_la_portada_ya_no_dice_hola_fuenti(client):
    """Se reemplazo el placeholder. Si vuelve, algo se revirtio."""
    html = client.get("/").data.decode("utf-8")

    assert "Hola Fuenti" not in html


def test_la_portada_lleva_al_login(client):
    """La unica puerta: no hay registro publico, las cuentas de facilitador
    las crea un administrador."""
    html = client.get("/").data.decode("utf-8")

    assert "/login" in html


def test_la_portada_no_ofrece_entrar_con_codigo(client):
    """Decision de producto: el participante llega por el enlace de su sesion,
    no escribiendo un codigo. Una caja de codigo en la portada prometeria un
    flujo que la app no tiene."""
    html = client.get("/").data.decode("utf-8")

    assert 'id="form-codigo"' not in html
    assert "__CODIGO__" not in html


def test_la_portada_no_necesita_javascript(client):
    """Quedo sin scripts propios. Si vuelve a aparecer uno, que sea a
    conciencia: es la clase de archivo que despues se cachea viejo."""
    html = client.get("/").data.decode("utf-8")

    assert "<script" not in html


def test_la_portada_ofrece_como_contactar(client):
    """Sin registro publico, escribir es el unico camino para una cuenta
    nueva. Si el enlace se rompe, el visitante interesado queda sin salida."""
    html = client.get("/").data.decode("utf-8")

    assert "mailto:" in html


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
