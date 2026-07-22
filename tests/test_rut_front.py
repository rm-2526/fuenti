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


RUT_INVALIDO = "11.111.111-2"  # DV incorrecto


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
