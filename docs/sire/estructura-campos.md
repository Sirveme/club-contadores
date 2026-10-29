# SIRE — Estructura de campos (transcrita de la norma, verificada el 27/10/2026)

Fuentes oficiales leídas página por página (no de memoria):

| Norma | Qué aporta | Archivo |
|---|---|---|
| RS 112-2021/SUNAT, anexos 1–5 | RVIE: tablas, propuesta (Anexo 2), reemplazo (Anexo 3), ajustes (4 y 5) | `anexo-112-2021.pdf` (sunat.gob.pe) |
| RS 040-2022/SUNAT, anexos A–K | RCE: tablas 11–23, **propuesta RCE (Anexo 8)**, no domiciliados (9), **reemplazo RCE (Anexo 11)**, ajustes (12, 13) | `anexo-040-2022.pdf` (sunat.gob.pe) |
| **RS 138-2023/SUNAT** (El Peruano 30/06/2023) | **Sustituye** los anexos 2, 3, 4 y 5 del RVIE y ajusta tablas 1, 3, 5, 7, 8 y los anexos 8, 12 y 13 del RCE | separata El Peruano |

Búsqueda de normas posteriores (2024–2026): solo hay prórrogas de obligatoriedad (p. ej. RS 125-2026)
y facultad discrecional; **no** se encontró otra modificación de estas estructuras. Reconfirmar antes de
cada versión del producto.

**Hay DOS estructuras por registro, y no son iguales:**
- **Propuesta** (lo que SUNAT entrega, se DESCARGA): RVIE = Anexo 2 (campos 1–40 + 41–57); RCE = Anexo 8 (1–41 + 42–80).
  Lo lee el sentido **TXT → Excel**.
- **Reemplazo** (lo que el contribuyente SUBE): RVIE = Anexo 3 (1–33 + 41–57 = 50 campos); RCE = Anexo 11 (1–37 + 42–80).
  Lo escribe el sentido **Excel → TXT**. Los campos informativos de la propuesta (RVIE 34–40, RCE 38–41) NO van.

## Reglas generales (Tabla 5 RVIE / Tabla 12 RCE)
- Separador `|` (palote). Campos 41–57 (RVIE) / 42–80 (RCE): libres; si no se usan, **ni el dato ni los palotes**.
- Monto: hasta 12 enteros y 2 decimales, **sin comas de miles**, punto decimal. Negativo: `-#.##`.
- Texto libre: no puede contener `|`, `/`, `\`.
- Fechas `DD/MM/AAAA`; periodo `AAAAMM` (01 ≤ MM ≤ 12).
- Campo 4 (CAR): en el archivo de reemplazo se consigna **vacío** (lo pone SUNAT).
- Anulados / baja comunicada / CDR distinto a aceptado: se anotan con importe 0.00.

## Nombre del archivo (Tabla 6 RVIE / Tabla 13 RCE)
`LE` + RUC(11) + AAAA + MM + `00` + libro(6) + CC(2) + O + I + M + G + [NN] + `.TXT`

| Pos. | Valor |
|---|---|
| 22–27 libro | RVIE `140400` · RCE `080400` (no domiciliados `080500`). Confirmado en el Manual de Usuario del PVSIRE 1.7.0: su ejemplo RCE es `LE…202404` `00` `080400` `02` `1112.txt` y el RVIE `…00` `140400` `02` `1112`. El PVSIRE compara el nombre con el **tipo de archivo elegido**: si objeta «22 - 27 Identificador del libro», se eligió «Reemplazo del Registro de Ventas e Ingresos (RVIE)» para un archivo de compras |
| 28–29 CC | `01` acepta propuesta · `02` **reemplaza propuesta** · `03` ajustes posteriores · `04`/`05` ajustes de periodos anteriores al SIRE (general / simplificado) · RCE `00`/`06` no domiciliados |
| 30 O | `0` cierre/baja de RUC · `1` empresa operativa · `2` cierre del libro |
| 31 I | `1` con información · `0` sin información |
| 32 M | `1` soles · `2` dólares |
| 33 G | `2` (generado en SIRE, fijo) |
| 34–35 NN | correlativo, solo ajustes posteriores |

Ejemplos (reemplazo, empresa operativa, con información, soles):
RVIE `LE20XXXXXXXXX2026100014040002` + `1112` + `.TXT` · RCE `LE20XXXXXXXXX2026100008040002` + `1112` + `.TXT`.
**Por confirmar en el manual SIRE:** si el portal exige el TXT comprimido en ZIP y la codificación (ANSI/UTF-8).

## RCE — Registro de Compras
Anexo 11 (reemplazo) y Anexo 8 (propuesta) comparten los campos 1–37. En la propuesta, 38–41 son informativos.

| # | Campo (nemotécnico) | Long. | Formato | Reglas clave |
|---|---|---|---|---|
| 1 | RUC del generador (RUC) | 11 | N | Obligatorio |
| 2 | Razón social del generador (ID) | ≤1500 | A | Obligatorio; del RUC del campo 1 |
| 3 | Periodo | 6 | N | AAAAMM; el de la propuesta |
| 4 | CAR SUNAT | 27 | A | Reemplazo: vacío (Tabla 7) |
| 5 | Fecha de emisión | 10 | A | DD/MM/AAAA; AAAAMM ≤ periodo |
| 6 | Fecha vcto / pago | 10 | A | Obligatoria si tipo 14, 46, 50, 51, 52, 53, 54; ≤ mes siguiente si 14 |
| 7 | Tipo CP/Doc. | 2 | A | Tabla 11; no admite 91, 97, 98 |
| 8 | Serie del CDP / código de aduana | ≤20 | A | Según Tabla 11; tipos 50–54: código de aduana (Tabla 4) |
| 9 | Año DAM/DSI | 4 | N | Obligatorio si tipo 50–54; > 1981 y ≤ año del periodo |
| 10 | Nro CP / Nro inicial (rango) | ≤20 | A | Obligatorio salvo tipo 00; consolidado diario: número inicial |
| 11 | Nro final (rango) | ≤20 | A | Solo consolidado (tipos listados), con 15–20 = 0.00 |
| 12 | Tipo doc. del proveedor | 1 | A | Tabla 1; obligatorio salvo tipo 00 o rango |
| 13 | **Nro doc. del proveedor** | ≤15 | A | **Aquí engancha el cruce de riesgo** (si 12 = 6, es RUC) |
| 14 | Razón social del proveedor | ≤1500 | A | Persona natural: ap. paterno, ap. materno, nombres |
| 15 | BI gravado DG | 12,2 | N | Negativo en notas 07/87 y tipo 25 (si 34 empieza con 1); tipo 46: BI = campo 16 / tasa |
| 16 | IGV/IPM DG | 12,2 | N | Mismo signo que 15 |
| 17 | BI gravado DGNG | 12,2 | N | Ídem 15 |
| 18 | IGV/IPM DGNG | 12,2 | N | Mismo signo que 17 |
| 19 | BI gravado DNG | 12,2 | N | Ídem 15 |
| 20 | IGV/IPM DNG | 12,2 | N | Mismo signo que 19 |
| 21 | Valor adq. no gravadas (exonerado + inafecto) | 12,2 | N | Negativo en 07/87/25 |
| 22 | ISC | 12,2 | N | Solo el ISC deducible |
| 23 | ICBPER | 12,2 | N | Obligatorio si tipo 01, 03, 07, 08, 12 (0.00 si no hay) |
| 24 | Otros tributos/cargos | 12,2 | N | Lo que no forma parte de la BI |
| 25 | Total CP | 12,2 | N | Negativo en 07/87/25 |
| 26 | Moneda | 3 | A | Tabla 2 (ISO 4217) |
| 27 | Tipo de cambio | 1,3 | N | Obligatorio si moneda ≠ PEN; > 0; formato `#.###` |
| 28 | Fecha emisión doc. modificado | 10 | A | Solo 07, 08, 87, 88 |
| 29 | Tipo CP modificado | 2 | A | Solo 07, 08, 87, 88 |
| 30 | Serie CP modificado | ≤20 | A | Obligatorio si 07, 08, 87, 88 |
| 31 | Cód. aduana DAM/DSI modificada | 3 | A | Obligatorio si campo 29 = 50 o 52 |
| 32 | Nro CP modificado | ≤20 | A | Obligatorio si 07, 08, 87, 88 |
| 33 | Clasificación bienes y servicios | 1 | N | 1–5 (Tabla 23); solo ingresos > 1,500 UIT |
| 34 | ID proyecto / contrato (operadores) | ≤50 | A | Obligatorio si tipo 25; `1-…` operador, `2-…` partícipe |
| 35 | % participación | 2,2 | N | Opcional; si 34 empieza con 1 y tipo ≠ 25 |
| 36 | Impuesto Ley 31053 (IMB) | 12,2 | N | Negativo en 07/87 |
| 37 | CAR CP a modificar / indicador E/I | 27 | A | Reemplazo: vacío (ajustes posteriores) |
| 38–41 | Detracción, tipo de nota, estado, inconsistencias | — | — | **Solo en la propuesta**, informativos; no se suben |
| 42–80 | Libre utilización | ≤200 | Texto | Si no se usan, ni dato ni palotes |

Cuadre (Anexo 8, complemento): suma 15 + 17 + 19 = BI de la propuesta y 16 + 18 + 20 = IGV, **tolerancia ±1**;
IGV ≈ BI × tasa vigente (tolerancia ±1).

## RVIE — Registro de Ventas e Ingresos (texto vigente: RS 138-2023)
Anexo 3 (reemplazo) y Anexo 2 (propuesta) comparten los campos 1–33. En la propuesta, 34–40 son informativos.

| # | Campo | Long. | Formato | Reglas clave |
|---|---|---|---|---|
| 1 | RUC del generador | 11 | N | Obligatorio |
| 2 | Razón social del generador | ≤1500 | A | Obligatorio |
| 3 | Periodo | 6 | N | AAAAMM; tipo 14: el periodo según la norma del IGV |
| 4 | CAR SUNAT | 27 | A | Reemplazo: vacío |
| 5 | Fecha de emisión | 10 | A | DD/MM/AAAA; ≤ periodo |
| 6 | Fecha vcto / pago | 10 | A | Obligatoria si tipo 14; ≤ mes siguiente del periodo |
| 7 | Tipo CP/Doc. | 2 | A | Tabla 3 |
| 8 | Serie | ≤20 | A | Tabla 3 + reglas por tipo (Tabla 5) |
| 9 | Nro CP / Nro inicial | ≤20 | A | Ídem |
| 10 | Nro final | ≤20 | A | Solo tipos 00, 03, 12, 13, 18, 87, 88; boletas ≥ S/ 700 van detalladas; consolidación diaria de 18 desde 10/2023 |
| 11 | Tipo doc. del cliente | 1 | A | Obligatorio salvo excepciones (tipos listados; notas sobre 03/12/13/14/36; exportación; boletas < S/ 700 **sin** datos del cliente; rangos). Tablas 1 y 5 |
| 12 | Nro doc. del cliente | ≤15 | A | Mismas excepciones |
| 13 | Razón social del cliente | ≤1500 | A | Mismas excepciones; persona natural: apellidos y nombres |
| 14 | Valor facturado exportación | 12,2 | N | Negativo en 07/87 |
| 15 | BI gravada | 12,2 | N | Negativo en 07/87 (si el modificado es del periodo); sin ISC |
| 16 | Descuento BI | 12,2 | N | Solo negativo; solo 07/87 de periodos anteriores |
| 17 | IGV/IPM | 12,2 | N | Negativo en 07/87 |
| 18 | Descuento IGV/IPM | 12,2 | N | Solo negativo; solo 07/87 de periodos anteriores |
| 19 | Exonerado | 12,2 | N | Negativo en 07/87 |
| 20 | Inafecto | 12,2 | N | Negativo en 07/87 |
| 21 | ISC | 12,2 | N | Negativo en 07/87 |
| 22 | BI IVAP | 12,2 | N | Obligatoria si tipo 49 |
| 23 | IVAP | 12,2 | N | Obligatorio si tipo 49 |
| 24 | ICBPER | 12,2 | N | Obligatorio si tipo 01, 03, 07, 08, 12 (0.00 si no hay) |
| 25 | Otros tributos | 12,2 | N | Lo que no forma parte de la BI |
| 26 | Total CP | 12,2 | N | Negativo en 07/87 |
| 27 | Moneda | 3 | A | ISO 4217 (ver contradicción abajo) |
| 28 | Tipo de cambio | 1,3 | N | Obligatorio si moneda ≠ PEN; > 0 |
| 29 | Fecha emisión doc. modificado | 10* | A | Solo 07, 08, 87, 88; nota múltiple: valores separados por coma (hasta 1500) |
| 30 | Tipo CP modificado | 2* | A/N | Ídem |
| 31 | Serie CP modificado | ≤20* | A | Ídem |
| 32 | Nro CP modificado | ≤20* | A | Ídem |
| 33 | ID proyecto / contrato | ≤50 | A | Operadores y partícipes |
| 34–40 | Tipo de nota, estado, uso interno, valor op. gratuitas, tipo de operación, inconsistencias, uso interno | — | — | **Solo en la propuesta**, informativos; no se suben |
| 41–57 | Libre utilización | ≤200 | Texto | Si no se usan, ni dato ni palotes |

## Contradicciones encontradas en la propia norma (decidir con criterio y avisar al usuario)
1. RVIE campo 27 dice "Tabla 3 Tipo de moneda"; en el Anexo 1 la moneda es la **Tabla 2** (la 3 es tipo de comprobante).
2. RVIE campo 28: formato `#.##` pero longitud "1 entero y 3 decimales"; el RCE dice `#.###`.
   Criterio: aceptar hasta 3 decimales.
3. RVIE campo 30: "Alfanumérico" en una página y "Numérico" en otra (Anexos 2 y 3 de la RS 138-2023).
   Criterio: tratarlo como 2 caracteres de la Tabla 3.
4. El prompt original ubicaba la estructura de compras en "Anexo 8, 8.4": ese es el de la **propuesta**.
   El archivo que se SUBE es el **Anexo 11**.

## Tablas de códigos a embeber (versionadas con la fecha de la norma)
Tabla 1 tipo de documento de identidad · Tabla 2 moneda · Tabla 3 tipos de CP (RVIE) · Tabla 11 tipos de CP (RCE,
con la marca de qué tipos admite cada campo) · Tabla 4 códigos de aduana · Tabla 5/12 reglas generales por tipo
(longitudes de serie y número) · Tabla 23 clasificación de bienes y servicios.

## Casos del mercado (comunidad contable, 10/2026) — casos de prueba en `tests_js/sire/`
Datos ficticios en `fixtures.mjs` (`casoPOS`, `casoLibros`, `casoExportador`).

**Caso 1 · Tipo 30 (adquirentes de tarjetas, POS).** Tabla 11: va en RCE; serie alfanumérica hasta 20
(al complementar: F si es electrónico, otra letra si es físico; al reemplazar: alfanumérico); número
numérico mayor a cero hasta 20. Admite rango (campo 11) solo sin crédito fiscal. Puede complementar la
propuesta si es electrónico y su emisión es anterior al periodo; "de contar con información que no se
permita complementar deberá reemplazar la propuesta" (Anexo 8, rubro 2). Fase 1: se lee, se valida y se
avisa. Fase 4: corregir en el Excel y devolver el TXT de reemplazo (Anexo 11).

**Caso 2 · Exoneradas (venta de libros).** En compras: adquisiciones exoneradas e inafectas → campo 21
"Valor Adq. NG" (casilla 120; importadas 122). Compras gravadas usadas solo para ventas exoneradas →
campos 19-20 DNG (casilla 113, sin crédito fiscal). Campo 36 IMB: beneficio editorial (Ley 31053, art. 30;
nota 10). Las "casillas 19 y 20" del caso son, en VENTAS (RVIE), los campos 19 Exonerado y 20 Inafecto
(→ casilla 105 del 621; fase 5).

**Caso 3 · Exportador, casilla 107 vs 110.** Destino de la adquisición = campo de base en el RCE:

| RCE | Destino | 621 internas | 621 importaciones (tipos 50-54) |
|---|---|---|---|
| 15-16 DG | Exclusivo a gravadas y/o exportación | 107 / 108 | 114 / 115 |
| 17-18 DGNG | Gravadas y/o exportación **y** no gravadas (prorrata, casilla 173) | 110 / 111 | 116 / 117 |
| 19-20 DNG | Solo no gravadas (sin crédito fiscal) | 113 | 119 |
| 21 NG | Adquisiciones no gravadas | 120 | 122 |

Las exportaciones cuentan como gravadas (campos 15-20: "gravadas y/o de exportación"; coeficiente 173 =
(gravadas + exportaciones) / (gravadas + exportaciones + no gravadas)). Ser exportador NO lleva por sí
solo a la 110: solo si la compra sirve también a ventas no gravadas. El SIRE pone todo en 15-16 por
defecto; **nota 5 del Anexo 8**: se puede reubicar en 17-18 o 19-20, con 15+17+19 y 16+18+20 iguales a lo
propuesto (±1). No hace falta "papeles de trabajo": se corrige en la propuesta o en el reemplazo.
Fase 1: casillas del 621 (referencial) + avisos según dos preguntas de perfil (no se adivina sin perfil).
Fase 4: reubicar por comprobante y generar el TXT.
Fuente de las casillas: Ayuda del Formulario 621 (SUNAT), casillas 107-122 y 173.

## Fase 4 · Archivo de reemplazo (Excel → TXT): cómo se arma y por qué
Fuentes leídas el 28/10/2026: Anexo 11, Tablas 12 y 13 de la RS 040-2022 (`anexo-040-2022.pdf`) y el
*Manual de servicios Web API SIRE Compras v28*, punto 5.3 «importar reemplazo de la propuesta» (cpe.sunat.gob.pe).

| Aspecto | Decisión | Base |
|---|---|---|
| Campos | 1–37 en orden; **38–41 no se envían**; 42–80 solo hasta el último usado | Anexo 11 (nota 6: SUNAT completa 38–41 desde la propuesta) |
| Campo 4 (CAR) y 37 | Vacíos | Anexo 11: «Consignar vacío»; 37 solo para ajustes posteriores |
| Montos sin dato | `0.00` (15–25 y 36) | Anexo 11, nota 2 |
| Campo 2 | **Un solo** nombre del generador para todo el archivo (en la propuesta viene de varias formas); el contador lo confirma | Anexo 11 campo 2: «debe pertenecer al RUC del campo 1»; el SIRE responde «406 · Nombre no corresponde al RUC» |
| Nombre | `LE` + RUC + AAAAMM + `00` + `080400` + `02` + O `1` + I `1` + M (`1` soles / `2` dólares) + `2` + `.TXT` | Tabla 13 (8.4, reemplaza la propuesta) |
| Envío | ZIP con el TXT adentro, mismo nombre, `.zip` | Manual API 5.3: «.txt zipeado»; error 1348 si la extensión no es `.zip` |
| Separador | `\|`; cada línea termina en palote (como la propuesta del portal) | Tabla 12 |
| Cabecera | **No** lleva fila de títulos (el Anexo 11 no la describe) | Anexo 11 |
| Texto libre (42–80) | `\|`, `/` y `\` se cambian por espacio y se avisa | Tabla 12, regla 2 |
| `/` en razón social u otros campos | **No** se toca: queda como advertencia (el nombre debe coincidir con la ficha RUC) | criterio |
| `&amp;` de la propuesta | Sale como `&` (el `&amp;` es un escape HTML del portal, no parte del nombre) | criterio |
| Codificación y fin de línea | UTF-8 sin BOM, LF (como la propuesta que entrega el portal) | criterio |
| Validación | Las mismas reglas de la Fase 1: un error **impide** generar; las advertencias solo se avisan | — |
| Destino (15-16 / 17-18 / 19-20) | Solo si el contador lo elige, por comprobante; las sumas no cambian | Anexo 8, nota 5; Anexo 11, nota 2 |

**Por confirmar con el PVSIRE** (en una muestra real, que corre en el equipo del contador): el palote final, el
`&` sin escapar, la codificación UTF-8 y la extensión `.TXT` en mayúscula dentro del ZIP (la Tabla 13 dice `.TXT`;
en foros se reporta un rechazo que se resolvió con `.txt`).

## Validaciones equivalentes al PVSIRE y las que el PVSIRE no hace (29/10/2026)
Duilio pasó archivos por el PVSIRE y comparó. Cada regla vive en `sire-spec.json` (generado; la fuente de
cada una está comentada en el generador) y tiene su prueba en `tests_js/sire/motor.test.mjs`.

| Regla (spec) | PVSIRE | Nivel | Qué revisa | Fuente |
|---|---|---|---|---|
| `sin_credito` | 818 | Error | Tipo sin derecho a crédito fiscal (hoy: **03 boleta**) con importes en 15–25: van en los campos libres (42+) | Anexo 8, nota 1 («…que no otorguen derecho a crédito fiscal … se realizan en los campos libres»); RS 007-99/SUNAT art. 4 num. 3.2 (la boleta no da crédito fiscal) |
| `negativo_15…25` | 425 | Error | En 07 y 87 (y 25 si el campo 34 empieza con «1») los montos 15, 17, 19, 21, 22, 24 y 25 van en negativo; el 23 solo en la 07 | Anexo 11, campos 15–25: «Valor negativo cuando campo 7 = '07', '87' o '25'…» |
| `positivo_15…25` | 425 | Error (24: advertencia) | En los demás tipos, esos montos no van en negativo. El 24 lleva descuentos: solo se avisa | Anexo 11 (se lee «Acepta negativo» junto con la regla 3: el negativo es para esos tipos; el ISC, campo 22, lo dice sin «acepta negativo») |
| `signo_15/17/19` | — | Error | El IGV lleva el signo de su base | Anexo 11, campos 16, 18 y 20 |
| `total` | **no lo valida** | Advertencia · revisión extra | 25 ≈ suma de 15–24 (±S/ 1) | Anexo 11, nota 2 |
| `igv_15/17/19` | **no lo valida** | Advertencia · revisión extra | IGV ≈ 18% de su base (±S/ 1); puede ser tasa reducida | Ley del IGV; nunca error (hay tasas distintas) |

Pendiente de decidir con más pruebas del PVSIRE:
- **Otros tipos sin crédito fiscal.** El ticket (12) y los boletos (05, 15, 16) dan crédito fiscal solo si
  identifican al comprador con su RUC y discriminan el IGV. Desde el archivo no se sabe, así que no se marcan.
  Si el PVSIRE da 818 en alguno, se agrega a `SIN_CREDITO` en el generador (una línea).
- **Factura con montos negativos.** Se trata como error, igual que el código 425. Si el SIRE acepta algún caso
  (por ejemplo, anticipos), se baja a advertencia (`nivel` de `positivo_*`).
