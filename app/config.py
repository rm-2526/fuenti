import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///fuenti.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUT_SALT = os.environ.get("RUT_SALT", "dev-rut-salt-cambiar-en-produccion")

    # Análisis de fortalezas/debilidades con IA (opcional). Si GEMINI_API_KEY
    # está vacía, la feature simplemente no genera nada y el informe se muestra
    # igual con los números. En Render se setea la clave; en local y en tests se
    # deja vacía a propósito para no llamar a la red.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")