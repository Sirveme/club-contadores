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

test("JSON Logic: operaciones del spec", () => {
  assert.equal(M.ev({ in: [{ var: "c7" }, ["14", "46"]] }, { c7: "14" }), true);
  assert.equal(M.ev({ mes_siguiente: { var: "c3" } }, { c3: "202612" }), 202701);
  assert.equal(M.ev({ aaaamm: { var: "c5" } }, { c5: "13/07/2026" }), 202607);
  assert.throws(() => M.ev({ eval: ["x"] }, {}), /no soportada/);
});
