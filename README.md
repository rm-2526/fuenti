# Fuenti

Plataforma web para tomar evaluaciones de opción múltiple durante sesiones de capacitación presenciales o sincrónicas. El facilitador arma la evaluación y abre una sesión; los participantes entran con su RUT desde un link, responden y ven su nota al instante.

Los datos quedan pseudonimizados, no anonimizados. El RUT no se almacena: se guarda su hash SHA-256 con un pepper secreto (una clave global que vive fuera de la base de datos), lo que permite seguir a un participante entre sesiones. El nombre del participante sí se almacena, así que sigue siendo un dato personal bajo la Ley 19.628 y la 21.719.

## Cómo funciona

El facilitador se autentica, crea una evaluación con sus preguntas y alternativas, y marca la respuesta correcta y un umbral de aprobación (0 a 100). Desde el detalle de la evaluación abre una sesión, que genera un código y un link público.

El participante entra por ese link, ingresa su RUT (validado con módulo 11) y responde. Al enviar, se calcula el puntaje, el porcentaje de logro, la nota y si aprobó o no, y se le muestra el resultado. No puede responder dos veces: si vuelve a ingresar, ve su nota.

La nota usa la escala chilena de 1.0 a 7.0: el umbral de la evaluación equivale a un 4.0, que es la nota de aprobación. Sobre ese umbral la nota sube hacia el 7.0; bajo el umbral, baja hacia el 1.0.

Cuando el facilitador cierra una sesión, deja de aceptar ingresos y respuestas. Cada facilitador solo ve y gestiona sus propias evaluaciones y sesiones.

## Stack

- Python 3.12, Flask, Flask-Login, Flask-Migrate
- SQLAlchemy 2.x sobre SQLite en local y PostgreSQL (Neon) en producción
- Bootstrap 5 por CDN, sin build de frontend
- pytest para los tests
- Desplegado en Render

## Ejecutar en local (Windows / PowerShell)

Se necesita Python 3.12+ y Git.

```powershell
git clone https://github.com/rm-2526/fuenti.git
cd fuenti
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se crea un archivo `.env` en la raíz:

```
FLASK_APP=app
SECRET_KEY=cualquier-string-aleatorio-para-desarrollo
```

Si no se definen `DATABASE_URL` ni `RUT_SALT`, la app usa SQLite local (`fuenti.db`) y un salt de desarrollo. Se aplican las migraciones y se crea un usuario facilitador:

```powershell
flask db upgrade
python scripts/seed_facilitador.py "correo@ejemplo.cl" "Nombre Apellido" "tuPassword"
```

El script actualiza la contraseña si el correo ya existe. El servidor se levanta con `flask run` y la app queda disponible en `http://127.0.0.1:5000`.

## Tests

```powershell
pytest
```

Se ejecutan sobre SQLite en memoria, así que no tocan ni la base local ni la de producción.

## Estructura

```
app/
  __init__.py        Application factory
  config.py          Configuración desde variables de entorno
  models.py          Modelos SQLAlchemy
  auth/              Login del facilitador
  evaluaciones/      CRUD de evaluaciones y gestión de sesiones
  participante/      Ingreso, cuestionario y resultado (público, sin login)
  utils/
    rut.py           Validación, normalización y hash del RUT
    sesion.py        Códigos de sesión
    calificacion.py  Cálculo de porcentaje, nota y aprobación
migrations/          Alembic
scripts/
  seed_facilitador.py
tests/
conftest.py
main.py
Procfile
```

## Despliegue

Se ejecuta en Render (plan Free) con `gunicorn main:app`, y la base es PostgreSQL en Neon. Cada push a `main` dispara un deploy.

Variables de entorno en Render:

- `SECRET_KEY`: string aleatorio largo, distinto al de desarrollo.
- `DATABASE_URL`: connection string *pooled* de Neon (el host termina en `-pooler`). Debe empezar con `postgresql://` y terminar en `?sslmode=require`, sin comillas.
- `RUT_SALT`: salt del hash de RUT. Se genera con `python -c "import secrets; print(secrets.token_hex(32))"`. Una vez que hay participantes reales no se puede cambiar: rotarlo invalida todos los hashes. Conviene guardar una copia aparte.

El plan Free no deja ejecutar comandos en el servidor, así que las migraciones y seeds de producción se hacen desde local apuntando a Neon, en una terminal nueva:

```powershell
$env:DATABASE_URL = "<connection string de Neon>"
$env:FLASK_APP = "app"
flask db upgrade
```

Al terminar, se cierra esa terminal para que la variable no quede activa.

Al copiar la connection string desde Neon se debe tomar la versión sin formato, no las opciones `psql` o `.env`, porque agregan texto que rompe el parser de SQLAlchemy. Además, la instancia gratuita se suspende por inactividad, lo que puede retrasar las solicitudes en 50 segundos o más al reactivarse.