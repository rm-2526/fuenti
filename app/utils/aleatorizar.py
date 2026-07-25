"""Orden de presentacion de las alternativas para el participante.

Baraja el orden VISUAL de las alternativas de cada pregunta, distinto para cada
participante, como medida anti-copia (que al de al lado no le sirva "marca la C").

Tres decisiones de diseno que conviene entender:

1. NO toca la correccion ni el informe. La foto congelada (foto_de_respuesta)
   guarda TEXTOS y el booleano acerto, nunca la posicion/letra elegida. Por eso
   barajar lo que se ve en pantalla no altera nada aguas abajo: el corrector
   compara alternativa.es_correcta, y la matriz muestra el texto y el ✓/✗. Este
   modulo solo reordena una lista para mostrarla.

2. Es ESTABLE dentro de la sesion del participante. Se siembra el barajado con
   (participante_id, pregunta_id), asi el mismo participante ve SIEMPRE el mismo
   orden aunque recargue la pagina, pero distinto del de otro participante. Se usa
   random.Random(semilla) —un generador propio y sembrado— y NO el random global,
   para no depender de ni alterar el estado global del proceso.

3. verdadero_falso NO se baraja. Su orden lo decide el importador a proposito
   ("Falso" puede ir primero); respetarlo es una regla del proyecto. Solo se
   baraja opcion_multiple.

Modulo puro: no toca la BD ni el request. Recibe objetos y devuelve una lista.
"""

import random


def _semilla(participante_id: int, pregunta_id: int) -> int:
    """Semilla determinista por (participante, pregunta).

    Se combinan con un desplazamiento grande en vez de sumarlos para que pares
    distintos no colisionen (p.ej. (1, 3) y (2, 2) no dan la misma semilla).
    """
    return participante_id * 1_000_003 + pregunta_id


def orden_alternativas(pregunta, participante_id: int) -> list:
    """Devuelve las alternativas de `pregunta` en el orden en que deben MOSTRARSE
    a este participante.

    - verdadero_falso: se devuelven en su orden canonico (campo .orden), sin
      barajar. El importador ya decidio ese orden a proposito.
    - opcion_multiple (y cualquier otro tipo): se barajan de forma estable segun
      (participante_id, pregunta.id).

    No modifica la pregunta ni su lista de alternativas: ordena sobre una copia.
    El barajado parte SIEMPRE del orden canonico (ordenado por .orden) para que la
    salida dependa solo de la semilla y no del orden en que la BD devolvio las
    filas; asi es reproducible.

    Args:
        pregunta: una Pregunta, con .tipo, .id y .alternativas (cada una con
            .orden).
        participante_id: id del Participante que rendira, para sembrar el orden.

    Returns:
        Lista de Alternativa en orden de presentacion.
    """
    canonicas = sorted(pregunta.alternativas, key=lambda a: a.orden)

    if pregunta.tipo == "verdadero_falso":
        return canonicas

    barajadas = list(canonicas)
    rng = random.Random(_semilla(participante_id, pregunta.id))
    rng.shuffle(barajadas)
    return barajadas
