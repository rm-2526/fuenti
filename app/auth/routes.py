from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse

from app import db
from app.auth import bp
from app.models import Facilitador


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        facilitador = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == email)
        )

        if facilitador is None or not facilitador.check_password(password):
            flash("Credenciales inválidas.", "danger")
            return redirect(url_for("auth.login"))

        if not facilitador.activo:
            flash("Esta cuenta está desactivada. Contacta a un administrador.", "danger")
            return redirect(url_for("auth.login"))

        login_user(facilitador)

        # Protección open-redirect: solo aceptar "next" si es relativo
        next_page = request.args.get("next")
        if not next_page or urlparse(next_page).netloc != "":
            next_page = url_for("dashboard")
        return redirect(next_page)

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))