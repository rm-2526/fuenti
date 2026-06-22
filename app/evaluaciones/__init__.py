from flask import Blueprint

bp = Blueprint("evaluaciones", __name__, url_prefix="/evaluaciones")

from app.evaluaciones import routes  # noqa: E402, F401