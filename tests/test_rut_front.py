"""Tests de la ayuda visual de RUT en el formulario de ingreso.

No prueban el algoritmo en JavaScript (pytest no corre JS): prueban lo que sí
se puede probar desde el servidor y es lo que efectivamente se rompe en la
práctica.

- Que la página de ingreso PIDA el script y traiga el enganche que el script
  busca (data-rut) más los nodos de feedback. Si alguien mueve o renombra algo,
  el JS quedaría cargando sin nada que hacer, en silencio.
- Que el archivo estático se SIRVA de verdad y con el contenido nuevo. Es la
  comprobación de la lección 4 del handoff 17 (el modal que "no aparecía" y era
  caché), automatizada: si el despliegue queda a medias, esto se cae acá en vez
  de descubrirse en la sala.
- Que el servidor SIGA rechazando un RUT inválido. Es el punto entero del
  diseño: el front adelanta el veredicto, no lo reemplaza. Si algún día alguien
  "simplifica" el POST confiando en el JavaScript, este test se pone rojo.
"""

from app import db
from app.models import Alternativa, Evaluacion, Participante, Pregunta, Sesion


RUT_INVALIDO = "15.432.198-4"   # DV incorrecto
RUT_BLOQUEADO = "11.111.111-1"  # pasa modulo 11, pero no se acepta


def _sesion_abierta(app, facilitador_id, codigo="RUTFRT"):
    """Evaluación con una pregunta + sesión abierta. Devuelve el código."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo="Eval RUT", umbral_aprobacion=60
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

        db.session.add(
            Sesion(
                evaluacion_id=e.id,
                codigo=codigo,
                estado="abierta",
                umbral_aprobacion=60,
            )
        )
        db.session.commit()
        return codigo


def test_ingreso_carga_el_script_de_rut(client, facilitador, app):
    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTJS1")

    resp = client.get(f"/sesion/{codigo}/ingreso")

    assert resp.status_code == 200
    assert b"js/rut.js" in resp.data


def test_ingreso_trae_el_enganche_y_los_nodos_de_feedback(client, facilitador, app):
    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTJS2")

    resp = client.get(f"/sesion/{codigo}/ingreso")
    html = resp.data.decode("utf-8")

    # El atributo que busca rut.js para conectarse.
    assert "data-rut" in html
    # Los dos nodos donde escribe el veredicto.
    assert "valid-feedback" in html
    assert "invalid-feedback" in html


def test_el_estatico_de_rut_se_sirve_y_trae_el_modulo_11(client):
    """Abrir la URL del estático es la comprobación decisiva del handoff 17."""
    resp = client.get("/static/js/rut.js")

    assert resp.status_code == 200
    cuerpo = resp.data.decode("utf-8")
    assert "dvEsperado" in cuerpo
    assert "Fuenti.rut" in cuerpo


def test_el_servidor_sigue_rechazando_un_rut_invalido(client, facilitador, app):
    """El front es una ayuda visual: la autoridad sigue siendo el POST."""
    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTSRV")

    resp = client.post(
        f"/sesion/{codigo}/ingreso",
        data={"rut": RUT_INVALIDO, "nombre": "Juan Perez"},
        follow_redirects=False,
    )

    assert resp.status_code == 200  # re-render, no redirect
    with app.app_context():
        assert db.session.query(Participante).count() == 0


# === Bloqueo de RUT que pasan modulo 11 pero no aceptamos ===

def test_el_servidor_rechaza_un_rut_bloqueado(client, facilitador, app):
    """La regla vive en el servidor, no solo en el JS: desactivar JavaScript no
    debe alcanzar para meter una identidad falsa en el historial."""
    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTBLQ")

    resp = client.post(
        f"/sesion/{codigo}/ingreso",
        data={"rut": RUT_BLOQUEADO, "nombre": "Juan Perez"},
        follow_redirects=False,
    )

    assert resp.status_code == 200  # re-render, no redirect
    with app.app_context():
        assert db.session.query(Participante).count() == 0


def test_el_bloqueo_ignora_el_formato(client, facilitador, app):
    """Sin puntos ni guion es el mismo RUT y se rechaza igual."""
    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTBL2")

    client.post(
        f"/sesion/{codigo}/ingreso",
        data={"rut": "111111111", "nombre": "Juan Perez"},
        follow_redirects=False,
    )

    with app.app_context():
        assert db.session.query(Participante).count() == 0


def test_el_mensaje_del_bloqueo_es_distinto_al_de_formato(client, facilitador, app):
    """Dos rechazos distintos necesitan dos mensajes distintos: 'esta mal
    escrito' no le sirve a quien escribio un RUT aritmeticamente perfecto."""
    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTBL3")

    resp = client.post(
        f"/sesion/{codigo}/ingreso",
        data={"rut": RUT_BLOQUEADO, "nombre": "Juan Perez"},
        follow_redirects=True,
    )
    html = resp.data.decode("utf-8")

    assert "no se acepta" in html
    assert "Revisa el formato" not in html


def test_un_rut_normal_sigue_entrando(client, facilitador, app):
    """La red de contencion del cambio: bloquear no puede dejar fuera a nadie
    mas que a los de la lista."""
    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTOK1")

    resp = client.post(
        f"/sesion/{codigo}/ingreso",
        data={"rut": "15.432.198-5", "nombre": "Juan Perez"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.query(Participante).count() == 1


def test_el_js_espeja_la_lista_completa_del_servidor(client):
    """La lista esta duplicada (Python y JavaScript) y las copias se separan.
    Este test es el pegamento: si alguien agrega un RUT a RUTS_BLOQUEADOS y se
    olvida de rut.js, se pone rojo aca en vez de descubrirse en la sala, donde
    el rechazo llegaria recien despues de enviar el formulario."""
    from app.utils.rut import RUTS_BLOQUEADOS

    cuerpo = client.get("/static/js/rut.js").data.decode("utf-8")

    assert "BLOQUEADOS" in cuerpo
    for rut in RUTS_BLOQUEADOS:
        assert f'"{rut}"' in cuerpo, f"falta {rut} en rut.js"


def test_el_placeholder_no_muestra_un_rut_bloqueado(client, facilitador, app):
    """Pedirle a alguien que escriba un RUT que despues rechazamos seria un gol
    en contra. El ejemplo del formulario tiene que ser un RUT aceptable."""
    from app.utils.rut import es_rut_bloqueado

    codigo = _sesion_abierta(app, facilitador.id, codigo="RUTPLC")
    html = client.get(f"/sesion/{codigo}/ingreso").data.decode("utf-8")

    for bloqueado in ["12.345.678-5", "11.111.111-1", "22.222.222-2"]:
        assert bloqueado not in html, bloqueado
    assert not es_rut_bloqueado("15.432.198-5")
