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
  assert.ok(f(14).includes("error:duplicado:10"));                   // 435: el SIRE lo rechaza
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

// --- Validaciones del SIRE (819/818, 390/391, 425, 346) y la que el SIRE deja pasar (cuadre) --------------
// Fuente: Control de Cambios del Aplicativo Cliente SIRE (SUNAT) y Anexo 11 de la RS 040-2022.
const una = (extra, proveedor = F.PROV.a) => M.procesar([F.CABECERA.join("|"), F.fila({ 1: F.GENERADOR, 2: "X", 3: "202607", 5: "01/07/2026",
  7: "01", 8: "F001", 10: "1", 12: "6", 13: proveedor, 14: "DISTRIBUIDORA FICTICIA S.A.C.", 15: "0.00", 16: "0.00", 17: "0.00", 18: "0.00",
  19: "0.00", 20: "0.00", 21: "0.00", 22: "0.00", 23: "0.00", 24: "0.00", 25: "0.00", 26: "PEN", 27: "1.000", ...extra })].join("\n"), spec);
const nc = (mod = "01", serie = "F001") => ({ 28: "01/07/2026", 29: mod, 30: serie, 32: "9" });   // documento modificado

test("819 · boleta (03) sin crédito fiscal: importes en 15-25 -> error, con los campos señalados", () => {
  const r = una({ 7: "03", 8: "B001", 21: "50.00", 25: "50.00" });
  const h = r.hallazgos.find(x => x.regla === "sin_credito");
  assert.equal(h.nivel, "error");
  assert.equal(h.codigo, "819");
  assert.deepEqual(h.marcas, [21, 25]);
  assert.match(h.msg, /03 - Boleta de venta.*libre utilización/);
  assert.deepEqual(reglas(una({ 7: "03", 8: "B001", 42: "50.00" }), 1), []);        // en los libres: bien
  assert.ok(!reglas(una({ 15: "100.00", 16: "18.00", 25: "118.00" }), 1).length);   // factura: sí da crédito
  assert.equal(M.reemplazo(r.filas, spec).texto, null);                             // y bloquea el TXT
});

test("818 · la nota que modifica una boleta -> error con el tipo modificado; la de una factura, no", () => {
  const r = una({ 7: "07", 8: "B001", 21: "-50.00", 25: "-50.00", ...nc("03", "B001") });
  const h = r.hallazgos.find(x => x.regla === "nota_sin_credito");
  assert.deepEqual([h.nivel, h.codigo, h.marcas], ["error", "818", [21, 25]]);
  assert.match(h.msg, /07 - Nota de crédito.*\(03 - Boleta de venta\)/);
  assert.deepEqual(reglas(una({ 7: "07", 8: "B001", 42: "-50.00", ...nc("03", "B001") }), 1), []);
  assert.deepEqual(reglas(una({ 7: "07", 15: "-100.00", 16: "-18.00", 25: "-118.00", ...nc() }), 1), []);
});

test("390 / 391 · ticket y boletos podrían no dar crédito -> advertencia (validación funcional, no bloquea)", () => {
  for (const t of ["12", "05", "15", "16"]) {
    const h = una({ 7: t, 8: "0001", 15: "100.00", 16: "18.00", 25: "118.00" }).hallazgos.find(x => x.regla === "podria_sin_credito");
    assert.deepEqual([h?.nivel, h?.codigo], ["advertencia", "390"], `tipo ${t}`);
  }
  const n = una({ 7: "07", 15: "-100.00", 16: "-18.00", 25: "-118.00", ...nc("12", "0001") });
  assert.deepEqual(reglas(n, 1), ["advertencia:nota_podria:15"]);
  assert.equal(n.hallazgos[0].codigo, "391");
  assert.ok(M.reemplazo(n.filas, spec).texto);                                     // no bloquea
  assert.deepEqual(reglas(una({ 7: "12", 8: "0001", 42: "118.00" }), 1), []);       // sin montos en 15-25: nada
});

test("425 · signo según el tipo (Anexo 11 y Cliente SIRE): notas de crédito en negativo, el resto en positivo", () => {
  assert.deepEqual(reglas(una({ 7: "07", 15: "100.00", 16: "18.00", 25: "118.00", ...nc() }), 1),
    ["error:negativo_15:15", "error:negativo_16:16", "error:negativo_25:25"]);
  assert.deepEqual(reglas(una({ 7: "07", 15: "-100.00", 16: "-18.00", 25: "-118.00", ...nc() }), 1), []);
  assert.ok(una({ 7: "07", 15: "100.00", ...nc() }).hallazgos.filter(h => /^(nega|posi)tivo_/.test(h.regla)).every(h => h.codigo === "425"));
  assert.ok(reglas(una({ 7: "87", 21: "5.00", 25: "5.00" }), 1).includes("error:negativo_21:21"));
  assert.deepEqual(reglas(una({ 15: "-100.00", 16: "-18.00", 25: "-118.00" }), 1),
    ["error:positivo_15:15", "error:positivo_16:16", "error:positivo_25:25"]);
  assert.deepEqual(reglas(una({ 21: "-5.00", 22: "-1.00" }), 1).filter(x => /positivo/.test(x)), ["error:positivo_21:21", "error:positivo_22:22"]);
  // IGV con base 0.00: también se revisa su signo (v3.21.0)
  assert.ok(reglas(una({ 7: "07", 16: "18.00", 25: "-82.00", 21: "-100.00", ...nc() }), 1).includes("error:negativo_16:16"));
  // Campo 24: el SIRE omite el 425 y acepta ambos signos en cualquier tipo (v3.30.0)
  assert.deepEqual(reglas(una({ 21: "10.00", 24: "-1.00", 25: "9.00" }), 1), []);
  assert.deepEqual(reglas(una({ 7: "07", 21: "-10.00", 24: "1.00", 25: "-9.00", ...nc() }), 1), []);
  // 25 (atribución) resta solo si el campo 34 empieza con «1»; el ICBPER (23) va en negativo solo en la 07
  const atrib = x => reglas(una({ 7: "25", 8: "0001", 21: "5.00", 25: "5.00", 34: x }), 1).filter(r => /negativo|positivo/.test(r));
  assert.deepEqual(atrib("1-ABC"), ["error:negativo_21:21", "error:negativo_25:25"]);
  assert.deepEqual(atrib("2-ABC"), []);
  assert.ok(!reglas(una({ 7: "87", 23: "0.50", 25: "-0.50", 21: "-1.00" }), 1).some(x => x.includes("_23")));
});

test("346 · IGV: 18% o la tasa reducida MYPE (10% hasta 2025, 10.5% en 2026) -> sin aviso; otra tasa -> advertencia", () => {
  assert.deepEqual(reglas(una({ 15: "1000.00", 16: "105.00", 25: "1105.00" }), 1), []);                    // 2026 al 10.5%
  assert.deepEqual(reglas(una({ 3: "202512", 5: "01/12/2025", 15: "1000.00", 16: "100.00", 25: "1100.00" }), 1), []);   // 2025 al 10%
  assert.deepEqual(reglas(una({ 3: "202601", 5: "30/12/2025", 15: "1000.00", 16: "100.00", 25: "1100.00" }), 1), []);   // emitida en 2025
  assert.deepEqual(reglas(una({ 3: "202512", 5: "01/12/2025", 15: "1000.00", 16: "105.00", 25: "1105.00" }), 1), ["advertencia:igv_15:15"]);
  const r = una({ 15: "1000.00", 16: "100.00", 25: "1100.00" });                                          // 10% en 2026: ya no
  assert.deepEqual(reglas(r, 1), ["advertencia:igv_15:15"]);
  assert.equal(r.hallazgos[0].codigo, "346");
  assert.ok(!r.hallazgos[0].extra && M.reemplazo(r.filas, spec).texto);
});

test("lo que el SIRE deja pasar: el total que no cuadra -> advertencia «revisión extra» (no bloquea)", () => {
  const r = una({ 15: "100.00", 16: "18.00", 25: "999.00" });
  assert.deepEqual(reglas(r, 1), ["advertencia:total:25"]);
  assert.ok(r.hallazgos[0].extra);
  const t = M.reemplazo(r.filas, spec);
  assert.ok(t.texto && !t.bloqueos.length && t.advertencias.length === 1);
});

test("diccionario de errores: cada código del spec está en el diccionario, y lo que el diccionario cita existe", () => {
  const d = JSON.parse(readFileSync(new URL("../../app/static/sire/diccionario-errores.json", import.meta.url), "utf8"));
  const por = new Map(d.codigos.map(x => [x.codigo, x]));
  assert.equal(por.size, d.codigos.length, "sin códigos repetidos");
  for (const r of est.reglas.filter(r => r.codigo)) assert.ok(por.get(r.codigo)?.conversor.some(id => id === r.id || (id.endsWith("*") && r.id.startsWith(id.slice(0, -1)))), `${r.id} -> ${r.codigo}`);
  const ids = new Set([...est.reglas.map(r => r.id), "duplicado", "serie"]);
  for (const x of d.codigos) {
    assert.match(x.codigo, /^\d{3}$/);
    assert.ok(x.sunat && d.fuentes[x.fuente] && x.registros.length && "en_sencillo" in x, x.codigo);
    for (const id of x.conversor) assert.ok(id.endsWith("*") ? [...ids].some(i => i.startsWith(id.slice(0, -1))) : ids.has(id), `${x.codigo}: ${id}`);
  }
});

// Siguen en sus fases (ver docs/sire/estructura-campos.md, "Casos del mercado").
// --- Fase 4: TXT de reemplazo (Anexo 11) ----------------------------------------------------------------
const lineas = t => t.split("\n").filter(Boolean).map(l => l.split("|"));

test("fase 4 · nombre y estructura del Anexo 11: 37 campos, CAR vacío, sin 38-41 ni libres vacíos, palote final", () => {
  const r = M.procesar(F.propuestaLimpia(), spec), t = M.reemplazo(r.filas, spec);
  assert.deepEqual(t.bloqueos, []);
  assert.equal(t.archivo, `LE${F.GENERADOR}20260700080400021112.TXT`);       // Tabla 13: 080400 · 02 reemplaza · O I M · 2
  assert.equal(t.zip, `LE${F.GENERADOR}20260700080400021112.zip`);
  // Pos. 22-27 = identificador del libro: RCE 080400 (Tabla 13 RS 040-2022 y el ejemplo RCE del Manual del
  // PVSIRE 1.7.0). 140400 es del RVIE: si el PVSIRE objeta 22-27, se eligió «Ventas» como tipo de archivo.
  assert.equal(t.zip.slice(21, 27), "080400");
  assert.equal(spec.estructuras.rce_reemplazo.archivo.libro, "080400");               // una sola fuente: sire-spec.json
  const ls = lineas(t.texto);
  assert.equal(ls.length, 6);                                                  // sin cabecera
  for (const v of ls) { assert.equal(v.length, 38); assert.equal(v[37], ""); assert.equal(v[3], ""); assert.equal(v[36], ""); }
  assert.ok(t.texto.endsWith("|\n") && !t.texto.includes("\r"));
  assert.ok(ls.every(v => v[1] === "COMERCIAL EJEMPLO S.A.C."), "un solo nombre del generador (el más frecuente)");
  assert.ok(ls.some(v => v[13] === "SERVICIOS & NEGOCIOS FICTICIOS E.I.R.L."), "«&amp;» del portal sale como «&»");
});

test("fase 4 · ida y vuelta sin pérdida: propuesta -> reemplazo -> se vuelve a leer igual (campos 1-37)", () => {
  const r = M.procesar(F.propuestaLimpia(), spec), t = M.reemplazo(r.filas, spec);
  const de_nuevo = M.parsear(t.texto, est).filas;                              // sin cabecera: por posicion
  assert.equal(de_nuevo.length, r.filas.length);
  de_nuevo.forEach((f, i) => { for (let n = 1; n <= 37; n++) {
    const esperado = n === 4 || n === 37 ? "" : n === 2 ? "COMERCIAL EJEMPLO S.A.C." : r.filas[i].c[n];
    assert.equal(f.c[n], esperado, `fila ${i + 1}, campo ${n}`);
  } });
  assert.deepEqual(M.totales(de_nuevo, spec).total, r.totales.total);
});

test("fase 4 · errores bloquean (no se entrega un TXT roto); advertencias no", () => {
  const malo = M.reemplazo(M.procesar(F.propuestaConErrores(), spec).filas, spec);
  assert.equal(malo.texto, null);
  assert.ok(malo.bloqueos.length > 5);
  const r = M.procesar(F.propuestaLimpia(), spec);
  r.filas[0].c[25] = "999.00";                                                  // total que no cuadra: solo advertencia
  const t = M.reemplazo(r.filas, spec);
  assert.ok(t.texto && t.advertencias.some(h => h.regla === "total"));
  const d = M.procesar(F.propuestaLimpia(), spec);
  d.filas[1].c[10] = d.filas[0].c[10];                                          // duplicado: error 435 (Cliente SIRE v3.18.0)
  assert.ok(M.reemplazo(d.filas, spec).bloqueos.some(h => h.regla === "duplicado" && h.codigo === "435"));
  r.filas[2].c[1] = "20100055237";                                             // otro generador en el mismo TXT
  assert.ok(M.reemplazo(r.filas, spec).bloqueos.some(h => h.regla === "reemplazo" && h.campo === 1));
  assert.ok(M.reemplazo(r.filas, spec, { razon: "  " }).bloqueos.some(h => h.campo === 2));
});

test("fase 4 · libres: solo hasta el último usado y sin «|», «/» ni «\\»; montos vacíos -> 0.00", () => {
  const r = M.procesar(F.propuestaLimpia(), spec);
  r.filas[0].c[43] = "centro/costo 01"; r.filas[1].c[22] = "";
  const t = M.reemplazo(r.filas, spec), ls = lineas(t.texto);
  assert.equal(ls[0].length, 37 + 2 + 1);                                       // 42 vacio + 43 usado + palote final
  assert.equal(ls[0][38], "centro costo 01");
  assert.equal(ls[1].length, 38);
  assert.equal(ls[1][21], "0.00");
  assert.equal(t.ajustes.length, 1);
});

test("fase 4 · caso 1: tipo 30 (POS) corregido en la pantalla/Excel y devuelto en el TXT", () => {
  const r = M.procesar(F.casoPOS(), spec);
  assert.equal(M.reemplazo(r.filas, spec).texto, null);                         // serie y numero malos: bloquea
  Object.assign(r.filas[3].c, { 8: "F701", 10: "20260700004" });                // el contador lo corrige
  const t = M.reemplazo(r.filas, spec);
  assert.deepEqual(t.bloqueos, []);
  const v = lineas(t.texto)[3];
  assert.deepEqual([v[6], v[7], v[9]], ["30", "F701", "20260700004"]);
});

test("fase 4 · caso 2: compra gravada usada solo para ventas exoneradas -> reubicada a 19-20 (DNG)", () => {
  const r = M.procesar(F.casoLibros(), spec), f = r.filas[2];
  assert.equal(M.destinoDe(f.c), "dg");
  assert.ok(M.reubicar(f, "dng"));
  assert.deepEqual([f.c[15], f.c[16], f.c[19], f.c[20]], ["0.00", "0.00", "50.00", "9.00"]);
  assert.equal(casilla(M.casillas621(r.filas, spec), 113), 10000 + 5000);
  const v = lineas(M.reemplazo(r.filas, spec).texto)[2];
  assert.deepEqual([v[14], v[15], v[18], v[19]], ["0.00", "0.00", "50.00", "9.00"]);
});

test("fase 4 · caso 3: exportador 107 -> 110 por comprobante, con las sumas intactas (nota 5)", () => {
  const r = M.procesar(F.casoExportador(), spec), antes = M.totales(r.filas, spec).total.montos;
  assert.ok(M.reubicar(r.filas[0], "dgng"));
  assert.equal(M.destinoDe(r.filas[0].c), "dgng");
  const k = M.casillas621(r.filas, spec), despues = M.totales(r.filas, spec).total.montos;
  assert.equal(casilla(k, 110), 100000);
  assert.equal(antes[15] + antes[17] + antes[19], despues[15] + despues[17] + despues[19]);
  assert.equal(antes[16] + antes[18] + antes[20], despues[16] + despues[18] + despues[20]);
  assert.equal(M.reemplazo(r.filas, spec).texto.split("\n")[0].split("|").slice(14, 18).join("|"), "0.00|0.00|1000.00|180.00");
  const neg = { c: { 15: "-100.00", 16: "-18.00", 17: "0.00", 18: "0.00", 19: "0.00", 20: "0.00" } };   // nota de credito
  M.reubicar(neg, "dng"); assert.deepEqual([neg.c[19], neg.c[20]], ["-100.00", "-18.00"]);
  assert.equal(M.reubicar({ c: { 15: "1,00" } }, "dng"), false);               // monto ilegible: no se mueve nada
});

test("fase 4 · tabla pegada / Excel: títulos del conversor o de la propuesta, números y fechas de Excel", () => {
  const r = M.procesar(F.propuestaLimpia(), spec);
  const tit = ["Fila", ...est.campos.filter(c => !c.libre).map(c => `${c.n}. ${c.nombre}`), "Observaciones"];
  const matriz = [tit, ...r.filas.map(f => [f.n, ...est.campos.filter(c => !c.libre).map(c => f.c[c.n]), ""])];
  const { filas } = M.filasDeTabla(matriz, spec);
  assert.deepEqual(M.reemplazo(filas, spec).texto, M.reemplazo(r.filas, spec).texto);
  const tsv = [F.CABECERA.slice(0, 27).join("\t"), [F.GENERADOR, "COMERCIAL EJEMPLO S.A.C.", "202607", "", "13/07/2026", "", "1", "F001", "", "7",
    "", "6", F.PROV.a, "DISTRIBUIDORA FICTICIA S.A.C.", "100", "18", "", "", "", "", "", "", "", "", "118", "PEN", "1"].join("\t")].join("\n");
  const p = M.filasDeTabla(M.tablaDePegado(tsv), spec);
  assert.equal(p.filas[0].c[7], "01");                                         // Excel se comio el cero
  assert.ok(p.avisos.length === 1);
  const fecha = M.filasDeTabla([["5. Fecha de emisión", "1. RUC del generador", "7. Tipo", "25. Importe total", "15. Base"],
    [new Date(Date.UTC(2026, 6, 13)), 20123456786, 1, 118, 100]], spec).filas[0].c;
  assert.deepEqual([fecha[5], fecha[1], fecha[7], fecha[25], fecha[15]], ["13/07/2026", "20123456786", "01", "118.00", "100.00"]);
  assert.throws(() => M.filasDeTabla([["A", "B"], ["1", "2"]], spec), /No reconocemos las columnas/);
});

test("fase 4 · ZIP para subir: un solo TXT con el mismo nombre, se vuelve a abrir igual", async () => {
  const t = M.reemplazo(M.procesar(F.propuestaLimpia(), spec).filas, spec);
  const z = M.zipear(t.archivo, new TextEncoder().encode(t.texto));
  const de_nuevo = await M.descomprimir(z);
  assert.equal(de_nuevo.length, 1);
  assert.equal(de_nuevo[0].nombre, t.archivo);
  assert.equal(new TextDecoder().decode(de_nuevo[0].data), t.texto);
});
test.todo("fase 5 · caso 2 en ventas: Exonerado (campo 19) e Inafecto (campo 20) del RVIE -> casilla 105 / 109");

test("JSON Logic: operaciones del spec", () => {
  assert.equal(M.ev({ in: [{ var: "c7" }, ["14", "46"]] }, { c7: "14" }), true);
  assert.equal(M.ev({ mes_siguiente: { var: "c3" } }, { c3: "202612" }), 202701);
  assert.equal(M.ev({ aaaamm: { var: "c5" } }, { c5: "13/07/2026" }), 202607);
  assert.throws(() => M.ev({ eval: ["x"] }, {}), /no soportada/);
});
