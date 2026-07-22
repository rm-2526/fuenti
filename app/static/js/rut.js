/* rut.js — Ayuda visual para escribir el RUT en el formulario de ingreso.
 *
 * ESTO NO ES LA VALIDACION. La validacion de verdad vive en app/utils/rut.py y
 * corre en el servidor: participante/routes.py llama a validar_rut() en cada
 * POST y rechaza lo que no pase. Este archivo solo ADELANTA ese veredicto para
 * que el participante vea el error mientras escribe y no despues de enviar el
 * formulario. Si este JS no carga, falla o queda desactualizado, el flujo sigue
 * funcionando igual de bien: el servidor rechaza el RUT malo como siempre.
 *
 * El algoritmo es el mismo modulo 11 de rut.py, reescrito aca. Es una COPIA, y
 * las copias se separan: si algun dia cambia rut.py, hay que cambiar tambien
 * este archivo. Los casos de borde estan documentados en tests/test_rut.py
 * (DV con K, RUT con puntos, cuerpo con letras).
 *
 * Reglas de interaccion, en orden de importancia:
 *  1. Mientras escribe NO se le reta a nadie. Modulo 11 dice "invalido" en cada
 *     tecla hasta que aparece el DV; pintar rojo ahi seria hostil y falso.
 *     El campo queda neutro hasta que el largo ya es plausible para un RUT
 *     completo, y recien ahi opina.
 *  2. Al salir del campo siempre opina, aunque el RUT este a medias.
 *  3. El check verde importa tanto como el rojo: confirmar que quedo bien es la
 *     mitad del beneficio.
 *  4. No se reformatea mientras escribe (mueve el cursor y en el celular
 *     enfurece). Se formatea una sola vez, al salir del campo y solo si es
 *     valido.
 */
(function () {
  "use strict";

  // Largo (ya normalizado) desde el cual tiene sentido opinar mientras escribe.
  // Los RUT en circulacion tienen 7 u 8 digitos de cuerpo mas el DV, o sea 8 o
  // 9 caracteres. Antes de eso, cualquier veredicto es prematuro.
  var LARGO_PLAUSIBLE = 8;

  var MENSAJES = {
    formato:
      "El RUT lleva solo numeros y, al final, el digito verificador (0-9 o K).",
    dv:
      "El digito verificador no coincide. Revisa si te falto o te sobro un numero.",
  };

  function normalizar(valor) {
    if (typeof valor !== "string") return "";
    return valor.replace(/[.\-\s]/g, "").toUpperCase();
  }

  /* Digito verificador que le corresponde a un cuerpo de solo digitos. */
  function dvEsperado(cuerpo) {
    var suma = 0;
    var multiplicador = 2;
    for (var i = cuerpo.length - 1; i >= 0; i--) {
      suma += parseInt(cuerpo.charAt(i), 10) * multiplicador;
      multiplicador += 1;
      if (multiplicador > 7) multiplicador = 2;
    }
    var dv = 11 - (suma % 11);
    if (dv === 11) return "0";
    if (dv === 10) return "K";
    return String(dv);
  }

  /* Diagnostico, no solo un booleano: distinguir "esto no parece un RUT" de
   * "el DV no calza" permite dar un mensaje util en vez de "RUT invalido".
   * Devuelve "vacio" | "formato" | "dv" | "ok".
   */
  function revisar(valor) {
    var rut = normalizar(valor);
    if (rut.length === 0) return "vacio";
    if (rut.length < 2) return "formato";

    var cuerpo = rut.slice(0, -1);
    var dv = rut.slice(-1);

    if (!/^[0-9]+$/.test(cuerpo)) return "formato";
    if (!/^[0-9K]$/.test(dv)) return "formato";

    return dv === dvEsperado(cuerpo) ? "ok" : "dv";
  }

  function esValido(valor) {
    return revisar(valor) === "ok";
  }

  /* "123456785" -> "12.345.678-5". Si el cuerpo no es numerico lo devuelve
   * normalizado y sin inventar puntos. */
  function formatear(valor) {
    var rut = normalizar(valor);
    if (rut.length < 2) return rut;

    var cuerpo = rut.slice(0, -1);
    var dv = rut.slice(-1);
    if (!/^[0-9]+$/.test(cuerpo)) return rut;

    return cuerpo.replace(/\B(?=([0-9]{3})+(?![0-9]))/g, ".") + "-" + dv;
  }

  /* Engancha un input. Busca los nodos de feedback de Bootstrap entre sus
   * hermanos, asi que el HTML manda: si no estan, el input igual se pinta. */
  function conectar(input) {
    var contenedor = input.parentElement;
    var nodoError = contenedor
      ? contenedor.querySelector(".invalid-feedback")
      : null;

    function pintar(estado) {
      input.classList.remove("is-valid", "is-invalid");

      if (estado === "ok") {
        input.classList.add("is-valid");
        input.setAttribute("aria-invalid", "false");
        return;
      }
      if (estado === "formato" || estado === "dv") {
        input.classList.add("is-invalid");
        input.setAttribute("aria-invalid", "true");
        if (nodoError) nodoError.textContent = MENSAJES[estado];
        return;
      }
      // "vacio": estado neutro, ni verde ni rojo.
      input.removeAttribute("aria-invalid");
    }

    /* exigente=false es el modo "mientras escribe": se calla hasta que el largo
     * da para opinar. exigente=true opina siempre. */
    function evaluar(exigente) {
      var estado = revisar(input.value);
      if (!exigente && normalizar(input.value).length < LARGO_PLAUSIBLE) {
        estado = "vacio";
      }
      pintar(estado);
      return estado;
    }

    input.addEventListener("input", function () {
      evaluar(false);
    });

    input.addEventListener("blur", function () {
      if (evaluar(true) === "ok") {
        input.value = formatear(input.value);
      }
    });

    /* Ultima red antes de gastar un viaje al servidor. Solo bloquea cuando el
     * campo tiene algo Y este JS esta seguro de que esta malo; el campo vacio
     * se lo dejamos al required del navegador y al servidor. */
    if (input.form) {
      input.form.addEventListener("submit", function (evento) {
        if (input.value.trim() === "") return;
        if (evaluar(true) !== "ok") {
          evento.preventDefault();
          input.focus();
        }
      });
    }

    /* Si el servidor re-renderizo la pagina con un RUT que rechazo, el campo
     * llega con valor: se pinta de entrada, para que el rojo del flash y el del
     * campo digan lo mismo. */
    if (input.value.trim() !== "") {
      evaluar(true);
    }
  }

  function iniciar() {
    var inputs = document.querySelectorAll("input[data-rut]");
    for (var i = 0; i < inputs.length; i++) {
      conectar(inputs[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }

  /* Mismo namespace que base.html, sin pisarlo (el orden de los <script> no
   * deberia importar). Expuesto para reusarlo en otra pagina o probarlo a mano
   * desde la consola: Fuenti.rut.esValido("11.111.111-1"). */
  window.Fuenti = window.Fuenti || {};
  window.Fuenti.rut = {
    normalizar: normalizar,
    dvEsperado: dvEsperado,
    revisar: revisar,
    esValido: esValido,
    formatear: formatear,
    conectar: conectar,
  };
})();
