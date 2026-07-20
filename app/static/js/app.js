/* Club de Contadores — embudo por etapas, mobile-first sin scroll. */
(() => {
  "use strict";

  // Numero de WhatsApp del Club (Peru). Cambiar por el real de Perú Sistemas.
  const WA_NUMBER = "51999888777";

  const CFG = window.__CFG__ || {};
  const state = { ruc: "", razon_social: "", tipo: "", distrito: "", ubigeo: "",
                  whatsapp: "", email: "", origen: originFromUrl() };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---- Navegacion de etapas -------------------------------------------------
  const stages = $$(".stage");
  const dots = $$("#progress .dot");
  function goto(n) {
    stages.forEach(s => s.classList.toggle("active", +s.dataset.stage === n));
    dots.forEach((d, i) => d.classList.toggle("on", i <= n));
    if (n === 2) cargarConteo();
    if (n === 3) cargarLista();
  }
  document.addEventListener("click", (e) => {
    const nx = e.target.closest("[data-next]"); if (nx) return goto(+nx.dataset.next);
    const bk = e.target.closest("[data-back]"); if (bk) return goto(+bk.dataset.back);
  });

  if (CFG.demo) {
    const b = document.createElement("div"); b.className = "demo-badge";
    b.textContent = "DEMO"; document.body.appendChild(b);
  }

  // ---- Etapa 1: RUC + combo de distritos -----------------------------------
  const rucEl = $("#ruc"), razonEl = $("#razon"), err1 = $("#err1");
  rucEl.addEventListener("input", () => {
    rucEl.value = rucEl.value.replace(/\D/g, "").slice(0, 11);
    razonEl.hidden = true; err1.hidden = true; state.razon_social = "";
  });

  let DISTRITOS = [];
  const distEl = $("#distrito"), comboList = $("#combo-list");
  fetch("/distritos.json").then(r => r.json()).then(d => { DISTRITOS = d; }).catch(() => {});

  const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  let hiIndex = -1, filtered = [];
  function renderCombo(q) {
    const nq = norm(q);
    filtered = !nq ? [] : DISTRITOS.filter(x => norm(x.d).includes(nq)).slice(0, 40);
    if (!filtered.length) { comboList.hidden = true; return; }
    hiIndex = -1;
    comboList.innerHTML = filtered.map((x, i) =>
      `<div class="opt" data-i="${i}">${x.d}<small>${x.p}, ${x.dep}</small></div>`).join("");
    comboList.hidden = false;
  }
  distEl.addEventListener("input", () => { state.distrito = ""; state.ubigeo = ""; renderCombo(distEl.value); });
  distEl.addEventListener("keydown", (e) => {
    if (comboList.hidden) return;
    const opts = $$(".opt", comboList);
    if (e.key === "ArrowDown") { e.preventDefault(); hiIndex = Math.min(hiIndex + 1, opts.length - 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); hiIndex = Math.max(hiIndex - 1, 0); }
    else if (e.key === "Enter" && hiIndex >= 0) { e.preventDefault(); pickDistrito(filtered[hiIndex]); return; }
    else return;
    opts.forEach((o, i) => o.classList.toggle("hi", i === hiIndex));
  });
  comboList.addEventListener("click", (e) => {
    const o = e.target.closest(".opt"); if (o) pickDistrito(filtered[+o.dataset.i]);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".combo")) comboList.hidden = true;
  });
  function pickDistrito(x) {
    if (!x) return;
    state.distrito = x.d; state.ubigeo = x.u;
    distEl.value = x.d; comboList.hidden = true;
    $$(".dist-name").forEach(el => el.textContent = titleCase(x.d));
  }

  // Validar RUC + distrito → etapa 2
  $("#btn-validar").addEventListener("click", async () => {
    err1.hidden = true;
    const ruc = rucEl.value.trim();
    if (ruc.length !== 11) return showErr(err1, "Ingresa un RUC de 11 dígitos.");
    if (!state.distrito) return showErr(err1, "Elige tu distrito de la lista.");
    const btn = $("#btn-validar"); btn.disabled = true; btn.textContent = "Validando…";
    try {
      const r = await fetch("/api/validar-ruc", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ruc }),
      });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || "RUC no válido.");
      state.ruc = d.ruc; state.tipo = d.tipo || ""; state.razon_social = d.razon_social || "";
      if (d.razon_social) {
        razonEl.innerHTML = `✓ <b style="color:#d7ffe9">${escapeHtml(d.razon_social)}</b>`;
        razonEl.hidden = false;
        await sleep(450);
      }
      goto(2);
    } catch (e) {
      showErr(err1, e.message || "No pudimos validar. Intenta de nuevo.");
    } finally {
      btn.disabled = false; btn.textContent = "Continuar";
    }
  });

  // ---- Etapa 2: conteo adelanto + captura ----------------------------------
  async function cargarConteo() {
    const box = $("#conteo");
    box.innerHTML = `<div class="loading-mini">Consultando ${titleCase(state.distrito)}…</div>`;
    try {
      const r = await fetch(`/api/conteo?distrito=${encodeURIComponent(state.distrito)}&ubigeo=${state.ubigeo}`);
      const d = await r.json();
      if (!d.meses || !d.meses.length) {
        box.innerHTML = `<div class="empty">Estamos cargando los datos de ${titleCase(state.distrito)}. Déjanos tu contacto y te avisamos apenas estén.</div>`;
        return;
      }
      box.innerHTML = d.meses.map(m =>
        `<div class="mcard"><div class="num">${m.n}</div><div class="lbl">${m.mes}</div></div>`).join("");
    } catch {
      box.innerHTML = `<div class="empty">Déjanos tu contacto y te enviamos los nuevos negocios cada mes.</div>`;
    }
  }

  const err2 = $("#err2");
  $("#btn-ver").addEventListener("click", async () => {
    err2.hidden = true;
    const wa = $("#whatsapp").value.replace(/\D/g, "");
    const email = $("#email").value.trim();
    if (wa.length !== 9) return showErr(err2, "Ingresa un WhatsApp de 9 dígitos.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return showErr(err2, "Ingresa un email válido.");
    state.whatsapp = wa; state.email = email;
    const btn = $("#btn-ver"); btn.disabled = true;
    goto(3); // entra a etapa 3 (muestra spinner) mientras guardamos + traemos lista
  });

  // ---- Etapa 3: guardar lead + lista real ----------------------------------
  let listaCargada = false;
  async function cargarLista() {
    if (listaCargada) return;
    listaCargada = true;
    const cont = $("#lista"), count = $("#neg-count");
    try {
      const r = await fetch("/api/inscripcion", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nombre: state.razon_social, ruc: state.ruc, razon_social: state.razon_social,
          distrito: state.distrito, ubigeo: state.ubigeo,
          whatsapp: state.whatsapp, email: state.email, origen: state.origen,
        }),
      });
      const d = await r.json();
      const negocios = (d && d.negocios) || [];
      count.textContent = negocios.length ? `${negocios.length} negocios` : "";
      cont.innerHTML = negocios.length
        ? negocios.map(renderNegocio).join("")
        : `<div class="spinner"><span>Aún estamos cargando los negocios de ${titleCase(state.distrito)}. Te los enviaremos por WhatsApp y email apenas estén listos.</span></div>`;
    } catch {
      cont.innerHTML = `<div class="spinner"><span>No pudimos cargar la lista ahora. Ya guardamos tu registro; te la enviamos por WhatsApp.</span></div>`;
    }
  }

  // Abreviaturas de régimen para que el badge quepa en móvil.
  const REGIMEN_CORTO = {
    "Régimen General / MYPE": "Gral/MYPE",
    "Régimen Especial (RER)": "RER",
    "RUS": "RUS",
    "Amazonía": "Amazonía",
    "Agrario": "Agrario",
    "Frontera": "Frontera",
  };
  function regimenCorto(r) {
    if (!r) return "";
    return REGIMEN_CORTO[r] || r;
  }

  function renderNegocio(n) {
    const tag = n.tipo === "juridica" ? "Jurídica" : (n.tipo === "natural" ? "Natural" : "");
    const reg = regimenCorto(n.regimen);
    return `<div class="neg">
      <div class="top"><div class="rs">${escapeHtml(n.razon_social || "—")}</div>
        <div class="fecha">${escapeHtml(n.fecha_inscripcion || "")}</div></div>
      <div class="meta">
        <span class="ruc">RUC ${escapeHtml(n.ruc || "")}</span>
        ${n.giro ? `<span>· ${escapeHtml(n.giro)}</span>` : ""}
        ${tag ? `<span class="tag">${tag}</span>` : ""}
        ${reg ? `<span class="regimen" title="${escapeHtml(n.regimen)}">${escapeHtml(reg)}</span>` : ""}
      </div>
      ${n.direccion ? `<div class="dir">📍 ${escapeHtml(n.direccion)}</div>` : ""}
    </div>`;
  }

  // WhatsApp honesto: abre wa.me con mensaje pre-cargado; el usuario envia.
  $("#btn-wa").addEventListener("click", () => {
    const msg = `Hola, quiero recibir los nuevos negocios de ${titleCase(state.distrito)} cada mes. Mi RUC es ${state.ruc}.`;
    window.open(`https://wa.me/${WA_NUMBER}?text=${encodeURIComponent(msg)}`, "_blank");
  });

  // ---- PWA: install + push (opcional, preparado) ---------------------------
  let deferredPrompt = null;
  const btnInstall = $("#btn-install");
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); deferredPrompt = e; if (btnInstall) btnInstall.hidden = false;
  });
  if (btnInstall) btnInstall.addEventListener("click", async () => {
    if (deferredPrompt) { deferredPrompt.prompt(); deferredPrompt = null; }
    await activarPush();
  });

  async function activarPush() {
    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window) || !CFG.vapidPublicKey) return;
      const reg = await navigator.serviceWorker.ready;
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(CFG.vapidPublicKey),
      });
      await fetch("/api/push/subscribe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subscription: sub.toJSON(), ruc: state.ruc, distrito: state.distrito }),
      });
    } catch { /* push es opcional; no romper el flujo */ }
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }

  // ---- Utils ----------------------------------------------------------------
  function showErr(el, msg) { el.textContent = msg; el.hidden = false; }
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
  function titleCase(s) {
    return (s || "").toLowerCase().replace(/(^|\s|-)\p{L}/gu, c => c.toUpperCase());
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function originFromUrl() {
    const o = new URLSearchParams(location.search).get("o");
    return (["colegio", "facebook", "youtube"].includes(o)) ? o : "directo";
  }
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
  }
})();
