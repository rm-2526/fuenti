"""Prueba de cargabilidad de Fuenti (escenarios CP-C-01 a CP-C-04).

Verifica el requerimiento no funcional RNF-10: sostener treinta participantes
concurrentes con sondeo del panel cada diez segundos, sin degradacion.

Los treinta son USUARIOS VIRTUALES generados desde un solo equipo, no personas.
La prueba mide la capacidad declarada en el diseno y es independiente del
tamano del grupo real de la sesion piloto.

--------------------------------------------------------------------------
COMO SE EJECUTA
--------------------------------------------------------------------------
  pip install locust

  1. En la aplicacion, abre una sesion de una evaluacion y copia su codigo
     de seis caracteres.
  2. Exporta los datos del escenario (PowerShell):

       $env:FUENTI_CODIGO   = "ABC123"
       $env:FUENTI_EMAIL    = "facilitador@ejemplo.cl"
       $env:FUENTI_PASSWORD = "tu-clave"
       $env:FUENTI_EVAL_ID  = "1"
       $env:FUENTI_SESION_ID= "1"

  3. Lanza la prueba contra el entorno de OPERACION, no contra localhost:
     el objeto de la medicion es la plataforma, no tu equipo.

       locust -f locustfile.py --host https://fuenti.onrender.com

  4. Abre http://localhost:8089 y configura:
       Number of users = 31      (30 participantes + 1 facilitador)
       Ramp up         = 30      (los 30 entran en el primer segundo, que es
                                  el momento de concurrencia concentrada)
     Deja correr entre tres y cinco minutos.

  Sin interfaz grafica, para dejar el resultado en archivo:

       locust -f locustfile.py --host https://fuenti.onrender.com \
              --headless -u 31 -r 30 -t 4m --csv=resultado_carga

--------------------------------------------------------------------------
QUE MIRAR EN EL RESULTADO (Tabla 30 del informe)
--------------------------------------------------------------------------
  Tasa de error                 -> columna "Fails" ; umbral 0 %
  Tiempo de respuesta p95       -> columna "95%"   ; umbral < 3000 ms
  Latencia del panel            -> fila "GET /resumen (CP-C-02)" ; < 15000 ms
  Consistencia de resultados    -> se valida en las pruebas funcionales, no aqui

--------------------------------------------------------------------------
ADVERTENCIAS
--------------------------------------------------------------------------
  * Consume cuota mensual de computo del plan gratuito. No la ejecutes el
    mismo dia de la sesion piloto.
  * La primera peticion puede tardar decenas de segundos si el servicio
    estaba suspendido por inactividad (arranque en frio, RNF-15). Descarta
    esa primera medicion o precalienta abriendo la aplicacion en el navegador.
  * Cada usuario virtual consume un cupo de participante en la sesion. Tras
    la prueba, la sesion queda con treinta participaciones de prueba: usala
    en una evaluacion desechable, no en una real.
"""

import os
import random
import re
import time

from locust import HttpUser, between, task

CODIGO = os.environ.get("FUENTI_CODIGO", "")
EMAIL = os.environ.get("FUENTI_EMAIL", "")
PASSWORD = os.environ.get("FUENTI_PASSWORD", "")
EVAL_ID = os.environ.get("FUENTI_EVAL_ID", "")
SESION_ID = os.environ.get("FUENTI_SESION_ID", "")

# Contador global para que cada usuario virtual reciba un RUT distinto: dos
# participantes con el mismo identificador chocarian contra la restriccion de
# unicidad y el error seria del escenario, no del sistema.
_secuencia = [0]


def _digito_verificador(cuerpo: int) -> str:
    """Modulo 11, mismo algoritmo que app/utils/rut.py."""
    suma, factor = 0, 2
    for d in reversed(str(cuerpo)):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def _rut_valido() -> str:
    """RUT sintetico con digito verificador correcto.

    Se parte desde 5.000.000 para no caer en el rango de los identificadores
    de ejemplo que el sistema rechaza deliberadamente (11111111-1 y similares).
    """
    _secuencia[0] += 1
    cuerpo = 5_000_000 + _secuencia[0] * 7 + random.randint(0, 3)
    return f"{cuerpo}-{_digito_verificador(cuerpo)}"


class Participante(HttpUser):
    """CP-C-01, CP-C-03: ingreso simultaneo y envio concurrente.

    Recorre el flujo completo una sola vez, que es lo que hace una persona
    real: ingresa, responde y ve su resultado. No repite en bucle.
    """

    weight = 30
    wait_time = between(1, 3)

    def on_start(self):
        if not CODIGO:
            raise RuntimeError("Falta la variable de entorno FUENTI_CODIGO.")
        self.terminado = False

    @task
    def rendir(self):
        if self.terminado:
            return

        base = f"/sesion/{CODIGO}"

        # --- CP-C-01: ingreso simultaneo -------------------------------
        self.client.get(f"{base}/ingreso", name="GET /ingreso (CP-C-01)")
        r = self.client.post(
            f"{base}/ingreso",
            data={"nombre": f"Carga {self._id()}", "rut": _rut_valido()},
            name="POST /ingreso (CP-C-01)",
        )
        if r.status_code >= 400:
            self.terminado = True
            return

        # --- Lectura del cuestionario ----------------------------------
        r = self.client.get(f"{base}/responder", name="GET /responder")
        if r.status_code >= 400:
            self.terminado = True
            return

        # Los identificadores de pregunta y de alternativa se leen del HTML
        # real: el barajado por participante impide fijarlos de antemano.
        formulario = self._extraer_respuestas(r.text)
        if not formulario:
            self.terminado = True
            return

        # --- CP-C-03: envio concurrente de respuestas -------------------
        self.client.post(
            f"{base}/responder", data=formulario, name="POST /responder (CP-C-03)"
        )
        self.client.get(f"{base}/resultado", name="GET /resultado")
        self.terminado = True

    # ------------------------------------------------------------------
    def _id(self):
        return int(time.time() * 1000) % 100000

    @staticmethod
    def _extraer_respuestas(html: str):
        """Arma el POST eligiendo una alternativa al azar por pregunta.

        Busca los radios name="pregunta_<id>" value="<alternativa_id>" y toma
        uno de cada grupo. Elegir al azar es lo correcto: la prueba mide
        capacidad, no exactitud de la correccion.
        """
        pares = re.findall(
            r'name="pregunta_(\d+)"[^>]*?value="(\d+)"'
            r'|value="(\d+)"[^>]*?name="pregunta_(\d+)"',
            html,
        )
        opciones = {}
        for a, b, c, d in pares:
            pid, aid = (a, b) if a else (d, c)
            opciones.setdefault(pid, []).append(aid)
        return {
            f"pregunta_{pid}": random.choice(alts) for pid, alts in opciones.items()
        }


class Facilitador(HttpUser):
    """CP-C-02 y CP-C-04: sondeo del panel y consulta de informes.

    Un solo usuario virtual, porque en una sesion real hay un facilitador.
    Sondea cada diez segundos, igual que el navegador.
    """

    weight = 1
    wait_time = between(9, 11)

    def on_start(self):
        if not (EMAIL and PASSWORD and EVAL_ID and SESION_ID):
            raise RuntimeError(
                "Faltan FUENTI_EMAIL, FUENTI_PASSWORD, FUENTI_EVAL_ID o FUENTI_SESION_ID."
            )
        self.client.get("/login", name="GET /login")
        self.client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD},
            name="POST /login",
        )

    @task(10)
    def sondear_panel(self):
        """CP-C-02: la peticion que el panel repite cada diez segundos."""
        self.client.get(
            f"/evaluaciones/{EVAL_ID}/sesiones/{SESION_ID}/resumen",
            name="GET /resumen (CP-C-02)",
        )

    @task(1)
    def consultar_informe(self):
        """CP-C-04: informe en matriz, la consulta mas pesada del sistema."""
        self.client.get(
            f"/evaluaciones/{EVAL_ID}/sesiones/{SESION_ID}/informe-todos",
            name="GET /informe-todos (CP-C-04)",
        )
