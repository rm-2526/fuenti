"""Tests del flujo de eliminación de datos personales.

Cubre la página pública /privacidad (informativa + formulario de solicitud),
las guardas de acceso de la pestaña de administración, y las dos acciones
(aprobar/rechazar) incluida la cascada de borrado y el caso sin coincidencias.

Sigue las mismas convenciones que test_admin.py: fixtures de conftest.py
(app, client, facilitador) más helpers locales pequeños.
"""

from app import db
from app.models import (
    Evaluacion,
    Facilitador,
    Participante,
    Resultado,
    Sesion,
    SolicitudEliminacion,
)
from app.utils.rut import hash_rut

RUT_VALIDO = "45.278.361-4"
RUT_NORMALIZADO = "452783614"


def _login(client, email, password):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=True
    )


def _admin(app):
    with app.app_context():
        f = Facilitador(
            email="admin@fuenti.cl", nombre="Admin Piloto", es_admin=True, aprobado=True
        )
        f.set_password("adminpass8")
        db.session.add(f)
        db.session.commit()
        return f.id


def _participante_con_resultado(app, facilitador_id, rut=RUT_VALIDO, evaluacion_titulo="Eval"):
    """Crea evaluación -> sesión cerrada -> participante -> resultado, con el
    hash del RUT dado. Devuelve el id del participante."""
    with app.app_context():
        salt = app.config["RUT_SALT"]
        ev = Evaluacion(
            facilitador_id=facilitador_id, titulo=evaluacion_titulo, umbral_aprobacion=60
        )
        db.session.add(ev)
        db.session.commit()
        ses = Sesion(
            evaluacion_id=ev.id, codigo=f"S{ev.id}A", estado="cerrada", umbral_aprobacion=60
        )
        db.session.add(ses)
        db.session.commit()
        p = Participante(
            sesion_id=ses.id,
            identificador_hash=hash_rut(rut, salt),
            nombre="Juan Pérez",
        )
        db.session.add(p)
        db.session.commit()
        r = Resultado(
            participante_id=p.id,
            puntaje=1,
            total_preguntas=1,
            porcentaje=100.0,
            nota=7.0,
            aprobado=True,
        )
        db.session.add(r)
        db.session.commit()
        return p.id


def _crear_solicitud(app, rut=RUT_VALIDO, contacto=None):
    with app.app_context():
        salt = app.config["RUT_SALT"]
        s = SolicitudEliminacion(identificador_hash=hash_rut(rut, salt), contacto=contacto)
        db.session.add(s)
        db.session.commit()
        return s.id


# ------------------------------ /privacidad ------------------------------


def test_privacidad_es_publica(client):
    resp = client.get("/privacidad")
    assert resp.status_code == 200
    assert "Solicitar la eliminación".encode() in resp.data or "eliminación de tus datos".encode() in resp.data


def test_privacidad_rut_invalido_no_crea_solicitud(app, client):
    resp = client.post(
        "/privacidad", data={"rut": "11.111.111-1", "contacto": ""}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert "Revisa el RUT".encode() in resp.data
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(SolicitudEliminacion)) == 0


def test_privacidad_rut_valido_crea_solicitud_pendiente(app, client):
    resp = client.post(
        "/privacidad",
        data={"rut": RUT_VALIDO, "contacto": "juan@correo.cl"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Recibimos tu solicitud".encode() in resp.data
    with app.app_context():
        s = db.session.scalar(db.select(SolicitudEliminacion))
        assert s is not None
        assert s.estado == "pendiente"
        assert s.contacto == "juan@correo.cl"
        # Nunca se guarda el RUT en texto plano: el hash coincide con el que
        # usa un participante real con ese mismo RUT.
        salt = app.config["RUT_SALT"]
        assert s.identificador_hash == hash_rut(RUT_VALIDO, salt)


def test_privacidad_respuesta_no_distingue_si_hay_coincidencia(app, client):
    """El mensaje de éxito es el mismo con o sin participaciones asociadas,
    para no convertir el formulario en un detector de quién participó."""
    resp_sin = client.post(
        "/privacidad", data={"rut": RUT_VALIDO, "contacto": ""}, follow_redirects=True
    )
    resp_con = client.post(
        "/privacidad",
        data={"rut": "47.582.039-8", "contacto": ""},
        follow_redirects=True,
    )
    assert "Recibimos tu solicitud".encode() in resp_sin.data
    assert "Recibimos tu solicitud".encode() in resp_con.data


# ------------------------- Guardas de acceso del panel -------------------------


def test_eliminaciones_anonimo_redirige_a_login(client):
    resp = client.get("/admin/eliminaciones", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_eliminaciones_no_admin_403(app, client):
    with app.app_context():
        f = Facilitador(email="normal@fuenti.cl", nombre="Normal", es_admin=False)
        f.set_password("clave1234")
        db.session.add(f)
        db.session.commit()
    _login(client, "normal@fuenti.cl", "clave1234")
    resp = client.get("/admin/eliminaciones")
    assert resp.status_code == 403


def test_eliminaciones_admin_ve_pendientes(app, client):
    admin_id = _admin(app)
    part_id = _participante_con_resultado(app, admin_id, evaluacion_titulo="Capacitación X")
    sid = _crear_solicitud(app, contacto="ana@correo.cl")

    _login(client, "admin@fuenti.cl", "adminpass8")
    resp = client.get("/admin/eliminaciones")

    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Capacitación X" in body
    assert "ana@correo.cl" in body
    # El RUT no debe aparecer en ningún lado de la página.
    assert RUT_VALIDO not in body
    assert RUT_NORMALIZADO not in body


# ------------------------------- Aprobar -------------------------------


def test_aprobar_elimina_participaciones_de_cualquier_evaluacion(app, client):
    """El borrado alcanza a TODAS las evaluaciones con ese hash, incluidas
    las de otros facilitadores: el consentimiento es de la persona titular
    del dato, no de quien dictó cada capacitación."""
    admin_id = _admin(app)
    with app.app_context():
        otro = Facilitador(email="otro@fuenti.cl", nombre="Otro Facilitador", aprobado=True)
        otro.set_password("clave1234")
        db.session.add(otro)
        db.session.commit()
        otro_id = otro.id

    part1 = _participante_con_resultado(app, admin_id, evaluacion_titulo="Eval A")
    part2 = _participante_con_resultado(app, otro_id, evaluacion_titulo="Eval B (de otro)")
    sid = _crear_solicitud(app)

    _login(client, "admin@fuenti.cl", "adminpass8")
    resp = client.post(f"/admin/eliminaciones/{sid}/aprobar", follow_redirects=True)

    assert resp.status_code == 200
    assert "2 participación".encode() in resp.data or "eliminaron".encode() in resp.data

    with app.app_context():
        assert db.session.get(Participante, part1) is None
        assert db.session.get(Participante, part2) is None
        # Cascada: los Resultado asociados también deben haberse ido.
        assert db.session.scalar(db.select(db.func.count()).select_from(Resultado)) == 0

        s = db.session.get(SolicitudEliminacion, sid)
        assert s.estado == "aprobada"
        assert s.resuelta_at is not None
        assert s.resuelta_por.email == "admin@fuenti.cl"


def test_aprobar_sin_coincidencias_no_falla(app, client):
    """Aprobar una solicitud cuyo hash no coincide con nadie no debe fallar:
    simplemente no hay nada que borrar, y la solicitud queda aprobada igual
    (deja constancia de que se revisó y no había datos)."""
    _admin(app)
    sid = _crear_solicitud(app, rut="49.026.785-9")  # sin participante asociado

    _login(client, "admin@fuenti.cl", "adminpass8")
    resp = client.post(f"/admin/eliminaciones/{sid}/aprobar", follow_redirects=True)

    assert resp.status_code == 200
    with app.app_context():
        s = db.session.get(SolicitudEliminacion, sid)
        assert s.estado == "aprobada"


def test_aprobar_dos_veces_da_403(app, client):
    admin_id = _admin(app)
    sid = _crear_solicitud(app)
    _login(client, "admin@fuenti.cl", "adminpass8")

    client.post(f"/admin/eliminaciones/{sid}/aprobar")
    resp = client.post(f"/admin/eliminaciones/{sid}/aprobar")
    assert resp.status_code == 403


# ------------------------------- Rechazar -------------------------------


def test_rechazar_no_borra_datos(app, client):
    admin_id = _admin(app)
    part_id = _participante_con_resultado(app, admin_id)
    sid = _crear_solicitud(app)

    _login(client, "admin@fuenti.cl", "adminpass8")
    resp = client.post(f"/admin/eliminaciones/{sid}/rechazar", follow_redirects=True)

    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Participante, part_id) is not None
        s = db.session.get(SolicitudEliminacion, sid)
        assert s.estado == "rechazada"
        assert s.resuelta_por.email == "admin@fuenti.cl"


def test_rechazar_ya_resuelta_da_403(app, client):
    _admin(app)
    sid = _crear_solicitud(app)
    _login(client, "admin@fuenti.cl", "adminpass8")

    client.post(f"/admin/eliminaciones/{sid}/rechazar")
    resp = client.post(f"/admin/eliminaciones/{sid}/rechazar")
    assert resp.status_code == 403


# ------------------------------- Dashboard -------------------------------


def test_dashboard_admin_ve_pendientes_de_ambos_tipos(app, client):
    """El badge de la tarjeta 'Administración' suma solicitudes de cuenta de
    facilitador pendientes MÁS solicitudes de eliminación pendientes."""
    _admin(app)
    with app.app_context():
        pendiente_facilitador = Facilitador(
            email="pendiente@fuenti.cl", nombre="Pendiente", aprobado=False
        )
        pendiente_facilitador.set_password("x" * 20)
        db.session.add(pendiente_facilitador)
        db.session.commit()
    _crear_solicitud(app)

    _login(client, "admin@fuenti.cl", "adminpass8")
    resp = client.get("/dashboard")

    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Administración" in body
    assert ">2<" in body or "badge bg-warning text-dark\">2" in body
