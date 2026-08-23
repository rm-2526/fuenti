"""Pruebas del enlace de activación y restablecimiento de contraseña.

Cubren las dos capas: el módulo puro (firma, vencimiento, manipulación) y el
recorrido por HTTP (establecer clave, un solo uso, cuenta desactivada).
"""

import time

from app import db
from app.models import Facilitador
from app.utils.activacion import generar_token, huella, leer_token

SECRETO = "test-secret-key-only-for-tests"


# --------------------------------------------------------------------------
# Módulo puro: sin app, sin base de datos
# --------------------------------------------------------------------------


def test_token_valido_devuelve_la_carga():
    token = generar_token(7, "pbkdf2:sha256:600000$abc$1234567890abcdef", SECRETO)
    carga = leer_token(token, SECRETO)
    assert carga["id"] == 7
    assert carga["h"] == "1234567890abcdef"


def test_token_firmado_con_otra_clave_se_rechaza():
    token = generar_token(1, "hash-cualquiera-de-prueba", SECRETO)
    assert leer_token(token, "otra-clave-distinta") is None


def test_token_manipulado_se_rechaza():
    token = generar_token(1, "hash-cualquiera-de-prueba", SECRETO)
    # Alterar un carácter del cuerpo rompe la firma.
    alterado = ("X" if token[0] != "X" else "Y") + token[1:]
    assert leer_token(alterado, SECRETO) is None


def test_token_vencido_se_rechaza():
    token = generar_token(1, "hash-cualquiera-de-prueba", SECRETO)
    time.sleep(1)
    assert leer_token(token, SECRETO, max_age=0) is None


# --------------------------------------------------------------------------
# Recorrido HTTP
# --------------------------------------------------------------------------


def test_activar_establece_la_contrasena(client, facilitador):
    token = generar_token(facilitador.id, facilitador.password_hash, SECRETO)

    r = client.post(
        f"/activar/{token}",
        data={"password": "claveNueva2026", "confirmacion": "claveNueva2026"},
        follow_redirects=True,
    )
    assert r.status_code == 200

    f = db.session.get(Facilitador, facilitador.id)
    assert f.check_password("claveNueva2026")
    assert not f.check_password("fuenti2026")


def test_el_enlace_sirve_una_sola_vez(client, facilitador):
    token = generar_token(facilitador.id, facilitador.password_hash, SECRETO)

    client.post(
        f"/activar/{token}",
        data={"password": "primeraClave2026", "confirmacion": "primeraClave2026"},
        follow_redirects=True,
    )
    # El hash cambió, así que la huella del token ya no coincide.
    client.post(
        f"/activar/{token}",
        data={"password": "segundaClave2026", "confirmacion": "segundaClave2026"},
        follow_redirects=True,
    )

    f = db.session.get(Facilitador, facilitador.id)
    assert f.check_password("primeraClave2026")
    assert not f.check_password("segundaClave2026")


def test_contrasenas_que_no_coinciden_no_persisten(client, facilitador):
    token = generar_token(facilitador.id, facilitador.password_hash, SECRETO)

    client.post(
        f"/activar/{token}",
        data={"password": "claveNueva2026", "confirmacion": "otraDistinta2026"},
        follow_redirects=True,
    )

    f = db.session.get(Facilitador, facilitador.id)
    assert f.check_password("fuenti2026")


def test_cuenta_desactivada_no_puede_activarse(client, facilitador):
    token = generar_token(facilitador.id, facilitador.password_hash, SECRETO)
    facilitador.activo = False
    db.session.commit()

    client.post(
        f"/activar/{token}",
        data={"password": "claveNueva2026", "confirmacion": "claveNueva2026"},
        follow_redirects=True,
    )

    f = db.session.get(Facilitador, facilitador.id)
    assert f.check_password("fuenti2026")


def test_huella_es_el_final_del_hash(facilitador):
    assert facilitador.password_hash.endswith(huella(facilitador.password_hash))
