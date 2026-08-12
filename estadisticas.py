#!/usr/bin/env python3
"""
estadisticas.py — Motor de estadisticas de creacion de empresas (altas de RUC /
Nuevos Negocios de SUNAT), parametrizado por NIVEL (departamento | provincia).

SOLO PRODUCE DATOS: no imprime HTML ni renderiza nada. Devuelve un dict y (opcional)
escribe JSON por territorio + CSV. Corre para CUALQUIER territorio sin tocar codigo.

FILTRO GEOGRAFICO: por PREFIJO DE UBIGEO, NUNCA por texto.
  - departamento -> 2 digitos (left(ubigeo,2))
  - provincia    -> 4 digitos (left(ubigeo,4))
El prefijo se resuelve desde app/static/distritos.json (nombres limpios).

REGIMEN: derivado del codigo de tributo de renta (SUNAT lo manda a 5 digitos;
se ELIMINA EL 4TO DIGITO -> codigo[:3]+codigo[4:]). Se hace en SQL, self-contained.

SUFICIENCIA:
  - Categoria con < 5 casos -> 'muestra insuficiente'.
  - Territorio con < 30 altas en el periodo -> reporte marcado 'volumen_bajo'.

CACHE: regenerar_todo() precalcula el JSON de TODOS los territorios con data; las
paginas publicas leen ese JSON (no golpean la BD). Un comando lo regenera:
  python estadisticas.py --regen
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parent
DISTRITOS_JSON = BASE / "app" / "static" / "distritos.json"
OUT_DATA = BASE / "reportes" / "data"

MIN_MUESTRA = 5     # < 5 casos en una categoria = 'muestra insuficiente'
MIN_VOLUMEN = 30    # < 30 altas en todo el territorio = 'volumen_bajo'

# Codigo de tributo de renta (4 dig, ya transformado) -> regimen.
REGIMENES = {
    "4100": "Nuevo RUS",
    "3121": "Régimen MYPE Tributario (RMT)",
    "3111": "Régimen Especial (RER)",
    "3031": "Régimen General",
    "3311": "Amazonía",
    "3411": "Agrario",
    "3611": "Frontera",
}
CODIGOS_EMPRESARIALES = tuple(REGIMENES.keys())

# Transformacion 5->4 en SQL (quita el 4to digito). Fuente: tributo_codigo_raw
# o, si viene vacio, tributo. Devuelve el codigo de 4 digitos o NULL.
COD4_SQL = """
CASE
  WHEN length(coalesce(nullif(tributo_codigo_raw,''), nullif(tributo,''))) = 5
    THEN left(coalesce(nullif(tributo_codigo_raw,''), nullif(tributo,'')),3)
       || substr(coalesce(nullif(tributo_codigo_raw,''), nullif(tributo,'')),5)
  WHEN length(coalesce(nullif(tributo_codigo_raw,''), nullif(tributo,''))) = 4
    THEN coalesce(nullif(tributo_codigo_raw,''), nullif(tributo,''))
  ELSE NULL
END
"""


# --- Utilidades -------------------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().upper()


def slug(s: str) -> str:
    """Slug sin tildes ni ñ: 'SAN MARTÍN' -> 'san-martin'."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 2) if total else 0.0


def cargar_dotenv() -> None:
    env = BASE / ".env"
    if not env.exists():
        return
    for linea in env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# --- Indice geografico (fuente de verdad de nombres y slugs) ----------------
@lru_cache(maxsize=1)
def geo():
    """{'departamentos': {pref2: {...}}, 'provincias': {pref4: {...}},
        'distritos': {ubigeo: nombre}, 'slug_dep': {slug: pref2},
        'slug_prov': {(dep_slug, prov_slug): pref4}}"""
    ref = json.loads(DISTRITOS_JSON.read_text(encoding="utf-8"))
    deps, provs, dist = {}, {}, {}
    for x in ref:
        u, d2, d4 = x["u"], x["u"][:2], x["u"][:4]
        dist[u] = x["d"]
        deps.setdefault(d2, {"prefijo": d2, "nombre": x["dep"], "slug": slug(x["dep"])})
        provs.setdefault(d4, {"prefijo": d4, "nombre": x["p"], "slug": slug(x["p"]),
                              "dep_prefijo": d2, "dep_nombre": x["dep"], "dep_slug": slug(x["dep"])})
    slug_dep = {v["slug"]: k for k, v in deps.items()}
    slug_prov = {(v["dep_slug"], v["slug"]): k for k, v in provs.items()}
    return {"departamentos": deps, "provincias": provs, "distritos": dist,
            "slug_dep": slug_dep, "slug_prov": slug_prov}


def resolver_prefijo(departamento: str, provincia: str | None = None) -> str:
    """(departamento[, provincia]) -> prefijo de ubigeo (2 o 4 digitos)."""
    g = geo()
    dep = _norm(departamento)
    if provincia is None:
        prefs = {p for p, v in g["departamentos"].items() if _norm(v["nombre"]) == dep}
        if not prefs:
            raise ValueError(f"No encontre el departamento {departamento!r}.")
        return sorted(prefs)[0]
    prov = _norm(provincia)
    prefs = {p for p, v in g["provincias"].items()
             if _norm(v["dep_nombre"]) == dep and _norm(v["nombre"]) == prov}
    if not prefs:
        raise ValueError(f"No encontre la provincia {provincia!r} en {departamento!r}.")
    if len(prefs) > 1:
        raise ValueError(f"Ambiguo {provincia}/{departamento}: {sorted(prefs)}.")
    return sorted(prefs)[0]


def slug_de_prefijo(prefijo: str) -> dict:
    g = geo()
    if len(prefijo) == 2:
        return g["departamentos"].get(prefijo, {"prefijo": prefijo, "nombre": prefijo, "slug": prefijo})
    return g["provincias"].get(prefijo, {"prefijo": prefijo, "nombre": prefijo, "slug": prefijo})


# --- Consultas (parametrizadas: $1 prefijo, $2 desde, $3 hasta) --------------
async def _stats(conn, nivel, prefijo, desde, hasta, comparables):
    # W unificado: prefijo='' (nacional) no filtra por ubigeo; prefijo de 2/4
    # digitos filtra por departamento/provincia. Parametrizado ($1/$2/$3).
    W = "($1 = '' OR left(ubigeo, length($1)) = $1) AND mes_inscripcion BETWEEN $2 AND $3"
    args = (prefijo, desde, hasta)

    total = await conn.fetchval(f"SELECT count(*) FROM nuevos_negocios WHERE {W}", *args)

    # 1) altas por mes + variacion
    por_mes = await conn.fetch(
        f"SELECT mes_inscripcion mes, count(*) n FROM nuevos_negocios WHERE {W} GROUP BY 1 ORDER BY 1", *args)
    meses = [{"mes": r["mes"], "n": r["n"]} for r in por_mes]
    variacion = None
    if len(meses) >= 2:
        # variacion contra el periodo INMEDIATO anterior (ultimo vs penultimo).
        a, b = meses[-2]["n"], meses[-1]["n"]
        variacion = {"de": meses[-2]["mes"], "a": meses[-1]["mes"],
                     "absoluta": b - a, "porcentual": _pct(b - a, a) if a else None}

    # 2) natural vs juridica
    por_tipo = await conn.fetch(
        f"SELECT tipo, count(*) n FROM nuevos_negocios WHERE {W} GROUP BY 1 ORDER BY 2 DESC", *args)
    tipos = [{"tipo": r["tipo"], "n": r["n"], "pct": _pct(r["n"], total)} for r in por_tipo]

    # 4) top 10 rubros CIIU
    ciiu_rows = await conn.fetch(
        f"SELECT ciiu, mode() WITHIN GROUP (ORDER BY descripcion) descripcion, count(*) n "
        f"FROM nuevos_negocios WHERE {W} AND ciiu IS NOT NULL AND ciiu <> '' "
        f"GROUP BY ciiu ORDER BY 3 DESC, 1 LIMIT 10", *args)
    top_rubros = [{"ciiu": r["ciiu"], "descripcion": r["descripcion"], "n": r["n"],
                   "pct": _pct(r["n"], total), "muestra_insuficiente": r["n"] < MIN_MUESTRA}
                  for r in ciiu_rows]

    # 5) regimen (derivado 5->4)
    reg_rows = await conn.fetch(
        f"SELECT ({COD4_SQL}) cod4, count(*) n FROM nuevos_negocios WHERE {W} GROUP BY 1", *args)
    agg: dict[str, int] = {}
    for r in reg_rows:
        nombre = REGIMENES.get(r["cod4"] or "", None) or "Sin régimen (no empresarial)"
        agg[nombre] = agg.get(nombre, 0) + r["n"]
    regimenes = sorted(
        ({"regimen": k, "n": v, "pct": _pct(v, total), "muestra_insuficiente": v < MIN_MUESTRA}
         for k, v in agg.items()), key=lambda x: x["n"], reverse=True)

    resultado = {
        "total": total, "por_mes": meses, "variacion": variacion, "por_tipo": tipos,
        "top_rubros": top_rubros, "regimenes": regimenes,
        # Concentracion del top 10 de actividades (suma de sus %).
        "top_rubros_concentracion": round(sum(r["pct"] for r in top_rubros[:10]), 2),
    }

    # --- Metricas por nivel ---
    if nivel == "nacional":
        # Ranking de los 25 departamentos (metrica principal del nivel pais).
        gd = geo()["departamentos"]
        dep_rows = await conn.fetch(
            f"SELECT left(ubigeo,2) pref, count(*) n FROM nuevos_negocios WHERE {W} "
            f"AND ubigeo IS NOT NULL AND ubigeo <> '' GROUP BY 1 ORDER BY 2 DESC, 1", *args)
        resultado["ranking_departamentos"] = [{
            "prefijo": r["pref"], "departamento": gd.get(r["pref"], {}).get("nombre", r["pref"]),
            "departamento_slug": gd.get(r["pref"], {}).get("slug", r["pref"]),
            "n": r["n"], "pct": _pct(r["n"], total), "muestra_insuficiente": r["n"] < MIN_MUESTRA
        } for r in dep_rows]
        resultado["ranking_concentracion"] = round(
            sum(x["pct"] for x in resultado["ranking_departamentos"][:10]), 2)

    elif nivel == "provincia":
        # 3) top 10 distritos (nombre limpio de distritos.json)
        nombres = geo()["distritos"]
        dist_rows = await conn.fetch(
            f"SELECT ubigeo, count(*) n FROM nuevos_negocios WHERE {W} AND ubigeo IS NOT NULL "
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10", *args)
        resultado["top_distritos"] = [{
            "ubigeo": r["ubigeo"], "distrito": nombres.get(r["ubigeo"]) or "(ubigeo sin nombre)",
            "n": r["n"], "pct": _pct(r["n"], total), "muestra_insuficiente": r["n"] < MIN_MUESTRA
        } for r in dist_rows]
        resultado["ranking_concentracion"] = round(
            sum(x["pct"] for x in resultado["top_distritos"][:10]), 2)

        # NUEVO: peso de la provincia dentro de su departamento
        dep_pref = prefijo[:2]
        dep_total = await conn.fetchval(
            "SELECT count(*) FROM nuevos_negocios WHERE left(ubigeo,2)=$1 AND mes_inscripcion BETWEEN $2 AND $3",
            dep_pref, desde, hasta)
        dep_info = geo()["departamentos"].get(dep_pref, {})
        resultado["peso_en_departamento"] = {
            "departamento": dep_info.get("nombre", dep_pref),
            "departamento_slug": dep_info.get("slug", dep_pref),
            "n_departamento": dep_total, "n_provincia": total, "pct": _pct(total, dep_total)}

        # 6) ranking nacional de provincias
        resultado["ranking_nacional"] = await _ranking_nacional(
            conn, 4, prefijo, desde, hasta, comparables, "provincia")

    else:  # departamento
        # Ranking INTERNO de provincias (la metrica clave del nivel regional)
        prov_rows = await conn.fetch(
            f"SELECT left(ubigeo,4) pref, count(*) n FROM nuevos_negocios WHERE {W} "
            f"AND ubigeo IS NOT NULL AND ubigeo <> '' GROUP BY 1 ORDER BY 2 DESC, 1", *args)
        gp = geo()["provincias"]
        resultado["ranking_provincias"] = [{
            "prefijo": r["pref"], "provincia": gp.get(r["pref"], {}).get("nombre", r["pref"]),
            "provincia_slug": gp.get(r["pref"], {}).get("slug", r["pref"]),
            "n": r["n"], "pct": _pct(r["n"], total), "muestra_insuficiente": r["n"] < MIN_MUESTRA
        } for r in prov_rows]
        resultado["ranking_concentracion"] = round(
            sum(x["pct"] for x in resultado["ranking_provincias"][:10]), 2)

        # Ranking nacional de departamentos (puesto de ~25)
        resultado["ranking_nacional"] = await _ranking_nacional(
            conn, 2, prefijo, desde, hasta, comparables, "departamento")

    # --- CONTROL DE CALIDAD ---
    qc = await conn.fetchrow(
        f"SELECT "
        f"  count(*) filter (WHERE ubigeo IS NULL OR ubigeo='') sin_ubigeo, "
        f"  count(*) filter (WHERE ciiu IS NULL OR ciiu='') sin_ciiu, "
        f"  count(*) filter (WHERE ({COD4_SQL}) IS NULL OR ({COD4_SQL}) NOT IN "
        f"     ('4100','3121','3111','3031','3311','3411','3611')) sin_regimen "
        f"FROM nuevos_negocios WHERE {W}", *args)
    resultado["calidad"] = {
        "total_universo": total,
        "sin_ubigeo": {"n": qc["sin_ubigeo"], "pct": _pct(qc["sin_ubigeo"], total)},
        "sin_ciiu": {"n": qc["sin_ciiu"], "pct": _pct(qc["sin_ciiu"], total)},
        "sin_regimen": {"n": qc["sin_regimen"], "pct": _pct(qc["sin_regimen"], total)},
        "umbral_muestra_insuficiente": MIN_MUESTRA,
    }
    resultado["volumen_bajo"] = total < MIN_VOLUMEN
    resultado["umbral_volumen_bajo"] = MIN_VOLUMEN
    return resultado


async def _ranking_nacional(conn, plen, prefijo, desde, hasta, comparables, tipo_terr):
    rows = await conn.fetch(
        f"SELECT left(ubigeo,{plen}) pref, count(*) n FROM nuevos_negocios "
        f"WHERE ubigeo IS NOT NULL AND ubigeo <> '' AND mes_inscripcion BETWEEN $1 AND $2 "
        f"GROUP BY 1 ORDER BY 2 DESC", desde, hasta)
    ranking = [(r["pref"], r["n"]) for r in rows]
    conteos = dict(ranking)
    puesto = next((i + 1 for i, (p, _) in enumerate(ranking) if p == prefijo), None)
    salida = {"puesto": puesto, "total_territorios_con_data": len(ranking),
              "tipo": tipo_terr, "n": conteos.get(prefijo, 0)}
    comps = []
    for comp in (comparables or []):
        pref_c = comp if re.fullmatch(r"\d{2,4}", str(comp)) else resolver_prefijo(*comp)
        info = slug_de_prefijo(pref_c)
        comps.append({"prefijo": pref_c, "nombre": info["nombre"], "slug": info["slug"],
                      "n": conteos.get(pref_c, 0),
                      "puesto": next((i + 1 for i, (p, _) in enumerate(ranking) if p == pref_c), None)})
    if comps:
        salida["comparables"] = comps
    return salida


async def _run(nivel, prefijo, desde, hasta, comparables, database_url):
    import asyncpg
    conn = await asyncpg.connect(database_url)
    try:
        return await _stats(conn, nivel, prefijo, desde, hasta, comparables)
    finally:
        await conn.close()


# --- API publica ------------------------------------------------------------
def generar_reporte(departamento, provincia=None, mes_desde=None, mes_hasta=None,
                    nivel=None, comparables=None, database_url=None):
    """Genera el reporte de un territorio y periodo (version sincrona, para CLI).
    `nivel` se infiere: si hay provincia -> 'provincia', si no -> 'departamento'.
    Devuelve un dict (NO escribe a disco; el archivo consolidado lo hace --regen)."""
    if nivel is None:
        nivel = "provincia" if provincia else "departamento"
    cargar_dotenv()
    database_url = database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL (env, .env o parametro).")
    prefijo = "" if nivel == "nacional" else \
        resolver_prefijo(departamento, provincia if nivel == "provincia" else None)
    data = asyncio.run(_run(nivel, prefijo, mes_desde, mes_hasta, comparables, database_url))
    return _armar_reporte(nivel, prefijo, mes_desde, mes_hasta, data)


async def generar_reporte_async(departamento, provincia=None, mes_desde=None, mes_hasta=None,
                                nivel=None, comparables=None, database_url=None, escribir=False):
    """Version async (para usar DENTRO del event loop de FastAPI). Mismo resultado
    que generar_reporte pero se puede await-ear."""
    if nivel is None:
        nivel = "provincia" if provincia else "departamento"
    cargar_dotenv()
    database_url = database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL.")
    prefijo = "" if nivel == "nacional" else \
        resolver_prefijo(departamento, provincia if nivel == "provincia" else None)
    data = await _run(nivel, prefijo, mes_desde, mes_hasta, comparables, database_url)
    return _armar_reporte(nivel, prefijo, mes_desde, mes_hasta, data)


# --- Lectura del JSON CONSOLIDADO (lo que consumen las paginas publicas) -----
# Un solo archivo reportes/data/reportes.json con claves:
#   "<dep_slug>"  y  "<dep_slug>/<prov_slug>".
CONSOLIDADO = OUT_DATA / "reportes.json"
_CACHE = {"mtime": None, "data": None}


def cargar_consolidado() -> dict | None:
    if not CONSOLIDADO.exists():
        return None
    m = CONSOLIDADO.stat().st_mtime
    if _CACHE["mtime"] != m:
        _CACHE["data"] = json.loads(CONSOLIDADO.read_text(encoding="utf-8"))
        _CACHE["mtime"] = m
    return _CACHE["data"]


def cargar_reporte(clave: str) -> dict | None:
    """clave = 'nacional' | '<dep_slug>' | '<dep_slug>/<prov_slug>'."""
    cons = cargar_consolidado()
    return cons["reportes"].get(clave) if cons else None


# --- Analisis MANUAL y editable (NUNCA lo toca --regen) ----------------------
# reportes/data/analisis.json, con clave por territorio: { texto, fecha }.
ANALISIS = OUT_DATA / "analisis.json"
_CACHE_AN = {"mtime": None, "data": None}


def cargar_analisis(clave: str) -> dict | None:
    """Devuelve {texto, fecha} para el territorio, o None si no hay entrada."""
    if not ANALISIS.exists():
        return None
    m = ANALISIS.stat().st_mtime
    if _CACHE_AN["mtime"] != m:
        try:
            _CACHE_AN["data"] = json.loads(ANALISIS.read_text(encoding="utf-8"))
        except Exception:
            _CACHE_AN["data"] = {}
        _CACHE_AN["mtime"] = m
    ent = (_CACHE_AN["data"] or {}).get(clave)
    return ent if (ent and ent.get("texto")) else None


def clave_territorio(r: dict) -> str:
    if r["nivel"] == "nacional":
        return "nacional"
    if r["nivel"] == "departamento":
        return r["slug"]
    return f"{r['departamento_slug']}/{r['slug']}"


# --- Precomputo de TODO (comando de regeneracion) ---------------------------
async def _regen(mes_desde, mes_hasta, database_url):
    import asyncpg
    conn = await asyncpg.connect(database_url)
    try:
        if not mes_desde or not mes_hasta:
            rng = await conn.fetchrow("SELECT min(mes_inscripcion) mn, max(mes_inscripcion) mx FROM nuevos_negocios")
            mes_desde = mes_desde or rng["mn"]
            mes_hasta = mes_hasta or rng["mx"]
        dep_prefs = [r["p"] for r in await conn.fetch(
            "SELECT distinct left(ubigeo,2) p FROM nuevos_negocios WHERE ubigeo IS NOT NULL AND ubigeo<>'' "
            "AND mes_inscripcion BETWEEN $1 AND $2 ORDER BY 1", mes_desde, mes_hasta)]
        prov_prefs = [r["p"] for r in await conn.fetch(
            "SELECT distinct left(ubigeo,4) p FROM nuevos_negocios WHERE ubigeo IS NOT NULL AND ubigeo<>'' "
            "AND mes_inscripcion BETWEEN $1 AND $2 ORDER BY 1", mes_desde, mes_hasta)]

        reportes: dict[str, dict] = {}
        # Nivel NACIONAL (clave 'nacional' -> ruta /reportes).
        data = await _stats(conn, "nacional", "", mes_desde, mes_hasta, None)
        reportes["nacional"] = _armar_reporte("nacional", "", mes_desde, mes_hasta, data)
        for pref in dep_prefs:
            data = await _stats(conn, "departamento", pref, mes_desde, mes_hasta, None)
            rep = _armar_reporte("departamento", pref, mes_desde, mes_hasta, data)
            reportes[rep["slug"]] = rep
        prov_bajo = 0
        for pref in prov_prefs:
            data = await _stats(conn, "provincia", pref, mes_desde, mes_hasta, None)
            rep = _armar_reporte("provincia", pref, mes_desde, mes_hasta, data)
            reportes[f'{rep["departamento_slug"]}/{rep["slug"]}'] = rep
            prov_bajo += 1 if rep.get("volumen_bajo") else 0

        consolidado = {"periodo": {"desde": mes_desde, "hasta": mes_hasta},
                       "actualizado": dt.date.today().isoformat(),
                       "reportes": reportes}
        OUT_DATA.mkdir(parents=True, exist_ok=True)
        CONSOLIDADO.write_text(json.dumps(consolidado, ensure_ascii=False), encoding="utf-8")
        _CACHE["mtime"] = None  # invalida cache en memoria
        return len(dep_prefs), len(prov_prefs), prov_bajo, mes_desde, mes_hasta
    finally:
        await conn.close()


def _armar_reporte(nivel, prefijo, desde, hasta, data):
    if nivel == "nacional":
        territorio, slug_, dep_nombre, dep_slug = "Perú", "nacional", None, None
    elif nivel == "departamento":
        info = slug_de_prefijo(prefijo)
        territorio, slug_, dep_nombre, dep_slug = info["nombre"], info["slug"], info["nombre"], info["slug"]
    else:
        info = slug_de_prefijo(prefijo)
        pv = geo()["provincias"][prefijo]
        territorio, slug_, dep_nombre, dep_slug = info["nombre"], info["slug"], pv["dep_nombre"], pv["dep_slug"]
    rep = {"nivel": nivel, "prefijo_ubigeo": prefijo, "territorio": territorio,
           "slug": slug_, "departamento": dep_nombre, "departamento_slug": dep_slug,
           "periodo": {"desde": desde, "hasta": hasta},
           "actualizado": dt.date.today().isoformat(), **data}
    rep["hallazgos"] = _hallazgos(rep)
    return rep


# --- Hallazgos automaticos (indicadores + frases por REGLAS con umbral) ------
# Umbrales de las reglas: una frase SOLO se dispara si se cumple su umbral;
# jamas se genera texto que la data no sustente.
UMBRAL_LIDER = 40        # % del territorio lider
UMBRAL_VARIACION = 10    # % de variacion (±)
UMBRAL_REGIMEN = 30      # % del regimen predominante
UMBRAL_TOP10_ACT = 50    # % que concentra el top 10 de actividades


def _ranking_principal(r):
    """Devuelve (lista, clave_nombre) del ranking segun el nivel."""
    if r["nivel"] == "nacional":
        return r.get("ranking_departamentos", []), "departamento"
    if r["nivel"] == "departamento":
        return r.get("ranking_provincias", []), "provincia"
    return r.get("top_distritos", []), "distrito"


def _hallazgos(r):
    total = r["total"]
    var = r.get("variacion") or {}
    var_pct = var.get("porcentual")
    tipo_nat = next((t for t in r["por_tipo"] if t["tipo"] == "natural"), None)
    tipo_jur = next((t for t in r["por_tipo"] if t["tipo"] == "juridica"), None)
    pct_nat = tipo_nat["pct"] if tipo_nat else 0.0
    pct_jur = tipo_jur["pct"] if tipo_jur else 0.0
    reg = r["regimenes"][0] if r.get("regimenes") else None

    indicadores = {
        "total": total,
        "variacion_pct": var_pct,
        "pct_natural": pct_nat,
        "pct_juridica": pct_jur,
        "regimen_predominante": ({"regimen": reg["regimen"], "pct": reg["pct"], "n": reg["n"]} if reg else None),
    }

    de = "del país" if r["nivel"] == "nacional" else f"de {_titulo(r['territorio'])}"
    destacan = []
    ranking, _ = _ranking_principal(r)
    lider = ranking[0] if ranking else None
    lider_nombre = None
    if lider:
        lider_nombre = lider.get("departamento") or lider.get("provincia") or lider.get("distrito")

    # Regla 1: concentracion del territorio lider > 40%
    if lider and lider["pct"] > UMBRAL_LIDER:
        destacan.append(f"{_titulo(lider_nombre)} concentra el {lider['pct']:.2f}% de los nuevos negocios {de}.")
    # Regla 2: variacion mensual > ±10%
    if var_pct is not None and abs(var_pct) >= UMBRAL_VARIACION:
        verbo = "subieron" if var_pct > 0 else "bajaron"
        destacan.append(f"Las altas {verbo} {abs(var_pct):.2f}% en {var['a']} respecto a {var['de']}.")
    # Regla 3: regimen predominante > 30%
    if reg and reg["pct"] > UMBRAL_REGIMEN:
        destacan.append(f"El {reg['regimen']} es el régimen más frecuente ({reg['pct']:.2f}% de los casos).")
    # Regla 4: concentracion del top 10 de actividades > 50%
    if r.get("top_rubros_concentracion", 0) > UMBRAL_TOP10_ACT:
        destacan.append(f"Las 10 principales actividades concentran el "
                        f"{r['top_rubros_concentracion']:.2f}% de los nuevos negocios.")

    return {"indicadores": indicadores, "destacan": destacan[:3]}


def _titulo(s):
    """Title Case peruano (misma logica que la web, para las frases de hallazgos)."""
    minus = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "EL", "EN"}
    out = []
    for i, w in enumerate((s or "").split()):
        out.append(w.capitalize() if (i == 0 or w.upper() not in minus) else w.lower())
    return " ".join(out)


def regenerar_todo(mes_desde=None, mes_hasta=None, database_url=None):
    cargar_dotenv()
    database_url = database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL.")
    return asyncio.run(_regen(mes_desde, mes_hasta, database_url))


# --- Resumen legible por consola --------------------------------------------
def resumen_consola(r: dict) -> str:
    L = [f"REPORTE [{r['nivel'].upper()}] — {r['territorio']}"
         + (f" ({r['departamento']})" if r["nivel"] == "provincia" else "")
         + f"  ubigeo {r['prefijo_ubigeo']}",
         f"Periodo: {r['periodo']['desde']} a {r['periodo']['hasta']}   Total altas: {r['total']}"]
    if r.get("volumen_bajo"):
        L.append(f"⚠ VOLUMEN BAJO (< {r['umbral_volumen_bajo']} altas): interpreta con cautela.")
    L.append("\nAltas por mes:")
    for m in r["por_mes"]:
        L.append(f"  {m['mes']}: {m['n']}")
    if r["variacion"] and r["variacion"]["porcentual"] is not None:
        v = r["variacion"]
        L.append(f"  Variacion {v['de']}->{v['a']}: {v['absoluta']:+d} ({v['porcentual']:+.2f}%)")
    L.append("\nNatural vs juridica:")
    for t in r["por_tipo"]:
        L.append(f"  {t['tipo']:9}: {t['n']:6}  ({t['pct']}%)")
    rn = r["ranking_nacional"]
    L.append(f"\nRanking nacional ({rn['tipo']}): puesto {rn['puesto']} de {rn['total_territorios_con_data']}")
    if r["nivel"] == "departamento":
        L.append("\nRanking interno de provincias:")
        for p in r["ranking_provincias"][:12]:
            flag = "  [muestra insuficiente]" if p["muestra_insuficiente"] else ""
            L.append(f"  {p['provincia'][:26]:26} {p['n']:5} ({p['pct']}%){flag}")
    else:
        pe = r["peso_en_departamento"]
        L.append(f"\nPeso en {pe['departamento']}: {pe['n_provincia']} de {pe['n_departamento']} ({pe['pct']}%)")
        L.append("\nTop distritos:")
        for d in r["top_distritos"]:
            flag = "  [muestra insuficiente]" if d["muestra_insuficiente"] else ""
            L.append(f"  {d['distrito'][:26]:26} {d['n']:5} ({d['pct']}%){flag}")
    L.append("\nTop rubros (CIIU):")
    for c in r["top_rubros"]:
        flag = "  [muestra insuficiente]" if c["muestra_insuficiente"] else ""
        L.append(f"  {c['ciiu']:5} {(c['descripcion'] or '')[:32]:32} {c['n']:5} ({c['pct']}%){flag}")
    L.append("\nRegimen tributario:")
    for g in r["regimenes"]:
        flag = "  [muestra insuficiente]" if g["muestra_insuficiente"] else ""
        L.append(f"  {g['regimen'][:32]:32} {g['n']:5} ({g['pct']}%){flag}")
    q = r["calidad"]
    L.append("\nControl de calidad:")
    L.append(f"  Sin ubigeo:  {q['sin_ubigeo']['n']} ({q['sin_ubigeo']['pct']}%)")
    L.append(f"  Sin CIIU:    {q['sin_ciiu']['n']} ({q['sin_ciiu']['pct']}%)")
    L.append(f"  Sin regimen: {q['sin_regimen']['n']} ({q['sin_regimen']['pct']}%)")
    return "\n".join(L)


if __name__ == "__main__":
    if "--regen" in sys.argv:
        nd, npv, pbajo, d, h = regenerar_todo()
        kb = CONSOLIDADO.stat().st_size / 1024
        print(f"Regenerado: {nd} departamentos + {npv} provincias = {nd + npv} reportes "
              f"({d}..{h}) en {CONSOLIDADO} ({kb:.0f} KB). "
              f"Provincias con volumen_bajo (<{MIN_VOLUMEN}): {pbajo}.")
    else:
        for args in [(("LORETO",), {"nivel": "departamento"}),
                     (("UCAYALI",), {"nivel": "departamento"}),
                     (("LORETO", "MAYNAS"), {})]:
            rep = generar_reporte(*args[0], mes_desde="2026-05", mes_hasta="2026-06", **args[1])
            print(resumen_consola(rep)); print("=" * 64)
