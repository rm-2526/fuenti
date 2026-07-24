"""Etiqueta del tipo de pregunta en el detalle de una evaluacion.

El participante responde con radio buttons y el backend exige exactamente UNA
alternativa correcta: eso es seleccion unica. "Opcion multiple" significa lo
contrario —varias correctas a la vez, con casillas— asi que como texto de cara
al usuario prometia justo lo opuesto a lo que la app hace.

La clave tecnica del formato JSON sigue siendo `opcion_multiple` y no se toca:
es una constante heredada del importador, no un texto que alguien lea.
"""

from app import db
from app.models import Alternativa, Evaluacion, Pregunta


def _login(client, facilitador):
    return client.post(
        "/login",
        data={"email": facilitador.email, "password": "fuenti2026"},
        follow_redirects=True,
    )


def _eval_con_pregunta(app, facilitador_id, tipo="opcion_multiple"):
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo="Eval tipos", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()

        p = Pregunta(evaluacion_id=e.id, enunciado="¿2+2?", orden=1, tipo=tipo)
        db.session.add(p)
        db.session.flush()

        if tipo == "verdadero_falso":
            textos = [("Verdadero", True), ("Falso", False)]
        else:
            textos = [("4", True), ("5", False), ("6", False)]
        for i, (texto, correcta) in enumerate(textos, start=1):
            db.session.add(
                Alternativa(
                    pregunta_id=p.id, texto=texto, es_correcta=correcta, orden=i
                )
            )

        db.session.commit()
        return e.id


def test_la_pregunta_de_alternativas_se_llama_seleccion_unica(
    client, facilitador, app
):
    eval_id = _eval_con_pregunta(app, facilitador.id)
    _login(client, facilitador)

    html = client.get(f"/evaluaciones/{eval_id}").data.decode("utf-8")

    assert "Selección única" in html


def test_el_detalle_no_dice_opcion_multiple(client, facilitador, app):
    """El termino describe lo contrario de lo que la app hace: marcar VARIAS
    correctas. Si reaparece como texto visible, es una regresion."""
    eval_id = _eval_con_pregunta(app, facilitador.id)
    _login(client, facilitador)

    html = client.get(f"/evaluaciones/{eval_id}").data.decode("utf-8")

    assert "Opción múltiple" not in html


def test_verdadero_falso_conserva_su_etiqueta(client, facilitador, app):
    """Los dos tipos tienen que seguir distinguiendose: si ambos dijeran lo
    mismo, la etiqueta dejaria de informar."""
    eval_id = _eval_con_pregunta(app, facilitador.id, tipo="verdadero_falso")
    _login(client, facilitador)

    html = client.get(f"/evaluaciones/{eval_id}").data.decode("utf-8")

    assert "Verdadero / Falso" in html
    assert "Selección única" not in html


def test_la_clave_del_formato_json_sigue_siendo_opcion_multiple(
    client, facilitador, app
):
    """Distincion deliberada: cambia el texto que se LEE, no el identificador
    que el importador PARSEA. Tocar la clave romperia el parser y cualquier JSON
    ya generado."""
    _login(client, facilitador)

    html = client.get("/evaluaciones/importar").data.decode("utf-8")

    assert "opcion_multiple" in html
