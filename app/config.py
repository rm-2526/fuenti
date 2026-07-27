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
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    # Segundos de pausa ENTRE llamadas al modelo, para no pasarse del límite por
    # minuto (RPM) del tier gratis. Con Flash-Lite (~15 RPM) 4s va holgado; si se
    # usa el Flash normal (~5 RPM) conviene subirlo a ~13. El backoff de gemini.py
    # cubre los 429 que igual se escapen.
    GEMINI_ESPACIADO_SEG = float(os.environ.get("GEMINI_ESPACIADO_SEG", "4"))