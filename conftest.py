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

import pytest

from app import create_app, db
from app.models import Facilitador


@pytest.fixture
def app():
    app = create_app()
    app.config.update(TESTING=True)
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