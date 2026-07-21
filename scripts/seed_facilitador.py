"""
Crea (o actualiza) un facilitador en la BD para poder hacer login.

Uso (PowerShell / cmd):
    python scripts/seed_facilitador.py "facilitador@fuenti.cl" "Nombre Apellido" "miPassword123"

Para crear/promover un ADMINISTRADOR (puede entrar al panel de gestión de
facilitadores), agrega --admin al final:
    python scripts/seed_facilitador.py "admin@fuenti.cl" "Nombre Apellido" "miPassword123" --admin

Si el email ya existe, actualiza la contraseña y el nombre en vez de fallar.
El rol admin solo se toca cuando se pasa --admin: si NO se pasa, no se degrada
a un admin existente (correr el script para cambiar la contraseña no le quita
el rol).
"""
import sys
from pathlib import Path

# Agregar la raíz del proyecto al sys.path para poder importar `app`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app, db
from app.models import Facilitador


def main():
    args = list(sys.argv[1:])
    es_admin = "--admin" in args
    if es_admin:
        args.remove("--admin")

    if len(args) != 3:
        print(
            "Uso: python scripts/seed_facilitador.py <email> <nombre> <password> [--admin]"
        )
        sys.exit(1)

    email = args[0].strip().lower()
    nombre = args[1].strip()
    password = args[2]

    app = create_app()
    with app.app_context():
        existing = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == email)
        )
        if existing:
            existing.set_password(password)
            existing.nombre = nombre
            if es_admin:
                existing.es_admin = True
            db.session.commit()
            estado = " (admin)" if existing.es_admin else ""
            print(f"Facilitador actualizado: {email}{estado}")
        else:
            f = Facilitador(email=email, nombre=nombre, es_admin=es_admin)
            f.set_password(password)
            db.session.add(f)
            db.session.commit()
            estado = " (admin)" if f.es_admin else ""
            print(f"Facilitador creado: {email} (id={f.id}){estado}")


if __name__ == "__main__":
    main()
