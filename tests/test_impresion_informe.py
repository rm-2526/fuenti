"""Impresion del informe de sesion (la matriz).

La matriz vive dentro de un .table-responsive de Bootstrap, que trae
overflow-x:auto. En pantalla eso da el scroll horizontal y esta bien. Al
imprimir, en cambio, lo que sobresale NO se encoge: se RECORTA. Con 20 preguntas
se perdian las ultimas cinco columnas del PDF sin ningun aviso, y el informe
seguia viendose correcto en el navegador.

Es un fallo silencioso y de datos: el acta impresa decia menos de lo que la
sesion registro. Estos tests cuidan las dos defensas que se pusieron.
"""

import pathlib

from app import db
from app.models import Alternativa, Evaluacion, Pregunta, Resultado, Sesion


PLANTILLA = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app" / "templates" / "evaluaciones" / "informe_todos.html"
)


def _estilos_de_impresion():
    """Devuelve el bloque @media print de la plantilla."""
    texto = PLANTILLA.read_text(encoding="utf-8")
    inicio = texto.index("@media print")
    return texto[inicio:texto.index("</style>", inicio)]


def test_la_impresion_no_recorta_la_tabla():
    """EL BUG: sin esto, .table-responsive recorta las columnas que sobran y el
    PDF sale incompleto sin avisar."""
    assert "overflow: visible" in _estilos_de_impresion()


def test_la_impresion_usa_hoja_horizontal():
    """Una matriz es ancha por naturaleza; en vertical cabe la mitad."""
    assert "landscape" in _estilos_de_impresion()


def test_la_impresion_compacta_la_matriz():
    """Reducir letra y padding es lo que permite pasar de ~15 preguntas a ~33
    en una hoja A4 horizontal."""
    estilos = _estilos_de_impresion()

    assert ".matriz" in estilos
    assert "font-size" in estilos


def test_el_nombre_no_se_trunca_al_imprimir():
    """El informe es un acta: cortar un apellido con '…' pierde el dato que
    identifica a la persona. Se parte en dos lineas, que ocupa lo mismo."""
    estilos = _estilos_de_impresion()
    inicio = estilos.index(".matriz td.nom")
    regla = estilos[inicio:estilos.index("}", inicio)]

    assert "normal" in regla, "el nombre debe poder partirse en varias lineas"
    assert "ellipsis" not in regla, "no truncar nombres en un acta"


# === El aviso para evaluaciones muy largas ===

def _login(client, facilitador):
    return client.post(
        "/login",
        data={"email": facilitador.email, "password": "fuenti2026"},
        follow_redirects=True,
    )


def _sesion_con_n_preguntas(app, facilitador_id, n, codigo="PRN123"):
    """Sesion cerrada con n preguntas y un participante que la rindio."""
    from app.models import Participante, Respuesta, ahora_utc
    from app.utils.rut import hash_rut

    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo="Eval larga", umbral_aprobacion=60
        )
        db.session.add(e)
        db.session.flush()

        preguntas = []
        for i in range(n):
            p = Pregunta(evaluacion_id=e.id, enunciado=f"Pregunta {i + 1}", orden=i + 1)
            db.session.add(p)
            db.session.flush()
            correcta = Alternativa(
                pregunta_id=p.id, texto="A", es_correcta=True, orden=1
            )
            db.session.add(correcta)
            db.session.add(
                Alternativa(pregunta_id=p.id, texto="B", es_correcta=False, orden=2)
            )
            db.session.flush()
            preguntas.append((p, correcta))

        s = Sesion(
            evaluacion_id=e.id, codigo=codigo, estado="cerrada", umbral_aprobacion=60
        )
        db.session.add(s)
        db.session.flush()

        part = Participante(
            sesion_id=s.id,
            nombre="Ana Soto",
            identificador_hash=hash_rut("15.432.198-5", "salt"),
        )
        part.finalizado_at = ahora_utc()
        db.session.add(part)
        db.session.flush()

        for p, correcta in preguntas:
            db.session.add(
                Respuesta(
                    participante_id=part.id,
                    pregunta_id=p.id,
                    alternativa_id=correcta.id,
                    enunciado_texto=p.enunciado,
                    elegida_texto="A",
                    correcta_texto="A",
                    acerto=True,
                    orden=p.orden,
                )
            )
        db.session.add(
            Resultado(
                participante_id=part.id,
                puntaje=n,
                total_preguntas=n,
                porcentaje=100,
                nota=7.0,
                aprobado=True,
                evaluacion_titulo=e.titulo,
                umbral_aprobacion=60,
            )
        )
        db.session.commit()
        return e.id, s.id


def test_una_evaluacion_larga_avisa_antes_de_imprimir(client, facilitador, app):
    """Pasadas ~35 preguntas la matriz ya no cabe ni compacta. Si se va a
    perder informacion al imprimir, la persona tiene que saberlo ANTES y tener
    a mano la salida completa (el CSV)."""
    eval_id, sesion_id = _sesion_con_n_preguntas(app, facilitador.id, 40, "PRNLAR")
    _login(client, facilitador)

    html = client.get(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/informe-todos"
    ).data.decode("utf-8")

    assert "no quepan" in html
    assert "Exportar CSV" in html


def test_una_evaluacion_normal_no_muestra_el_aviso(client, facilitador, app):
    """El aviso solo cuando de verdad hay riesgo: si aparece siempre, se
    convierte en ruido y nadie lo lee."""
    eval_id, sesion_id = _sesion_con_n_preguntas(app, facilitador.id, 10, "PRNCOR")
    _login(client, facilitador)

    html = client.get(
        f"/evaluaciones/{eval_id}/sesiones/{sesion_id}/informe-todos"
    ).data.decode("utf-8")

    assert "no quepan" not in html
