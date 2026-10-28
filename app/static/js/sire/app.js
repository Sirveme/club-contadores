// Conversor SIRE · pantalla (modo local). Lee el archivo EN EL NAVEGADOR: no se sube a ninguna parte.
// Los textos del archivo se pintan siempre con textContent (nunca como HTML).
import * as M from "./motor.js?v=3";

const $ = id => document.getElementById(id);
const CAP = JSON.parse(document.currentScript?.dataset.capacidades || document.querySelector("script[data-capacidades]")?.dataset.capacidades || "{}");
const POR_PAGINA = 200;
let spec = null, estado = null, filtro = "todos", pagina = 0, abierta = null;

function el(tag, props = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v; else if (k === "texto") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const h of hijos.flat(Infinity)) if (h !== null && h !== undefined && h !== false && h !== "") e.append(h);
  return e;
}
// --- Modo video: enmascara RUC y razones sociales SOLO a la vista (CSS); el dato real sigue ahi ------
const tapa = (real, puntos) => [el("span", { class: "tapa", texto: real }), el("span", { class: "puntos", "aria-hidden": "true", texto: puntos })];
const R = ruc => !ruc ? "" : el("span", { class: "m" }, ruc.slice(0, 2), tapa(ruc.slice(2), "•".repeat(Math.max(0, ruc.length - 2))));
const N = nom => !nom ? "" : el("span", { class: "m" }, nom.slice(0, 2), tapa(nom.slice(2), "•".repeat(Math.min(12, Math.max(0, nom.length - 2)))));
const conRucs = texto => String(texto).split(/(?<!\d)(\d{11})(?!\d)/).map((x, i) => i % 2 ? R(x) : x);   // RUC dentro de un texto
const CAMPOS_RUC = new Set([1, 13]), CAMPOS_NOMBRE = new Set([2, 14]), CAMPOS_CAR = new Set([4, 37]);
const valorCampo = (n, v) => !v ? "—" : CAMPOS_RUC.has(n) ? R(v) : CAMPOS_NOMBRE.has(n) ? N(v) : CAMPOS_CAR.has(n) && /^\d{11}/.test(v) ? [R(v.slice(0, 11)), v.slice(11)] : v;
const MASC = "sire.mascara";
function mascara(on) {
  document.documentElement.toggleAttribute("data-mascara", on);
  $("bMascara").setAttribute("aria-pressed", String(on));
  try { if (on) localStorage.setItem(MASC, "1"); else localStorage.removeItem(MASC); } catch (_) { /* sin almacenamiento */ }
}
let mascaraInicial = false;
try { mascaraInicial = localStorage.getItem(MASC) === "1"; } catch (_) { /* nada */ }

const msg = (texto, tipo = "info") => $("msg").replaceChildren(el("div", { class: "msg " + tipo, texto }));
const nombreCampo = n => (spec.estructuras.rce_propuesta.campos.find(c => c.n === n) || {}).nombre || `Campo ${n}`;
const montoTxt = v => { const c = M.centimos(v || "0"); return c === null ? (v || "") : M.soles(c); };

async function cargarSpec() {
  if (!spec) spec = await (await fetch("/static/sire/sire-spec.json?v=2", { cache: "no-cache" })).json();
  return spec;
}

// --- Entrada de archivos -------------------------------------------------------------------------
async function leer(archivos) {
  $("estadoTxt").textContent = "Leyendo…";
  try {
    await cargarSpec();
    let propuesta = null, resumen = null;
    for (const a of archivos) {
      const bytes = new Uint8Array(await a.arrayBuffer());
      const piezas = /\.zip$/i.test(a.name) || (bytes[0] === 0x50 && bytes[1] === 0x4b) ? await M.descomprimir(bytes) : [{ nombre: a.name, data: bytes }];
      for (const p of piezas) {
        const { texto, codificacion } = M.decodificar(p.data);
        const primera = texto.split(/\r?\n/, 1)[0] || "";
        if (/^tipo de documento\|/i.test(primera)) resumen = { nombre: p.nombre, texto };
        else if (!propuesta) propuesta = { nombre: p.nombre, texto, codificacion, origen: a.name };
      }
    }
    if (!propuesta) throw new Error(resumen ? "Ese es el resumen: sube también la propuesta (el ZIP o el TXT con el detalle)." : "No encontramos una propuesta en lo que subiste.");
    const r = M.procesar(propuesta.texto, spec);
    estado = { ...r, propuesta, resumen, corregidas: 0 };
    filtro = "todos"; pagina = 0; abierta = null;
    pintar();
    $("msg").replaceChildren();
  } catch (e) {
    $("resultado").hidden = true;
    zona.classList.add("inicio");
    msg(e.message || "No pudimos leer el archivo.", "err");
  } finally { $("estadoTxt").textContent = "Listo"; }
}

const zona = $("zona"), entrada = $("archivo");
entrada.addEventListener("change", () => entrada.files.length && leer([...entrada.files]));
zona.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); entrada.click(); } });
["dragenter", "dragover"].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.add("encima"); }));
["dragleave", "drop"].forEach(t => zona.addEventListener(t, e => { e.preventDefault(); zona.classList.remove("encima"); }));
zona.addEventListener("drop", e => e.dataTransfer.files.length && leer([...e.dataTransfer.files]));

// --- Pintar resultado -----------------------------------------------------------------------------
function recalcular() {
  estado.hallazgos = M.validar(estado.filas, spec);
  estado.totales = M.totales(estado.filas, spec);
  estado.comas = M.detectarComas(estado.filas, spec.estructuras.rce_propuesta);
}
function porFila() {
  const m = new Map();
  for (const h of estado.hallazgos) { if (!m.has(h.fila)) m.set(h.fila, []); m.get(h.fila).push(h); }
  return m;
}

// --- Jerarquia: naranja = "aca actuas"; gris = solo lectura -------------------------------------------
function accion(seccion, tag, texto) {
  $(seccion).classList.toggle("sire-actua", !!texto);
  $(seccion).classList.toggle("sire-lee", !texto);
  $(tag).hidden = !texto; $(tag).textContent = texto || "";
}
// Guia: el siguiente paso se resalta un momento, la primera vez que se ve en pantalla (no permanente).
let guiaObs = null;
function guiar(objetivo) {
  guiaObs?.disconnect(); guiaObs = null;
  document.querySelectorAll(".sire-guia").forEach(x => x.classList.remove("sire-guia"));
  if (!objetivo || !("IntersectionObserver" in window)) return;
  guiaObs = new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) return;
    guiaObs.disconnect(); guiaObs = null;
    objetivo.classList.add("sire-guia");
    objetivo.addEventListener("animationend", () => objetivo.classList.remove("sire-guia"), { once: true });
  }, { threshold: 0.6 });
  guiaObs.observe(objetivo);
}

function pintar() {
  $("resultado").hidden = false;
  zona.classList.remove("inicio");
  const f0 = estado.filas[0]?.c || {};
  const errores = estado.hallazgos.filter(h => h.nivel === "error").length, adv = estado.hallazgos.length - errores;
  $("fxVal").replaceChildren(el("span", { class: "q", texto: "=" }), "SIRE(", conRucs(estado.propuesta.nombre), "; compras)");
  $("resNombre").replaceChildren(...conRucs(estado.propuesta.origen !== estado.propuesta.nombre ? `${estado.propuesta.origen} → ${estado.propuesta.nombre}` : estado.propuesta.nombre));
  const dato = (dt, dd, clase = "") => el("div", {}, el("dt", { texto: dt }), el("dd", { class: clase }, dd));
  $("resDatos").replaceChildren(
    dato("RUC del generador", f0[1] ? R(f0[1]) : "—", "mono"), dato("Periodo", f0[3] ? `${f0[3].slice(4)}/${f0[3].slice(0, 4)}` : "—", "mono"),
    dato("Comprobantes", String(estado.filas.length), "mono"),
    dato("Errores", String(errores), errores ? "rojo" : "verde"), dato("Advertencias", String(adv), adv ? "amarillo" : "verde"),
    dato("Codificación", estado.propuesta.codificacion), dato("Monedas", estado.totales.monedas.join(", ") || "—"));
  pintarCorrecciones();
  pintarActividad(f0[1]);
  pintarTotales();
  pintar621();
  pintarDetalle();
  guiar(errores ? document.querySelector('.ver-filtros button[data-f="error"]') : perfil.noGravadas == null ? $("perfil") : null);
}

function pintarCorrecciones() {
  const bloques = [];
  const comas = estado.comas.filter(h => h.sugerido != null);
  if (comas.length) {
    const dudosos = comas.filter(h => h.dudoso).length;
    bloques.push(el("div", { class: "msg err" },
      el("b", { texto: `Encontramos ${comas.length} monto${comas.length === 1 ? "" : "s"} con coma (${comas[0].valor} → ${comas[0].sugerido}). ` }),
      "El formato pide punto decimal y sin separador de miles. ",
      dudosos ? `${dudosos} no se pudieron confirmar: revísalos después. ` : "",
      el("button", { type: "button", class: "btn-ver", texto: `Corregir ${comas.length === 1 ? "el monto" : `los ${comas.length} montos`}`, onclick: () => {
        M.aplicarComas(estado.filas, comas); estado.corregidas += comas.length; recalcular(); pintar(); } }),
      el("ul", {}, comas.slice(0, 5).map(h => el("li", {}, `Fila ${h.fila}, ${nombreCampo(h.campo)}: `, el("code", { texto: h.valor }), " → ", el("code", { texto: h.sugerido }),
        h.razon ? ` (${h.razon})` : "")))));
  }
  const raros = estado.comas.filter(h => h.sugerido == null);
  if (raros.length) bloques.push(el("div", { class: "msg err", texto: `${raros.length} monto(s) con un formato que no reconocemos (por ejemplo «${raros[0].valor}» en la fila ${raros[0].fila}): corrígelos en el Excel.` }));
  if (estado.corregidas) bloques.push(el("div", { class: "msg info", texto: `Corregiste ${estado.corregidas} monto(s) de coma a punto.` }));
  // Avisos contables (p. ej. tipo 30): a la vista. Ajustes tecnicos de lectura: colapsados.
  const TECNICOS = new Set(["limpieza", "generador", "estructura"]);
  for (const a of estado.avisos.filter(a => !TECNICOS.has(a.tipo))) bloques.push(el("div", { class: "msg info" }, conRucs(a.msg)));
  const tec = estado.avisos.filter(a => TECNICOS.has(a.tipo)), s = tec.length === 1 ? "" : "s";
  if (tec.length) bloques.push(el("details", { class: "sire-tecnicos" },
    el("summary", {}, el("span", { class: "chip-sem verde" }, el("s", { class: "sem verde" }), `✓ ${tec.length} ajuste${s} técnico${s} aplicado${s}`),
      el("span", { class: "faint", texto: " · de lectura del archivo, no contables" })),
    el("ol", {}, tec.map(a => el("li", {}, a.tipo === "generador" && a.variantes
      ? [`El nombre del generador aparece de ${a.variantes.length} formas distintas (es normal en la propuesta): `, a.variantes.flatMap((v, i) => i ? [" · ", N(v)] : [N(v)]), "."]
      : a.msg)))));
  accion("pCorr", "tagCorr", comas.length ? `${comas.length} por corregir` : "");
  $("pCorr").hidden = !bloques.length;
  $("corr").replaceChildren(el("div", { class: "sire-corr" }, bloques));
}

function pintarTotales() {
  const t = estado.totales, cols = t.conMonto.length ? t.conMonto : [25];
  const cab = el("tr", {}, el("th", { texto: "Tipo de comprobante" }), t.monedas.length > 1 ? el("th", { texto: "Moneda" }) : null,
    el("th", { class: "num", texto: "Comprobantes" }), cols.map(c => el("th", { class: "num", texto: nombreCampo(c) })));
  const filas = t.porTipo.map(g => el("tr", {}, el("td", { texto: `${g.tipo} · ${g.nombre}` }), t.monedas.length > 1 ? el("td", { class: "mono", texto: g.moneda }) : null,
    el("td", { class: "num", texto: String(g.n) }), cols.map(c => el("td", { class: "num", texto: M.soles(g.montos[c]) }))));
  const tot = el("tr", { class: "total" }, el("td", { texto: "Total" }), t.monedas.length > 1 ? el("td", { texto: "" }) : null,
    el("td", { class: "num", texto: String(t.total.n) }), cols.map(c => el("td", { class: "num", texto: M.soles(t.total.montos[c]) })));
  $("tot").replaceChildren(el("thead", {}, cab), el("tbody", {}, filas, tot));
  $("totNota").textContent = `Solo las columnas con monto · ${t.monedas.length > 1 ? "por moneda, sin convertir" : "en " + (t.monedas[0] || "PEN")}`;
  const caja = $("cuadre");
  if (!estado.resumen) { caja.replaceChildren(el("p", { class: "faint sire-cuadre", texto: "Sube también el TXT del resumen y comprobamos que estos totales cuadren con él." })); return; }
  try {
    const c = M.compararResumen(estado.resumen.texto, t, spec);
    caja.replaceChildren(c.cuadra
      ? el("div", { class: "msg info sire-cuadre" }, el("span", { class: "chip-sem verde" }, el("s", { class: "sem verde" }), "Cuadra con el resumen"), ` · comprobantes y montos iguales (${estado.resumen.nombre}).`)
      : el("div", { class: "msg err sire-cuadre" }, el("b", { texto: "No cuadra con el resumen. " }),
          el("ul", {}, c.diferencias.slice(0, 8).map(d => el("li", { texto: `${d.tipo} · ${d.campo}: resumen ${d.centimos ? M.soles(d.resumen) : d.resumen}, archivo ${d.centimos ? M.soles(d.nuestro) : d.nuestro}` })))));
  } catch (e) { caja.replaceChildren(el("div", { class: "msg err sire-cuadre", texto: e.message })); }
}

// --- Actividad / marcas del generador ---------------------------------------------------------------
// Lo unico que sale del navegador: el RUC del generador (sin montos ni fechas). No se guarda cual fue.
const actividades = new Map();
async function pintarActividad(ruc) {
  const caja = $("actividad");
  if (!ruc || !M.rucValido(ruc)) { caja.replaceChildren(); return; }
  if (!actividades.has(ruc)) {
    caja.replaceChildren(el("span", { class: "faint", texto: "Buscando la actividad del generador…" }));
    actividades.set(ruc, fetch("/api/sire/actividad", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ruc }), cache: "no-store" })
      .then(r => r.json()).catch(() => ({ ok: false })));
  }
  const d = await actividades.get(ruc);
  if (estado?.filas[0]?.c[1] !== ruc) return;                     // ya cargaron otro archivo
  if (!d.ok) { caja.replaceChildren(el("span", { class: "faint", texto: "No pudimos ver la actividad del generador ahora." })); actividades.delete(ruc); return; }
  const vigentes = d.marcas.filter(m => !m.historico);
  const etiquetas = [...d.sectores, ...vigentes.filter(m => !m.sector).map(m => m.nombre)];
  caja.replaceChildren(el("button", { type: "button", class: "sire-chip" + (vigentes.some(m => m.tipo === "riesgo") ? " riesgo" : ""), onclick: () => abrirFicha(d, ruc) },
    el("small", { texto: "Actividad / marcas detectadas" }), el("b", { texto: etiquetas.length ? etiquetas.join(" · ") : "Ninguna marca especial" }),
    el("span", { class: "faint", texto: "Ver ficha →" })));
}
function abrirFicha(d, ruc) {
  const fecha = iso => iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "";
  const grupo = m => el("div", { class: "sire-marca" + (m.tipo === "riesgo" ? " riesgo" : "") + (m.historico ? " historico" : "") },
    el("div", {}, el("b", { texto: m.nombre }), m.sector ? el("span", { class: "sire-sector", texto: m.sector }) : null,
      m.desde ? el("span", { class: "faint", texto: ` · desde ${fecha(m.desde)}` }) : null, m.historico ? el("span", { class: "faint", texto: " · lista antigua" }) : null),
    m.notas.length ? el("ul", {}, m.notas.map(n => el("li", { texto: n }))) : null);
  $("fichaCuerpo").replaceChildren(
    el("p", { class: "faint" }, "RUC del generador ", el("span", { class: "mono" }, R(ruc)), d.datos_al ? ` · datos al ${d.datos_al}` : ""),
    d.marcas.length ? el("div", { class: "sire-marcas" }, d.marcas.map(grupo)) : el("p", { texto: "No figura en ninguna de las listas que revisamos: sin particularidades especiales que mostrar." }),
    el("div", { class: "sire-pronto" }, el("b", { texto: "Correcciones automáticas de tu sector" }), el("span", { class: "faint", texto: " — pronto" })),
    el("p", { class: "faint", texto: "Texto informativo: no reemplaza tu revisión. Solo consultamos el RUC, sin montos ni fechas; no guardamos qué RUC consultas." }));
  $("ficha").showModal();
}
$("fichaCerrar").addEventListener("click", () => $("ficha").close());
$("ficha").addEventListener("click", e => { if (e.target === $("ficha")) $("ficha").close(); });
$("bMascara").addEventListener("click", () => mascara(!document.documentElement.hasAttribute("data-mascara")));
mascara(mascaraInicial);

// --- Destino de las compras y casillas del 621 ------------------------------------------------------
// El perfil solo vive en este navegador (comodidad): no se envía a ninguna parte.
let perfil = {};
try { perfil = JSON.parse(localStorage.getItem("sire.perfil") || "{}") || {}; } catch (_) { perfil = {}; }
const PREGUNTAS = [
  { k: "noGravadas", q: "¿En los últimos 12 meses tuviste ventas no gravadas (exoneradas o inafectas, sin contar exportaciones)?", op: [["si", "Sí"], ["no", "No"]] },
  { k: "exporta", q: "¿Exportas?", op: [[true, "Sí"], [false, "No"]] },
];
function pintar621() {
  $("perfil").replaceChildren(...PREGUNTAS.map(p => el("div", { class: "ver-filtros sire-perfil" }, el("span", { texto: p.q }),
    p.op.map(([v, t]) => el("button", { type: "button", "data-p": p.k, "aria-pressed": String(perfil[p.k] === v), texto: t, onclick: () => {
      perfil[p.k] = perfil[p.k] === v ? null : v;
      try { localStorage.setItem("sire.perfil", JSON.stringify(perfil)); } catch (_) { /* sin almacenamiento: igual funciona */ }
      pintar621(); } })))));
  const av = M.avisosDestino(estado.filas, spec, perfil);
  $("destino").replaceChildren(...(av.length ? av : [{ nivel: "info", msg: perfil.noGravadas == null
    ? "Responde la primera pregunta y revisamos si el destino de tus compras (casillas 107, 110 o 113) calza con tu caso." : "El destino de tus compras calza con lo que indicaste." }])
    .map(a => el("div", { class: "msg " + (a.nivel === "advertencia" ? "err" : "info") }, el("span", { texto: a.msg }),
      a.fundamento ? el("small", { class: "sire-fund", texto: "Fundamento: " + a.fundamento }) : null)));
  const k = M.casillas621(estado.filas, spec), con = k.casillas.filter(c => c.centimos !== 0);
  $("f621").replaceChildren(el("thead", {}, el("tr", {}, el("th", { class: "num", texto: "Casilla" }), el("th", { texto: "Concepto" }),
    el("th", { texto: "Viene del campo" }), el("th", { class: "num", texto: "Monto" }))),
    el("tbody", {}, (con.length ? con : k.casillas.slice(0, 1)).map(c => el("tr", {}, el("td", { class: "num", texto: String(c.c) }), el("td", { texto: c.nombre }),
      el("td", { class: "mono", texto: `${c.campo}${c.origen === "importaciones" ? " (importaciones)" : ""}` }), el("td", { class: "num", texto: M.soles(c.centimos) })))));
  $("f621Nota").textContent = "El Formulario 621 precarga estas casillas desde tu registro y son editables; el IGV de las casillas 108, 111, 115 y 117 lo recalcula el formulario con la tasa." +
    (k.convertidos ? ` ${k.convertidos} comprobante(s) en otra moneda se convirtieron con su propio tipo de cambio.` : "");
}

function pintarDetalle() {
  const pf = porFila();
  const nivel = n => { const hs = pf.get(n) || []; return hs.some(h => h.nivel === "error") ? "error" : hs.length ? "advertencia" : ""; };
  const todas = estado.filas, conErr = todas.filter(f => nivel(f.n) === "error"), conAdv = todas.filter(f => nivel(f.n) === "advertencia");
  $("nTodos").textContent = todas.length; $("nErr").textContent = conErr.length; $("nAdv").textContent = conAdv.length;
  accion("pDet", "tagDet", conErr.length ? `${conErr.length} por corregir` : "");
  document.querySelectorAll(".ver-filtros button[data-f]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.f === filtro)));
  const lista = filtro === "error" ? conErr : filtro === "advertencia" ? conAdv : todas;
  const paginas = Math.max(1, Math.ceil(lista.length / POR_PAGINA));
  pagina = Math.min(pagina, paginas - 1);
  const vista = lista.slice(pagina * POR_PAGINA, (pagina + 1) * POR_PAGINA);
  const cab = el("tr", {}, ["#", "Tipo", "Serie-Número", "Emisión", "Proveedor", "Base imp.", "IGV", "No gravadas", "Total", "Moneda", "Observaciones"]
    .map((t, i) => el("th", { class: i === 0 ? "n" : i >= 5 && i <= 8 ? "num" : "", texto: t })));
  const cuerpo = [];
  for (const f of vista) {
    const c = f.c, hs = pf.get(f.n) || [], nv = nivel(f.n);
    const bi = (M.centimos(c[15] || "0") ?? 0) + (M.centimos(c[17] || "0") ?? 0) + (M.centimos(c[19] || "0") ?? 0);
    const igv = (M.centimos(c[16] || "0") ?? 0) + (M.centimos(c[18] || "0") ?? 0) + (M.centimos(c[20] || "0") ?? 0);
    const e = hs.filter(h => h.nivel === "error").length, a = hs.length - e;
    cuerpo.push(el("tr", { class: "fila " + nv, tabindex: "0", title: "Ver todos los campos", onclick: () => { abierta = abierta === f.n ? null : f.n; pintarDetalle(); },
        onkeydown: ev => { if (ev.key === "Enter") { abierta = abierta === f.n ? null : f.n; pintarDetalle(); } } },
      el("td", { class: "n", texto: String(f.n) }), el("td", { class: "mono", texto: c[7] }), el("td", { class: "mono", texto: `${c[8]}-${c[10]}` }),
      el("td", { class: "mono", texto: c[5] }), el("td", {}, el("span", { class: "mono" }, R(c[13])), " ", N(c[14])),
      el("td", { class: "num", texto: M.soles(bi) }), el("td", { class: "num", texto: M.soles(igv) }), el("td", { class: "num", texto: montoTxt(c[21]) }),
      el("td", { class: "num", texto: montoTxt(c[25]) }), el("td", { class: "mono", texto: c[26] }),
      el("td", { class: "obs" }, e ? el("span", { class: "e", texto: `${e} error${e === 1 ? "" : "es"}` }) : null, e && a ? " · " : null,
        a ? el("span", { class: "a", texto: `${a} advertencia${a === 1 ? "" : "s"}` }) : null, !hs.length ? "—" : null)));
    if (abierta === f.n) cuerpo.push(el("tr", { class: "detalle" }, el("td", { colspan: "11" }, detalleFila(f, hs))));
  }
  if (!vista.length) cuerpo.push(el("tr", {}, el("td", { colspan: "11", class: "faint", texto: filtro === "todos" ? "El archivo no trae comprobantes." : "Ninguno. ✓" })));
  $("det").replaceChildren(el("thead", {}, cab), el("tbody", {}, cuerpo));
  $("detNota").textContent = "Toca una fila para ver todos sus campos";
  $("pag").replaceChildren(paginas > 1 ? [
    el("button", { type: "button", class: "btn-sec", texto: "← Anteriores", onclick: () => { pagina--; pintarDetalle(); }, ...(pagina === 0 ? { disabled: "" } : {}) }),
    el("span", { texto: `Página ${pagina + 1} de ${paginas}` }),
    el("button", { type: "button", class: "btn-sec", texto: "Siguientes →", onclick: () => { pagina++; pintarDetalle(); }, ...(pagina >= paginas - 1 ? { disabled: "" } : {}) })] : []);
}

function detalleFila(f, hs) {
  const malos = new Map(hs.map(h => [h.campo, h.nivel]));
  const est = spec.estructuras.rce_propuesta;
  const visibles = est.campos.filter(c => !c.libre || f.c[c.n]);
  return el("div", {}, hs.length ? el("ul", {}, hs.map(h => el("li", { class: h.nivel === "error" ? "e" : "a" }, `${h.nivel === "error" ? "Error" : "Advertencia"} · `, conRucs(h.msg)))) : null,
    el("div", { class: "sire-campos" }, visibles.map(c => el("div", { class: malos.get(c.n) === "error" ? "mal" : malos.get(c.n) ? "ojo" : "" },
      el("small", { texto: `${c.n} · ${c.nombre}` }), valorCampo(c.n, f.c[c.n])))));
}

document.querySelectorAll(".ver-filtros button[data-f]").forEach(b => b.addEventListener("click", () => { filtro = b.dataset.f; pagina = 0; abierta = null; pintarDetalle(); }));

// --- Excel (ExcelJS se carga recien al descargar) ----------------------------------------------------
async function descargar(imprimir) {
  const b1 = $("bExcel"), b2 = $("bImprimir");
  b1.disabled = b2.disabled = true; $("descMsg").textContent = "Armando el Excel en tu equipo…";
  try {
    const { generarExcel } = await import("./excel.js?v=3");
    const blob = await generarExcel({ ...estado, perfil }, spec, { imprimir });
    const base = estado.propuesta.nombre.replace(/\.(txt|zip)$/i, "");
    const a = el("a", { href: URL.createObjectURL(blob), download: `${base}${imprimir ? "-imprimir" : ""}.xlsx` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    $("descMsg").textContent = "Listo: revisa tus descargas.";
  } catch (e) { $("descMsg").textContent = "No pudimos armar el Excel: " + (e.message || e); }
  finally { b1.disabled = b2.disabled = false; }
}
$("bExcel").addEventListener("click", () => descargar(false));
$("bImprimir").addEventListener("click", () => descargar(true));
window.__sireCapacidades = CAP;                    // riesgo / servidor: se encienden desde el servidor (suscripcion)
