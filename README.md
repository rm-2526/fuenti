# Fuenti

Plataforma web de evaluación de aprendizaje para sesiones de capacitación corporativa sincrónicas en Chile.

## Diferenciadores

- Control de sesión en tiempo real desde el servidor.
- Seguimiento longitudinal del participante por hash del RUT.
- Tratamiento seguro del RUT bajo Ley N°19.628 y Ley N°21.719: el RUT en claro nunca se almacena.

## Stack técnico

| Capa | Herramienta |
|---|---|
| Backend | Python 3.12 + Flask 3.x + Flask-Login |
| ORM | SQLAlchemy 2.x |
| BD desarrollo | SQLite |
| BD producción | PostgreSQL (conectada vía `DATABASE_URL`) |
| Tiempo real | Polling AJAX cada 3 segundos, validación en servidor |
| PDF | WeasyPrint (mejora condicional) |
| Frontend | HTML + Bootstrap 5 + JavaScript vanilla |
| Hashing RUT | `hashlib` (SHA-256) |
| Hashing contraseñas | `werkzeug.security` |
| Despliegue | Render.com |
| Tests | pytest |

## Estructura del proyecto

```
fuenti/
├── app/                 # Código de la aplicación Flask
│   ├── __init__.py
│   └── utils/
│       ├── __init__.py
│       └── rut.py       # Validación, normalización y hash del RUT
├── tests/               # Tests automatizados con pytest
│   └── test_rut.py
├── docs/                # Documentación del proyecto
│   ├── REQUERIMIENTOS.md
│   └── diagramas/
│       └── er-fuenti-v1.png
├── static/              # Archivos estáticos (CSS, JS, imágenes)
├── templates/           # Plantillas Jinja2
├── main.py              # Punto de entrada de la app Flask
├── Procfile             # Comando de arranque para producción
├── requirements.txt     # Dependencias Python
└── conftest.py          # Configuración de pytest
```

## Setup local (Windows)

Requisitos previos: Python 3.12, Git.

```powershell
git clone https://github.com/rm-2526/fuenti.git
cd fuenti
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

La aplicación responde en `http://localhost:5000`.

## Correr los tests

Con el entorno virtual activado, desde la raíz del proyecto:

```powershell
pytest -v
```

## Despliegue

La aplicación está desplegada en Render.com en la rama `main`. Cada push a `main` dispara un deploy automático.

URL pública: https://fuenti.onrender.com

Nota: el plan free de Render duerme la aplicación tras 15 minutos sin tráfico. El primer request después de un período inactivo puede tardar 30–60 segundos en responder.