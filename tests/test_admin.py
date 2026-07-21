"""Tests del panel de administración (gestión de facilitadores).

Cubre las guardas de acceso (anónimo -> login, no-admin -> 403, admin -> 200) y
la creación de facilitadores (alta válida, rol admin, correo duplicado,
contraseña corta), incluyendo que el nuevo facilitador pueda iniciar sesión.
"""

from app import db
from app.models import Evaluacion, Facilitador


def _login(client, email, password):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=True
    )


def _crear_facilitador(app, email, nombre, password, es_admin=False):
    with app.app_context():
        f = Facilitador(email=email, nombre=nombre, es_admin=es_admin)
        f.set_password(password)
        db.session.add(f)
        db.session.commit()
        return f.id


def _admin(app):
    return _crear_facilitador(
        app, "admin@fuenti.cl", "Admin Piloto", "adminpass8", es_admin=True
    )


# ------------------------- Guardas de acceso -------------------------

def test_admin_anonimo_redirige_a_login(client):
    resp = client.get("/admin/facilitadores", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_admin_no_admin_recibe_403(client, facilitador):
    # El facilitador del fixture NO es admin (es_admin=False por defecto).
    _login(client, "facilitador@fuenti.cl", "fuenti2026")
    resp = client.get("/admin/facilitadores")
    assert resp.status_code == 403


def test_admin_no_admin_post_tambien_403(client, facilitador):
    _login(client, "facilitador@fuenti.cl", "fuenti2026")
    resp = client.post(
        "/admin/facilitadores",
        data={"nombre": "X", "email": "x@x.cl", "password": "12345678"},
    )
    assert resp.status_code == 403
    with client.application.app_context():
        assert (
            db.session.scalar(
                db.select(Facilitador).where(Facilitador.email == "x@x.cl")
            )
            is None
        )


def test_admin_ve_la_lista(client, app):
    _admin(app)
    _login(client, "admin@fuenti.cl", "adminpass8")
    resp = client.get("/admin/facilitadores")
    assert resp.status_code == 200
    assert "admin@fuenti.cl" in resp.get_data(as_text=True)


# ------------------------- Creación -------------------------

def test_admin_crea_facilitador_y_puede_loguear(client, app):
    _admin(app)
    _login(client, "admin@fuenti.cl", "adminpass8")

    resp = client.post(
        "/admin/facilitadores",
        data={
            "nombre": "Nuevo Facilitador",
            "email": "nuevo@fuenti.cl",
            "password": "clave1234",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        f = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == "nuevo@fuenti.cl")
        )
        assert f is not None
        assert f.nombre == "Nuevo Facilitador"
        assert f.es_admin is False
        assert f.check_password("clave1234")

    # El nuevo facilitador puede iniciar sesión.
    client.get("/logout")
    r = _login(client, "nuevo@fuenti.cl", "clave1234")
    assert r.status_code == 200


def test_admin_crea_otro_admin_con_checkbox(client, app):
    _admin(app)
    _login(client, "admin@fuenti.cl", "adminpass8")

    client.post(
        "/admin/facilitadores",
        data={
            "nombre": "Otra Admin",
            "email": "otra@fuenti.cl",
            "password": "clave1234",
            "es_admin": "on",
        },
        follow_redirects=True,
    )
    with app.app_context():
        f = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == "otra@fuenti.cl")
        )
        assert f is not None and f.es_admin is True


def test_admin_correo_duplicado_no_crea(client, app):
    _admin(app)
    _crear_facilitador(app, "existe@fuenti.cl", "Existente", "clave1234")
    _login(client, "admin@fuenti.cl", "adminpass8")

    resp = client.post(
        "/admin/facilitadores",
        data={
            "nombre": "Repetido",
            "email": "existe@fuenti.cl",
            "password": "otraclave1",
        },
        follow_redirects=True,
    )
    assert "Ya existe un facilitador con ese correo" in resp.get_data(as_text=True)
    with app.app_context():
        n = db.session.scalar(
            db.select(db.func.count())
            .select_from(Facilitador)
            .where(Facilitador.email == "existe@fuenti.cl")
        )
        assert n == 1  # sigue habiendo uno solo


def test_admin_password_corta_no_crea(client, app):
    _admin(app)
    _login(client, "admin@fuenti.cl", "adminpass8")

    resp = client.post(
        "/admin/facilitadores",
        data={"nombre": "Corta", "email": "corta@fuenti.cl", "password": "123"},
        follow_redirects=True,
    )
    assert "al menos 8 caracteres" in resp.get_data(as_text=True)
    with app.app_context():
        assert (
            db.session.scalar(
                db.select(Facilitador).where(Facilitador.email == "corta@fuenti.cl")
            )
            is None
        )


# ------------------------- Edición -------------------------

def test_admin_edita_nombre_email_y_rol(client, app):
    _admin(app)
    fid = _crear_facilitador(app, "edita@fuenti.cl", "Nombre Viejo", "clave1234")
    _login(client, "admin@fuenti.cl", "adminpass8")

    resp = client.post(
        f"/admin/facilitadores/{fid}/editar",
        data={"nombre": "Nombre Nuevo", "email": "nuevo@fuenti.cl", "es_admin": "on"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        f = db.session.get(Facilitador, fid)
        assert f.nombre == "Nombre Nuevo"
        assert f.email == "nuevo@fuenti.cl"
        assert f.es_admin is True


def test_admin_edita_no_puede_tomar_correo_de_otro(client, app):
    _admin(app)
    _crear_facilitador(app, "ocupado@fuenti.cl", "Otro", "clave1234")
    fid = _crear_facilitador(app, "libre@fuenti.cl", "Libre", "clave1234")
    _login(client, "admin@fuenti.cl", "adminpass8")

    resp = client.post(
        f"/admin/facilitadores/{fid}/editar",
        data={"nombre": "Libre", "email": "ocupado@fuenti.cl"},
        follow_redirects=True,
    )
    assert "Ya existe otro facilitador con ese correo" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Facilitador, fid).email == "libre@fuenti.cl"


def test_admin_no_puede_quitarse_el_rol_siendo_ultimo_admin(client, app):
    admin_id = _admin(app)  # único admin
    _login(client, "admin@fuenti.cl", "adminpass8")

    resp = client.post(
        f"/admin/facilitadores/{admin_id}/editar",
        data={"nombre": "Admin Piloto", "email": "admin@fuenti.cl"},  # sin es_admin
        follow_redirects=True,
    )
    assert "último admin" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Facilitador, admin_id).es_admin is True


def test_admin_puede_degradar_a_un_admin_si_queda_otro(client, app):
    _admin(app)  # admin A (logueado)
    b_id = _crear_facilitador(app, "b@fuenti.cl", "Admin B", "clave1234", es_admin=True)
    _login(client, "admin@fuenti.cl", "adminpass8")

    client.post(
        f"/admin/facilitadores/{b_id}/editar",
        data={"nombre": "Admin B", "email": "b@fuenti.cl"},  # sin es_admin -> degradar
        follow_redirects=True,
    )
    with app.app_context():
        assert db.session.get(Facilitador, b_id).es_admin is False  # A sigue siendo admin


# ------------------------- Desactivar / reactivar -------------------------

def test_desactivar_conserva_las_evaluaciones(client, app):
    _admin(app)
    fid = _crear_facilitador(app, "baja@fuenti.cl", "Se Va", "clave1234")
    with app.app_context():
        e = Evaluacion(facilitador_id=fid, titulo="Evaluación de X", umbral_aprobacion=60)
        db.session.add(e)
        db.session.commit()
        eval_id = e.id

    _login(client, "admin@fuenti.cl", "adminpass8")
    resp = client.post(
        f"/admin/facilitadores/{fid}/estado", follow_redirects=True
    )
    assert resp.status_code == 200
    with app.app_context():
        f = db.session.get(Facilitador, fid)
        assert f.activo is False                      # quedó desactivado
        # …pero su evaluación (y por ende sus informes) sigue existiendo:
        assert db.session.get(Evaluacion, eval_id) is not None


def test_reactivar_vuelve_a_activo(client, app):
    _admin(app)
    fid = _crear_facilitador(app, "vuelve@fuenti.cl", "Vuelve", "clave1234")
    with app.app_context():
        db.session.get(Facilitador, fid).activo = False
        db.session.commit()

    _login(client, "admin@fuenti.cl", "adminpass8")
    client.post(f"/admin/facilitadores/{fid}/estado", follow_redirects=True)
    with app.app_context():
        assert db.session.get(Facilitador, fid).activo is True


def test_admin_no_puede_desactivarse_a_si_mismo(client, app):
    admin_id = _admin(app)
    _login(client, "admin@fuenti.cl", "adminpass8")

    resp = client.post(
        f"/admin/facilitadores/{admin_id}/estado", follow_redirects=True
    )
    assert "No puedes desactivar tu propia cuenta" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Facilitador, admin_id).activo is True


def test_facilitador_desactivado_no_puede_loguear(client, app):
    fid = _crear_facilitador(app, "off@fuenti.cl", "Apagado", "clave1234")
    with app.app_context():
        db.session.get(Facilitador, fid).activo = False
        db.session.commit()

    r = _login(client, "off@fuenti.cl", "clave1234")
    assert "desactivada" in r.get_data(as_text=True)


def test_no_admin_no_puede_editar_ni_cambiar_estado(client, app, facilitador):
    otro = _crear_facilitador(app, "otro@fuenti.cl", "Otro", "clave1234")
    _login(client, "facilitador@fuenti.cl", "fuenti2026")  # no es admin
    assert client.get(f"/admin/facilitadores/{otro}/editar").status_code == 403
    assert client.post(f"/admin/facilitadores/{otro}/estado").status_code == 403
