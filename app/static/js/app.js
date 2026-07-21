/* Club de Contadores — embudo por etapas, mobile-first sin scroll. */
(() => {
  "use strict";

  // Numero de WhatsApp del Club (Peru). Cambiar por el real de Perú Sistemas.
  const WA_NUMBER = "51999888777";

  const CFG = window.__CFG__ || {};
  const state = { ruc: "", razon_social: "", tipo: "", distrito: "", ubigeo: "",
                  provincia: "", departamento: "",
                  whatsapp: "", email: "", origen: origenFromUrl(),
                  meses: [], mesSel: "" };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---- Captura temprana progresiva del lead --------------------------------
  // Un solo registro por usuario (session_id en localStorage) que se va
  // completando por UPSERT. Se guarda apenas hay dato (RUC+distrito al avanzar;
  // WhatsApp/email al blur/debounce — sin esperar a ningun boton).
  const SID = (() => {
    const KEY = "cc_sid";
    let v = "";
    try { v = localStorage.getItem(KEY) || ""; } catch (_) {}
    if (!v) {
      v = (self.crypto && crypto.randomUUID) ? crypto.randomUUID()
          : "s-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
      try { localStorage.setItem(KEY, v); } catch (_) {}
    }
    return v;
  })();

  function saveLead(partial) {
    // La IDENTIDAD del lead es el RUC (validado). Sin RUC no se guarda: asi nunca
    // se crea ni se pisa un registro sin RUC, y el backend hace UPSERT por RUC.
    if (!state.ruc) return;
    const body = JSON.stringify({
      session_id: SID, origen: state.origen,
      ruc: state.ruc, razon_social: state.razon_social, nombre: state.razon_social,
      distrito: state.distrito, ubigeo: state.ubigeo,
      ...partial,
    });
    // sendBeacon sobrevive a que el usuario cierre/navegue; fallback a fetch.
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/api/lead", new Blob([body], { type: "application/json" }));
        return;
      }
    } catch (_) {}
    fetch("/api/lead", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body, keepalive: true,
    }).catch(() => {});
  }

  function debounce(fn, ms) {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

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
    state.provincia = x.p || ""; state.departamento = x.dep || "";
    state.meses = []; state.mesSel = ""; stage3Init = false; // distrito nuevo -> recargar
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
      // Guardado TEMPRANO: RUC + distrito apenas se valida (etapa 1->2).
      saveLead({ etapa: 2 });
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
      state.meses = (d && d.meses) || [];
      if (!state.meses.length) {
        box.innerHTML = `<div class="empty">Estamos cargando los datos de ${titleCase(state.distrito)}. Déjanos tu contacto y te avisamos apenas estén.</div>`;
        return;
      }
      box.innerHTML = state.meses.map(m =>
        `<div class="mcard"><div class="num">${m.n}</div><div class="lbl">${m.mes}</div></div>`).join("");
    } catch {
      box.innerHTML = `<div class="empty">Déjanos tu contacto y te enviamos los nuevos negocios cada mes.</div>`;
    }
  }

  const err2 = $("#err2");
  const waEl = $("#whatsapp"), emailEl = $("#email");

  // CAPTURA TEMPRANA de WhatsApp/email: al blur (inmediato) y al tipear
  // (debounce), SIN esperar a que toque ningun boton. Si escribe el WhatsApp y
  // abandona ahi, igual queda guardado.
  const guardarWa = () => {
    const wa = waEl.value.replace(/\D/g, "");
    if (wa.length >= 6) { state.whatsapp = wa; saveLead({ whatsapp: wa, etapa: 2 }); }
  };
  const guardarEmail = () => {
    const em = emailEl.value.trim();
    if (em.includes("@")) { state.email = em; saveLead({ email: em, etapa: 2 }); }
  };
  waEl.addEventListener("input", debounce(guardarWa, 800));
  waEl.addEventListener("blur", guardarWa);
  emailEl.addEventListener("input", debounce(guardarEmail, 900));
  emailEl.addEventListener("blur", guardarEmail);

  $("#btn-ver").addEventListener("click", async () => {
    err2.hidden = true;
    const wa = waEl.value.replace(/\D/g, "");
    const email = emailEl.value.trim();
    if (wa.length !== 9) return showErr(err2, "Ingresa un WhatsApp de 9 dígitos.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return showErr(err2, "Ingresa un email válido.");
    state.whatsapp = wa; state.email = email;
    // Guardado al avanzar a etapa 3 (lead completo: WhatsApp + email).
    saveLead({ whatsapp: wa, email, etapa: 3 });
    const btn = $("#btn-ver"); btn.disabled = true;
    goto(3); // entra a etapa 3 (muestra spinner) mientras traemos la lista
  });

  // ---- Etapa 3: lista real (el lead ya se guardo progresivamente) ----------
  // Chips de mes: el usuario elige el mes; la lista se filtra por ESE mes con el
  // MISMO filtro del conteo -> el numero del panorama cuadra con lo que se lista.
  let stage3Init = false;
  const mesesEl = $("#meses");
  function renderMeses() {
    if (!state.meses.length) { mesesEl.hidden = true; return; }
    if (!state.mesSel) state.mesSel = state.meses[state.meses.length - 1].ym; // por defecto el mas reciente
    mesesEl.innerHTML = state.meses.map(m =>
      `<button class="mes-chip${m.ym === state.mesSel ? " on" : ""}" data-ym="${m.ym}">
         ${m.mes} ${m.anio} · <b>${m.n}</b></button>`).join("");
    mesesEl.hidden = false;
  }
  mesesEl.addEventListener("click", (e) => {
    const c = e.target.closest(".mes-chip"); if (!c) return;
    state.mesSel = c.dataset.ym;
    renderMeses(); cargarLista(true);
  });

  async function cargarLista(force = false) {
    if (stage3Init && !force) return;
    if (!stage3Init) { stage3Init = true; saveLead({ etapa: 3 }); renderMeses(); }
    const cont = $("#lista"), count = $("#neg-count");
    cont.innerHTML = `<div class="spinner"><div class="ring"></div><span>Buscando…</span></div>`;
    try {
      const r = await fetch(
        `/api/negocios?distrito=${encodeURIComponent(state.distrito)}&ubigeo=${state.ubigeo}` +
        (state.mesSel ? `&mes=${state.mesSel}` : "")
      );
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
    "Régimen General": "General",
    "Régimen MYPE Tributario (RMT)": "RMT",
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
  // Incluye PROVINCIA y DEPARTAMENTO (hay distritos homonimos en varias regiones).
  $("#btn-wa").addEventListener("click", () => {
    const ubic = [state.distrito, state.provincia, state.departamento]
      .filter(Boolean).map(titleCase).join(", ");
    const msg = `Hola, quiero recibir los nuevos negocios de ${ubic} cada mes. Mi RUC es ${state.ruc}.`;
    window.open(`https://wa.me/${WA_NUMBER}?text=${encodeURIComponent(msg)}`, "_blank");
    goto(4); // pantalla de cierre
  });

  // Etapa 4 (cierre): volver a la lista.
  $("#btn-volver-lista").addEventListener("click", () => goto(3));

  // ---- Modal: Política de Privacidad y Términos (no rompe sin-scroll) -------
  const modal = $("#modal-legal");
  $("#lnk-legal").addEventListener("click", (e) => { e.preventDefault(); modal.hidden = false; });
  modal.addEventListener("click", (e) => { if (e.target.closest("[data-close-modal]")) modal.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") modal.hidden = true; });

  // ---- PWA: install + push (opcional, preparado) ---------------------------
  let deferredPrompt = null;
  const btnsInstall = [$("#btn-install"), $("#btn-install-2")].filter(Boolean);
  const installHint = $("#install-hint");
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); deferredPrompt = e;
    btnsInstall.forEach(b => b.hidden = false);   // escritorio/Android con prompt nativo
  });
  async function onInstall() {
    if (deferredPrompt) {
      deferredPrompt.prompt(); deferredPrompt = null;
      btnsInstall.forEach(b => b.hidden = true);
    } else if (installHint) {
      installHint.hidden = false;                 // iOS / sin prompt: instruccion breve
    }
    await activarPush();
  }
  btnsInstall.forEach(b => b.addEventListener("click", onInstall));

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
  function origenFromUrl() {
    // Captura el ORIGEN/UTM real de la convocatoria (colegio-X, facebook, youtube…).
    // NADA de fingerprinting/geo/IP: solo parametros que vienen en el enlace.
    const q = new URLSearchParams(location.search);
    const raw = q.get("origen") || q.get("o") || q.get("utm_source") || q.get("ref") || "";
    const camp = q.get("utm_campaign") || "";
    let v = [raw, camp].filter(Boolean).join("-");
    v = v.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30);
    return v || "directo";
  }
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
  }
})();
