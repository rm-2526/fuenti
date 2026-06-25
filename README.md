# Fuenti

Plataforma web de evaluación formativa para sesiones de capacitación corporativa sincrónicas en Chile.

## Diferenciadores

- Control de sesión en tiempo real desde el servidor.
- Seguimiento longitudinal del participante por hash del RUT.
- Tratamiento del RUT alineado con Ley N°19.628 y Ley N°21.719: el RUT en claro no se almacena en la base de datos.

## Estado del proyecto

MVP en desarrollo como proyecto de tesis. Avance por objetivo específico:

| OE | Descripción | Estado |
|---|---|---|
| OE1 | Facilitador crea, lista y elimina evaluaciones de opción múltiple | ✅ Done |
| OE2 | Participante ingresa con RUT, responde la evaluación, recibe resultado | 🟡 Parcial |
| OE3 | Facilitador visualiza resultados agregados de una sesión | ⏳ Pendiente |
| OE4 | Hash de RUT con salt, aislamiento por facilitador, sesiones cerradas no aceptan más respuestas | 🟡 Parcial |

Detalle de OE2 parcial: el facilitador puede abrir y cerrar sesiones de cada evaluación. El participante puede ingresar a una sesión abierta con su RUT (link público `/sesion/<codigo>/ingreso`), el RUT se valida con el algoritmo módulo 11, se hashea con SHA-256 + salt y se persiste un registro de Participante. Falta el formulario de respuesta del cuestionario, el cálculo del resultado y la vista de resultado para el participante.

Detalle de OE4 parcial: el aislamiento por facilitador está implementado y testeado (403 cross-facilitador en lectura, eliminación y gestión de sesiones). El hash de RUT usa SHA-256 con salt configurado vía variable de entorno `RUT_SALT`. El chequeo de "sesiones cerradas no aceptan más interacciones" está activo en los dos endpoints públicos existentes (ingreso y placeholder de responder). Queda pendiente extender el mismo chequeo al endpoint de envío de respuestas cuando se implemente.

**Tests automatizados: 60 passing.**

## Stack técnico

| Capa | Herramienta |
|---|---|
| Backend | Python 3.12+ + Flask 3.x + Flask-Login |
| ORM | SQLAlchemy 2.x |
| Migraciones | Alembic vía Flask-Migrate |
| BD desarrollo | SQLite |
| BD producción | PostgreSQL en Neon (AWS us-west-2) |
| Frontend | HTML + Bootstrap 5 (CDN) + JavaScript vanilla |
| Hashing RUT | `hashlib` (SHA-256) con salt |
| Hashing contraseñas | `werkzeug.security` |
| Despliegue | Render.com (plan Free) |
| Tests | pytest |

## Estructura del proyecto

```
fuenti/
├── app/                          # Código de la aplicación Flask
│   ├── __init__.py               # Application factory (create_app)
│   ├── config.py                 # Configuración (lee env vars)
│   ├── models.py                 # Modelos SQLAlchemy
│   ├── auth/                     # Blueprint de autenticación
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── evaluaciones/             # Blueprint del facilitador: CRUD evaluaciones + sesiones
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── participante/             # Blueprint público: ingreso del participante
│   │   ├── __init__.py
│   │   └── routes.py
│   └── utils/
│       ├── __init__.py
│       ├── rut.py                # Validación, normalización y hash con salt del RUT
│       └── sesion.py             # Generación de códigos de sesión (alfabeto sin ambigüedades)
├── migrations/                   # Migraciones Alembic (Flask-Migrate)
├── scripts/
│   └── seed_facilitador.py       # Crea o actualiza un facilitador para login
├── tests/
│   ├── test_rut.py
│   ├── test_auth.py
│   ├── test_evaluaciones.py
│   ├── test_sesion_utils.py
│   └── test_sesiones.py          # Flujo completo: facilitador abre/cierra, participante ingresa
├── docs/
│   ├── REQUERIMIENTOS.md
│   └── diagramas/
├── conftest.py                   # Configuración de pytest
├── main.py                       # Punto de entrada (gunicorn / flask run)
├── Procfile                      # Comando de arranque para Render
├── requirements.txt              # Dependencias Python
├── runtime.txt
└── README.md
```

## Setup local (Windows / PowerShell)

Requisitos previos: Python 3.12+, Git.

Clonar e instalar dependencias:

```powershell
git clone https://github.com/rm-2526/fuenti.git
cd fuenti
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Crear un archivo `.env` en la raíz del proyecto con el siguiente contenido mínimo:

```
FLASK_APP=app
SECRET_KEY=cualquier-string-aleatorio-para-desarrollo
```

No es necesario definir `DATABASE_URL` ni `RUT_SALT` para desarrollo: si no están, la app usa SQLite local (`fuenti.db`) y un salt placeholder. En producción ambas son obligatorias y se setean en el dashboard de Render.

Inicializar la base de datos aplicando las migraciones:

```powershell
flask db upgrade
```

Crear un facilitador para poder hacer login:

```powershell
python scripts/seed_facilitador.py "[email protected]" "Nombre Apellido" "tuPasswordLocal"
```

El script es idempotente: si el email ya existe, actualiza nombre y password en vez de fallar.

Levantar la aplicación:

```powershell
flask run
```

La aplicación responde en `http://127.0.0.1:5000`.

## Correr los tests

Con el entorno virtual activado, desde la raíz del proyecto:

```powershell
pytest -v
```

Los tests usan SQLite en memoria, no tocan la base de desarrollo ni la de producción.

## Despliegue

La aplicación está desplegada en **https://fuenti.onrender.com**.

### Arquitectura de producción

- **Render** hospeda el web service (plan Free), corriendo `gunicorn main:app` según el Procfile.
- **Neon** hospeda PostgreSQL en AWS us-west-2 (Oregon), misma región que Render para minimizar la latencia de las queries.
- Cada push a la rama `main` dispara un deploy automático en Render.

### Variables de entorno requeridas en Render

| Variable | Descripción |
|---|---|
| `SECRET_KEY` | String aleatorio largo. No reusar el de desarrollo. Rotable: solo invalida sesiones de login. |
| `DATABASE_URL` | Connection string **pooled** de Neon. Debe empezar con `postgresql://` y terminar con `?sslmode=require`. Pegar el valor pelado, sin comillas envolviendo. |
| `RUT_SALT` | Salt para el hash de RUT. Generar con `python -c "import secrets; print(secrets.token_hex(32))"`. **No rotable** una vez que hay participantes reales en la BD: rotarlo invalida todos los hashes existentes. Guardar copia de respaldo fuera de Render. |

### Migraciones y seeds en producción

El plan Free de Render no permite ejecutar comandos one-off en el servidor: no hay Shell, el campo "Pre-deploy command" no está disponible en este plan, y las directivas `release:` del Procfile son ignoradas silenciosamente.

Por lo tanto, **las migraciones y seeds productivos se ejecutan desde local apuntando a la BD de Neon**. En una terminal PowerShell nueva (importante que sea nueva para evitar contaminar otras sesiones):

```powershell
cd C:\projects\fuenti
.\venv\Scripts\Activate.ps1
$env:DATABASE_URL = "<connection string pooled de Neon>"
$env:FLASK_APP = "app"

# Aplicar migraciones
flask db upgrade

# O seedear un facilitador
python scripts/seed_facilitador.py "<email>" "<nombre>" "<password>"
```

Cerrar la terminal al terminar para que `$env:DATABASE_URL` no persista en sesiones donde se trabaje localmente.

### Notas operativas

- El plan Free de Render duerme la aplicación tras 15 minutos sin tráfico. El primer request después de un período inactivo puede tardar 30–60 segundos en responder.
- La connection string de Neon debe ser la **pooled** (host con sufijo `-pooler`). La direct también funciona pero el pooling es recomendado para apps Flask con múltiples workers de gunicorn.
- Al copiar la connection string desde el dashboard de Neon, copiarla como "Connection string" pelada, no como formato `psql`, `.env` o `Prisma`. Esos formatos agregan texto extra que rompe el parser de SQLAlchemy.

## Próximos pasos

HC3 está en desarrollo. Cerrado en HC3 Día 1: salt para el hash de RUT (variable `RUT_SALT`). Cerrado en HC3 Día 2: flujo de sesiones del facilitador (abrir, cerrar, listar) y endpoint público de ingreso del participante con hash y chequeo de sesión cerrada. Pendiente en HC3 Día 3: formulario de respuesta del cuestionario, cálculo del resultado contra el umbral, vista de resultado para el participante. Esto completa OE2 y deja OE4 listo para ✅. Después viene OE3: visualización agregada de resultados para el facilitador.
