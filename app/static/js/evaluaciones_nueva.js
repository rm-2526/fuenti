(function () {
  "use strict";

  const container = document.getElementById("preguntas-container");
  const btnAgregarPregunta = document.getElementById("btn-agregar-pregunta");

  const MAX_ALTERNATIVAS = 6;
  const MIN_ALTERNATIVAS = 2;

  // -------- Helpers de índices --------

  function getNextPreguntaIdx() {
    const existentes = container.querySelectorAll(".pregunta");
    if (existentes.length === 0) return 0;
    let max = -1;
    existentes.forEach((el) => {
      const idx = parseInt(el.dataset.preguntaIdx, 10);
      if (idx > max) max = idx;
    });
    return max + 1;
  }

  function getNextAlternativaIdx(preguntaEl) {
    const existentes = preguntaEl.querySelectorAll(".alternativa");
    if (existentes.length === 0) return 0;
    let max = -1;
    existentes.forEach((el) => {
      const idx = parseInt(el.dataset.alternativaIdx, 10);
      if (idx > max) max = idx;
    });
    return max + 1;
  }

  // -------- Constructores --------

  function crearAlternativa(preguntaIdx, alternativaIdx) {
    const div = document.createElement("div");
    div.className = "input-group mb-2 alternativa";
    div.dataset.alternativaIdx = alternativaIdx;
    div.innerHTML = `
      <div class="input-group-text">
        <input type="radio"
               name="pregunta_${preguntaIdx}_correcta"
               value="${alternativaIdx}"
               required>
      </div>
      <input type="text"
             class="form-control"
             name="pregunta_${preguntaIdx}_alternativa_${alternativaIdx}_texto"
             placeholder="Alternativa"
             maxlength="500"
             required>
      <button type="button" class="btn btn-outline-danger btn-quitar-alternativa">×</button>
    `;
    return div;
  }

  function crearPregunta(preguntaIdx) {
    const div = document.createElement("div");
    div.className = "card mb-3 pregunta";
    div.dataset.preguntaIdx = preguntaIdx;
    div.dataset.tipo = "opcion_multiple";
    div.innerHTML = `
      <div class="card-body">
        <input type="hidden" name="pregunta_${preguntaIdx}_tipo" value="opcion_multiple">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span><strong class="pregunta-titulo">Pregunta</strong></span>
          <button type="button" class="btn btn-sm btn-outline-danger btn-quitar-pregunta">
            Quitar pregunta
          </button>
        </div>
        <input type="text"
               class="form-control mb-3"
               name="pregunta_${preguntaIdx}_enunciado"
               placeholder="Enunciado de la pregunta"
               maxlength="1000"
               required>
        <div class="alternativas-container"></div>
        <button type="button" class="btn btn-sm btn-outline-primary btn-agregar-alternativa mt-2">
          + Agregar alternativa
        </button>
      </div>
    `;
    const altContainer = div.querySelector(".alternativas-container");
    altContainer.appendChild(crearAlternativa(preguntaIdx, 0));
    altContainer.appendChild(crearAlternativa(preguntaIdx, 1));
    return div;
  }

  // Alternativa fija (Verdadero/Falso): texto de solo lectura, sin botón de
  // quitar. El facilitador solo elige cuál es la correcta con el radio.
  function alternativaVFHtml(preguntaIdx, alternativaIdx, texto) {
    return `
      <div class="input-group mb-2 alternativa" data-alternativa-idx="${alternativaIdx}">
        <div class="input-group-text">
          <input type="radio"
                 name="pregunta_${preguntaIdx}_correcta"
                 value="${alternativaIdx}"
                 required>
        </div>
        <input type="text"
               class="form-control"
               name="pregunta_${preguntaIdx}_alternativa_${alternativaIdx}_texto"
               value="${texto}"
               maxlength="500"
               readonly
               required>
      </div>
    `;
  }

  function crearPreguntaVF(preguntaIdx) {
    const div = document.createElement("div");
    div.className = "card mb-3 pregunta";
    div.dataset.preguntaIdx = preguntaIdx;
    div.dataset.tipo = "verdadero_falso";
    div.innerHTML = `
      <div class="card-body">
        <input type="hidden" name="pregunta_${preguntaIdx}_tipo" value="verdadero_falso">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span>
            <strong class="pregunta-titulo">Pregunta</strong>
            <span class="badge bg-secondary ms-1">V/F</span>
          </span>
          <button type="button" class="btn btn-sm btn-outline-danger btn-quitar-pregunta">
            Quitar pregunta
          </button>
        </div>
        <input type="text"
               class="form-control mb-3"
               name="pregunta_${preguntaIdx}_enunciado"
               placeholder="Enunciado de la pregunta"
               maxlength="1000"
               required>
        <div class="alternativas-container">
          ${alternativaVFHtml(preguntaIdx, 0, "Verdadero")}
          ${alternativaVFHtml(preguntaIdx, 1, "Falso")}
        </div>
        <div class="d-flex align-items-center gap-2 flex-wrap">
          <button type="button" class="btn btn-sm btn-outline-secondary btn-intercambiar-vf">
            &#8645; Intercambiar
          </button>
          <span class="form-text mb-0">
            Marca cuál es la afirmación correcta. Con "Intercambiar" cambias el
            orden en que se le muestran las opciones al participante.
          </span>
        </div>
      </div>
    `;
    return div;
  }

  // Intercambia las dos alternativas de una pregunta V/F: se permutan los textos
  // y TAMBIEN el radio marcado, de modo que la respuesta correcta siga siendo la
  // misma afirmacion (si "Verdadero" era la correcta, lo sigue siendo despues de
  // moverse al segundo lugar). Solo cambia el orden en que se presentan.
  function intercambiarVF(preguntaEl) {
    const alts = preguntaEl.querySelectorAll(".alternativa");
    if (alts.length !== 2) return;

    const textos = [
      alts[0].querySelector('input[type="text"]'),
      alts[1].querySelector('input[type="text"]'),
    ];
    const radios = [
      alts[0].querySelector('input[type="radio"]'),
      alts[1].querySelector('input[type="radio"]'),
    ];
    if (!textos[0] || !textos[1] || !radios[0] || !radios[1]) return;

    const textoTmp = textos[0].value;
    textos[0].value = textos[1].value;
    textos[1].value = textoTmp;

    const marcadoTmp = radios[0].checked;
    radios[0].checked = radios[1].checked;
    radios[1].checked = marcadoTmp;
  }

  // -------- Diálogos --------
  // Se usa el modal compartido de base.html (window.Fuenti) en vez de los
  // alert()/confirm() del navegador, para que esta página se vea igual que
  // eliminar una evaluación o cerrar una sesión. Si por algún motivo el modal no
  // está disponible (Bootstrap no cargó), se cae a los diálogos nativos: es
  // preferible un popup feo a que el botón no haga nada.

  function avisar(mensaje) {
    if (window.Fuenti && window.Fuenti.avisar) {
      window.Fuenti.avisar({ mensaje: mensaje });
      return;
    }
    alert(mensaje);
  }

  function confirmar(opciones, alAceptar) {
    if (window.Fuenti && window.Fuenti.confirmar) {
      window.Fuenti.confirmar({
        titulo: opciones.titulo,
        mensaje: opciones.mensaje,
        boton: opciones.boton,
        onAceptar: alAceptar,
      });
      return;
    }
    if (confirm(opciones.mensaje)) alAceptar();
  }

  function renumerarTitulos() {
    container.querySelectorAll(".pregunta-titulo").forEach((el, i) => {
      el.textContent = `Pregunta ${i + 1}`;
    });
  }

  // -------- Listeners --------

  btnAgregarPregunta.addEventListener("click", () => {
    const idx = getNextPreguntaIdx();
    container.appendChild(crearPregunta(idx));
    renumerarTitulos();
  });

  const btnAgregarPreguntaVF = document.getElementById("btn-agregar-pregunta-vf");
  if (btnAgregarPreguntaVF) {
    btnAgregarPreguntaVF.addEventListener("click", () => {
      const idx = getNextPreguntaIdx();
      container.appendChild(crearPreguntaVF(idx));
      renumerarTitulos();
    });
  }

  container.addEventListener("click", (e) => {
    const t = e.target;

    if (t.classList.contains("btn-agregar-alternativa")) {
      const preguntaEl = t.closest(".pregunta");
      const altContainer = preguntaEl.querySelector(".alternativas-container");
      const n = altContainer.querySelectorAll(".alternativa").length;
      if (n >= MAX_ALTERNATIVAS) {
        avisar(`Máximo ${MAX_ALTERNATIVAS} alternativas por pregunta.`);
        return;
      }
      const preguntaIdx = parseInt(preguntaEl.dataset.preguntaIdx, 10);
      const altIdx = getNextAlternativaIdx(preguntaEl);
      altContainer.appendChild(crearAlternativa(preguntaIdx, altIdx));
      return;
    }

    if (t.classList.contains("btn-quitar-alternativa")) {
      const preguntaEl = t.closest(".pregunta");
      const altContainer = preguntaEl.querySelector(".alternativas-container");
      const n = altContainer.querySelectorAll(".alternativa").length;
      if (n <= MIN_ALTERNATIVAS) {
        avisar(`Mínimo ${MIN_ALTERNATIVAS} alternativas por pregunta.`);
        return;
      }
      t.closest(".alternativa").remove();
      return;
    }

    if (t.classList.contains("btn-intercambiar-vf")) {
      intercambiarVF(t.closest(".pregunta"));
      return;
    }

    if (t.classList.contains("btn-quitar-pregunta")) {
      const n = container.querySelectorAll(".pregunta").length;
      if (n <= 1) {
        avisar("Debe haber al menos 1 pregunta.");
        return;
      }
      // Se captura la pregunta ahora: el modal responde después, de forma
      // asíncrona, y para entonces el evento ya no sirve para ubicarla.
      const preguntaEl = t.closest(".pregunta");
      confirmar(
        {
          titulo: "Quitar pregunta",
          mensaje:
            "¿Quitar esta pregunta del formulario? Todavía no se ha guardado nada.",
          boton: "Quitar",
        },
        () => {
          preguntaEl.remove();
          renumerarTitulos();
        }
      );
      return;
    }
  });

  // -------- Inicialización --------

  // Si no hay preguntas iniciales (entrada fresh, no re-render por error),
  // agregamos una vacía.
  if (container.querySelectorAll(".pregunta").length === 0) {
    container.appendChild(crearPregunta(0));
    renumerarTitulos();
  } else {
    renumerarTitulos();
  }
})();