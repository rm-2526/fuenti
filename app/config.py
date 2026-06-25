import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///fuenti.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUT_SALT = os.environ.get("RUT_SALT", "dev-rut-salt-cambiar-en-produccion")