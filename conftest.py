"""Fixtures pytest para Fuenti.

Setea variables de entorno ANTES de importar la app, de modo que la
configuración usual de Config las lea y arranque con SQLite en memoria.
load_dotenv() por default no sobrescribe variables ya seteadas en os.environ,
así que esto pisa lo que pueda venir del .env solo durante los tests.
"""

import os

# Setear ANTES de importar la app
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-tests"
# Sin pausa entre llamadas al modelo durante los tests: no queremos que la suite
# duerma. En producción GEMINI_ESPACIADO_SEG trae su default real.
os.environ["GEMINI_ESPACIADO_SEG"] = "0"

import pytest

from app import create_app, db, limiter
from app.models import Facilitador


@pytest.fixture
def app():
    app = create_app()
    app.config.update(TESTING=True)
    # El rate limiting queda APAGADO en la suite. Varios tests hacen decenas de
    # POST al login o a los formularios publicos desde el mismo cliente, y con
    # el limitador activo empezarian a recibir 429 a mitad de camino. Se apaga
    # aca, en el fixture, y no con una variable de entorno, para que la
    # configuracion real de produccion no tenga una via de desactivacion.
    limiter.enabled = False
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def facilitador(app):
    f = Facilitador(email="facilitador@fuenti.cl", nombre="Facilitador Piloto")
    f.set_password("fuenti2026")
    db.session.add(f)
    db.session.commit()
    return f