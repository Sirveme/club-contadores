/* Club de Contadores — menu vertical derecho (tamano de letra, 3 temas) e "Ir a".
   "Ir a" busca entre las tarjetas de la pagina ([data-nombre]); no tiene su
   propia lista: la fuente es app/club_herramientas.py, ya pintada por el servidor. */
(function () {
  const root = document.documentElement;
  const app = document.getElementById("app");
  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

  // Tamano de letra
  const TAM = [11, 12, 13.5, 15];
  let t = 1;
  function setTam(k) {
    t = Math.max(0, Math.min(TAM.length - 1, k));
    app.style.setProperty("--fs", TAM[t] + "px");
    guardar("club.fs", t);
  }
  try { const f = localStorage.getItem("club.fs"); if (f !== null) setTam(+f); } catch (e) {}
  document.getElementById("fMenos").onclick = () => setTam(t - 1);
  document.getElementById("fMas").onclick = () => setTam(t + 1);

  // Temas (el <head> ya aplico el guardado antes de pintar, sin parpadeo)
  function marcarTema() {
    const n = root.dataset.tema || "grafito";
    document.querySelectorAll(".rail [data-tema]").forEach(b => b.setAttribute("aria-pressed", b.dataset.tema === n));
  }
  document.querySelectorAll(".rail [data-tema]").forEach(b => b.onclick = () => {
    if (b.dataset.tema === "grafito") delete root.dataset.tema; else root.dataset.tema = b.dataset.tema;
    guardar("club.tema", b.dataset.tema);
    marcarTema();
  });
  marcarTema();

  // Movil: abrir/cerrar cada nivel del tablero (en escritorio el boton no se ve).
  function abrirCol(col, abierta) {
    col.classList.toggle("abierta", abierta);
    const b = col.querySelector(".col-toggle");
    if (b) b.setAttribute("aria-expanded", abierta);
  }
  document.querySelectorAll(".col-toggle").forEach(b => b.onclick = () => {
    const col = b.closest(".col, .seccion");
    abrirCol(col, !col.classList.contains("abierta"));
  });

  // Ir a (Ctrl+G o /)
  const irA = document.getElementById("irA"), inp = document.getElementById("irInput"), lst = document.getElementById("irLista");
  const btnIr = document.getElementById("btnIr");
  const tarjetas = () => [...document.querySelectorAll("[data-nombre]")];
  const sinTilde = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  let sel = 0, res = [];
  const esc = s => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function filtrar() {
    const q = sinTilde(inp.value.trim());
    const todas = tarjetas();
    res = todas.filter(el => !q || sinTilde(el.dataset.nombre + " " + el.textContent).includes(q) || sinTilde(el.dataset.dir) === q);
    sel = 0;
    lst.innerHTML = res.map((el, i) => `<li data-i="${i}" class="${i === 0 ? "on" : ""}"><span class="d">${esc(el.dataset.dir)}</span>` +
      `<span>${esc(el.dataset.nombre)}</span><span class="e">${el.classList.contains("activa") ? "disponible" : "pronto"}</span></li>`).join("")
      || `<li><span></span><span style="color:var(--muted)">Sin resultados</span><span></span></li>`;
    todas.forEach(el => el.classList.toggle("oculta", !!q && !res.includes(el)));
    const hoja = document.getElementById("hoja");
    if (hoja) hoja.classList.toggle("buscando", !!q);
  }
  function cerrar() {
    irA.hidden = true; btnIr.setAttribute("aria-pressed", "false");
    tarjetas().forEach(el => el.classList.remove("oculta"));
    const hoja = document.getElementById("hoja");
    if (hoja) hoja.classList.remove("buscando");
  }
  function abrir() {
    if (!tarjetas().length) { location.href = "/"; return; }
    irA.hidden = false; btnIr.setAttribute("aria-pressed", "true"); inp.value = ""; filtrar(); inp.focus();
  }
  function ir(el) {
    if (!el) return;
    cerrar();
    const col = el.closest(".col, .seccion");
    if (col) abrirCol(col, true);
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("match"); setTimeout(() => el.classList.remove("match"), 1400);
    if (el.tagName === "A") el.focus();
  }
  btnIr.onclick = () => irA.hidden ? abrir() : cerrar();
  inp.oninput = filtrar;
  inp.onkeydown = e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + res.length) % Math.max(res.length, 1);
      lst.querySelectorAll("li").forEach((li, i) => li.classList.toggle("on", i === sel));
    }
    if (e.key === "Enter") ir(res[sel]);
    if (e.key === "Escape") cerrar();
  };
  lst.onclick = e => { const li = e.target.closest("li[data-i]"); if (li) ir(res[+li.dataset.i]); };
  document.addEventListener("keydown", e => {
    const escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if ((e.ctrlKey && e.key.toLowerCase() === "g") || (e.key === "/" && !escribiendo)) { e.preventDefault(); abrir(); }
    if (e.key === "Escape" && !irA.hidden) cerrar();
  });
})();
