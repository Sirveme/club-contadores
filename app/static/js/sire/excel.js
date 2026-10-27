// Conversor SIRE · Excel con estilo (ExcelJS, MIT, servido desde nuestro propio servidor).
// Se arma en el navegador: el archivo no sale del equipo. Dos versiones: oscura (pantalla, la de la
// casa) y clara para imprimir (sin rellenos oscuros).
import * as M from "./motor.js?v=1";

const RUTA_EXCELJS = "/static/vendor/exceljs/4.4.0/exceljs.min.js";
let cargando = null;
function cargarExcelJS() {
  if (window.ExcelJS) return Promise.resolve(window.ExcelJS);
  cargando = cargando || new Promise((ok, mal) => {
    const s = document.createElement("script");
    s.src = RUTA_EXCELJS; s.onload = () => ok(window.ExcelJS); s.onerror = () => mal(new Error("no se pudo cargar el generador de Excel"));
    document.head.append(s);
  });
  return cargando;
}

// Paletas (tokens Sepia del Club). Ningun color es blanco puro.
const OSCURO = { fondo: "FF1E1711", cab: "FF261D15", grilla: "FF3D3024", texto: "FFF3EADF", tenue: "FFAD9A84", acento: "FFE8A04A",
                 err: "FF4A2420", errTxt: "FFF3A79F", adv: "FF40331A", advTxt: "FFE9C873", total: "FF2E241A" };
const CLARO = { fondo: null, cab: "FFE9E4DC", grilla: "FFB9AE9F", texto: "FF1A110A", tenue: "FF6B5D4D", acento: "FF8A5212",
                err: "FFF6D5D1", errTxt: "FF8E2A20", adv: "FFF7EBC8", advTxt: "FF6E5310", total: "FFEFE9E0" };

const relleno = c => (c ? { type: "pattern", pattern: "solid", fgColor: { argb: c } } : undefined);
const borde = c => ({ top: { style: "thin", color: { argb: c } }, left: { style: "thin", color: { argb: c } },
                      bottom: { style: "thin", color: { argb: c } }, right: { style: "thin", color: { argb: c } } });

function estilar(celda, P, { cab = false, fill = null, color = null, bold = false, num = null } = {}) {
  celda.font = { name: "Calibri", size: 10, color: { argb: color || (cab ? P.tenue : P.texto) }, bold: bold || cab };
  const f = relleno(fill || (cab ? P.cab : P.fondo)); if (f) celda.fill = f;
  celda.border = borde(P.grilla);
  celda.alignment = { vertical: "top", wrapText: cab };
  if (num) { celda.numFmt = num; celda.alignment = { ...celda.alignment, horizontal: "right" }; }
}

export async function generarExcel(estado, spec, { imprimir = false } = {}) {
  const ExcelJS = await cargarExcelJS();
  const P = imprimir ? CLARO : OSCURO;
  const est = spec.estructuras.rce_propuesta;
  const wb = new ExcelJS.Workbook();
  wb.creator = "Conversor SIRE · Perú Sistemas Pro"; wb.created = new Date();
  const vista = [{ state: "frozen", ySplit: 1, showGridLines: false }];

  // Hallazgos por fila y campo
  const porFila = new Map();
  for (const h of estado.hallazgos) { if (!porFila.has(h.fila)) porFila.set(h.fila, []); porFila.get(h.fila).push(h); }

  // --- Hoja Compras: los campos con nombre (sin columnas libres vacias) -------------------------
  const campos = est.campos.filter(c => !c.libre || estado.filas.some(f => f.c[c.n]));
  const ws = wb.addWorksheet("Compras", { views: vista, properties: { tabColor: { argb: P.acento } } });
  const cab = ["Fila", ...campos.map(c => `${c.n}. ${c.nombre}`), "Observaciones"];
  ws.addRow(cab).eachCell(c => estilar(c, P, { cab: true }));
  ws.getRow(1).height = 42;
  for (const f of estado.filas) {
    const hs = porFila.get(f.n) || [];
    const valores = [f.n, ...campos.map(c => {
      const v = f.c[c.n] ?? "";
      if ((c.tipo === "monto" || c.tipo === "tc") && v !== "") { const x = c.tipo === "tc" ? Number(v) : (M.centimos(v) ?? NaN) / 100; return Number.isFinite(x) ? x : v; }
      return v;                                                    // texto: RUC, series, numeros y fechas no pierden ceros
    }), hs.map(h => `${h.nivel === "error" ? "ERROR" : "Advertencia"} (campo ${h.campo}): ${h.msg}`).join("\n")];
    const row = ws.addRow(valores);
    row.eachCell({ includeEmpty: true }, (celda, i) => {
      const campo = campos[i - 2];
      const h = campo && hs.find(x => x.campo === campo.n);
      const num = campo && (campo.tipo === "monto" ? "#,##0.00" : campo.tipo === "tc" ? "0.000" : null);
      if (campo && !num) celda.numFmt = "@";
      estilar(celda, P, { num, fill: h ? (h.nivel === "error" ? P.err : P.adv) : null, color: h ? (h.nivel === "error" ? P.errTxt : P.advTxt) : null });
      if (i === valores.length && hs.length) celda.alignment = { wrapText: true, vertical: "top" };
    });
  }
  ws.columns.forEach((col, i) => {
    const c = campos[i - 1];
    col.width = i === 0 ? 6 : i === cab.length - 1 ? 60 : c && c.tipo === "monto" ? 14 : c && /razon/.test(c.id) ? 36 : c && c.n === 4 ? 30 : 13;
  });
  ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: cab.length } };

  // --- Hoja Totales ------------------------------------------------------------------------------
  const t = estado.totales, cols = t.conMonto.length ? t.conMonto : [25], variasMonedas = t.monedas.length > 1;
  const nombre = n => (est.campos.find(c => c.n === n) || {}).nombre || `Campo ${n}`;
  const wt = wb.addWorksheet("Totales", { views: vista });
  wt.addRow(["Tipo de comprobante", ...(variasMonedas ? ["Moneda"] : []), "Comprobantes", ...cols.map(nombre)]).eachCell(c => estilar(c, P, { cab: true }));
  wt.getRow(1).height = 30;
  for (const g of t.porTipo)
    wt.addRow([`${g.tipo} · ${g.nombre}`, ...(variasMonedas ? [g.moneda] : []), g.n, ...cols.map(c => g.montos[c] / 100)])
      .eachCell((c, i) => estilar(c, P, { num: i > (variasMonedas ? 3 : 2) ? "#,##0.00" : i === (variasMonedas ? 3 : 2) ? "0" : null }));
  wt.addRow(["Total", ...(variasMonedas ? [""] : []), t.total.n, ...cols.map(c => t.total.montos[c] / 100)])
    .eachCell((c, i) => estilar(c, P, { bold: true, fill: P.total, num: i > (variasMonedas ? 3 : 2) ? "#,##0.00" : i === (variasMonedas ? 3 : 2) ? "0" : null }));
  if (estado.resumen) {
    let texto;
    try { const r = M.compararResumen(estado.resumen.texto, t, spec); texto = r.cuadra ? "✓ Cuadra con el resumen descargado (comprobantes y montos iguales)." : `✗ No cuadra con el resumen: ${r.diferencias.length} diferencia(s).`; }
    catch (e) { texto = e.message; }
    wt.addRow([]); const r = wt.addRow([texto]); estilar(r.getCell(1), P, { bold: true });
  }
  wt.columns.forEach((col, i) => { col.width = i === 0 ? 46 : 16; });

  // --- Hoja Observaciones ---------------------------------------------------------------------------
  const wo = wb.addWorksheet("Observaciones", { views: vista });
  wo.addRow(["Fila", "Campo", "Nivel", "Detalle"]).eachCell(c => estilar(c, P, { cab: true }));
  const avisos = estado.avisos.map(a => ["—", "—", "Lectura", a.msg]);
  for (const v of [...avisos, ...estado.hallazgos.map(h => [h.fila, `${h.campo}. ${nombre(h.campo)}`, h.nivel === "error" ? "Error" : "Advertencia", h.msg])]) {
    const row = wo.addRow(v);
    row.eachCell({ includeEmpty: true }, c => estilar(c, P, { fill: v[2] === "Error" ? P.err : v[2] === "Advertencia" ? P.adv : null,
      color: v[2] === "Error" ? P.errTxt : v[2] === "Advertencia" ? P.advTxt : null }));
  }
  if (!estado.hallazgos.length && !avisos.length) estilar(wo.addRow(["", "", "", "Sin observaciones."]).getCell(4), P);
  wo.columns.forEach((col, i) => { col.width = [6, 34, 13, 100][i]; });

  // --- Hoja Acerca de -----------------------------------------------------------------------------
  const wa = wb.addWorksheet("Acerca de", { views: [{ showGridLines: false }] });
  [["Conversor SIRE · Perú Sistemas Pro"], [`Archivo: ${estado.propuesta.nombre}`], [`Generado: ${new Date().toLocaleString("es-PE")}`],
   [`Estructura: ${est.nombre} (${est.anexo})`], ["Procesado en tu equipo: el archivo y sus montos no se enviaron a ningún servidor."],
   [imprimir ? "Versión clara para imprimir." : "Versión oscura (pantalla). Para imprimir, usa «Versión para imprimir»."]]
    .forEach((v, i) => estilar(wa.addRow(v).getCell(1), P, { bold: i === 0 }));
  wa.getColumn(1).width = 100;

  const buf = await wb.xlsx.writeBuffer();
  return new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}
