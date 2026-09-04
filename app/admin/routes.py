"""Panel de administración: gestión de facilitadores.

Solo accesible por facilitadores con es_admin=True. El primer administrador se
crea/promueve con scripts/seed_facilitador.py --admin (no por este panel, ya que
requeriría un admin previo).

Invariante de credenciales. El panel NO permite fijar ni cambiar contraseñas de
nadie. Al crear una cuenta se le asigna una clave aleatoria que nadie conoce, y
el titular establece la suya a través de un enlace de activación firmado
(app/utils/activacion.py). Mientras esto fue opcional era una buena práctica que
dependía de que el administrador la eligiera cada vez; al retirar el campo pasa
a ser una propiedad del sistema.

Lo que esto garantiza, y lo que no. No impide que un administrador se apodere de
una cuenta ajena: puede emitir un enlace y usarlo. Lo que impide es que lo haga
sin dejar rastro, porque al establecer una clave nueva la anterior deja de
funcionar y el titular lo advierte en su siguiente ingreso. La toma de control
deja de ser silenciosa.

Excepción documentada: scripts/seed_facilitador.py sí fija contraseñas, porque
es el arranque del sistema y exige acceso al servidor o a la base.
"""
import secrets
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import db
from app.admin import bp
from app.models import (
    Evaluacion,
    Facilitador,
    Participante,
    Sesion,
    SolicitudEliminacion,
    ahora_utc,
)
from app.utils.activacion import ACTIVACION_MAX_AGE, generar_token


def admin_required(view):
    """Exige sesión iniciada Y rol admin. A los no-admin les responde 403; a los
    anónimos, login_required los manda a la pantalla de login."""

    @wraps(view)
    @login_required
    def envuelta(*args, **kwargs):
        if not current_user.es_admin:
            abort(403)
        return view(*args, **kwargs)

    return envuelta


def _enlace_activacion(f):
    """URL absoluta para que f establezca su contraseña.

    Absoluta (_external=True) porque el enlace viaja fuera de la aplicación: se
    copia y se envía por correo, mensajería o se entrega en persona.
    """
    return url_for(
        "auth.activar",
        token=generar_token(f.id, f.password_hash, current_app.config["SECRET_KEY"]),
        _external=True,
    )


def _validar_nuevo_facilitador(email, nombre):
    errores = []
    if not email or "@" not in email:
        errores.append("El correo no es válido.")
    if not nombre:
        errores.append("El nombre es obligatorio.")
    return errores


@bp.route("/facilitadores", methods=["GET", "POST"])
@admin_required
def facilitadores():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nombre = request.form.get("nombre", "").strip()
        es_admin = request.form.get("es_admin") == "on"
        # La contraseña no se lee del formulario a propósito: aunque alguien la
        # envíe a mano, se ignora.

        errores = _validar_nuevo_facilitador(email, nombre)

        # Chequeo de duplicado antes de intentar insertar (mensaje claro).
        if not errores:
            existe = db.session.scalar(
                db.select(Facilitador).where(Facilitador.email == email)
            )
            if existe is not None:
                errores.append("Ya existe un facilitador con ese correo.")

        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            # aprobado=True explicito: crear la cuenta desde el panel ES el acto
            # de aprobacion. Se deja escrito y no se confia en el default del
            # modelo, porque este es el punto donde la decision se toma.
            nuevo = Facilitador(
                email=email, nombre=nombre, es_admin=es_admin, aprobado=True
            )
            # Clave aleatoria que nadie conoce ni necesita conocer: la cuenta
            # solo se abre por el enlace de activación. No se guarda en ningún
            # lado ni se muestra.
            nuevo.set_password(secrets.token_urlsafe(32))
            db.session.add(nuevo)
            try:
                db.session.commit()
                flash(f"Facilitador \"{email}\" creado.", "success")
                return redirect(
                    url_for("admin.mensaje_activacion", fid=nuevo.id)
                )
            except IntegrityError:
                # Carrera improbable: alguien insertó el mismo correo en paralelo.
                db.session.rollback()
                flash("Ya existe un facilitador con ese correo.", "danger")
            return redirect(url_for("admin.facilitadores"))

    # Dos listados separados a proposito: una solicitud pendiente y una cuenta
    # dada de baja no son lo mismo, y mezclarlas obligaria al administrador a
    # distinguirlas por la fecha.
    lista = db.session.scalars(
        db.select(Facilitador)
        .where(Facilitador.aprobado.is_(True))
        .order_by(Facilitador.created_at)
    ).all()
    pendientes = db.session.scalars(
        db.select(Facilitador)
        .where(Facilitador.aprobado.is_(False))
        .order_by(Facilitador.created_at)
    ).all()
    return render_template(
        "admin/facilitadores.html",
        facilitadores=lista,
        pendientes=pendientes,
        pendientes_eliminacion=_contar_eliminaciones_pendientes(),
    )


def _contar_eliminaciones_pendientes() -> int:
    """Cuenta de solicitudes de eliminación en 'pendiente'.

    Se usa en la pestaña de Facilitadores (para el badge de la navegación
    compartida) y en la propia pantalla de eliminaciones. Es una consulta
    liviana (COUNT), separada de listar las solicitudes completas.
    """
    return db.session.scalar(
        db.select(db.func.count())
        .select_from(SolicitudEliminacion)
        .where(SolicitudEliminacion.estado == "pendiente")
    )


@bp.route("/facilitadores/<int:fid>/mensaje")
@admin_required
def mensaje_activacion(fid):
    """Pantalla con el mensaje de bienvenida listo para copiar y enviar.

    Existe por dos razones. La primera es de uso: el enlace de activacion es
    largo e ilegible, y pegarlo suelto en un WhatsApp no le dice a quien lo
    recibe que tiene que establecer una contrasena ni que el enlace vence. Aca
    el texto viene redactado, con el boton de copiar al lado.

    La segunda es de seguridad. Antes el enlace viajaba dentro de un mensaje
    flash, y Flask guarda los flash en la cookie de sesion, que esta FIRMADA
    pero no cifrada: el token quedaba legible en el navegador del
    administrador hasta que se renderizara. Aca se pasa por el contexto de la
    plantilla y no toca la cookie.

    Es GET a proposito: no muta nada. _enlace_activacion solo lee el id y el
    password_hash vigentes, asi que recargar esta pagina regenera el mismo
    enlace en vez de invalidar el anterior. Tampoco abre una via nueva: el
    boton "Enlace" del panel ya permitia emitirlo para cualquier cuenta.
    """
    f = _get_facilitador(fid)

    if not f.activo:
        flash(
            "La cuenta está desactivada. Reactívala antes de emitir el enlace.",
            "danger",
        )
        return redirect(url_for("admin.facilitadores"))

    return render_template(
        "admin/mensaje_activacion.html",
        facilitador=f,
        enlace=_enlace_activacion(f),
        dias=ACTIVACION_MAX_AGE // 86400,
    )


def _get_facilitador(fid):
    f = db.session.get(Facilitador, fid)
    if f is None:
        abort(404)
    return f


def _admins_activos_count():
    return db.session.scalar(
        db.select(db.func.count())
        .select_from(Facilitador)
        .where(Facilitador.es_admin.is_(True), Facilitador.activo.is_(True))
    )


def _es_ultimo_admin_activo(f):
    """True si f es un admin activo y es el único que queda."""
    return f.es_admin and f.activo and _admins_activos_count() <= 1


@bp.route("/facilitadores/<int:fid>/enlace", methods=["POST"])
@admin_required
def enlace_activacion(fid):
    """Emite un enlace de activación para una cuenta existente.

    Es la única vía frente a una contraseña olvidada. NO cambia la clave
    vigente: si el titular nunca usa el enlace, la que tenía sigue sirviendo.
    """
    f = _get_facilitador(fid)

    if not f.activo:
        flash(
            "La cuenta está desactivada. Reactívala antes de emitir el enlace.",
            "danger",
        )
        return redirect(url_for("admin.facilitadores"))

    return redirect(url_for("admin.mensaje_activacion", fid=f.id))


@bp.route("/facilitadores/<int:fid>/editar", methods=["GET", "POST"])
@admin_required
def editar_facilitador(fid):
    f = _get_facilitador(fid)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        es_admin = request.form.get("es_admin") == "on"
        # Tampoco aquí se lee la contraseña: el cambio de clave pasa siempre por
        # el enlace de activación.

        errores = []
        if not email or "@" not in email:
            errores.append("El correo no es válido.")
        if not nombre:
            errores.append("El nombre es obligatorio.")

        # Correo único: puede ser el mismo de f, pero no el de OTRO facilitador.
        if not errores:
            otro = db.session.scalar(
                db.select(Facilitador).where(
                    Facilitador.email == email, Facilitador.id != f.id
                )
            )
            if otro is not None:
                errores.append("Ya existe otro facilitador con ese correo.")

        # No dejar al sistema sin administradores: no se puede quitar el rol admin
        # al último admin activo.
        if not es_admin and _es_ultimo_admin_activo(f):
            errores.append(
                "No puedes quitar el rol de administrador al último admin activo."
            )

        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            f.nombre = nombre
            f.email = email
            f.es_admin = es_admin
            db.session.commit()
            flash("Facilitador actualizado.", "success")
            return redirect(url_for("admin.facilitadores"))

    return render_template("admin/editar_facilitador.html", facilitador=f)


@bp.route("/facilitadores/<int:fid>/estado", methods=["POST"])
@admin_required
def cambiar_estado(fid):
    f = _get_facilitador(fid)

    if f.activo:  # se está intentando DESACTIVAR
        if f.id == current_user.id:
            flash("No puedes desactivar tu propia cuenta.", "danger")
            return redirect(url_for("admin.facilitadores"))
        if _es_ultimo_admin_activo(f):
            flash("No puedes desactivar al último administrador activo.", "danger")
            return redirect(url_for("admin.facilitadores"))
        f.activo = False
        db.session.commit()
        flash(
            f"Facilitador \"{f.email}\" desactivado. Sus datos se conservan.",
            "success",
        )
    else:  # REACTIVAR (siempre permitido)
        f.activo = True
        db.session.commit()
        flash(f"Facilitador \"{f.email}\" reactivado.", "success")

    return redirect(url_for("admin.facilitadores"))


@bp.route("/solicitudes/<int:fid>/aprobar", methods=["POST"])
@admin_required
def aprobar_solicitud(fid):
    """Convierte una solicitud pendiente en cuenta.

    No inventa una via nueva de alta: aprobar es marcar `aprobado` y emitir el
    mismo enlace de activacion que emite la creacion desde el panel. El
    solicitante establece su propia contrasena, igual que siempre.
    """
    f = _get_facilitador(fid)

    if f.aprobado:
        # Ya no es una solicitud. Se responde 403 y no 404 porque el registro
        # existe: lo que no corresponde es la operacion.
        abort(403)

    f.aprobado = True
    db.session.commit()
    flash(f"Solicitud de \"{f.email}\" aprobada.", "success")
    return redirect(url_for("admin.mensaje_activacion", fid=f.id))


@bp.route("/solicitudes/<int:fid>/rechazar", methods=["POST"])
@admin_required
def rechazar_solicitud(fid):
    """Descarta una solicitud pendiente, borrando el registro.

    Es la UNICA operacion del sistema que borra fisicamente un facilitador, y
    por eso esta acotada por dos condiciones verificadas en el servidor.

    La primera define el alcance: solo alcanza a quien nunca fue aprobado, o
    sea a un registro que nunca llego a ser una cuenta.

    La segunda es un cinturon de seguridad. Facilitador.evaluaciones tiene
    cascade="all, delete-orphan", y esa cascada sigue hasta preguntas,
    alternativas, sesiones, participantes, respuestas y resultados: borrar a un
    facilitador con historia destruiria la evidencia de sus capacitaciones, que
    es justo lo que el diseno evita con la desactivacion reversible. Hoy una
    solicitud pendiente no puede tener evaluaciones (no puede iniciar sesion),
    pero el borrado no debe depender de que ese supuesto siga siendo cierto.

    Se borra en lugar de dejarlo como registro rechazado porque el correo es
    unico: conservarlo dejaria la direccion tomada y esa persona no podria
    volver a solicitar.
    """
    f = _get_facilitador(fid)

    if f.aprobado:
        abort(403)
    if f.evaluaciones:
        abort(403)

    email = f.email
    db.session.delete(f)
    db.session.commit()
    flash(f"Solicitud de \"{email}\" rechazada.", "info")
    return redirect(url_for("admin.facilitadores"))


# --------------------- Solicitudes de eliminación de datos ---------------------
#
# Pestaña hermana de Facilitadores dentro del mismo panel de administración:
# ambas gestionan quién puede estar en el sistema y qué datos conserva, así
# que comparten la navegación (ver admin/_nav.html) aunque viven en tablas
# distintas y no tienen relación entre sí.


def _resumen_de_solicitud(s: SolicitudEliminacion):
    """Participaciones que el hash de esta solicitud tiene HOY en el sistema.

    Se calcula en vivo (no se guarda snapshot) porque el numero puede crecer
    entre que alguien pide la eliminacion y un administrador la revisa: la
    misma persona podria rendir otra evaluacion mientras tanto. Nunca expone
    el RUT ni el hash en la plantilla, solo a que evaluaciones y sesiones
    corresponde, que es lo que el administrador necesita para decidir.
    """
    return db.session.execute(
        db.select(
            Evaluacion.titulo, Sesion.codigo, Participante.finalizado_at
        )
        .join(Sesion, Sesion.id == Participante.sesion_id)
        .join(Evaluacion, Evaluacion.id == Sesion.evaluacion_id)
        .where(Participante.identificador_hash == s.identificador_hash)
        .order_by(Participante.finalizado_at)
    ).all()


@bp.route("/eliminaciones")
@admin_required
def eliminaciones():
    pendientes = db.session.scalars(
        db.select(SolicitudEliminacion)
        .where(SolicitudEliminacion.estado == "pendiente")
        .order_by(SolicitudEliminacion.solicitado_at)
    ).all()
    # Historial acotado: es para auditoria rapida, no un registro sin fin.
    resueltas = db.session.scalars(
        db.select(SolicitudEliminacion)
        .where(SolicitudEliminacion.estado != "pendiente")
        .order_by(SolicitudEliminacion.resuelta_at.desc())
        .limit(50)
    ).all()

    resumenes = {s.id: _resumen_de_solicitud(s) for s in pendientes}

    return render_template(
        "admin/eliminaciones.html",
        pendientes=pendientes,
        resueltas=resueltas,
        resumenes=resumenes,
        pendientes_eliminacion=len(pendientes),
    )


def _get_solicitud(sid):
    s = db.session.get(SolicitudEliminacion, sid)
    if s is None:
        abort(404)
    return s


@bp.route("/eliminaciones/<int:sid>/aprobar", methods=["POST"])
@admin_required
def aprobar_eliminacion(sid):
    """Borra físicamente todas las participaciones del hash solicitado.

    Es, junto con rechazar_solicitud (facilitadores nunca aprobados), una de
    las dos únicas operaciones del sistema que borran datos de verdad. Borra
    Participante; Respuesta y Resultado se van por la cascada ya declarada en
    el modelo. Alcanza a TODAS las evaluaciones donde aparezca el hash, sin
    importar de qué facilitador sean: el titular del dato pidió que se vaya
    de todas partes, no solo de una.
    """
    s = _get_solicitud(sid)
    if s.estado != "pendiente":
        # Ya no es una solicitud pendiente: no hay nada que aprobar de nuevo.
        abort(403)

    participantes = db.session.scalars(
        db.select(Participante).where(
            Participante.identificador_hash == s.identificador_hash
        )
    ).all()
    cantidad = len(participantes)
    for p in participantes:
        db.session.delete(p)

    s.estado = "aprobada"
    s.resuelta_at = ahora_utc()
    s.resuelta_por_id = current_user.id
    db.session.commit()

    if cantidad:
        flash(
            f"Datos eliminados: {cantidad} participación(es) borradas de forma "
            "permanente.",
            "success",
        )
    else:
        flash(
            "Solicitud aprobada. No se encontró ninguna participación asociada "
            "a ese RUT (puede que ya no quedara ninguna, o que nunca haya "
            "rendido una evaluación).",
            "info",
        )
    return redirect(url_for("admin.eliminaciones"))


@bp.route("/eliminaciones/<int:sid>/rechazar", methods=["POST"])
@admin_required
def rechazar_eliminacion(sid):
    """Descarta la solicitud sin borrar ningún dato.

    A diferencia de rechazar_solicitud (facilitadores), aquí el registro NO
    se borra: se conserva como 'rechazada' para dejar constancia de que la
    solicitud existió y fue evaluada, con quién y cuándo. No hay un correo
    único que liberar (el mismo RUT puede volver a solicitar cuando quiera).
    """
    s = _get_solicitud(sid)
    if s.estado != "pendiente":
        abort(403)

    s.estado = "rechazada"
    s.resuelta_at = ahora_utc()
    s.resuelta_por_id = current_user.id
    db.session.commit()
    flash("Solicitud rechazada. No se eliminó ningún dato.", "info")
    return redirect(url_for("admin.eliminaciones"))
