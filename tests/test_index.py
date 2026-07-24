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


# === La franja de la escala (control del umbral) ===
# Explica el diferenciador del producto: la nota 4,0 no esta fija en un
# porcentaje, cae donde el facilitador ponga el umbral. Es interactiva a
# proposito y SIN JavaScript (ver el test de arriba): radios + :checked.

def test_la_escala_ofrece_varios_umbrales(client):
    html = client.get("/").data.decode("utf-8")

    for umbral in ("umbral-50", "umbral-60", "umbral-70", "umbral-80"):
        assert f'id="{umbral}"' in html, umbral


def test_la_escala_muestra_las_dos_dimensiones(client):
    """Antes solo mostraba notas (1,0 / 4,0 / 7,0) y el texto hablaba de un
    umbral que no se veia por ninguna parte. Ahora el eje es el % de logro."""
    html = client.get("/").data.decode("utf-8")

    assert "% de logro" in html
    assert "0%" in html and "100%" in html    # extremos del eje
    assert "1,0" in html and "7,0" in html    # extremos de la nota


def test_el_control_del_umbral_es_accesible(client):
    """Los radios se ocultan a la vista pero deben seguir siendo un grupo de
    radios de verdad: enfocables y manejables con las flechas. Cada label
    apunta a su input."""
    html = client.get("/").data.decode("utf-8")

    assert html.count('name="umbral"') == 4
    for umbral in ("umbral-50", "umbral-60", "umbral-70", "umbral-80"):
        assert f'for="{umbral}"' in html, umbral


def test_la_escala_arranca_con_un_umbral_marcado(client):
    """Sin un radio marcado de entrada, el 4,0 no tendria posicion y la franja
    apareceria rota."""
    html = client.get("/").data.decode("utf-8")

    assert "checked" in html
