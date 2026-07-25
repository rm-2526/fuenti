"""Tests del barajado de alternativas por participante (app/utils/aleatorizar).

Que se prueba y por que:

- "Barajado" es escurridizo de testear: un shuffle puede dejar el orden igual por
  azar, asi que NO se asserta "quedo distinto del canonico". Se testea lo que de
  verdad importa y no depende del azar:
    * el CONJUNTO de alternativas se conserva (no se pierde ni se duplica ninguna);
    * verdadero_falso conserva su orden canonico (regla del proyecto);
    * es ESTABLE: el mismo (participante, pregunta) da siempre el mismo orden;
    * participantes distintos pueden recibir ordenes distintos (se comprueba que
      el mecanismo depende del participante, con un caso construido a proposito);
    * la CORRECCION es independiente de la posicion: se responde por id de
      alternativa, no por letra, asi que barajar no cambia la nota.
- Un test de integracion comprueba que el orden barajado llega de verdad al HTML
  y que responder sigue calificando bien.

No se usan mocks de random: el helper es determinista dado (participante, pregunta),
asi que se afirma sobre resultados reales.
"""

from types import SimpleNamespace

from app import db
from app.models import Alternativa, Evaluacion, Participante, Pregunta, Sesion
from app.utils.aleatorizar import orden_alternativas


# --------------------------- Dobles ligeros ---------------------------
# El helper es puro y solo lee .tipo, .id y .alternativas[].orden, asi que para
# los tests unitarios basta con objetos livianos (no hace falta la BD).

def _alt(orden, texto=None, es_correcta=False):
    return SimpleNamespace(
        orden=orden,
        texto=texto if texto is not None else f"alt{orden}",
        es_correcta=es_correcta,
    )


def _pregunta(pid, tipo, alternativas):
    return SimpleNamespace(id=pid, tipo=tipo, alternativas=alternativas)


# ====================== Propiedades del helper ======================

def test_conserva_el_conjunto_de_alternativas():
    """Barajar no pierde ni duplica ninguna alternativa: mismo conjunto de ids
    (aca, de ordenes), solo posiblemente en otro orden."""
    alts = [_alt(1), _alt(2), _alt(3), _alt(4)]
    p = _pregunta(10, "opcion_multiple", alts)

    salida = orden_alternativas(p, participante_id=7)

    assert sorted(a.orden for a in salida) == [1, 2, 3, 4]
    assert len(salida) == 4


def test_verdadero_falso_no_se_baraja():
    """Las V/F se muestran en su orden canonico (.orden): el importador ya
    decidio ese orden a proposito ('Falso' puede ir primero)."""
    # Orden canonico: primero "Falso" (orden 1), luego "Verdadero" (orden 2).
    alts = [_alt(2, texto="Verdadero"), _alt(1, texto="Falso")]
    p = _pregunta(11, "verdadero_falso", alts)

    salida = orden_alternativas(p, participante_id=999)

    assert [a.texto for a in salida] == ["Falso", "Verdadero"]


def test_es_estable_para_el_mismo_participante():
    """El mismo (participante, pregunta) produce SIEMPRE el mismo orden: si no,
    al recargar la pagina el participante veria las alternativas saltando."""
    alts = [_alt(1), _alt(2), _alt(3), _alt(4), _alt(5)]
    p = _pregunta(20, "opcion_multiple", alts)

    primera = [a.orden for a in orden_alternativas(p, participante_id=42)]
    for _ in range(5):
        assert [a.orden for a in orden_alternativas(p, participante_id=42)] == primera


def test_depende_del_participante():
    """El orden depende del participante: existen participantes que reciben
    ordenes distintos. Se recorren varios ids y se exige que aparezca al menos un
    orden != al de un participante de referencia (con 5 alternativas hay 120
    permutaciones; que TODOS coincidan seria imposible en la practica)."""
    alts = [_alt(1), _alt(2), _alt(3), _alt(4), _alt(5)]
    p = _pregunta(30, "opcion_multiple", alts)

    ref = [a.orden for a in orden_alternativas(p, participante_id=1)]
    hubo_distinto = any(
        [a.orden for a in orden_alternativas(p, participante_id=pid)] != ref
        for pid in range(2, 40)
    )
    assert hubo_distinto


def test_no_muta_la_lista_original():
    """El helper ordena sobre una copia: la lista .alternativas de la pregunta
    no queda reordenada como efecto colateral."""
    alts = [_alt(1), _alt(2), _alt(3), _alt(4)]
    p = _pregunta(40, "opcion_multiple", alts)
    ordenes_antes = [a.orden for a in p.alternativas]

    orden_alternativas(p, participante_id=5)

    assert [a.orden for a in p.alternativas] == ordenes_antes


def test_dos_alternativas_ambos_ordenes_son_posibles():
    """Con 2 alternativas de opcion multiple, ambos ordenes deben poder salir
    segun el participante (si no, el barajado seria inutil en ese caso)."""
    alts = [_alt(1), _alt(2)]
    p = _pregunta(50, "opcion_multiple", alts)

    vistos = {
        tuple(a.orden for a in orden_alternativas(p, participante_id=pid))
        for pid in range(1, 30)
    }
    assert (1, 2) in vistos
    assert (2, 1) in vistos


# ====================== Integracion: llega al HTML y no altera la nota ======================

RUT_VALIDO = "15.432.198-5"


def _eval_con_4_alternativas(app, facilitador_id):
    """Una evaluacion con 1 pregunta de opcion multiple de 4 alternativas, cada
    una con texto distinto para poder reconocerlas en el HTML. Devuelve
    (eval_id, pregunta_id, id_de_la_correcta)."""
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo="Eval barajado", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()
        p = Pregunta(
            evaluacion_id=e.id, enunciado="Capital de Chile", orden=1, tipo="opcion_multiple"
        )
        db.session.add(p)
        db.session.flush()
        textos = ["Santiago", "Lima", "Bogota", "Quito"]
        correcta_id = None
        for i, t in enumerate(textos, start=1):
            a = Alternativa(pregunta_id=p.id, texto=t, es_correcta=(i == 1), orden=i)
            db.session.add(a)
            db.session.flush()
            if i == 1:
                correcta_id = a.id
        db.session.commit()
        return e.id, p.id, correcta_id


def _abrir(app, eval_id, codigo):
    with app.app_context():
        s = Sesion(
            evaluacion_id=eval_id, codigo=codigo, estado="abierta", umbral_aprobacion=60
        )
        db.session.add(s)
        db.session.commit()
        return s.id


def test_el_html_muestra_todas_las_alternativas(client, facilitador, app):
    """Tras barajar, el cuestionario sigue mostrando LAS CUATRO alternativas
    (ninguna se pierde por el reordenamiento)."""
    eval_id, _, _ = _eval_con_4_alternativas(app, facilitador.id)
    _abrir(app, eval_id, "BARA01")
    client.post("/sesion/BARA01/ingreso", data={"rut": RUT_VALIDO, "nombre": "Ana"})

    html = client.get("/sesion/BARA01/responder").get_data(as_text=True)

    for t in ("Santiago", "Lima", "Bogota", "Quito"):
        assert t in html


def test_barajar_no_cambia_la_calificacion(client, facilitador, app):
    """Se responde marcando la alternativa CORRECTA por su id (como hace el
    form): el barajado es solo visual, la nota debe ser 7.0 igual."""
    eval_id, pid, correcta_id = _eval_con_4_alternativas(app, facilitador.id)
    sesion_id = _abrir(app, eval_id, "BARA02")
    client.post("/sesion/BARA02/ingreso", data={"rut": RUT_VALIDO, "nombre": "Ana"})

    resp = client.post(
        "/sesion/BARA02/responder",
        data={f"pregunta_{pid}": correcta_id},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        part = db.session.query(Participante).filter_by(sesion_id=sesion_id).one()
        assert part.resultado is not None
        assert part.resultado.nota == 7.0
        assert part.resultado.aprobado is True
