// Conversor SIRE · motor (modo local). Funciones puras: corren en el navegador y en Node (pruebas).
// Todo se calcula en el equipo de la persona: este modulo no hace ninguna llamada de red.
// La estructura y las reglas vienen de /static/sire/sire-spec.json (una sola fuente de verdad).

// --- ZIP (el portal entrega la propuesta comprimida) ----------------------------------------
// Lector minimo de ZIP: directorio central + "deflate" con el DecompressionStream del navegador.
export async function descomprimir(bytes) {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  let fin = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { fin = i; break; }
  if (fin < 0) throw new Error("El archivo no es un ZIP válido.");
  const total = dv.getUint16(fin + 10, true);
  let p = dv.getUint32(fin + 16, true);
  const out = [];
  for (let k = 0; k < total; k++) {
    if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("ZIP dañado.");
    const metodo = dv.getUint16(p + 10, true), comp = dv.getUint32(p + 20, true);
    const ln = dv.getUint16(p + 28, true), lx = dv.getUint16(p + 30, true), lc = dv.getUint16(p + 32, true);
    const local = dv.getUint32(p + 42, true);
    const nombre = new TextDecoder().decode(u8.subarray(p + 46, p + 46 + ln));
    p += 46 + ln + lx + lc;
    if (nombre.endsWith("/")) continue;
    const inicio = local + 30 + dv.getUint16(local + 26, true) + dv.getUint16(local + 28, true);
    const crudo = u8.subarray(inicio, inicio + comp);
    let data;
    if (metodo === 0) data = crudo.slice();
    else if (metodo === 8) data = new Uint8Array(await new Response(new Blob([crudo]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer());
    else throw new Error(`ZIP con compresión no soportada (${metodo}).`);
    out.push({ nombre, data });
  }
  return out;
}

export function decodificar(bytes) {
  try { return { texto: new TextDecoder("utf-8", { fatal: true }).decode(bytes).replace(/^﻿/, ""), codificacion: "UTF-8" }; }
  catch (_) { return { texto: new TextDecoder("windows-1252").decode(bytes), codificacion: "Windows-1252" }; }
}

// --- JSON Logic (subconjunto) -----------------------------------------------------------------
const ops = {
  var: (a, d) => d[Array.isArray(a) ? a[0] : a] ?? "",
  "==": (a, d) => ev(a[0], d) == ev(a[1], d), "!=": (a, d) => ev(a[0], d) != ev(a[1], d),
  "<": (a, d) => ev(a[0], d) < ev(a[1], d), "<=": (a, d) => ev(a[0], d) <= ev(a[1], d),
  ">": (a, d) => ev(a[0], d) > ev(a[1], d), ">=": (a, d) => ev(a[0], d) >= ev(a[1], d),
  "!": (a, d) => !ev(Array.isArray(a) ? a[0] : a, d),
  and: (a, d) => a.every(x => ev(x, d)), or: (a, d) => a.some(x => ev(x, d)),
  in: (a, d) => { const h = ev(a[1], d); return Array.isArray(h) ? h.includes(ev(a[0], d)) : String(h).includes(ev(a[0], d)); },
  "+": (a, d) => a.reduce((s, x) => s + Number(ev(x, d)), 0),
  "-": (a, d) => a.length === 1 ? -Number(ev(a[0], d)) : Number(ev(a[0], d)) - Number(ev(a[1], d)),
  "*": (a, d) => a.reduce((s, x) => s * Number(ev(x, d)), 1),
  abs: (a, d) => Math.abs(Number(ev(Array.isArray(a) ? a[0] : a, d))),
  num: (a, d) => Number(ev(Array.isArray(a) ? a[0] : a, d)),
  substr: (a, d) => String(ev(a[0], d)).substr(ev(a[1], d), a[2] === undefined ? undefined : ev(a[2], d)),
  // AAAAMM de una fecha DD/MM/AAAA, y el mes siguiente a un periodo AAAAMM (como numero)
  aaaamm: (a, d) => { const f = String(ev(Array.isArray(a) ? a[0] : a, d)); return Number(f.slice(6, 10) + f.slice(3, 5)); },
  mes_siguiente: (a, d) => { const p = String(ev(Array.isArray(a) ? a[0] : a, d)); let y = +p.slice(0, 4), m = +p.slice(4, 6) + 1; if (m > 12) { m = 1; y++; } return y * 100 + m; },
};
export function ev(regla, datos) {
  if (regla === null || typeof regla !== "object") return regla;
  if (Array.isArray(regla)) return regla.map(r => ev(r, datos));
  const [op] = Object.keys(regla);
  if (!ops[op]) throw new Error("Operación no soportada en la regla: " + op);
  return ops[op](regla[op], datos);
}

// --- Montos (en centimos enteros: sin errores de redondeo) -------------------------------------
export function centimos(v) {
  const t = String(v ?? "").trim().replace(/^-\s+/, "-");
  if (!/^-?\d+(\.\d{1,2})?$/.test(t)) return null;
  const neg = t.startsWith("-"), [e, dec = ""] = t.replace("-", "").split(".");
  return (neg ? -1 : 1) * (Number(e) * 100 + Number((dec + "00").slice(0, 2)));
}
export const soles = c => (c < 0 ? "-" : "") + Math.abs(Math.trunc(c / 100)).toLocaleString("es-PE") + "." + String(Math.abs(c) % 100).padStart(2, "0");

// --- Validaciones basicas ------------------------------------------------------------------------
const PESOS = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
export function rucValido(r) {
  if (!/^(10|15|16|17|20)\d{9}$/.test(r)) return false;
  let s = 0; for (let i = 0; i < 10; i++) s += Number(r[i]) * PESOS[i];
  const d = 11 - (s % 11);
  return (d === 10 ? 0 : d === 11 ? 1 : d) === Number(r[10]);
}
export function fechaValida(f) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(f);
  if (!m) return false;
  const d = new Date(Date.UTC(+m[3], +m[2] - 1, +m[1]));
  return d.getUTCFullYear() === +m[3] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[1];
}

// --- Limpieza de textos ---------------------------------------------------------------------------
const ENTIDADES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
export function desescapar(t) {
  return t.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === "#") { const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10); return Number.isFinite(n) ? String.fromCodePoint(n) : m; }
    return ENTIDADES[e.toLowerCase()] ?? m;
  });
}
const normal = t => String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");

// --- Lectura de la propuesta -----------------------------------------------------------------------
// Con cabecera (como la entrega el portal) se ubica cada columna por su nombre; sin cabecera, por
// posicion. El palote final de cada fila se tolera.
export function parsear(texto, estructura) {
  const campos = estructura.campos;
  const lineas = texto.split(/\r?\n/).filter(l => l.trim() !== "");
  const avisos = [];
  if (!lineas.length) throw new Error("El archivo está vacío.");
  const primera = lineas[0].split("|");
  const conCabecera = !/^\d{11}$/.test((primera[0] || "").trim());
  let mapa = campos.map((c, i) => i);                         // indice de columna de cada campo
  if (conCabecera) {
    const cab = primera.map(normal);
    const pos = campos.map(c => cab.indexOf(normal(c.cabecera)));
    const faltan = campos.filter((c, i) => pos[i] < 0 && !c.libre && !c.informativo);
    if (faltan.length > 3) throw new Error("Este archivo no parece una propuesta del Registro de Compras: faltan columnas como " +
      faltan.slice(0, 3).map(c => `«${c.cabecera}»`).join(", ") + ".");
    if (faltan.length) avisos.push({ tipo: "estructura", msg: `Columnas no encontradas por nombre (se usó su posición): ${faltan.map(c => c.cabecera).join(", ")}.` });
    mapa = pos.map((p, i) => (p >= 0 ? p : i));
  }
  const filas = [];
  let entidades = 0, espacios = 0;
  lineas.slice(conCabecera ? 1 : 0).forEach((l, k) => {
    const v = l.split("|");
    if (v.length < estructura.campos_minimos) {
      avisos.push({ tipo: "fila", fila: k + 1, msg: `La fila ${k + 1} tiene ${v.length} columnas; se esperaban al menos ${estructura.campos_minimos}.` });
    }
    const c = {};
    campos.forEach((f, i) => {
      let x = v[mapa[i]] ?? "";
      if (f.tipo === "texto") {
        const d = desescapar(x); if (d !== x) { entidades++; x = d; }
      }
      const t = x.trim(); if (t !== x) { espacios++; x = t; }
      c[f.n] = x;
    });
    filas.push({ n: k + 1, c });
  });
  if (entidades) avisos.push({ tipo: "limpieza", msg: `${entidades} texto${entidades === 1 ? "" : "s"} con códigos HTML (como «&amp;») se corrigieron a su carácter («&»).` });
  if (espacios) avisos.push({ tipo: "limpieza", msg: `${espacios} dato${espacios === 1 ? "" : "s"} con espacios sobrantes al inicio o al final se limpiaron.` });
  const variantes = [...new Set(filas.map(f => f.c[2]).filter(Boolean))];
  if (variantes.length > 1) avisos.push({ tipo: "generador", msg: `El nombre del generador aparece de ${variantes.length} formas distintas (es normal en la propuesta): ${variantes.join(" · ")}.` });
  return { filas, avisos, conCabecera, columnas: primera.length };
}

// --- Punto / coma (error n.º 1 por la configuracion regional de Windows) ---------------------------
// "1,234.56" -> miles; "12,50" -> coma decimal; "3,454" -> ambiguo: se decide con el resto del
// archivo (si hay comas decimales claras) o con el cuadre de la fila (IGV y total).
export function detectarComas(filas, estructura) {
  const montos = estructura.campos.filter(f => f.tipo === "monto" || f.tipo === "tc").map(f => f.n);
  const hallazgos = [];
  let decimalesClaros = 0, milesClaros = 0;
  for (const f of filas) for (const n of montos) {
    const x = f.c[n]; if (!x || !x.includes(",")) continue;
    if (/^-?\d{1,3}(,\d{3})+\.\d{1,3}$/.test(x) || /^-?\d{1,3}(,\d{3}){2,}$/.test(x)) { milesClaros++; hallazgos.push({ fila: f.n, campo: n, valor: x, sugerido: x.replace(/,/g, ""), tipo: "miles" }); }
    else if (/^-?\d+,\d{1,2}$/.test(x) || /^-?\d{1,3}(\.\d{3})+,\d{1,3}$/.test(x)) { decimalesClaros++; hallazgos.push({ fila: f.n, campo: n, valor: x, sugerido: x.replace(/\./g, "").replace(",", "."), tipo: "decimal" }); }
    else if (/^-?\d{1,3},\d{3}$/.test(x)) hallazgos.push({ fila: f.n, campo: n, valor: x, tipo: "ambiguo" });
    else hallazgos.push({ fila: f.n, campo: n, valor: x, sugerido: null, tipo: "raro" });
  }
  for (const h of hallazgos.filter(h => h.tipo === "ambiguo")) {
    const comoMiles = h.valor.replace(",", ""), comoDecimal = h.valor.replace(",", ".");
    if (decimalesClaros && !milesClaros) { h.sugerido = comoDecimal; h.razon = "en este archivo la coma se usa como decimal"; continue; }
    if (milesClaros && !decimalesClaros) { h.sugerido = comoMiles; h.razon = "en este archivo la coma separa miles"; continue; }
    const fila = filas.find(f => f.n === h.fila);
    const cuadra = val => { const c = { ...fila.c, [h.campo]: val }; return cuadreTotal(c, estructura) === true; };
    const a = cuadra(comoDecimal), b = cuadra(comoMiles);
    if (a !== b) { h.sugerido = a ? comoDecimal : comoMiles; h.razon = "es el valor con el que cuadra el total de la fila"; }
    else { h.sugerido = comoDecimal; h.razon = "no se pudo confirmar: revísalo"; h.dudoso = true; }
  }
  return hallazgos;
}
export function aplicarComas(filas, hallazgos) {
  for (const h of hallazgos) if (h.sugerido != null) { const f = filas.find(x => x.n === h.fila); if (f) f.c[h.campo] = h.sugerido; }
}
function cuadreTotal(c, estructura) {
  const t = centimos(c[25]); if (t === null) return null;
  let s = 0; for (const n of estructura.montos_cuadre) { const v = centimos(c[n] || "0"); if (v === null) return null; s += v; }
  return Math.abs(t - s) <= 100;
}

// --- Validacion -----------------------------------------------------------------------------------
export function validar(filas, spec, estructuraId = "rce_propuesta") {
  const est = spec.estructuras[estructuraId], T = spec.tablas, out = [];
  const add = (fila, campo, nivel, regla, msg) => out.push({ fila, campo, nivel, regla, msg });
  const vistos = new Map();
  for (const f of filas) {
    const c = f.c;
    const datos = {};
    for (const k in c) { datos["c" + k] = c[k]; const m = centimos(c[k]); datos["m" + k] = m === null ? 0 : m / 100; }
    for (const campo of est.campos) {
      const x = c[campo.n], n = campo.n;
      const oblig = campo.obligatorio || (campo.obligatorio_si && ev(campo.obligatorio_si, datos));
      if (x === "" || x === undefined) {
        if (oblig && !campo.informativo) add(f.n, n, "error", "obligatorio", `Falta «${campo.nombre}» (campo ${n}), que es obligatorio${campo.obligatorio_si ? " para este tipo de comprobante" : ""}.`);
        continue;
      }
      if (campo.long && typeof campo.long === "number" && x.length > campo.long) add(f.n, n, "error", "longitud", `«${campo.nombre}» tiene ${x.length} caracteres; el máximo es ${campo.long}.`);
      switch (campo.tipo) {
        case "ruc": if (!rucValido(x)) add(f.n, n, "error", "ruc", `El RUC ${x} no es válido (11 dígitos y dígito verificador).`); break;
        case "periodo": if (!/^\d{4}(0[1-9]|1[0-2])$/.test(x)) add(f.n, n, "error", "periodo", `El periodo «${x}» debe tener el formato AAAAMM.`); break;
        case "fecha": if (!fechaValida(x)) add(f.n, n, "error", "fecha", `«${campo.nombre}» (${x}) debe ser una fecha DD/MM/AAAA válida.`); break;
        case "entero": if (!/^\d+$/.test(x)) add(f.n, n, "error", "entero", `«${campo.nombre}» debe ser un número entero.`); break;
        case "monto": {
          const [ent, dec] = campo.long || [12, 2];
          const re = new RegExp(`^-?\\s?\\d{1,${ent}}(\\.\\d{1,${dec}})?$`);
          if (!re.test(x)) add(f.n, n, "error", x.includes(",") ? "coma" : "monto",
            x.includes(",") ? `«${campo.nombre}» (${x}) usa coma: el formato pide punto decimal y sin separador de miles.` : `«${campo.nombre}» (${x}) no es un monto válido (hasta ${ent} enteros y ${dec} decimales).`);
          break;
        }
        case "tc":
          if (!/^\d\.?\d{0,3}$/.test(x) || Number(x) <= 0) add(f.n, n, "error", x.includes(",") ? "coma" : "tc", `El tipo de cambio (${x}) debe ser mayor a cero, con punto y hasta 3 decimales.`);
          break;
        case "codigo": {
          const tabla = T[campo.tabla];
          if (tabla && !(x in tabla)) add(f.n, n, "error", "tabla", `«${x}» no es un código válido de «${campo.nombre}».`);
          break;                                    // (91, 97 y 98 en compras: regla "rce_tipo" del spec)
        }
        case "texto":
          if (!campo.libre && /[|\\/]/.test(x) && n !== 4 && n !== 37 && !/^\d{2}\/\d{2}\/\d{4}$/.test(x))
            add(f.n, n, "advertencia", "caracteres", `«${campo.nombre}» contiene «|», «/» o «\\», que no se aceptan al reemplazar la propuesta.`);
          break;
      }
      if (campo.ruc_si && ev(campo.ruc_si, datos) && !rucValido(x)) add(f.n, n, "error", "ruc", `El RUC del proveedor ${x} no es válido (11 dígitos y dígito verificador).`);
    }
    // Serie y numero segun el tipo de comprobante (Tabla 11)
    const tipo = c[7];
    if (est.series[tipo] && c[8] && !new RegExp(est.series[tipo]).test(c[8]))
      add(f.n, 8, "error", "serie", `La serie «${c[8]}» no corresponde a un comprobante tipo ${tipo}.`);
    if (est.numeros[tipo] && c[10] && !new RegExp(est.numeros[tipo]).test(c[10]))
      add(f.n, 10, "error", "numero", `El número «${c[10]}» debe ser numérico, mayor a cero y de hasta 8 dígitos.`);
    // Reglas de la estructura (JSON Logic)
    for (const r of est.reglas) {
      let aplica = false;
      try { aplica = ev(r.cuando, datos); } catch (_) { aplica = false; }
      if (aplica && !(r.debe === false ? false : ev(r.debe, datos))) add(f.n, r.campos[0], r.nivel, r.id, r.msg);
    }
    // Duplicados
    const llave = [tipo, c[8], c[10], c[13]].join("|");
    if (vistos.has(llave)) add(f.n, 10, "advertencia", "duplicado", `El comprobante ${tipo} ${c[8]}-${c[10]} del proveedor ${c[13]} se repite (ver fila ${vistos.get(llave)}).`);
    else vistos.set(llave, f.n);
  }
  return out;
}

// --- Totales por tipo de comprobante y moneda (como el resumen) -------------------------------------
export function totales(filas, spec, estructuraId = "rce_propuesta") {
  const est = spec.estructuras[estructuraId], cols = est.totales, grupos = new Map();
  const total = { tipo: "TOTAL", moneda: "", n: 0, montos: Object.fromEntries(cols.map(c => [c, 0])) };
  for (const f of filas) {
    const k = f.c[7] + "|" + (f.c[26] || "PEN");
    if (!grupos.has(k)) grupos.set(k, { tipo: f.c[7], nombre: spec.tablas.t11[f.c[7]] || "", moneda: f.c[26] || "PEN", n: 0, montos: Object.fromEntries(cols.map(c => [c, 0])) });
    const g = grupos.get(k); g.n++; total.n++;
    for (const c of cols) { const v = centimos(f.c[c] || "0") ?? 0; g.montos[c] += v; total.montos[c] += v; }
  }
  const porTipo = [...grupos.values()].sort((a, b) => (a.tipo + a.moneda).localeCompare(b.tipo + b.moneda));
  const conMonto = cols.filter(c => porTipo.some(g => g.montos[c] !== 0));
  const monedas = [...new Set(porTipo.map(g => g.moneda))];
  return { porTipo, total, columnas: cols, conMonto, monedas };
}

// Resumen descargado junto a la propuesta -> diferencias con nuestros totales (por tipo y total).
export function compararResumen(textoResumen, tot, spec) {
  const est = spec.estructuras.rce_resumen;
  const lineas = textoResumen.split(/\r?\n/).filter(l => l.trim());
  const cab = lineas[0].split("|").map(normal);
  if (cab[0] !== normal(est.cabecera[0])) throw new Error("Ese archivo no es el resumen de la propuesta.");
  const dif = [];
  let filasLeidas = 0;
  for (const l of lineas.slice(1)) {
    const v = l.split("|");
    const etiqueta = v[0].trim(), esTotal = /^total$/i.test(etiqueta);
    const tipo = esTotal ? "TOTAL" : etiqueta.slice(0, 2);
    const nuestros = esTotal ? tot.total : tot.porTipo.filter(g => g.tipo === tipo).reduce((acc, g) => {
      acc.n += g.n; for (const c of tot.columnas) acc.montos[c] = (acc.montos[c] || 0) + g.montos[c]; return acc; }, { n: 0, montos: {} });
    filasLeidas++;
    if (Number(v[1]) !== nuestros.n) dif.push({ tipo, campo: "Comprobantes", resumen: Number(v[1]), nuestro: nuestros.n });
    est.campos_detalle.forEach((c, i) => {
      const r = centimos(v[i + 2]); const o = nuestros.montos[c] || 0;
      if (r !== null && r !== o) dif.push({ tipo, campo: est.cabecera[i + 2], resumen: r, nuestro: o, centimos: true });
    });
  }
  return { cuadra: dif.length === 0, diferencias: dif, filas: filasLeidas };
}

// Todo de una vez: lo que usa la pantalla.
export function procesar(texto, spec, estructuraId = "rce_propuesta") {
  const est = spec.estructuras[estructuraId];
  const p = parsear(texto, est);
  const comas = detectarComas(p.filas, est);
  return { ...p, comas, hallazgos: validar(p.filas, spec, estructuraId), totales: totales(p.filas, spec, estructuraId) };
}
