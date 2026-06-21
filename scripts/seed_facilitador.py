"""
Crea un facilitador en la BD para poder hacer login.

Uso (PowerShell):
    python scripts/seed_facilitador.py "facilitador@fuenti.cl" "Nombre Apellido" "miPassword123"

Si el email ya existe, actualiza la contraseña en vez de fallar.
"""
import sys
from pathlib import Path

# Agregar la raíz del proyecto al sys.path para poder importar `app`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app, db
from app.models import Facilitador


def main():
    if len(sys.argv) != 4:
        print("Uso: python scripts/seed_facilitador.py <email> <nombre> <password>")
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    nombre = sys.argv[2].strip()
    password = sys.argv[3]

    app = create_app()
    with app.app_context():
        existing = db.session.scalar(
            db.select(Facilitador).where(Facilitador.email == email)
        )
        if existing:
            existing.set_password(password)
            existing.nombre = nombre
            db.session.commit()
            print(f"Facilitador actualizado: {email}")
        else:
            f = Facilitador(email=email, nombre=nombre)
            f.set_password(password)
            db.session.add(f)
            db.session.commit()
            print(f"Facilitador creado: {email} (id={f.id})")


if __name__ == "__main__":
    main()