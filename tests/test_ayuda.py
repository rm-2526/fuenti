"""Pagina de ayuda y modal de bienvenida.

La ayuda es una pagina fija y sin estado, asi que lo que hay que garantizar es
poco pero importante: que exista, que sea publica, que este enlazada
desde el menu (o queda huerfana) y que el modal viva SOLO en el panel.
"""


def _login(client, facilitador):
    return client.post(
        "/login",
        data={"email": facilitador.email, "password": "fuenti2026"},
        follow_redirects=True,
    )


def test_la_ayuda_es_publica(client):
    """Es el manual de usuario, no datos operativos: se consulta sin cuenta
    para poder citarla desde el informe y compartirla por enlace."""
    respuesta = client.get("/ayuda")

    assert respuesta.status_code == 200
    assert "Cómo funciona Fuenti" in respuesta.data.decode("utf-8")


def test_la_ayuda_cubre_los_cinco_pasos(client, facilitador):
    """Si alguien recorta la pagina, que se note aca antes que en produccion."""
    _login(client, facilitador)

    html = client.get("/ayuda").data.decode("utf-8")

    assert "Cómo funciona Fuenti" in html
    for hito in [
        "Crea una evaluación",
        "Inicia una sesión",
        "Sigue el avance",
        "Cierra la sesión",
        "Lee los informes",
    ]:
        assert hito in html


def test_la_ayuda_esta_enlazada_desde_el_menu(client, facilitador):
    """Una pagina sin enlace es una pagina que nadie encuentra."""
    _login(client, facilitador)

    html = client.get("/dashboard").data.decode("utf-8")

    assert 'href="/ayuda"' in html
    assert "Cómo funciona" in html
    # Y tambien como tarjeta del panel: el menu se descubre poco. La tarjeta ya
    # no tiene boton propio (toda ella es el enlace), asi que se verifica por su
    # descripcion, que es lo que quedo como texto visible.
    assert "El recorrido completo" in html


def test_el_modal_de_bienvenida_solo_esta_en_el_panel(client, facilitador):
    """Un modal encima de una sesion en curso interrumpe a quien ya sabe lo que
    hace. Por eso vive solo en el panel."""
    _login(client, facilitador)

    panel = client.get("/dashboard").data.decode("utf-8")
    biblioteca = client.get("/evaluaciones/").data.decode("utf-8")

    assert "modalBienvenida" in panel
    assert "modalBienvenida" not in biblioteca
