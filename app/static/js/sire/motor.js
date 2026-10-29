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
  if (variantes.length > 1) avisos.push({ tipo: "generador", variantes, msg: `El nombre del generador aparece de ${variantes.length} formas distintas (es normal en la propuesta): ${variantes.join(" · ")}.` });
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
  const add = (fila, campo, nivel, regla, msg, extra) => out.push({ fila, campo, nivel, regla, msg, ...extra });
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
      add(f.n, 10, "error", "numero", `El número «${c[10]}» debe ser numérico, mayor a cero y de hasta ${Number((est.numeros[tipo].match(/\\d\{0,(\d+)\}/) || [, 7])[1]) + 1} dígitos.`);
    // Reglas de la estructura (JSON Logic). {tipo} en el mensaje = "03 - Boleta de venta"; {tipo_mod}, el del
    // documento modificado (campo 29). marca "montos": se señalan los campos de la regla que traen monto.
    // codigo: el de la validacion del SIRE que la regla replica (ver diccionario-errores.json).
    const nombreTipo = t => `${t} - ${T.t11[t] || "tipo " + t}`;
    for (const r of est.reglas) {
      let aplica = false;
      try { aplica = ev(r.cuando, datos); } catch (_) { aplica = false; }
      if (!aplica || (r.debe === false ? false : ev(r.debe, datos))) continue;
      const marcas = r.marca === "montos" ? r.campos.filter(n => datos["m" + n] !== 0) : r.campos;
      add(f.n, marcas[0] ?? r.campos[0], r.nivel, r.id, r.msg.replace("{tipo}", nombreTipo(tipo)).replace("{tipo_mod}", nombreTipo(c[29])),
        { marcas, ...(r.extra ? { extra: true } : {}), ...(r.codigo ? { codigo: r.codigo } : {}) });
    }
    // Duplicados
    // Duplicado en el archivo: error (435). Cliente SIRE v3.18.0: "Todos los comprobantes de pago duplicados
    // incluidos en el archivo de reemplazo, serán considerados como un error paramétrico". El año de la DAM
    // (campo 9) es parte de la llave: dos DAM de años distintos pueden tener el mismo número.
    const llave = [tipo, c[8], c[9], c[10], c[13]].join("|");
    if (vistos.has(llave)) add(f.n, 10, "error", "duplicado", `El comprobante ${tipo} ${c[8]}-${c[10]} del proveedor ${c[13]} se repite (ver fila ${vistos.get(llave)}): el SIRE no acepta comprobantes duplicados en el reemplazo. Deja uno solo.`,
      { codigo: "435" });
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

// --- Casillas del Formulario 621 que se precargan desde el registro (referencial) ---------------------
// Montos en soles: lo que no esta en PEN se convierte con el tipo de cambio del propio comprobante.
export function casillas621(filas, spec) {
  const F = spec.formulario621, imp = new Set(F.importaciones);
  const suma = Object.fromEntries(F.casillas.map(k => [k.c, 0]));
  let convertidos = 0;
  for (const f of filas) {
    const origen = imp.has(f.c[7]) ? "importaciones" : "internas";
    const pen = !f.c[26] || f.c[26] === "PEN", tc = pen ? 1 : Number(f.c[27]) || 0;
    if (!pen) convertidos++;
    for (const k of F.casillas) if (k.origen === origen) suma[k.c] += Math.round((centimos(f.c[k.campo] || "0") ?? 0) * tc);
  }
  return { casillas: F.casillas.map(k => ({ ...k, centimos: suma[k.c] })), convertidos };
}

// --- Destino de las adquisiciones: avisos con fundamento ----------------------------------------------
// perfil.noGravadas: "si" | "no" | null (¿ventas no gravadas en los ultimos 12 meses, sin exportaciones?)
// perfil.exporta: true | false | null. Nada se corrige solo: el contador decide (y en la fase 4, el TXT).
const NOTA5 = "Anexo 8 de la RS 040-2022/SUNAT, nota 5: la base e IGV que el SIRE pone por defecto en los campos 15 y 16 se pueden reubicar en los campos 17-18 o 19-20, siempre que 15+17+19 y 16+18+20 sigan sumando lo propuesto (±1).";
export function avisosDestino(filas, spec, perfil = {}) {
  const t = totales(filas, spec).total.montos, out = [];
  const dg = t[15] + t[16], dgng = t[17] + t[18], dng = t[19] + t[20];
  const imb = filas.reduce((s, f) => s + (centimos(f.c[36] || "0") ?? 0), 0);      // campo 36: no va en los totales
  if (perfil.noGravadas === "si" && dg !== 0 && dgng === 0 && dng === 0)
    out.push({ nivel: "advertencia", id: "todo_dg", msg: "Todas tus compras gravadas están como destino gravado exclusivo (casilla 107). Si en los últimos 12 meses tuviste ventas no gravadas, revisa el destino de cada compra: las que sirven a la vez a ventas gravadas (o exportaciones) y a no gravadas van en los campos 17-18 (casilla 110, el IGV se prorratea con el coeficiente de la casilla 173), y las que sirven solo a no gravadas en 19-20 (casilla 113, sin crédito fiscal).", fundamento: NOTA5 + " Formulario 621: casillas 107, 110, 113 y 173; Reglamento de la Ley del IGV, artículo 6." });
  if (perfil.noGravadas === "no" && (dgng !== 0 || dng !== 0))
    out.push({ nivel: "advertencia", id: "dgng_sin_ng", msg: "Tienes compras como destino gravado y no gravado (campos 17-20, casillas 110 o 113), pero indicaste que no tuviste ventas no gravadas. Si solo vendes gravado o exportas, esas compras van como destino gravado (campos 15-16, casilla 107) con todo su crédito fiscal.", fundamento: NOTA5 + " Formulario 621: la casilla 110 se usa si tuviste ventas no gravadas en los últimos 12 meses." });
  if (perfil.exporta)
    out.push({ nivel: "info", id: "exportador", msg: "Para el destino de tus compras, las exportaciones cuentan como operaciones gravadas: lo que usas para exportar va como destino gravado (casilla 107) y da crédito fiscal o saldo a favor del exportador. Solo pasa a «gravado y no gravado» (casilla 110) si la misma compra sirve también a ventas no gravadas; entonces se prorratea con el coeficiente (casilla 173 = gravadas + exportaciones, entre gravadas + exportaciones + no gravadas).", fundamento: "Anexo 8 de la RS 040-2022/SUNAT, campos 15 a 20 («gravadas y/o de exportación»); Ayuda del Formulario 621, casillas 107, 110 y 173." });
  if (t[21] !== 0)
    out.push({ nivel: "info", id: "no_gravadas", msg: `Tienes ${soles(t[21])} en adquisiciones no gravadas (exoneradas más inafectas, campo 21 → casilla 120 o 122 si es importación). No llevan IGV ni dan crédito fiscal. Si además vendes exonerado (por ejemplo, libros), las compras gravadas que usas solo para esas ventas van en los campos 19-20 (casilla 113).`, fundamento: "Anexo 8 de la RS 040-2022/SUNAT, campo 21 («Exoneradas más Inafectas») y campos 19-20." });
  if (imb !== 0)
    out.push({ nivel: "info", id: "ley31053", msg: `Hay ${soles(imb)} en «Impuesto materia de beneficio Ley 31053» (campo 36): es el beneficio de la actividad editorial; el contribuyente lo completa.`, fundamento: "Anexo 8 de la RS 040-2022/SUNAT, campo 36 y nota 10 (artículo 30 de la Ley 31053)." });
  return out;
}

// Avisos de lectura por tipo de comprobante (no son errores).
function avisosTipo(filas) {
  const pos = filas.filter(f => f.c[7] === "30").length;
  return pos ? [{ msg: `Hay ${pos} comprobante${pos === 1 ? "" : "s"} tipo 30 (adquirentes de tarjetas, los del POS). La base e IGV se pueden reubicar entre destinos dentro de la propuesta; si otro dato del comprobante viene mal, la norma pide reemplazar la propuesta con el TXT del Anexo 11 (corrígelo en el detalle del comprobante o en el Excel, y genera el TXT de reemplazo al final de esta página).`, tipo: "30" }] : [];
}

// Todo de una vez: lo que usa la pantalla.
export function procesar(texto, spec, estructuraId = "rce_propuesta") {
  const p = parsear(texto, spec.estructuras[estructuraId]);
  return { ...p, ...desdeFilas(p.filas, spec, p.avisos, estructuraId) };
}
// Lo mismo a partir de filas ya leidas (de la propuesta, de un Excel o de una tabla pegada).
export function desdeFilas(filas, spec, avisos = [], estructuraId = "rce_propuesta") {
  return { filas, avisos: [...avisos, ...avisosTipo(filas)], comas: detectarComas(filas, spec.estructuras[estructuraId]),
    hallazgos: validar(filas, spec, estructuraId), totales: totales(filas, spec, estructuraId) };
}

// === Fase 4: de vuelta al SIRE ======================================================================
// --- Destino de la adquisicion (nota 5 del Anexo 8): el contador mueve base e IGV entre 15-16 (DG),
// 17-18 (DGNG) y 19-20 (DNG). Las sumas 15+17+19 y 16+18+20 no cambian. Nunca se hace solo.
export const DESTINOS = { dg: [15, 16], dgng: [17, 18], dng: [19, 20] };
const aMonto = c => `${c < 0 ? "-" : ""}${Math.trunc(Math.abs(c) / 100)}.${String(Math.abs(c) % 100).padStart(2, "0")}`;
export function destinoDe(c) {
  const con = Object.keys(DESTINOS).filter(k => DESTINOS[k].some(n => (centimos(c[n] || "0") ?? 0) !== 0));
  return con.length === 1 ? con[0] : con.length ? "mixto" : null;
}
export function reubicar(fila, destino) {
  if (!DESTINOS[destino]) return false;
  const c = fila.c; let bi = 0, igv = 0;
  for (const [b, i] of Object.values(DESTINOS)) {
    const x = centimos(c[b] || "0"), y = centimos(c[i] || "0");
    if (x === null || y === null) return false;                    // monto ilegible: primero se corrige
    bi += x; igv += y;
  }
  for (const [k, [b, i]] of Object.entries(DESTINOS)) { c[b] = aMonto(k === destino ? bi : 0); c[i] = aMonto(k === destino ? igv : 0); }
  return true;
}

// --- Filas desde una tabla (Excel del conversor, plantilla o filas pegadas desde otro Excel) ---------
// La primera fila son los titulos: "15. Base imponible…" (Excel del conversor), el de la propuesta
// ("BI Gravado DG") o el nombre del campo. Lo demas se ignora (p. ej. "Fila", "Observaciones").
export function tablaDePegado(texto) {
  return texto.replace(/^﻿/, "").split(/\r?\n/).filter(l => l.trim() !== "").map(l => l.split("\t"));
}
const dosDig = n => String(n).padStart(2, "0");
function valorDeCelda(campo, v) {
  if (v === null || v === undefined) return "";
  if (v instanceof Date) return `${dosDig(v.getUTCDate())}/${dosDig(v.getUTCMonth() + 1)}/${v.getUTCFullYear()}`;
  if (typeof v === "number") {
    if (campo.tipo === "monto") return v.toFixed(2);
    if (campo.tipo === "tc") return v.toFixed(3);
    v = String(v);
  }
  v = String(v).trim();
  if (campo.tipo === "codigo" && campo.long === 2 && /^\d$/.test(v)) v = "0" + v;      // Excel se come el 0 de "01"
  return v;
}
export function filasDeTabla(matriz, spec, estructuraId = "rce_propuesta") {
  const est = spec.estructuras[estructuraId];
  if (!matriz.length) throw new Error("La tabla está vacía.");
  const col = new Map();                                            // columna -> campo
  matriz[0].forEach((t, i) => {
    const s = String(t ?? "").trim(), num = s.match(/^(\d{1,2})\.\s/);
    const campo = num ? est.campos.find(c => c.n === Number(num[1]))
      : est.campos.find(c => normal(c.cabecera) === normal(s) || normal(c.nombre) === normal(s));
    if (campo && ![...col.values()].includes(campo)) col.set(i, campo);
  });
  const tiene = n => [...col.values()].some(c => c.n === n);
  if (!tiene(1) || !tiene(7) || !tiene(25))
    throw new Error("No reconocemos las columnas: la primera fila debe traer los títulos (como en el Excel del conversor: «1. RUC del generador», «7. Tipo de comprobante», «25. Importe total»…).");
  const filas = [];
  for (const r of matriz.slice(1)) {
    const c = Object.fromEntries(est.campos.map(f => [f.n, ""]));
    for (const [i, campo] of col) c[campo.n] = valorDeCelda(campo, r[i]);
    if (est.campos.every(f => c[f.n] === "")) continue;            // fila vacia
    filas.push({ n: filas.length + 1, c });
  }
  if (!filas.length) throw new Error("La tabla solo trae títulos: no hay comprobantes.");
  const faltan = est.campos.filter(f => !f.libre && !f.informativo && !tiene(f.n));
  const avisos = faltan.length ? [{ tipo: "estructura", msg: `Columnas que no vinieron (se toman vacías): ${faltan.map(f => `${f.n}. ${f.nombre}`).join(", ")}.` }] : [];
  return { filas, avisos };
}

// --- TXT de reemplazo (Anexo 11) ---------------------------------------------------------------------
// Antes de armarlo se re-valida con las mismas reglas: un error lo impide (no se entrega un archivo roto);
// las advertencias solo se avisan. Montos ya vienen con punto y sin miles (si no, es error).
const masFrecuente = xs => { const k = new Map(); for (const x of xs) if (x) k.set(x, (k.get(x) || 0) + 1); return [...k].sort((a, b) => b[1] - a[1])[0]?.[0] || ""; };
export function razonGenerador(filas) { return masFrecuente(filas.map(f => f.c[2])); }
export function reemplazo(filas, spec, { razon = null, oportunidad = "1", moneda = "1" } = {}) {
  const est = spec.estructuras.rce_reemplazo, A = est.archivo, prohibido = new RegExp(est.texto_prohibido, "g");
  const hallazgos = validar(filas, spec);
  const bloqueos = hallazgos.filter(h => h.nivel === "error"), advertencias = hallazgos.filter(h => h.nivel !== "error");
  const bloquea = (fila, campo, msg) => bloqueos.push({ fila, campo, nivel: "error", regla: "reemplazo", msg });
  const ruc = filas[0]?.c[1] || "", periodo = filas[0]?.c[3] || "", nombre = String(razon ?? razonGenerador(filas)).trim();
  if (!filas.length) bloquea(0, 0, "No hay comprobantes para armar el TXT.");
  if (!nombre) bloquea(0, 2, "Falta la razón social del generador.");
  else if (/[|]/.test(nombre)) bloquea(0, 2, "La razón social del generador no puede llevar «|».");
  if (!A.oportunidad[oportunidad] || !A.moneda[moneda]) bloquea(0, 0, "Indicador de oportunidad o de moneda no válido.");
  let limpiados = 0;
  const lineas = filas.map(f => {
    const c = f.c;
    if (c[1] !== ruc) bloquea(f.n, 1, `Todo el TXT debe ser de un solo generador: esta fila es del RUC ${c[1]} y la primera del ${ruc}.`);
    if (c[3] !== periodo) bloquea(f.n, 3, `Todo el TXT debe ser de un solo periodo: esta fila es del ${c[3]} y la primera del ${periodo}.`);
    const v = est.campos.map(n => est.vacios.includes(n) ? "" : n === 2 ? nombre
      : est.cero_si_vacio.includes(n) && !c[n] ? "0.00" : String(c[n] ?? ""));
    v.forEach((x, i) => { if (x.includes("|")) bloquea(f.n, est.campos[i], `El campo ${est.campos[i]} lleva «|», que es el separador del archivo.`); });
    let ultimo = 0;                                                  // campos libres: solo hasta el ultimo usado
    for (let n = est.libres[0]; n <= est.libres[1]; n++) if (c[n]) ultimo = n;
    for (let n = est.libres[0]; n <= ultimo; n++) {
      const x = String(c[n] ?? ""), y = x.replace(prohibido, " ");
      if (y !== x) limpiados++;
      v.push(y);
    }
    return v.join("|") + "|";
  });
  const archivo = `${A.prefijo}${ruc}${periodo}00${A.libro}${A.cc}${oportunidad}${filas.length ? 1 : 0}${moneda}${A.g}${A.extension}`;
  const ajustes = limpiados ? [`${limpiados} campo(s) de libre utilización llevaban «|», «/» o «\\» (no se aceptan): se cambiaron por un espacio.`] : [];
  return { archivo, zip: archivo.replace(/\.TXT$/, A.comprimido), texto: bloqueos.length ? null : lineas.join("\n") + "\n",
    bloqueos, advertencias, ajustes, razon: nombre, n: filas.length, totales: totales(filas, spec) };
}

// ZIP con el TXT adentro, sin comprimir (metodo "stored": cualquier lector lo abre). Mismo nombre que el TXT.
const CRC = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
function crc32(b) { let c = 0xffffffff; for (const x of b) c = CRC[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
export function zipear(nombre, datos) {
  const n = new TextEncoder().encode(nombre), crc = crc32(datos), out = new Uint8Array(30 + n.length + datos.length + 46 + n.length + 22);
  const dv = new DataView(out.buffer); let p = 0;
  const u32 = v => { dv.setUint32(p, v, true); p += 4; }, u16 = v => { dv.setUint16(p, v, true); p += 2; }, bytes = b => { out.set(b, p); p += b.length; };
  u32(0x04034b50); u16(20); u16(0x0800); u16(0); u16(0); u16(0x21); u32(crc); u32(datos.length); u32(datos.length); u16(n.length); u16(0); bytes(n); bytes(datos);
  const central = p;
  u32(0x02014b50); u16(20); u16(20); u16(0x0800); u16(0); u16(0); u16(0x21); u32(crc); u32(datos.length); u32(datos.length);
  u16(n.length); u16(0); u16(0); u16(0); u16(0); u32(0); u32(0); bytes(n);
  const largo = p - central;
  u32(0x06054b50); u16(0); u16(0); u16(1); u16(1); u32(largo); u32(central); u16(0);
  return out;
}
