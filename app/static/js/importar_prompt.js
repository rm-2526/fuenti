// Prompt editable de la pagina "Importar evaluacion".
//
// El prompt es un solo texto continuo: los tramos ambar son regiones
// contenteditable DENTRO del prompt, no campos que lo alimentan. El texto que
// se copia se arma leyendo esas mismas regiones y la parte fija que esta a la
// vista, asi que nunca puede diferir de lo que el usuario esta leyendo.
(function () {
  var btn = document.getElementById("btnCopiarPrompt");
  if (!btn) return;

  var titulo = document.getElementById("pTitulo");
  var contenido = document.getElementById("pContenido");
  var campoTitulo = document.getElementById("titulo");
  var cantidad = document.getElementById("pCantidad");
  var fijo = document.getElementById("promptFijo");
  var aviso = document.getElementById("copiaAviso");
  var editables = [titulo, contenido, cantidad];
  var temporizador = null;

  // innerText respeta los saltos de linea que el navegador haya insertado al
  // editar; textContent es el respaldo para navegadores viejos.
  function leer(el) {
    var t = el.innerText !== undefined ? el.innerText : el.textContent;
    return t.replace(/\s+/g, " ").trim();
  }

  // La clase .vacio dispara el texto guia por CSS. No se usa :empty porque el
  // navegador suele dejar un <br> residual al borrar todo.
  function marcarVacio(el) {
    if (!el.dataset.marcador) return;
    el.classList.toggle("vacio", leer(el) === "");
  }

  editables.forEach(function (el) {
    marcarVacio(el);

    el.addEventListener("input", function () {
      marcarVacio(el);
    });

    // Cada region es de una sola linea: Enter romperia el formato del prompt.
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter") e.preventDefault();
    });

    // Pegar desde Word o desde una pagina arrastra HTML con estilos. Se fuerza
    // texto plano para que el prompt no se ensucie.
    el.addEventListener("paste", function (e) {
      e.preventDefault();
      var texto = (e.clipboardData || window.clipboardData).getData("text");
      document.execCommand("insertText", false, texto.replace(/\s+/g, " "));
    });
  });

  // El titulo del prompt y el del paso 2 son el mismo dato, asi que se arrastra
  // solo. Deja de arrastrarse en cuanto el usuario escribe en el campo del paso
  // 2: a partir de ahi manda lo que el tecleo ahi, y no se le pisa.
  var arrastrarTitulo = campoTitulo && campoTitulo.value.trim() === "";

  if (campoTitulo) {
    campoTitulo.addEventListener("input", function () {
      arrastrarTitulo = false;
    });

    titulo.addEventListener("input", function () {
      if (arrastrarTitulo) campoTitulo.value = leer(titulo).slice(0, 255);
    });
  }

  function armarPrompt() {
    var lineas = ["Quiero un conjunto de preguntas para una evaluación."];
    lineas.push("Título de la evaluación: " + leer(titulo));

    // Si no se detalló el contenido, la línea no viaja: un encabezado vacío
    // solo le da a la IA una instrucción sin contenido.
    var detalle = leer(contenido);
    if (detalle) lineas.push("Contenido que deben cubrir: " + detalle);

    var n = parseInt(leer(cantidad), 10);
    if (!n || n < 1) n = 10;
    lineas.push("Cantidad: " + n + " preguntas.");

    var cola = fijo.innerText !== undefined ? fijo.innerText : fijo.textContent;
    return lineas.join("\n") + "\n\n" + cola.trim() + "\n";
  }

  // navigator.clipboard solo existe en contextos seguros (https o localhost).
  // El fallback cubre el resto sin depender de librerias.
  function copiar(texto) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(texto);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = texto;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      document.body.removeChild(ta);
      if (ok) resolve();
      else reject();
    });
  }

  function confirmarCopia() {
    aviso.classList.remove("d-none");
    if (temporizador) clearTimeout(temporizador);
    temporizador = setTimeout(function () {
      aviso.classList.add("d-none");
    }, 3000);
  }

  btn.addEventListener("click", function () {
    if (!leer(titulo)) {
      titulo.focus();
      window.Fuenti.avisar({
        titulo: "Falta el título",
        mensaje:
          "Escribe el título de la evaluación en el prompt antes de copiarlo: " +
          "sin él, la IA no sabe sobre qué preguntar.",
      });
      return;
    }

    copiar(armarPrompt()).then(confirmarCopia, function () {
      window.Fuenti.avisar({
        titulo: "No se pudo copiar",
        mensaje:
          "El navegador bloqueó el portapapeles. Selecciona el texto del " +
          "prompt a mano y cópialo con Ctrl+C.",
      });
    });
  });
})();
