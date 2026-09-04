import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    # Algunos proveedores entregan la URL con esquema "postgres://", que
    # SQLAlchemy 2.0 ya no acepta. Se normaliza aca para no depender de como
    # venga escrita la variable de entorno.
    _url = os.environ.get("DATABASE_URL", "sqlite:///fuenti.db")
    if _url.startswith("postgres://"):
        _url = _url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _url

    # Resiliencia frente a la suspension por inactividad de Neon (~5 min de
    # ocio suspenden el compute). Sin esto, la primera peticion despues de una
    # pausa saca del pool una conexion que el servidor ya cerro por su lado y
    # responde 500. Con pool_pre_ping SQLAlchemy la verifica antes de
    # entregarla, la descarta si esta muerta y abre una nueva: la peticion se
    # completa, solo mas lenta (lo que tarde Neon en despertar). pool_recycle
    # cierra proactivamente las conexiones viejas antes de que las corte Neon,
    # y connect_timeout acota el peor caso: si la base no responde en 10s falla
    # ahi, en vez de colgarse hasta el timeout de gunicorn.
    #
    # Solo aplica a Postgres. En local y en los tests se usa SQLite, cuyo
    # driver NO acepta connect_timeout y lanzaria TypeError al abrir la
    # conexion. pool_size/max_overflow se dejan en sus valores por defecto
    # (5 + 10): son holgados para un worker con 4 threads y bajarlos solo
    # arriesga que una peticion se quede esperando una conexion libre.
    SQLALCHEMY_ENGINE_OPTIONS = (
        {
            "pool_pre_ping": True,
            "pool_recycle": 240,
            "connect_args": {"connect_timeout": 10},
        }
        if _url.startswith("postgresql")
        else {}
    )

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