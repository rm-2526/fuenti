from flask import Blueprint

bp = Blueprint("participante", __name__, url_prefix="/sesion")

from app.participante import routes  # noqa: E402, F401