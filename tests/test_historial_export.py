"""Tests de la exportacion del historial longitudinal a CSV.

Cubre:
- El helper puro filas_csv_historial: aplana por evaluacion y marca pendientes.
- La ruta de descarga: exige login, 404 si el hash no tiene sesiones cerradas
  de este facilitador, aislamiento por facilitador, y el contenido del CSV
  (cabecera + datos, con el nombre de archivo de adjunto).
"""

from app import db
from app.models import Evaluacion, Facilitador, Participante, Resultado, Sesion


# ------------------------------ helpers ------------------------------

def _login(client, email="facilitador@fuenti.cl", password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _crear_facilitador(app, email, nombre="Otro Facilitador", password="clave1234"):
    with app.app_context():
        f = Facilitador(email=email, nombre=nombre)
        f.set_password(password)
        db.session.add(f)
        db.session.commit()
        return f.id


def _crear_evaluacion(app, facilitador_id, titulo, umbral=60):
    with app.app_context():
        e = Evaluacion(
            facilitador_id=facilitador_id, titulo=titulo, umbral_aprobacion=umbral
        )
        db.session.add(e)
        db.session.commit()
        return e.id


def _crear_sesion(app, evaluacion_id, codigo, estado="cerrada", umbral=60):
    with app.app_context():
        s = Sesion(
            evaluacion_id=evaluacion_id,
            codigo=codigo,
            estado=estado,
            umbral_aprobacion=umbral,
        )
        db.session.add(s)
        db.session.commit()
        return s.id


def _agregar_persona(
    app, sesion_id, identificador_hash, nombre=None,
    finalizado=True, porcentaje=90.0, nota=6.5, aprobado=True,
):
    with app.app_context():
        p = Participante(
            sesion_id=sesion_id, identificador_hash=identificador_hash, nombre=nombre
        )
        db.session.add(p)
        db.session.flush()
        if finalizado:
            db.session.add(
                Resultado(
                    participante_id=p.id,
                    puntaje=1,
                    total_preguntas=1,
                    porcentaje=porcentaje,
                    nota=nota,
                    aprobado=aprobado,
                )
            )
        db.session.commit()
        return p.id


# ===================== helper puro: filas_csv_historial =====================

def test_filas_csv_historial_aplana_y_marca_pendiente():
    from app.utils.reporte import FilaHistorial, GrupoHistorial, filas_csv_historial

    grupos = [
        GrupoHistorial(
            evaluacion_titulo="Induccion",
            filas=[
                FilaHistorial(
                    fecha="F1", codigo="S1", porcentaje=90.0, nota=6.5,
                    umbral=60, aprobado=True,
                ),
                FilaHistorial(
                    fecha="F2", codigo="S2", porcentaje=40.0, nota=3.0,
                    umbral=60, aprobado=False,
                ),
                FilaHistorial(
                    fecha="F3", codigo="S3", porcentaje=None, nota=None,
                    umbral=60, aprobado=None,  # ingreso pero no finalizo
                ),
            ],
        )
    ]
    # El formateador de fecha se recibe por argumento: aca uno de prueba.
    filas = filas_csv_historial(grupos, formatear_fecha=lambda d: f"[{d}]")

    assert filas[0] == ["Induccion", "[F1]", "S1", "90.0", "6.5", "60", "Aprobado"]
    assert filas[1] == ["Induccion", "[F2]", "S2", "40.0", "3.0", "60", "Reprobado"]
    # Pendiente: % y nota vacios, resultado "Pendiente".
    assert filas[2] == ["Induccion", "[F3]", "S3", "", "", "60", "Pendiente"]


# ===================== ruta: exportar_historial_csv =====================

def test_export_requiere_login(client, app):
    resp = client.get("/evaluaciones/participante/loquesea/historial/export.csv")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_export_404_si_no_existe_ese_hash(client, facilitador, app):
    _login(client)
    resp = client.get("/evaluaciones/participante/hash_inexistente/historial/export.csv")
    assert resp.status_code == 404


def test_export_aislado_por_facilitador(client, facilitador, app):
    otro_id = _crear_facilitador(app, "otro@fuenti.cl")
    eval_otro = _crear_evaluacion(app, otro_id, "Ajena")
    s = _crear_sesion(app, eval_otro, "AJENA1", estado="cerrada")
    _agregar_persona(app, s, "hash_ajeno", nombre="Persona Ajena")

    _login(client)  # facilitador del fixture
    resp = client.get("/evaluaciones/participante/hash_ajeno/historial/export.csv")
    assert resp.status_code == 404


def test_export_contenido_csv(client, facilitador, app):
    eval_id = _crear_evaluacion(app, facilitador.id, "Induccion")
    s = _crear_sesion(app, eval_id, "HSES01", estado="cerrada")
    _agregar_persona(app, s, "hash_ana", nombre="Ana Soto")

    _login(client)
    resp = client.get("/evaluaciones/participante/hash_ana/historial/export.csv")

    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    disp = resp.headers["Content-Disposition"]
    assert "attachment" in disp
    assert "historial_hash_ana." in disp  # nombre de archivo con el hash corto

    cuerpo = resp.get_data(as_text=True)
    # Cabecera y datos de la fila.
    assert "Evaluación" in cuerpo
    assert "Código" in cuerpo
    assert "Induccion" in cuerpo
    assert "HSES01" in cuerpo
    assert "Aprobado" in cuerpo
