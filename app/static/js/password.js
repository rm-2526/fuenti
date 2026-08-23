/* Utilidades de campos de contraseña: mostrar/ocultar y coincidencia.
 *
 * Dos comportamientos, ambos declarados en el HTML con atributos data-, para
 * que agregar un campo nuevo no obligue a tocar este archivo:
 *
 *   data-password-toggle="<id>"  en un <button>: alterna entre type password
 *                                y text sobre el input con ese id.
 *   data-password-igual="<id>"   en un <input>: exige que su valor coincida
 *                                con el del input indicado.
 *
 * El listener del toggle esta DELEGADO en el documento: funciona para
 * cualquier boton presente ahora o agregado despues.
 *
 * Por que se permite ver la contrasena. En un teclado tactil, escribir una
 * clave a ciegas es la principal causa de errores de tipeo, y el costo de
 * equivocarse aqui es alto: el enlace de activacion es de un solo uso. Mostrar
 * el texto es decision del usuario, nunca el estado inicial.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- toggle
  document.addEventListener("click", function (ev) {
    var boton = ev.target.closest("[data-password-toggle]");
    if (!boton) return;

    var campo = document.getElementById(boton.dataset.passwordToggle);
    if (!campo) return;

    var oculto = campo.type === "password";
    campo.type = oculto ? "text" : "password";

    // Los dos iconos viven en el DOM; se muestra el que corresponde.
    var ojo = boton.querySelector(".icono-ojo");
    var ojoTachado = boton.querySelector(".icono-ojo-tachado");
    if (ojo && ojoTachado) {
      ojo.hidden = oculto;
      ojoTachado.hidden = !oculto;
    }

    boton.setAttribute("aria-pressed", oculto ? "true" : "false");
    boton.setAttribute(
      "aria-label",
      oculto ? "Ocultar la contraseña" : "Mostrar la contraseña"
    );

    // Devolver el foco al campo, en la misma posicion: alternar la vista no
    // deberia interrumpir la escritura.
    var pos = campo.value.length;
    campo.focus();
    try {
      campo.setSelectionRange(pos, pos);
    } catch (e) {
      // Algunos navegadores no permiten setSelectionRange en type="password".
    }
  });

  // ----------------------------------------------------------- coincidencia
  // Se usa setCustomValidity en vez de mensajes propios: asi el navegador
  // bloquea el envio con su propia burbuja y no hace falta interceptar submit.
  var confirmaciones = document.querySelectorAll("[data-password-igual]");

  Array.prototype.forEach.call(confirmaciones, function (confirmacion) {
    var original = document.getElementById(confirmacion.dataset.passwordIgual);
    if (!original) return;

    var aviso = document.getElementById(confirmacion.dataset.passwordAviso || "");

    function revisar() {
      // Con la confirmacion vacia no se reclama todavia: la persona aun escribe.
      var coincide = confirmacion.value === "" || confirmacion.value === original.value;

      confirmacion.setCustomValidity(coincide ? "" : "Las contraseñas no coinciden.");
      confirmacion.classList.toggle("is-invalid", !coincide);
      confirmacion.classList.toggle(
        "is-valid",
        coincide && confirmacion.value !== "" && confirmacion.value.length >= 8
      );

      if (aviso) {
        aviso.textContent = coincide ? "" : "Las contraseñas no coinciden.";
      }
    }

    confirmacion.addEventListener("input", revisar);
    // Tambien al escribir en el original: si lo corrige despues, la
    // confirmacion tiene que dejar de estar en verde.
    original.addEventListener("input", revisar);
  });
})();
