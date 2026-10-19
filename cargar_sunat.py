#!/usr/bin/env python3
"""
cargar_sunat.py — Carga los padrones públicos de SUNAT (ZIP de la extensión) en su esquema.

  python cargar_sunat.py RUTA.zip --corte 2026-10-19 --dry-run   # lee y valida: NO escribe en la base
  python cargar_sunat.py RUTA.zip --corte 2026-10-19 --prueba    # carga en prueba_sunat (ensayo)
  python cargar_sunat.py RUTA.zip --corte 2026-10-19 --aplicar   # carga en sunat (producción)

--dry-run  Lee el ZIP completo, valida RUC/fechas/claves, repara textos con doble codificación
           ("SEÃ‘ORA" -> "SEÑORA") y comillas sobrantes, compara los conteos con los esperados y
           guarda el informe y la huella sha256 en cargas-padron/ (ignorado por git).
--prueba   Lo mismo y carga en el esquema de ensayo prueba_sunat; verifica en la base que cada
           tabla tenga las filas del CSV y que la vista v_ruc_padrones responda por RUC.
--aplicar  Carga en el esquema sunat. Exige el --dry-run y el --prueba de este corte con la MISMA
           huella del ZIP. Todo en UNA transacción: o entra el corte completo, o nada.

Nunca escribe en public. No usa load.sql (\\copy de psql): COPY por asyncpg con el CSV ya limpio.
SSCO (ssco.csv) NO se carga: el SSCO del Verificador (ruc_marcas) es la fuente; la vista lo lee de allí.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
CARPETA = BASE / "cargas-padron"
DDL = BASE / "sql" / "alter_v15_sunat.sql"
ESQUEMAS = {"prueba": "prueba_sunat", "aplicar": "sunat"}
_RUC = re.compile(r"^[0-9]{11}$")
# Tipos de las columnas (los del DDL), validados en el --dry-run ANTES de tocar la base.
ENTEROS = {"nro", "item", "ord", "cant_rep_legales", "cant_supuestos", "cant_ssco_origen", "nro_solicitud",
           "nro_inscripcion_rea"}
DECIMALES = {"monto_deuda", "monto_ingreso"}
TEXTO_FECHA = {"fecha_documento", "fecha_expediente"}       # en la fuente son texto libre
_ENTERO, _DECIMAL, _FECHA = re.compile(r"^-?[0-9]+$"), re.compile(r"^-?[0-9]+(\.[0-9]+)?$"), re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SIN_DATO = {"sin información", "sin informacion", "-"}    # la fuente dice "no se sabe": va como vacio (NULL)

# archivo -> (tabla, filas esperadas segun la extension). ssco.csv queda FUERA (ver arriba).
ARCHIVOS = {
    "padron_rs.csv": ("padron_rs", 63990),
    "exceptuadas_percepcion.csv": ("exceptuadas_percepcion", 30480),
    "exportadores_servicios.csv": ("exportadores_servicios", 21756),
    "spot_ingreso_fondos.csv": ("spot_ingreso_fondos", 15778),
    "spot_no_aplica_ilima.csv": ("spot_no_aplica_ilima", 12903),
    "deuda_coactiva.csv": ("deuda_coactiva", 9056),
    "imprentas_autorizadas.csv": ("imprentas_autorizadas", 2362),
    "registro_dl1552.csv": ("registro_dl1552", 517),
    "ssco_vinculadas_detalle.csv": ("ssco_vinculadas_detalle", 121),
    "ssco_vinculadas.csv": ("ssco_vinculadas", 66),
    "taxfree_establecimientos.csv": ("taxfree_establecimientos", 66),
    "rs295_2018.csv": ("rs295_2018", 21),
    "cpe_anotaciones_judiciales.csv": ("cpe_anotaciones_judiciales", 2),
    "exportadores_sin_garantia.csv": ("exportadores_sin_garantia", 1),
}
SUBCONTEOS = {
    "padron_rs.csv": ("padron", {"AGENTE_RETENCION": 7212, "BUEN_CONTRIBUYENTE": 50716, "PERCEPCION_HIDROCARBUROS": 25,
                                 "PERCEPCION_VENTA_INTERNA": 551, "RENUNCIA_EXONERACION_APENDICE_I": 5486}),
    "registro_dl1552.csv": ("tipo", {"PRODUCTOR_MINERO": 495, "FABRICANTE_JOYAS": 22}),
    "taxfree_establecimientos.csv": ("estado", {"VIGENTE": 63, "EXCLUIDO": 3}),
}
IGNORADOS = {"ssco.csv": "SSCO: ya está en el Verificador (ruc_marcas), pendiente de tu decisión",
             "load.sql": "se reemplaza por este cargador (COPY por asyncpg)"}


def reparar(v: str) -> tuple[str, bool]:
    """Texto con doble codificacion UTF-8 (UTF-8 leido como cp1252) -> original. Y comillas
    literales que envuelven todo el valor ('"GRUPO X S.A.C."' -> 'GRUPO X S.A.C.')."""
    orig = v
    if "Ã" in v or "Â" in v:
        try:
            v = v.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    if len(v) >= 2 and v[0] == v[-1] == '"' and '"' not in v[1:-1]:
        v = v[1:-1]
    return v, v != orig


def leer_zip(ruta: str) -> tuple[dict, str, list[str]]:
    """-> ({archivo: {cab, filas, reparados, ejemplos}}, sha256, problemas)."""
    datos = open(ruta, "rb").read()
    huella = hashlib.sha256(datos).hexdigest()
    z = zipfile.ZipFile(io.BytesIO(datos))
    nombres = set(z.namelist())
    problemas = [f"falta {a}" for a in ARCHIVOS if a not in nombres]
    extra = sorted(nombres - set(ARCHIVOS) - set(IGNORADOS))
    if extra:
        problemas.append(f"archivos no esperados en el ZIP: {extra}")
    out = {}
    for a, (tabla, esperadas) in ARCHIVOS.items():
        if a not in nombres:
            continue
        texto = z.read(a).decode("utf-8-sig")              # falla si no es UTF-8
        filas = list(csv.reader(io.StringIO(texto, newline="")))
        cab, cuerpo = filas[0], [r for r in filas[1:] if any(x.strip() for x in r)]
        reparados, ejemplos, malos, sin_dato = 0, [], Counter(), Counter()
        for r in cuerpo:
            if len(r) != len(cab):
                malos["ancho"] += 1
                continue
            for i, x in enumerate(r):
                nuevo, cambio = reparar(x)
                if cambio:
                    reparados += 1
                    if len(ejemplos) < 4:
                        ejemplos.append(f"{x[:50]} -> {nuevo[:50]}")
                    r[i] = nuevo
            for i, c in enumerate(cab):
                if (c == "ruc" or c.startswith("ruc_") or c == "ssco_ruc") and r[i] and not _RUC.match(r[i]):
                    malos[f"{c} inválido"] += 1
                patron = (_ENTERO if c in ENTEROS else _DECIMAL if c in DECIMALES else
                          _FECHA if (c.startswith("fecha") or c.startswith("vigencia")) and c not in TEXTO_FECHA else None)
                if patron and r[i] and not patron.match(r[i]):
                    if r[i].strip().lower() in SIN_DATO:
                        sin_dato[c] += 1
                        r[i] = ""
                    else:
                        malos[f"{c} no es {'fecha' if patron is _FECHA else 'número'} ({r[i][:20]!r})"] += 1
        if len(cuerpo) != esperadas:
            problemas.append(f"{a}: {len(cuerpo)} filas, se esperaban {esperadas}")
        if malos:
            problemas.append(f"{a}: {dict(malos)}")
        if a in SUBCONTEOS:
            col, esp = SUBCONTEOS[a]
            real = dict(Counter(r[cab.index(col)] for r in cuerpo))
            if real != esp:
                problemas.append(f"{a}: por {col} {real}, se esperaba {esp}")
        out[a] = {"tabla": tabla, "cab": cab, "filas": cuerpo, "reparados": reparados, "ejemplos": ejemplos,
                  "sin_dato": dict(sin_dato)}
    return out, huella, problemas


def informe_ruta(corte: str, tipo: str) -> Path:
    return CARPETA / f"{tipo}_sunat_{corte}.json"


async def cargar(datos: dict, huella: str, corte: str, esquema: str) -> dict:
    import asyncpg
    url = os.environ.get("DATABASE_URL") or next(
        l.split("=", 1)[1].strip().strip('"') for l in (BASE / ".env").read_text(encoding="utf-8").splitlines()
        if l.startswith("DATABASE_URL="))
    assert esquema in ESQUEMAS.values(), esquema
    c = await asyncpg.connect(url)
    try:
        async with c.transaction():
            await c.execute(f"CREATE SCHEMA IF NOT EXISTS {esquema}")
            # SOLO el esquema elegido: ningun nombre sin esquema puede caer en public. Las
            # funciones de sistema (pg_catalog) se resuelven igual.
            await c.execute(f"SET LOCAL search_path TO {esquema}")
            await c.execute(DDL.read_text(encoding="utf-8"))
            reales = {}
            for a, d in datos.items():
                await c.execute(f"TRUNCATE {esquema}.{d['tabla']}")
                buf = io.StringIO()
                csv.writer(buf, lineterminator="\n").writerows(d["filas"])
                await c.copy_to_table(d["tabla"], schema_name=esquema, columns=d["cab"],
                                      source=io.BytesIO(buf.getvalue().encode("utf-8")), format="csv", null="")
                reales[a] = await c.fetchval(f"SELECT count(*) FROM {esquema}.{d['tabla']}")
                if reales[a] != len(d["filas"]):
                    raise RuntimeError(f"{a}: la base tiene {reales[a]} filas y el CSV {len(d['filas'])}. No se cargó nada.")
                await c.execute(f"INSERT INTO {esquema}.cargas (archivo, tabla, filas, corte, huella_zip, reparados) "
                                "VALUES ($1, $2, $3, $4, $5, $6)", a, d["tabla"], reales[a], date.fromisoformat(corte),
                                huella, d["reparados"])
            # Verificaciones dentro de la misma transaccion (si fallan, no queda nada).
            tipos = {r["data_type"] for r in await c.fetch(
                "SELECT DISTINCT data_type FROM information_schema.columns WHERE table_schema = $1 "
                "AND column_name ~ '^(fecha|vigencia)' AND column_name NOT IN ('fecha_documento', 'fecha_expediente')", esquema)}
            if tipos != {"date"}:
                raise RuntimeError(f"columnas de fecha con tipo {tipos}: deben ser date")
            ejemplo = await c.fetchval(f"SELECT ruc FROM {esquema}.deuda_coactiva ORDER BY nro LIMIT 1")
            plan = "\n".join(r[0] for r in await c.fetch(
                f"EXPLAIN SELECT * FROM {esquema}.v_ruc_padrones WHERE ruc = $1", ejemplo))
            ficha = [dict(r) for r in await c.fetch(
                f"SELECT padron, desde, historico FROM {esquema}.v_ruc_padrones WHERE ruc = $1 ORDER BY padron", ejemplo)]
            barridos = [l.strip() for l in plan.splitlines() if "Seq Scan" in l and "ruc_marcas" not in l
                        and "cpe_anotaciones" not in l and "exportadores_sin_garantia" not in l]
            tildes = await c.fetchval(f"SELECT count(*) FROM {esquema}.padron_rs WHERE razon_social ~ '[ÑÁÉÍÓÚ]'")
            moji = await c.fetchval(
                "SELECT " + " + ".join(f"(SELECT count(*) FROM {esquema}.{d['tabla']} t WHERE t::text ~ '[ÃÂ]')"
                                       for d in datos.values()))
    finally:
        await c.close()
    return {"esquema": esquema, "filas_en_base": reales, "fechas_son_date": True, "padron_rs_con_tildes": tildes,
            "restos_doble_codificacion": moji, "vista_ejemplo": {"ruc": ejemplo, "padrones": ficha},
            "vista_barridos_completos": barridos}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip")
    ap.add_argument("--corte", required=True, help="fecha del ZIP descargado (AAAA-MM-DD)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--prueba", action="store_true")
    g.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    date.fromisoformat(a.corte)
    datos, huella, problemas = leer_zip(a.zip)
    print(f"ZIP {Path(a.zip).name} · sha256 {huella[:16]}… · corte {a.corte}")
    for arch, d in datos.items():
        print(f"  {arch:32} {len(d['filas']):>7,} filas -> {d['tabla']}"
              + (f" · {d['reparados']} textos reparados" if d["reparados"] else "")
              + "".join(f" · {n} con {c} 'Sin información' -> vacío" for c, n in d["sin_dato"].items()))
        for e in d["ejemplos"]:
            print(f"      {e}")
    for arch, motivo in IGNORADOS.items():
        print(f"  {arch:32}  (no se carga: {motivo})")
    total = sum(len(d["filas"]) for d in datos.values())
    print(f"  total: {total:,} filas en {len(datos)} tablas")
    if problemas:
        print("\nPROBLEMAS (no se carga nada):\n  " + "\n  ".join(problemas))
        sys.exit(1)
    print("  conteos = los esperados ✓ · RUC de 11 dígitos ✓ · números y fechas válidos ✓ · claves: las valida la base")
    CARPETA.mkdir(exist_ok=True)
    resumen = {"zip": Path(a.zip).name, "huella": huella, "corte": a.corte, "total": total,
               "filas": {k: len(v["filas"]) for k, v in datos.items()}, "reparados": {k: v["reparados"] for k, v in datos.items()},
               "sin_dato": {k: v["sin_dato"] for k, v in datos.items() if v["sin_dato"]}}
    if a.dry_run:
        informe_ruta(a.corte, "dryrun").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nDRY-RUN: no se escribió nada en la base. Informe: {informe_ruta(a.corte, 'dryrun')}")
        return
    previo = informe_ruta(a.corte, "dryrun")
    if not previo.exists() or json.loads(previo.read_text(encoding="utf-8"))["huella"] != huella:
        sys.exit("Falta el --dry-run de este corte con el MISMO ZIP (huella distinta o sin informe). No se cambió nada.")
    if a.aplicar:
        ensayo = informe_ruta(a.corte, "prueba")
        if not ensayo.exists() or json.loads(ensayo.read_text(encoding="utf-8"))["huella"] != huella:
            sys.exit("Falta el --prueba de este corte con el MISMO ZIP. No se cambió nada.")
    esquema = ESQUEMAS["aplicar" if a.aplicar else "prueba"]
    r = asyncio.run(cargar(datos, huella, a.corte, esquema))
    print(f"\nCargado en {esquema}: cada tabla con las filas de su CSV ✓")
    print(f"  fechas como date ✓ · razones sociales con Ñ/tilde en padron_rs: {r['padron_rs_con_tildes']:,}"
          f" · restos de doble codificación: {r['restos_doble_codificacion']}")
    print(f"  vista v_ruc_padrones para {r['vista_ejemplo']['ruc']}: "
          + ", ".join(p["padron"] for p in r["vista_ejemplo"]["padrones"]))
    print("  la vista usa el índice por RUC en cada tabla ✓" if not r["vista_barridos_completos"]
          else "  OJO, barridos completos en la vista:\n    " + "\n    ".join(r["vista_barridos_completos"]))
    if a.prueba:
        informe_ruta(a.corte, "prueba").write_text(json.dumps({**resumen, **r}, ensure_ascii=False, indent=1, default=str),
                                                   encoding="utf-8")
        print(f"Informe del ensayo: {informe_ruta(a.corte, 'prueba')}")


if __name__ == "__main__":
    main()
