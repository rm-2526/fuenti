# Requerimientos — Proyecto Fuenti

Plataforma web de evaluación de aprendizaje para sesiones de capacitación corporativa sincrónicas en Chile.

## Diferenciadores

- Control de sesión en tiempo real desde el servidor (apertura/cierre, validación de respuestas).
- Seguimiento longitudinal del participante a través de múltiples sesiones.
- Tratamiento seguro del RUT como dato personal bajo Ley N°19.628 y Ley N°21.719: el RUT en claro nunca se almacena, solo su hash SHA-256.

## Objetivos Específicos y criterios de aceptación

### OE1 — Módulo de creación de evaluaciones por el facilitador

El facilitador autenticado puede construir una evaluación lista para usar en una sesión.

Criterios de aceptación:

1. Existe un formulario que permite crear una evaluación con título y umbral de aprobación (porcentaje entre 0 y 100).
2. Cada evaluación se compone de una o más preguntas; cada pregunta tiene un enunciado y exactamente 4 alternativas (A, B, C, D).
3. Exactamente una alternativa por pregunta está marcada como correcta.
4. El orden de las preguntas y de las alternativas es estable y coincide con el orden de creación.
5. Una evaluación creada no puede editarse; el facilitador puede eliminarla y crear otra.

### OE2 — Control de sesión en tiempo real

El facilitador controla la apertura y cierre de la sesión; la validación de respuestas ocurre en el servidor.

Criterios de aceptación:

1. El facilitador puede abrir una sesión sobre una evaluación existente; al abrirla se genera un código único de 6 caracteres.
2. Los participantes ingresan a la sesión usando ese código junto con su RUT.
3. El facilitador puede cerrar la sesión manualmente; al cerrarla, el sistema rechaza cualquier nueva respuesta.
4. La validación del estado de la sesión (`abierta` / `cerrada`) ocurre en el servidor antes de aceptar cada respuesta, no solo en el cliente.
5. El panel del facilitador refresca cada 3 segundos (polling AJAX) el número de participantes ingresados y finalizados.

### OE3 — Generación automática de informes individuales al cierre

Al cerrarse la sesión, se calcula y persiste el resultado de cada participante.

Criterios de aceptación:

1. Al cerrar la sesión, el sistema calcula puntaje, total de preguntas, porcentaje, nota en escala 1.0–7.0 y estado de aprobación para cada participante.
2. Las preguntas no respondidas cuentan como incorrectas.
3. El resultado se guarda como snapshot en la tabla `resultado`; consultas posteriores leen ese snapshot, no recalculan.
4. El facilitador puede descargar el informe individual de cada participante en formato CSV. La generación de PDF con WeasyPrint queda como mejora condicional al tiempo disponible.

### OE4 — Seguimiento longitudinal por participante

Un mismo participante en distintas sesiones queda vinculado por el hash de su RUT, sin almacenar el RUT en claro.

Criterios de aceptación:

1. El identificador único del participante es el hash SHA-256 del RUT normalizado.
2. El RUT se valida con el algoritmo módulo 11 y se normaliza (sin puntos, sin guion, K en mayúscula) antes de hashear; RUTs inválidos son rechazados.
3. El RUT en claro nunca se persiste en la base de datos.
4. La función de hash es determinística: el mismo RUT produce el mismo hash en cualquier sesión.
5. El facilitador autenticado puede consultar el historial de resultados de un participante a través de múltiples sesiones, ordenado cronológicamente.
6. La función de hash está cubierta por tests automatizados con pytest.

## Supuestos y exclusiones del MVP

Estas funcionalidades están explícitamente fuera del alcance del piloto:

- Escala de notas configurable. Se fija en 1.0–7.0 (estándar chileno).
- Edición de evaluaciones publicadas, duplicación y plantillas.
- Reordenamiento de preguntas mediante drag-and-drop.
- Notificaciones por email al cierre de sesión.
- Reconexión automática de participantes ante caída de red.
- Reportes longitudinales agregados por grupo (solo se cubren los individuales).
- Registro abierto de facilitadores: se crea un único facilitador manualmente en la base de datos para el piloto.
- Roles diferenciados (facilitador, RRHH, administrador): solo existe el rol "facilitador".

## Criterio de éxito del piloto

El piloto se considera exitoso si una sesión real con un facilitador y al menos 8 participantes:

- Se abre, recibe respuestas y se cierra sin pérdida de datos.
- Genera correctamente los resultados individuales con nota en escala 1.0–7.0.
- Permite al facilitador descargar el informe CSV de cada participante.