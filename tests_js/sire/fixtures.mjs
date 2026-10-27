// Archivos SINTETICOS con el formato exacto de la propuesta real del portal (cabecera de 80 columnas,
// LF, palote final, UTF-8, "&amp;", espacios sobrantes, nombre del generador en varias formas) y su
// resumen. Datos FICTICIOS: ninguna persona ni empresa real.
import { deflateRawSync } from "node:zlib";

const PESOS = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
export function ruc(base10) {                      // RUC valido a partir de sus 10 primeros digitos
  let s = 0; for (let i = 0; i < 10; i++) s += Number(base10[i]) * PESOS[i];
  const d = 11 - (s % 11); return base10 + (d === 10 ? 0 : d === 11 ? 1 : d);
}
export const rucMalo = b => { const r = ruc(b); return r.slice(0, 10) + ((Number(r[10]) + 1) % 10); };
export const GENERADOR = ruc("2012345678");
export const PROV = { a: ruc("2055555555"), b: ruc("2066666666"), c: ruc("1012345678") };

export const CABECERA = ["RUC", "Apellidos y Nombres o Razón social", "Periodo", "CAR SUNAT", "Fecha de emisión", "Fecha Vcto/Pago",
  "Tipo CP/Doc.", "Serie del CDP", "Año", "Nro CP o Doc. Nro Inicial (Rango)", "Nro Final (Rango)", "Tipo Doc Identidad",
  "Nro Doc Identidad", "Apellidos Nombres/ Razón  Social", "BI Gravado DG", "IGV / IPM DG", "BI Gravado DGNG", "IGV / IPM DGNG",
  "BI Gravado DNG", "IGV / IPM DNG", "Valor Adq. NG", "ISC", "ICBPER", "Otros Trib/ Cargos", "Total CP", "Moneda", "Tipo de Cambio",
  "Fecha Emisión Doc Modificado", "Tipo CP Modificado", "Serie CP Modificado", "COD. DAM O DSI", "Nro CP Modificado",
  "Clasif de Bss y Sss", "ID Proyecto Operadores", "PorcPart", "IMB", "CAR Orig/ Ind E o I", "Detracción", "Tipo de Nota",
  "Est. Comp.", "Incal", ...Array.from({ length: 39 }, (_, i) => `CLU${i + 1}`)];

// Una fila: valores por numero de campo; el resto vacio (como el portal).
export function fila(v) {
  const c = Array.from({ length: 80 }, (_, i) => v[i + 1] ?? "");
  return c.slice(0, 79).join("|") + "|";             // 79 valores + palote final = 80 columnas al partir
}
const base = (n, extra = {}) => ({
  1: GENERADOR, 2: "COMERCIAL EJEMPLO S.A.C.", 3: "202607", 4: `${PROV.a}01F00100000${String(n).padStart(4, "0")}`,
  5: "13/07/2026", 7: "01", 8: "F001", 10: String(1000 + n), 12: "6", 13: PROV.a, 14: "DISTRIBUIDORA FICTICIA S.A.C.",
  15: "0.00", 16: "0.00", 17: "0.00", 18: "0.00", 19: "0.00", 20: "0.00", 21: "0.00", 22: "0.00", 23: "0.00", 24: "0.00",
  25: "0.00", 26: "PEN", 27: "1.000", 36: "0.00", 40: "1", 41: "0", ...extra,
});

// Propuesta "limpia": 6 comprobantes que deben dar 0 errores y cuadrar con el resumen.
export function propuestaLimpia() {
  const filas = [
    base(1, { 15: "100.00", 16: "18.00", 25: "118.00" }),
    base(2, { 2: "COMERCIAL EJEMPLO SAC", 21: "50.00", 25: "50.00" }),
    base(3, { 2: "COMERCIAL &amp; EJEMPLO S.A.C.", 13: PROV.b, 14: "SERVICIOS &amp; NEGOCIOS FICTICIOS E.I.R.L.", 15: "42.37", 16: "7.63", 25: "50.00" }),
    base(4, { 13: PROV.b, 14: " SERVICIOS &amp; NEGOCIOS FICTICIOS E.I.R.L.", 21: "99.60", 24: "0.40", 25: "100.00" }),
    base(5, { 8: "FF01", 13: PROV.c, 14: "PEREZ GARCIA JUAN", 21: "250.00", 25: "250.00" }),
    base(6, { 8: "F013", 15: "0.85", 16: "0.15", 25: "1.00" }),
  ];
  return [CABECERA.join("|"), ...filas.map(fila)].join("\n") + "\n";
}
export function resumenLimpio() {
  // BI 143.22 · IGV 25.78 · NG 399.60 · otros 0.40 · total 569.00 (6 facturas)
  return ["Tipo de Documento|Total Documentos|BI Gravado DG|IGV / IPM DG|BI Gravado DGNG|IGV / IPM DGNG|BI Gravado DNG|IGV / IPM DNG|Valor Adq. NG|ISC|ICBPER|Otros Trib/ Cargos|Total CP",
    "01-Factura|6|143.22|25.78|0.00|0.00|0.00|0.00|399.60|0.00|0.00|0.40|569.00",
    "TOTAL |6|143.22|25.78|0.00|0.00|0.00|0.00|399.60|0.00|0.00|0.40|569.00"].join("\n");
}

// Propuesta con errores conocidos, uno por fila (para comprobar cada regla).
export function propuestaConErrores() {
  const filas = [
    base(1, { 15: "1,234.56", 16: "222.22", 25: "1456.78" }),                 // miles con coma
    base(2, { 21: "12,50", 25: "12,50" }),                                     // coma decimal
    base(3, { 13: rucMalo("2011111111") }),                                    // RUC del proveedor invalido
    base(4, { 5: "31/02/2026" }),                                              // fecha imposible
    base(5, { 7: "14", 8: "S001" }),                                           // servicio publico sin vencimiento
    base(6, { 7: "91" }),                                                      // no domiciliado en compras
    base(7, { 15: "100.00", 16: "10.00", 25: "110.00" }),                      // IGV 10% (tasa reducida): advertencia
    base(8, { 15: "100.00", 16: "-18.00", 25: "82.00" }),                      // signos distintos
    base(9, { 21: "50.00", 25: "70.00" }),                                     // total no cuadra
    base(10, { 8: "X001" }),                                                   // serie invalida para factura
    base(11, { 26: "USD", 27: "" , 21: "10.00", 25: "10.00" }),                // dolares sin tipo de cambio
    base(12, { 7: "07", 21: "-5.00", 25: "-5.00" }),                           // nota de credito sin doc. modificado
    base(13, { 26: "XYZ" }),                                                   // moneda inexistente
    base(14, { 10: "1011" }),                                                  // duplicado de la fila 11 (F001-1011)
    base(15, { 5: "05/08/2026" }),                                             // emision posterior al periodo
  ];
  return [CABECERA.join("|"), ...filas.map(fila)].join("\n") + "\n";
}

// ZIP minimo (un archivo, deflate) como el que entrega el portal.
export function zip(nombre, texto) {
  const datos = Buffer.from(texto, "utf8"), comp = deflateRawSync(datos), n = Buffer.from(nombre, "utf8");
  const crc = crc32(datos);
  const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(8, 8);
  local.writeUInt32LE(crc, 14); local.writeUInt32LE(comp.length, 18); local.writeUInt32LE(datos.length, 22); local.writeUInt16LE(n.length, 26);
  const central = Buffer.alloc(46); central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6);
  central.writeUInt16LE(8, 10); central.writeUInt32LE(crc, 16); central.writeUInt32LE(comp.length, 20); central.writeUInt32LE(datos.length, 24);
  central.writeUInt16LE(n.length, 28); central.writeUInt32LE(0, 42);
  const off = 30 + n.length + comp.length;
  const fin = Buffer.alloc(22); fin.writeUInt32LE(0x06054b50, 0); fin.writeUInt16LE(1, 8); fin.writeUInt16LE(1, 10);
  fin.writeUInt32LE(46 + n.length, 12); fin.writeUInt32LE(off, 16);
  return Buffer.concat([local, n, comp, central, n, fin]);
}
function crc32(b) {
  let c, crc = 0xffffffff;
  for (let i = 0; i < b.length; i++) { c = (crc ^ b[i]) & 0xff; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; crc = (crc >>> 8) ^ c; }
  return (crc ^ 0xffffffff) >>> 0;
}
