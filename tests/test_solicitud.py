"""Solicitud publica de acceso y su resolucion por el administrador.

Lo que hay que garantizar es acotado pero delicado: que una solicitud no otorgue
acceso por si sola, que el formulario no sirva para averiguar quien tiene cuenta,
que aprobar reutilice el alta de siempre y que rechazar solo alcance a registros
sin historia.
"""
import secrets

from app import db
from app.models import Evaluacion, Facilitador


def _login(client, facilitador, password="fuenti2026"):
    return client.post(
        "/login",
        data={"email": facilitador.email, "password": password},
        follow_redirects=True,
    )


def _solicitar(client, email="nueva@empresa.cl", nombre="Ana Solis",
               organizacion="Constructora Andes"):
    return client.post(
        "/solicitud",
        data={"nombre": nombre, "email": email, "organizacion": organizacion},
        follow_redirects=True,
    )


# ---------------------------------------------------------------- formulario


def test_el_formulario_de_solicitud_es_publico(client):
    """Es la puerta de entrada: no puede exigir sesion iniciada."""
    respuesta = client.get("/solicitud")

    assert respuesta.status_code == 200
    assert "Solicitar acceso" in respuesta.data.decode("utf-8")


def test_la_solicitud_crea_un_registro_pendiente(client, app):
    _solicitar(client)

    with app.app_context():
        f = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == "nueva@empresa.cl")
        )
        assert f is not None
        assert f.aprobado is False
        assert f.organizacion == "Constructora Andes"
        assert f.es_admin is False


def test_una_solicitud_pendiente_no_da_acceso(client, app):
    """Aunque alguien acertara la clave, el estado debe bloquear igual."""
    _solicitar(client)

    with app.app_context():
        f = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == "nueva@empresa.cl")
        )
        f.set_password("clave-conocida")
        db.session.commit()

    respuesta = client.post(
        "/login",
        data={"email": "nueva@empresa.cl", "password": "clave-conocida"},
        follow_redirects=True,
    )
    html = respuesta.data.decode("utf-8")

    assert "en revisión" in html
    # Y NO el mensaje de cuenta desactivada: nunca tuvo cuenta.
    assert "desactivada" not in html


def test_el_formulario_no_revela_si_el_correo_ya_existe(client, facilitador, app):
    """Misma respuesta exista o no: si no, es un detector de cuentas."""
    with app.app_context():
        total_antes = db.session.scalar(
            db.select(db.func.count()).select_from(Facilitador)
        )

    respuesta = _solicitar(client, email=facilitador.email)
    html = respuesta.data.decode("utf-8")

    assert "Recibimos tu solicitud" in html
    assert "ya existe" not in html.lower()

    with app.app_context():
        total_despues = db.session.scalar(
            db.select(db.func.count()).select_from(Facilitador)
        )
    assert total_despues == total_antes


def test_la_solicitud_incompleta_no_crea_registro(client, app):
    client.post(
        "/solicitud",
        data={"nombre": "", "email": "sin-nombre@empresa.cl", "organizacion": "X"},
        follow_redirects=True,
    )

    with app.app_context():
        f = db.session.scalar(
            db.select(Facilitador).where(
                Facilitador.email == "sin-nombre@empresa.cl"
            )
        )
    assert f is None


# ------------------------------------------------------------------- panel


def test_las_solicitudes_no_aparecen_como_cuentas(client, app):
    """Pendientes y cuentas van en listados separados."""
    _solicitar(client)

    with app.app_context():
        admin = Facilitador(
            email="admin@fuenti.cl", nombre="Admin", es_admin=True, aprobado=True
        )
        admin.set_password("fuenti2026")
        db.session.add(admin)
        db.session.commit()

    _login(client, type("F", (), {"email": "admin@fuenti.cl"})())
    html = client.get("/admin/facilitadores").data.decode("utf-8")

    assert "Solicitudes de acceso" in html
    assert "Constructora Andes" in html


def test_aprobar_convierte_la_solicitud_en_cuenta(client, app):
    _solicitar(client)

    with app.app_context():
        admin = Facilitador(
            email="admin@fuenti.cl", nombre="Admin", es_admin=True, aprobado=True
        )
        admin.set_password("fuenti2026")
        db.session.add(admin)
        db.session.commit()
        pendiente_id = db.session.scalar(
            db.select(Facilitador.id).where(
                Facilitador.email == "nueva@empresa.cl"
            )
        )

    _login(client, type("F", (), {"email": "admin@fuenti.cl"})())
    respuesta = client.post(
        f"/admin/solicitudes/{pendiente_id}/aprobar", follow_redirects=True
    )
    html = respuesta.data.decode("utf-8")

    assert "aprobada" in html
    # Aprobar emite el mismo enlace de activacion que la creacion desde el panel.
    assert "/activar/" in html

    with app.app_context():
        f = db.session.get(Facilitador, pendiente_id)
        assert f.aprobado is True


def test_rechazar_elimina_la_solicitud_y_libera_el_correo(client, app):
    _solicitar(client)

    with app.app_context():
        admin = Facilitador(
            email="admin@fuenti.cl", nombre="Admin", es_admin=True, aprobado=True
        )
        admin.set_password("fuenti2026")
        db.session.add(admin)
        db.session.commit()
        pendiente_id = db.session.scalar(
            db.select(Facilitador.id).where(
                Facilitador.email == "nueva@empresa.cl"
            )
        )

    _login(client, type("F", (), {"email": "admin@fuenti.cl"})())
    client.post(f"/admin/solicitudes/{pendiente_id}/rechazar", follow_redirects=True)

    with app.app_context():
        assert db.session.get(Facilitador, pendiente_id) is None

    # La direccion queda libre: puede volver a solicitar. Se cierra sesion
    # primero porque /solicitud manda al panel a quien ya tiene una: alguien
    # autenticado no necesita pedir acceso.
    client.get("/logout", follow_redirects=True)
    _solicitar(client)
    with app.app_context():
        assert (
            db.session.scalar(
                db.select(Facilitador).where(
                    Facilitador.email == "nueva@empresa.cl"
                )
            )
            is not None
        )


def test_no_se_puede_rechazar_una_cuenta_aprobada(client, app):
    """El borrado fisico no debe alcanzar a cuentas con historia: la cascada
    llega hasta respuestas y resultados."""
    with app.app_context():
        admin = Facilitador(
            email="admin@fuenti.cl", nombre="Admin", es_admin=True, aprobado=True
        )
        admin.set_password("fuenti2026")
        otro = Facilitador(
            email="otro@fuenti.cl", nombre="Otro", es_admin=False, aprobado=True
        )
        otro.set_password(secrets.token_urlsafe(16))
        db.session.add_all([admin, otro])
        db.session.commit()
        otro_id = otro.id

    _login(client, type("F", (), {"email": "admin@fuenti.cl"})())
    respuesta = client.post(f"/admin/solicitudes/{otro_id}/rechazar")

    assert respuesta.status_code == 403
    with app.app_context():
        assert db.session.get(Facilitador, otro_id) is not None


def test_no_se_puede_aprobar_dos_veces(client, app):
    with app.app_context():
        admin = Facilitador(
            email="admin@fuenti.cl", nombre="Admin", es_admin=True, aprobado=True
        )
        admin.set_password("fuenti2026")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, type("F", (), {"email": "admin@fuenti.cl"})())
    respuesta = client.post(f"/admin/solicitudes/{admin_id}/aprobar")

    assert respuesta.status_code == 403


def test_un_facilitador_normal_no_resuelve_solicitudes(client, facilitador, app):
    _solicitar(client)

    with app.app_context():
        pendiente_id = db.session.scalar(
            db.select(Facilitador.id).where(
                Facilitador.email == "nueva@empresa.cl"
            )
        )

    _login(client, facilitador)

    assert client.post(f"/admin/solicitudes/{pendiente_id}/aprobar").status_code == 403
    assert client.post(f"/admin/solicitudes/{pendiente_id}/rechazar").status_code == 403


def test_las_cuentas_creadas_desde_el_panel_nacen_aprobadas(client, app):
    with app.app_context():
        admin = Facilitador(
            email="admin@fuenti.cl", nombre="Admin", es_admin=True, aprobado=True
        )
        admin.set_password("fuenti2026")
        db.session.add(admin)
        db.session.commit()

    _login(client, type("F", (), {"email": "admin@fuenti.cl"})())
    client.post(
        "/admin/facilitadores",
        data={"nombre": "Directa", "email": "directa@empresa.cl"},
        follow_redirects=True,
    )

    with app.app_context():
        f = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == "directa@empresa.cl")
        )
        assert f is not None
        assert f.aprobado is True
