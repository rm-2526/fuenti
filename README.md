# Fuenti

Plataforma web para aplicar evaluaciones de aprendizaje durante sesiones de capacitación corporativa, presenciales o sincrónicas. El facilitador arma la evaluación y abre una sesión; los participantes entran con su RUT desde un enlace o un código QR, responden y ven su nota al instante. Los resultados de una misma persona quedan vinculados entre sesiones, lo que permite consultar su historial longitudinal.

Los datos quedan seudonimizados, no anonimizados. El RUT no se almacena: se guarda su hash SHA-256 con una clave global secreta que vive fuera de la base de datos (una *pepper*), lo que permite seguir a un participante entre sesiones sin conservar su identificador. El nombre del participante sí se almacena, así que sigue siendo un dato personal bajo la Ley 19.628 y la Ley 21.719.

## Cómo funciona

El facilitador se autentica, crea una evaluación con sus preguntas y alternativas, marca la respuesta correcta y define un umbral de aprobación (0 a 100). Las preguntas pueden ser de opción múltiple (2 a 6 alternativas) o de verdadero o falso. Una evaluación puede importarse y exportarse en JSON.

Desde el detalle de la evaluación abre una sesión, que genera un código de acceso, un enlace público y un código QR. El umbral se fija al abrir la sesión y es inmutable en adelante, de modo que un mismo instrumento puede reutilizarse con exigencias distintas.

El participante entra por ese enlace o escaneando el QR, ingresa su RUT (validado con módulo 11 y normalizado) y responde. Las alternativas se presentan barajadas de forma estable por participante: el orden no cambia al recargar, pero difiere entre personas. Al enviar, se calcula el puntaje, el porcentaje de logro, la nota y la condición de aprobación, y se le muestra el resultado. No puede responder dos veces: si vuelve a ingresar, ve su nota.

La nota usa la escala chilena de 1,0 a 7,0: el umbral de la sesión equivale a un 4,0, que es la nota de aprobación. Sobre ese umbral la nota sube hacia el 7,0; bajo el umbral, baja hacia el 1,0.

Cada respuesta persiste una copia congelada de su evidencia: el enunciado, el texto de las alternativas y el umbral vigentes al momento del envío. Por eso un informe ya emitido no cambia aunque la evaluación se edite después.

Cuando el facilitador cierra una sesión, el servidor deja de aceptar ingresos y respuestas, con independencia del estado del cliente. El cierre es irreversible. Cada facilitador solo ve y gestiona sus propias evaluaciones y sesiones.

No hay registro autónomo. Una cuenta de facilitador nace de dos maneras, y ambas terminan igual: el administrador la crea desde el panel, o alguien la solicita desde el formulario público y el administrador la aprueba. En los dos casos el sistema nunca fija una contraseña que alguien conozca: emite un enlace de activación firmado, de un solo uso y con siete días de vigencia, y el titular establece la suya. Una solicitud rechazada se elimina, de modo que esa dirección queda libre para volver a intentarlo; una cuenta ya aprobada solo se desactiva, y esa baja es reversible y conserva sus evaluaciones e informes.

La aplicación incorpora una guía de uso propia, accesible sin credenciales, que recorre el funcionamiento en cinco pasos.

Opcionalmente, el sistema genera un análisis narrativo del grupo y de cada participante mediante un modelo generativo externo, a partir de datos ya despersonalizados. Si el servicio no está disponible, la sesión se cierra y los informes se emiten igual: la funcionalidad degrada en silencio.

## Stack

- Python 3.12, Flask 3.1, Flask-Login, Flask-Migrate
- SQLAlchemy 2.0 sobre SQLite en local y PostgreSQL (Neon) en producción
- Bootstrap 5 por CDN, sin build de frontend
- segno para la generación local de códigos QR
- pytest para las pruebas
- Desplegado en Render con Gunicorn

## Ejecutar en local (Windows / PowerShell)

Se necesita Python 3.12+ y Git.

```
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

```
flask db upgrade
python scripts/seed_facilitador.py "correo@ejemplo.cl" "Nombre Apellido" "tuPassword"
```

El script actualiza la contraseña si el correo ya existe. El servidor se levanta con `flask run` y la app queda disponible en `http://127.0.0.1:5000`.

## Pruebas

```
pytest
```

393 casos en 30 archivos, que se ejecutan sobre SQLite en memoria, así que no tocan ni la base local ni la de producción. Cubren tres niveles:

- **Unitario**: lógica pura sin contexto de aplicación (identidad, calificación, aleatorización, estadísticas, reportería).
- **Integración con la base de datos**: restricciones del esquema ante inserciones que evaden el controlador, y correspondencia entre las vistas y el cálculo equivalente en Python.
- **Integración HTTP**: recorridos completos sobre el cliente de pruebas de Flask (autoría, sesión, rendición, informes).

## Modelo de datos

Ocho entidades: `Facilitador`, `Evaluacion`, `Pregunta`, `Alternativa`, `Sesion`, `Participante`, `Respuesta` y `Resultado`. Diez migraciones de Alembic, aditivas y reversibles.

En `Facilitador`, `aprobado` y `activo` son campos separados a propósito: el primero dice si un administrador dio el visto bueno alguna vez, el segundo si la cuenta puede operar ahora. Una solicitud pendiente es `aprobado = false`; una cuenta dada de baja es `aprobado = true, activo = false`.

Parte de la lógica vive en el esquema, no solo en el código: restricciones `UNIQUE` que impiden participaciones duplicadas por sesión, restricciones `CHECK` que acotan la nota a la escala 1,0–7,0, los estados válidos de una sesión y la coherencia temporal entre apertura y cierre, y un índice sobre el identificador seudonimizado que resuelve la consulta longitudinal sin recorrer la tabla completa.

Dos vistas resuelven la agregación en el motor en lugar de en Python:

- `v_resumen_sesion`: conteo de participantes, finalizados, aprobados y promedio de nota por sesión. Alimenta el panel de monitoreo, que sondea cada 10 segundos.
- `v_historial_longitudinal`: serie de participaciones de una persona a través de sus sesiones cerradas.

Ambas son SQL estándar y corren igual en SQLite y en PostgreSQL.

## Estructura

```
app/
  __init__.py        Application factory
  config.py          Configuración desde variables de entorno
  models.py          Modelos SQLAlchemy (8 entidades)
  vistas.py          Definición y creación de las dos vistas
  cli.py             Comandos de mantención (flask analisis-backfill)
  auth/              Login, solicitud de acceso y activación de cuenta
  admin/             Gestión de cuentas y resolución de solicitudes
  evaluaciones/      CRUD de evaluaciones, sesiones e informes
  participante/      Ingreso, cuestionario y resultado (público, sin login)
  utils/
    rut.py           Validación módulo 11, normalización y hash del RUT
    sesion.py        Códigos de sesión
    calificacion.py  Porcentaje de logro, nota y condición de aprobación
    aleatorizar.py   Barajado estable por participante
    estadisticas.py  Agregados de sesión
    reporte.py       Armado de informes
    analisis.py      Análisis narrativo
    activacion.py    Enlaces firmados de activación y restablecimiento
    gemini.py        Adaptador al modelo generativo externo
    qr.py            Generación local de códigos QR (segno)
  templates/         Plantillas Jinja2
  static/            JS propio (validación de RUT, sondeo del panel)
migrations/          Alembic (10 revisiones)
scripts/
  seed_facilitador.py
  locustfile.py      Escenarios de prueba de carga
docs/
  REQUERIMIENTOS.md
tests/               30 archivos, 393 casos
conftest.py
main.py
Procfile
```

## Despliegue

Se ejecuta en Render (plan Free) con `gunicorn main:app --threads 4 --timeout 120`, y la base es PostgreSQL en Neon. Cada push a `main` dispara un deploy.

Variables de entorno en Render:

- `SECRET_KEY`: string aleatorio largo, distinto al de desarrollo.
- `DATABASE_URL`: connection string *pooled* de Neon (el host termina en `-pooler`). Debe empezar con `postgresql://` y terminar en `?sslmode=require`, sin comillas.
- `RUT_SALT`: clave global del hash de RUT. Se genera con `python -c "import secrets; print(secrets.token_hex(32))"`. Una vez que hay participantes reales no se puede cambiar: rotarla invalida todos los hashes y rompe el historial longitudinal. Conviene guardar una copia aparte.
- `GEMINI_API_KEY`: opcional. Su ausencia desactiva el análisis narrativo sin afectar el resto del sistema.

El plan Free no deja ejecutar comandos en el servidor, así que las migraciones y seeds de producción se hacen desde local apuntando a Neon, en una terminal nueva:

```
$env:DATABASE_URL = "<connection string de Neon>"
$env:FLASK_APP = "app"
flask db upgrade
```

Al terminar, se cierra esa terminal para que la variable no quede activa.

Las migraciones se aplican **antes** de publicar el código: invertir ese orden deja al servicio en línea consultando un esquema que aún no existe. Como son aditivas y reversibles, una actualización fallida se revierte volviendo a la revisión anterior del esquema y redesplegando la versión previa.

Al copiar la connection string desde Neon se debe tomar la versión sin formato, no las opciones `psql` o `.env`, porque agregan texto que rompe el parser de SQLAlchemy. Además, la instancia gratuita se suspende por inactividad, lo que puede retrasar las solicitudes en 50 segundos o más al reactivarse.

## Rendimiento

El sistema está dimensionado para 30 participantes concurrentes. La prueba de carga (`scripts/locustfile.py`, ejecutada con Locust contra el entorno de producción) registró 0 % de peticiones fallidas y una latencia del panel de monitoreo muy por debajo de su umbral. El percentil 95 de las operaciones de escritura queda sobre el umbral de 3 segundos en el plan Free: la mejora obtenida al pasar de uno a cuatro hilos por trabajador eliminó la espera en cola, y el tiempo restante es cómputo, acotado por la fracción de CPU de la instancia.
