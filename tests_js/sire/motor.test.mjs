// node --test tests_js/sire/motor.test.mjs — motor del Conversor SIRE con archivos sinteticos.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as M from "../../app/static/js/sire/motor.js";
import * as F from "./fixtures.mjs";

const spec = JSON.parse(readFileSync(new URL("../../app/static/sire/sire-spec.json", import.meta.url), "utf8"));
const est = spec.estructuras.rce_propuesta;
const reglas = (r, fila) => r.hallazgos.filter(h => h.fila === fila).map(h => `${h.nivel}:${h.regla}:${h.campo}`);

test("spec: 80 campos, tablas de la norma", () => {
  assert.equal(est.campos.length, 80);
  assert.deepEqual(est.campos.map(c => c.cabecera), F.CABECERA);
  assert.ok(spec.tablas.t2.PEN && spec.tablas.t2.USD && Object.keys(spec.tablas.t2).length > 150);
  assert.equal(spec.tablas.t11["01"], "Factura");
  assert.ok(!spec.tablas.t11_rce.includes("91"));
});

test("ZIP del portal -> TXT (deflate en el navegador)", async () => {
  const z = await M.descomprimir(F.zip("20XXXXXXXXX-20261019-1528-propuesta.txt", F.propuestaLimpia()));
  assert.equal(z.length, 1);
  assert.equal(M.decodificar(z[0].data).texto, F.propuestaLimpia());
  assert.equal(M.decodificar(z[0].data).codificacion, "UTF-8");
  assert.equal(M.decodificar(Buffer.from("Raz\xf3n", "latin1")).codificacion, "Windows-1252");
});

test("propuesta limpia: cabecera, palote final, &amp;, espacios, variantes del generador; 0 hallazgos", () => {
  const r = M.procesar(F.propuestaLimpia(), spec);
  assert.equal(r.conCabecera, true);
  assert.equal(r.columnas, 80);
  assert.equal(r.filas.length, 6);
  assert.equal(r.filas[2].c[14], "SERVICIOS & NEGOCIOS FICTICIOS E.I.R.L.");
  assert.equal(r.filas[3].c[14], "SERVICIOS & NEGOCIOS FICTICIOS E.I.R.L.");    // tambien sin el espacio inicial
  assert.ok(r.avisos.some(a => /HTML/.test(a.msg)) && r.avisos.some(a => /espacios/.test(a.msg)) && r.avisos.some(a => /3 formas/.test(a.msg)));
  assert.deepEqual(r.hallazgos, []);
  assert.deepEqual(r.comas, []);
});

test("totales en centimos y cuadre con el resumen", () => {
  const r = M.procesar(F.propuestaLimpia(), spec);
  assert.deepEqual(r.totales.conMonto, [15, 16, 21, 24, 25]);
  assert.equal(r.totales.total.montos[25], 56900);
  assert.equal(r.totales.porTipo[0].n, 6);
  const c = M.compararResumen(F.resumenLimpio(), r.totales, spec);
  assert.equal(c.cuadra, true, JSON.stringify(c.diferencias));
  const mal = M.compararResumen(F.resumenLimpio().replace("569.00", "570.00"), r.totales, spec);
  assert.equal(mal.cuadra, false);
  assert.throws(() => M.compararResumen(F.propuestaLimpia(), r.totales, spec), /no es el resumen/);
});

test("cada regla de la norma, fila por fila", () => {
  const r = M.procesar(F.propuestaConErrores(), spec);
  const f = n => reglas(r, n);
  assert.ok(f(1).includes("error:coma:15"));
  assert.ok(f(2).includes("error:coma:21"));
  assert.ok(f(3).includes("error:ruc:13"));
  assert.ok(f(4).includes("error:fecha:5"));
  assert.ok(f(5).includes("error:obligatorio:6"));
  assert.ok(f(6).includes("error:rce_tipo:7"));
  assert.deepEqual(f(7), ["advertencia:igv_15:15"]);              // tasa reducida: SOLO advertencia
  assert.ok(f(8).includes("error:signo_15:15"));
  assert.ok(f(9).includes("advertencia:total:25"));
  assert.ok(f(10).includes("error:serie:8"));
  assert.ok(f(11).includes("error:obligatorio:27"));
  assert.ok(["28", "29", "30", "32"].every(n => f(12).includes(`error:obligatorio:${n}`)));
  assert.ok(f(13).includes("error:tabla:26"));
  assert.ok(f(14).includes("advertencia:duplicado:10"));
  assert.ok(f(15).includes("error:emision_periodo:5"));
});

test("punto/coma: miles, decimal y ambiguo resuelto por el cuadre", () => {
  const r = M.procesar(F.propuestaConErrores(), spec);
  const h = r.comas;
  assert.deepEqual(h.find(x => x.fila === 1 && x.campo === 15), { fila: 1, campo: 15, valor: "1,234.56", sugerido: "1234.56", tipo: "miles" });
  assert.equal(h.find(x => x.fila === 2 && x.campo === 21).sugerido, "12.50");
  const ambiguo = M.procesar([F.CABECERA.join("|"), F.fila({ 1: F.GENERADOR, 2: "X", 3: "202607", 5: "01/07/2026", 7: "01", 8: "F001", 10: "1",
    12: "6", 13: F.PROV.a, 14: "Y", 21: "3,454", 25: "3454.00", 26: "PEN", 27: "1.000" })].join("\n"), spec);
  const a = ambiguo.comas[0];
  assert.equal(a.tipo, "ambiguo"); assert.equal(a.sugerido, "3454"); assert.match(a.razon, /cuadra el total/);
  M.aplicarComas(ambiguo.filas, ambiguo.comas);
  assert.equal(ambiguo.filas[0].c[21], "3454");
  assert.deepEqual(M.validar(ambiguo.filas, spec).filter(x => x.nivel === "error"), []);
});

test("sin cabecera: por posicion", () => {
  const sin = F.propuestaLimpia().split("\n").slice(1).join("\n");
  const r = M.procesar(sin, spec);
  assert.equal(r.conCabecera, false); assert.equal(r.filas.length, 6); assert.deepEqual(r.hallazgos, []);
});

test("archivo equivocado: mensaje claro", () => {
  assert.throws(() => M.procesar("Columna A|Columna B\n1|2\n", spec), /no parece una propuesta del Registro de Compras/);
  assert.throws(() => M.procesar("   \n", spec), /vacío/);
});

// --- Casos del mercado -----------------------------------------------------------------------------
const casilla = (r, c) => r.casillas.find(k => k.c === c).centimos;

test("caso 1 · tipo 30 (POS): se lee, se valida con sus reglas y se avisa cómo se corrige", () => {
  const r = M.procesar(F.casoPOS(), spec);
  assert.equal(r.filas.length, 4);
  assert.equal(r.filas[0].c[7], "30");
  assert.deepEqual(r.hallazgos.filter(h => h.fila <= 3), []);                  // numero de 14 digitos: valido para el 30
  assert.ok(reglas(r, 4).includes("error:serie:8") && reglas(r, 4).includes("error:numero:10"));
  assert.match(r.hallazgos.find(h => h.regla === "numero").msg, /hasta 20 dígitos/);
  assert.ok(r.avisos.some(a => a.tipo === "30" && /reemplazar la propuesta/.test(a.msg)));
  const g = r.totales.porTipo.find(x => x.tipo === "30");
  assert.equal(g.n, 3); assert.equal(g.montos[15], 6500 + 2500); assert.equal(g.montos[16], 1170 + 450);
  assert.equal(casilla(M.casillas621(r.filas, spec), 107), 2500 + 4000 + 10000 + 2500);
});

test("caso 2 · exoneradas (libros): campo 21 -> casilla 120; gravadas solo para exoneradas -> 19-20 (casilla 113)", () => {
  const r = M.procesar(F.casoLibros(), spec);
  assert.deepEqual(r.hallazgos, []);
  assert.deepEqual(r.totales.conMonto, [15, 16, 19, 20, 21, 25]);
  const k = M.casillas621(r.filas, spec);
  assert.equal(casilla(k, 120), 50000); assert.equal(casilla(k, 113), 10000); assert.equal(casilla(k, 107), 5000);
  const av = M.avisosDestino(r.filas, spec, { noGravadas: "si" });
  assert.ok(av.some(a => a.id === "no_gravadas" && /casilla 120/.test(a.msg)));
  assert.ok(!av.some(a => a.id === "todo_dg"));                                  // ya usa destino no gravado
});

test("caso 3 · exportador: casillas 107/114 y aviso de destino según su perfil, con fundamento", () => {
  const r = M.procesar(F.casoExportador(), spec);
  assert.deepEqual(r.hallazgos, []);
  const k = M.casillas621(r.filas, spec);
  assert.equal(casilla(k, 107), 100000 + 20000 + 37500);                        // USD 100 x 3.750
  assert.equal(casilla(k, 114), 300000); assert.equal(casilla(k, 115), 54000);   // la DAM va a importaciones
  assert.equal(k.convertidos, 1);
  const ids = p => M.avisosDestino(r.filas, spec, p).map(a => a.id);
  assert.deepEqual(ids({ noGravadas: "si", exporta: true }), ["todo_dg", "exportador"]);
  assert.deepEqual(ids({ noGravadas: "no", exporta: true }), ["exportador"]); // solo exporta y vende gravado: 107 esta bien
  assert.deepEqual(ids({}), []);                                                 // sin perfil no se adivina nada
  assert.match(M.avisosDestino(r.filas, spec, { noGravadas: "si" })[0].fundamento, /nota 5/);
  // Si ya reubico en 17-18 (casilla 110) pero no tiene ventas no gravadas: aviso al reves.
  const mixto = M.procesar(F.casoExportador({ 15: "0.00", 16: "0.00", 17: "200.00", 18: "36.00" }), spec);
  assert.equal(casilla(M.casillas621(mixto.filas, spec), 110), 20000);
  assert.deepEqual(M.avisosDestino(mixto.filas, spec, { noGravadas: "no" }).map(a => a.id), ["dgng_sin_ng"]);
});

test("campo 11 (rango): solo para consolidar operaciones sin crédito fiscal", () => {
  const r = M.procesar([F.CABECERA.join("|"), F.fila({ 1: F.GENERADOR, 2: "X", 3: "202607", 5: "01/07/2026", 7: "01", 8: "F001", 10: "1", 11: "9",
    15: "10.00", 16: "1.80", 25: "11.80", 26: "PEN", 27: "1.000" })].join("\n"), spec);
  assert.ok(reglas(r, 1).includes("error:rango:11"));
});

// Siguen en sus fases (ver docs/sire/estructura-campos.md, "Casos del mercado").
test.todo("fase 4 · caso 1: corregir un tipo 30 en el Excel y devolverlo en el TXT de reemplazo (Anexo 11)");
test.todo("fase 4 · caso 3: reubicar 15-16 -> 17-18 / 19-20 por comprobante y generar el TXT (15+17+19 = propuesto ±1)");
test.todo("fase 5 · caso 2 en ventas: Exonerado (campo 19) e Inafecto (campo 20) del RVIE -> casilla 105 / 109");

test("JSON Logic: operaciones del spec", () => {
  assert.equal(M.ev({ in: [{ var: "c7" }, ["14", "46"]] }, { c7: "14" }), true);
  assert.equal(M.ev({ mes_siguiente: { var: "c3" } }, { c3: "202612" }), 202701);
  assert.equal(M.ev({ aaaamm: { var: "c5" } }, { c5: "13/07/2026" }), 202607);
  assert.throws(() => M.ev({ eval: ["x"] }, {}), /no soportada/);
});
