// Conversor SIRE · pantalla (modo local). Lee el archivo EN EL NAVEGADOR: no se sube a ninguna parte.
// Los textos del archivo se pintan siempre con textContent (nunca como HTML).
import * as M from "./motor.js?v=1";

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
  for (const h of hijos.flat()) if (h !== null && h !== undefined && h !== false && h !== "") e.append(h);
  return e;
}
const msg = (texto, tipo = "info") => $("msg").replaceChildren(el("div", { class: "msg " + tipo, texto }));
const nombreCampo = n => (spec.estructuras.rce_propuesta.campos.find(c => c.n === n) || {}).nombre || `Campo ${n}`;
const montoTxt = v => { const c = M.centimos(v || "0"); return c === null ? (v || "") : M.soles(c); };

async function cargarSpec() {
  if (!spec) spec = await (await fetch("/static/sire/sire-spec.json?v=1", { cache: "no-cache" })).json();
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

function pintar() {
  $("resultado").hidden = false;
  const f0 = estado.filas[0]?.c || {};
  const errores = estado.hallazgos.filter(h => h.nivel === "error").length, adv = estado.hallazgos.length - errores;
  $("fxVal").replaceChildren(el("span", { class: "q", texto: "=" }), `SIRE(${estado.propuesta.nombre}; compras)`);
  $("resNombre").textContent = estado.propuesta.origen !== estado.propuesta.nombre ? `${estado.propuesta.origen} → ${estado.propuesta.nombre}` : estado.propuesta.nombre;
  const dato = (dt, dd, clase = "") => el("div", {}, el("dt", { texto: dt }), el("dd", { class: clase, texto: dd }));
  $("resDatos").replaceChildren(
    dato("RUC del generador", f0[1] || "—", "mono"), dato("Periodo", f0[3] ? `${f0[3].slice(4)}/${f0[3].slice(0, 4)}` : "—", "mono"),
    dato("Comprobantes", String(estado.filas.length), "mono"),
    dato("Errores", String(errores), errores ? "rojo" : "verde"), dato("Advertencias", String(adv), adv ? "amarillo" : "verde"),
    dato("Codificación", estado.propuesta.codificacion), dato("Monedas", estado.totales.monedas.join(", ") || "—"));
  pintarCorrecciones();
  pintarTotales();
  pintarDetalle();
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
  for (const a of estado.avisos) bloques.push(el("div", { class: "msg info", texto: a.msg }));
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

function pintarDetalle() {
  const pf = porFila();
  const nivel = n => { const hs = pf.get(n) || []; return hs.some(h => h.nivel === "error") ? "error" : hs.length ? "advertencia" : ""; };
  const todas = estado.filas, conErr = todas.filter(f => nivel(f.n) === "error"), conAdv = todas.filter(f => nivel(f.n) === "advertencia");
  $("nTodos").textContent = todas.length; $("nErr").textContent = conErr.length; $("nAdv").textContent = conAdv.length;
  document.querySelectorAll(".ver-filtros button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.f === filtro)));
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
      el("td", { class: "mono", texto: c[5] }), el("td", {}, el("span", { class: "mono", texto: c[13] }), " ", c[14]),
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
  return el("div", {}, hs.length ? el("ul", {}, hs.map(h => el("li", { class: h.nivel === "error" ? "e" : "a", texto: `${h.nivel === "error" ? "Error" : "Advertencia"} · ${h.msg}` }))) : null,
    el("div", { class: "sire-campos" }, visibles.map(c => el("div", { class: malos.get(c.n) === "error" ? "mal" : malos.get(c.n) ? "ojo" : "" },
      el("small", { texto: `${c.n} · ${c.nombre}` }), f.c[c.n] || "—"))));
}

document.querySelectorAll(".ver-filtros button").forEach(b => b.addEventListener("click", () => { filtro = b.dataset.f; pagina = 0; abierta = null; pintarDetalle(); }));

// --- Excel (ExcelJS se carga recien al descargar) ----------------------------------------------------
async function descargar(imprimir) {
  const b1 = $("bExcel"), b2 = $("bImprimir");
  b1.disabled = b2.disabled = true; $("descMsg").textContent = "Armando el Excel en tu equipo…";
  try {
    const { generarExcel } = await import("./excel.js?v=1");
    const blob = await generarExcel(estado, spec, { imprimir });
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
