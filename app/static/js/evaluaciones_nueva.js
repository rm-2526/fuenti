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
        <div class="form-text">Marca cuál es la afirmación correcta.</div>
      </div>
    `;
    return div;
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
        alert(`Máximo ${MAX_ALTERNATIVAS} alternativas por pregunta.`);
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
        alert(`Mínimo ${MIN_ALTERNATIVAS} alternativas por pregunta.`);
        return;
      }
      t.closest(".alternativa").remove();
      return;
    }

    if (t.classList.contains("btn-quitar-pregunta")) {
      const n = container.querySelectorAll(".pregunta").length;
      if (n <= 1) {
        alert("Debe haber al menos 1 pregunta.");
        return;
      }
      if (confirm("¿Quitar esta pregunta?")) {
        t.closest(".pregunta").remove();
        renumerarTitulos();
      }
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