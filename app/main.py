"""
Club de Contadores — WebApp (PWA) de pre-inscripcion.
contadores.perusistemas.pro

Stack: FastAPI + PostgreSQL (asyncpg) + Jinja2 + Vanilla JS. Deploy Railway.
"""
from __future__ import annotations

import os
import sys
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from . import ruc as ruc_mod
from .ruc import validar_ruc

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Motor de estadisticas (esta en la raiz del proyecto).
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
import estadisticas as est  # noqa: E402

SITE_BASE = os.getenv("SITE_BASE", "https://contadores.perusistemas.pro").rstrip("/")
MESES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "setiembre", "octubre", "noviembre", "diciembre"]


_MINUS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "EL", "EN"}


def titulo(s: str) -> str:
    """Title Case peruano: 'SAN JUAN DE LURIGANCHO' -> 'San Juan de Lurigancho'."""
    palabras = (s or "").split()
    out = []
    for i, w in enumerate(palabras):
        out.append(w.capitalize() if (i == 0 or w.upper() not in _MINUS) else w.lower())
    return " ".join(out)


def _periodo_txt(desde: str, hasta: str) -> str:
    (yd, md), (yh, mh) = desde.split("-"), hasta.split("-")
    if desde == hasta:
        return f"{MESES_ES[int(md)]} {yd}"
    if yd == yh:
        return f"{MESES_ES[int(md)]}–{MESES_ES[int(mh)]} {yd}"
    return f"{MESES_ES[int(md)]} {yd} – {MESES_ES[int(mh)]} {yh}"


def _meses_rango(desde: str, hasta: str) -> list[str]:
    y, m = map(int, desde.split("-"))
    y2, m2 = map(int, hasta.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out

# Logger que sale por stderr -> visible en los logs de Railway.
log = logging.getLogger("uvicorn.error")

# Prueba social configurable (irá subiendo). NO poner 1600.
ESTUDIOS_TOTAL = os.getenv("ESTUDIOS_TOTAL", "800")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VIDEO_URL = os.getenv("VIDEO_URL", "").strip()  # embed opcional (YouTube/otro)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ruc_mod.aviso_config()   # avisa si falta APIS_NET_PE_TOKEN (bloquea registros)
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Club de Contadores", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["titulo"] = lambda s: titulo(s)  # Title Case peruano en plantillas


# --- Pagina (embudo, una sola vista) ----------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "estudios_total": ESTUDIOS_TOTAL,
            "video_url": VIDEO_URL,
            "vapid_public_key": VAPID_PUBLIC_KEY,
            "demo": db.demo_mode(),
        },
    )


# --- API del embudo ---------------------------------------------------------
# RUCs ya confirmados en el padron de SUNAT (cache de proceso). Evita repetir la
# llamada a la API en cada guardado parcial del lead.
RUC_VERIFICADOS: set[str] = set()


async def ruc_confirmado(ruc: str) -> bool:
    """True si el RUC es valido. Un RUC del PADRON de contadores ya es valido (es
    data de SUNAT) y no depende de que la API este arriba; si no, se consulta
    SUNAT una sola vez por RUC."""
    ruc = (ruc or "").strip()
    if not ruc:
        return False
    if ruc in RUC_VERIFICADOS:
        return True
    try:
        if await db.padron_lookup(ruc):
            RUC_VERIFICADOS.add(ruc)
            return True
    except Exception:
        pass
    res = await validar_ruc(ruc)
    if res.get("ok"):
        RUC_VERIFICADOS.add(ruc)
        return True
    return False


@app.post("/api/validar-ruc")
async def api_validar_ruc(payload: dict):
    ruc = str(payload.get("ruc", "")).strip()
    res = await validar_ruc(ruc)
    if res.get("ok"):
        RUC_VERIFICADOS.add(res.get("ruc") or ruc)
        # Regla: un RUC = UN distrito. Si ya tiene uno registrado, se devuelve
        # para que la UI lo fije y no permita cambiarlo (version gratuita).
        try:
            ya = await db.distrito_de_ruc(res.get("ruc") or ruc)
        except Exception:
            ya = None
        if ya:
            res["distrito_registrado"] = ya["distrito"]
            res["ubigeo_registrado"] = ya["ubigeo"]
    status = 200 if res.get("ok") else 422
    return JSONResponse(res, status_code=status)


@app.get("/api/conteo")
async def api_conteo(distrito: str = "", ubigeo: str = ""):
    meses = await db.conteo_por_mes(ubigeo.strip(), distrito.strip())
    total = sum(m["n"] for m in meses)
    return {"distrito": distrito, "meses": meses, "total": total}


@app.post("/api/lead")
async def api_lead(payload: dict, request: Request):
    """
    CAPTURA TEMPRANA PROGRESIVA. Recibe un SUBCONJUNTO de campos y hace UPSERT por
    session_id (un solo registro por usuario que se completa). Se llama al pasar
    de etapa 1->2 (RUC+distrito), al escribir WhatsApp/email (blur/debounce, sin
    tocar boton) y al entrar a la etapa 3. Nunca bloquea la UI.
    """
    session_id = (payload.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse({"ok": False, "error": "session_id requerido"}, status_code=422)

    # La VALIDACION ocurre ANTES de cualquier insercion: si SUNAT no reconoce el
    # RUC, no se graba nada (ni como parcial). No basta con validar en el front:
    # este endpoint recibe beacons y podria llamarse con cualquier RUC.
    ruc_in = (payload.get("ruc") or "").strip()
    if not await ruc_confirmado(ruc_in):
        log.warning("Lead RECHAZADO: RUC %r no confirmado en SUNAT", ruc_in)
        return JSONResponse({"ok": False, "error": "ruc_no_validado"}, status_code=422)
    data = {
        "session_id": session_id[:40],
        "nombre": (payload.get("nombre") or "").strip() or None,
        "ruc": (payload.get("ruc") or "").strip() or None,
        "razon_social": (payload.get("razon_social") or "").strip() or None,
        "distrito": (payload.get("distrito") or "").strip() or None,
        "ubigeo": (payload.get("ubigeo") or "").strip() or None,
        "whatsapp": (payload.get("whatsapp") or "").strip() or None,
        "email": (payload.get("email") or "").strip() or None,
        "origen": (payload.get("origen") or "").strip() or None,
        "etapa": payload.get("etapa") or 0,
        "user_agent": request.headers.get("user-agent", "")[:400],
    }
    try:
        res = await db.upsert_lead(data)
    except Exception:
        # LOGUEAR el error real (visible en los logs de Railway). Antes se tragaba
        # la excepcion y devolvia 200: el lead no se guardaba y no se veia nada.
        log.exception("FALLO guardando lead ruc=%s etapa=%s", data.get("ruc"), data.get("etapa"))
        return JSONResponse({"ok": False, "error": "no_guardado"}, status_code=500)
    return {"ok": True, **res}


@app.post("/api/reconocer-ruc")
async def api_reconocer_ruc(payload: dict):
    """RECONOCIMIENTO DE RUC (TAREA 3). Si el RUC esta en el padron de contadores,
    devuelve su distrito (del ubigeo) para saludarlo y mostrar los negocios de su
    zona sin preguntar el distrito. Ademas indica si ese distrito tiene negocios
    en los meses disponibles; si NO, se registra en contadores_no_listados
    (marca 'sin_data') para saber donde hay contadores esperando data."""
    ruc = str(payload.get("ruc", "")).strip()
    if not ruc_mod.ruc_formato_valido(ruc):
        return {"en_padron": False, "formato_ok": False}
    p = await db.padron_lookup(ruc)
    if not p:
        return {"en_padron": False, "ruc": ruc}
    meses = await db.conteo_por_mes(p.get("ubigeo") or "", p.get("distrito") or "")
    tiene = len(meses) > 0
    if not tiene:
        try:
            await db.log_no_listado(ruc, p.get("distrito"), "sin_data")
        except Exception:
            log.exception("no pude registrar sin_data ruc=%s", ruc)
    return {"en_padron": True, **p, "tiene_negocios": tiene, "meses": meses}


@app.post("/api/no-listado")
async def api_no_listado(payload: dict):
    """Registra un RUC 'no_encontrado' (dice ser contador pero no esta en el
    padron; cae al flujo manual). Idempotente por RUC."""
    ruc = str(payload.get("ruc", "")).strip()
    distrito = (payload.get("distrito") or "").strip() or None
    marca = (payload.get("marca") or "no_encontrado").strip()
    if not ruc_mod.ruc_formato_valido(ruc):
        return JSONResponse({"ok": False, "error": "ruc_invalido"}, status_code=422)
    try:
        await db.log_no_listado(ruc, distrito, marca)
    except Exception:
        log.exception("no pude registrar no_listado ruc=%s", ruc)
        return JSONResponse({"ok": False}, status_code=200)
    return {"ok": True}


@app.get("/api/negocios")
async def api_negocios(distrito: str = "", ubigeo: str = "", mes: str = "", ruc: str = ""):
    # GATE (backend): verifica/registra el distrito contra el límite del lead
    # (con WhatsApp → 3 distritos, sin WhatsApp → 1). Si ya lo alcanzó, NO entrega
    # la data: la UI ofrece agregar WhatsApp para desbloquear. Nunca degrada al que
    # ya tiene acceso a su distrito.
    acc = await db.acceso_distrito(ruc, ubigeo, distrito)
    if not acc["ok"]:
        return {"bloqueado": True, "limite": acc["limite"], "usados": acc["usados"],
                "distrito": distrito, "negocios": [], "total": 0, "mes": mes}
    # `mes` ('YYYY-MM') usa el MISMO filtro que /api/conteo -> el numero cuadra.
    negocios = await db.lista_negocios(ubigeo.strip(), distrito.strip(), mes.strip())
    return {"negocios": negocios, "total": len(negocios), "mes": mes,
            "limite": acc["limite"], "usados": acc["usados"]}


@app.post("/api/push/subscribe")
async def api_push_subscribe(payload: dict):
    sub = payload.get("subscription") or {}
    try:
        await db.guardar_push(sub, (payload.get("ruc") or None), (payload.get("distrito") or None))
    except Exception:
        return JSONResponse({"ok": False}, status_code=500)
    return {"ok": True}


@app.get("/api/negocios.csv")
async def api_negocios_csv(distrito: str = "", ubigeo: str = "", mes: str = "", ruc: str = ""):
    """Descarga la lista visible (distrito + mes) como CSV listo para Excel."""
    # Mismo GATE que /api/negocios (el distrito ya suele estar registrado desde la
    # vista; aquí solo se ASEGURA que no se entregue un distrito sobre el límite).
    acc = await db.acceso_distrito(ruc, ubigeo, distrito)
    if not acc["ok"]:
        return JSONResponse(
            {"ok": False, "bloqueado": True, "limite": acc["limite"]}, status_code=403)
    negocios = await db.lista_negocios(ubigeo.strip(), distrito.strip(), mes.strip())
    cols = [("ruc", "RUC"), ("razon_social", "Razon Social"), ("giro", "Giro"),
            ("ciiu", "CIIU"), ("tipo", "Tipo"), ("regimen", "Regimen"),
            ("fecha_inscripcion", "Fecha"), ("direccion", "Direccion")]

    def esc(v):
        s = "" if v is None else str(v)
        return '"' + s.replace('"', '""') + '"' if (";" in s or '"' in s or "\n" in s) else s

    lineas = [";".join(t for _, t in cols)]
    for n in negocios:
        lineas.append(";".join(esc(n.get(k)) for k, _ in cols))
    # BOM para que Excel (es-PE) respete los acentos; separador ';'.
    csv = "﻿" + "\r\n".join(lineas) + "\r\n"
    nombre = f"nuevos-negocios-{(distrito or 'peru').lower().replace(' ', '-')}"
    if mes:
        nombre += f"-{mes}"
    return Response(
        content=csv.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'},
    )


@app.get("/health")
async def health():
    return {"ok": True, "demo": db.demo_mode(),
            "ruc_validacion_activa": ruc_mod.validacion_activa(),
            "ruc_estricto": ruc_mod.RUC_VALIDACION_ESTRICTA}


# ============================================================================
# REPORTES — panel interno (live) + paginas publicas (leen cache JSON) + sitemap
# ============================================================================
def _cita(r: dict, url: str) -> str:
    anio = (r.get("actualizado") or "2026")[:4]
    per = _periodo_txt(r["periodo"]["desde"], r["periodo"]["hasta"])
    terr = titulo(r["territorio"]) + (f", {titulo(r['departamento'])}" if r["nivel"] == "provincia" else "")
    return (f"Perú Sistemas Pro E.I.R.L. ({anio}). Nuevos negocios en {terr}: "
            f"altas de RUC ({per}). Club de Contadores — contadores.perusistemas.pro. "
            f"Fuente: SUNAT. {url} (consultado el {r.get('actualizado')}).")


def _meta_publica(r: dict, url: str) -> dict:
    per = _periodo_txt(r["periodo"]["desde"], r["periodo"]["hasta"])
    terr, dep = titulo(r["territorio"]), titulo(r.get("departamento", ""))
    if r["nivel"] == "departamento":
        title = f"Nuevos negocios en {terr}: {r['total']} altas de RUC ({per})"
        desc = (f"En {terr} se registraron {r['total']} empresas nuevas ({per}). "
                f"Ranking de provincias, rubros (CIIU) y régimen tributario. Fuente: SUNAT.")
    else:
        title = f"Nuevos negocios en {terr} ({dep}): {r['total']} altas ({per})"
        desc = (f"En {terr}, {dep}, se registraron {r['total']} empresas "
                f"nuevas ({per}). Distritos, rubros (CIIU) y régimen tributario. Fuente: SUNAT.")
    return {"title": f"{title} | Club de Contadores", "description": desc,
            "url": url, "image": f"{SITE_BASE}/static/icons/icon-512.png"}


def _ctx_publico(request, r):
    url = f"{SITE_BASE}/reportes/{r['slug']}" if r["nivel"] == "departamento" \
        else f"{SITE_BASE}/reportes/{r['departamento_slug']}/{r['slug']}"
    per = _periodo_txt(r["periodo"]["desde"], r["periodo"]["hasta"])
    return {"request": request, "r": r, "periodo_txt": per,
            "meta": _meta_publica(r, url), "cita": _cita(r, url)}


@app.get("/sitemap.xml")
async def sitemap():
    idx = est.indice_cache() or {"departamentos": [], "provincias": []}
    lastmod = idx.get("actualizado", "")
    urls = [f"{SITE_BASE}/reportes"]
    for d in idx["departamentos"]:
        urls.append(f"{SITE_BASE}/reportes/{d['slug']}")
    for p in idx["provincias"]:
        urls.append(f"{SITE_BASE}/reportes/{p['dep_slug']}/{p['slug']}")
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        body.append(f"  <url><loc>{u}</loc>"
                    + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")


@app.get("/panel/reportes", response_class=HTMLResponse)
async def panel_reportes(request: Request):
    idx = est.indice_cache()
    if not idx:
        return HTMLResponse("<p>No hay cache. Corre: python estadisticas.py --regen</p>", status_code=503)
    provs_por_dep: dict[str, list] = {}
    for p in sorted(idx["provincias"], key=lambda x: x["nombre"]):
        provs_por_dep.setdefault(p["dep_slug"], []).append({"slug": p["slug"], "nombre": p["nombre"]})
    meses = _meses_rango(idx["periodo"]["desde"], idx["periodo"]["hasta"])
    return templates.TemplateResponse(request, "reportes/panel.html", {
        "departamentos": sorted(idx["departamentos"], key=lambda x: x["nombre"]),
        "provincias_por_dep": provs_por_dep, "meses": meses, "periodo": idx["periodo"],
        "periodo_txt": _periodo_txt(idx["periodo"]["desde"], idx["periodo"]["hasta"])})


@app.get("/panel/reportes/resultado", response_class=HTMLResponse)
async def panel_resultado(request: Request, dep: str = "", prov: str = "",
                          desde: str = "", hasta: str = ""):
    g = est.geo()
    if not dep or dep not in g["slug_dep"]:
        return HTMLResponse('<p class="sub">Elige una región.</p>')
    idx = est.indice_cache() or {}
    desde = desde or idx.get("periodo", {}).get("desde")
    hasta = hasta or idx.get("periodo", {}).get("hasta")
    if desde > hasta:
        desde, hasta = hasta, desde
    dep_pref = g["slug_dep"][dep]
    dep_nombre = g["departamentos"][dep_pref]["nombre"]
    try:
        if prov and (dep, prov) in g["slug_prov"]:
            prov_pref = g["slug_prov"][(dep, prov)]
            prov_nombre = g["provincias"][prov_pref]["nombre"]
            r = await est.generar_reporte_async(dep_nombre, prov_nombre, desde, hasta, escribir=False)
        else:
            r = await est.generar_reporte_async(dep_nombre, None, desde, hasta,
                                                nivel="departamento", escribir=False)
    except Exception:
        log.exception("panel_resultado fallo dep=%s prov=%s", dep, prov)
        return HTMLResponse('<p class="sub">No pude generar el reporte.</p>', status_code=500)
    return templates.TemplateResponse(request, "reportes/_resultado.html",
                                      {"r": r, "periodo_txt": _periodo_txt(desde, hasta)})


@app.get("/reportes/descargar")
async def reportes_descargar(prefijo: str = "", tipo: str = "principal"):
    import re as _re
    if not _re.fullmatch(r"\d{2}|\d{4}", prefijo):
        return JSONResponse({"error": "prefijo invalido"}, status_code=400)
    if tipo == "json":
        p = est.OUT_DATA / f"{prefijo}.json"
        return FileResponse(p, media_type="application/json", filename=p.name) if p.exists() \
            else JSONResponse({"error": "no existe"}, status_code=404)
    if tipo == "rubros":
        p = est.OUT_CSV / f"{prefijo}-rubros.csv"
    else:  # principal: distritos (provincia) o provincias (departamento)
        cand = est.OUT_CSV / (f"{prefijo}-distritos.csv" if len(prefijo) == 4
                              else f"{prefijo}-provincias.csv")
        p = cand
    if not p.exists():
        return JSONResponse({"error": "no existe"}, status_code=404)
    return FileResponse(p, media_type="text/csv", filename=p.name)


@app.get("/reportes", response_class=HTMLResponse)
async def reportes_index(request: Request):
    idx = est.indice_cache()
    if not idx:
        return HTMLResponse("Sin datos.", status_code=503)
    deps = sorted(idx["departamentos"], key=lambda x: x["nombre"])
    per = _periodo_txt(idx["periodo"]["desde"], idx["periodo"]["hasta"])
    chips = "".join(
        f'<a class="chip" href="/reportes/{d["slug"]}">{d["nombre"]} <small>{d["total"]}</small></a>'
        for d in deps)
    html = f"""<!DOCTYPE html><html lang="es-PE"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reportes de nuevos negocios por región — Club de Contadores</title>
<meta name="description" content="Altas de RUC por departamento y provincia del Perú ({per}). Fuente: SUNAT.">
<link rel="canonical" href="{SITE_BASE}/reportes">
<link rel="stylesheet" href="/static/css/reportes.css?v=1"></head>
<body><main class="wrap">
<div class="brand-row"><div class="brand-mark">₡</div><div class="brand-name">Club de Contadores · Perú Sistemas</div></div>
<h1>Nuevos negocios por región</h1>
<p class="sub">Altas de RUC en el Perú · {per} · Fuente: SUNAT</p>
<section class="card"><h2>Elige un departamento</h2><div class="chips">{chips}</div></section>
</main></body></html>"""
    return HTMLResponse(html)


@app.get("/reportes/{dep}", response_class=HTMLResponse)
async def reporte_departamento(request: Request, dep: str):
    g = est.geo()
    if dep not in g["slug_dep"]:
        return HTMLResponse("Departamento no encontrado.", status_code=404)
    r = est.cargar_cache(g["slug_dep"][dep])
    if not r:
        return HTMLResponse("Reporte no disponible.", status_code=404)
    return templates.TemplateResponse(request, "reportes/publico.html", _ctx_publico(request, r))


@app.get("/reportes/{dep}/{prov}", response_class=HTMLResponse)
async def reporte_provincia(request: Request, dep: str, prov: str):
    g = est.geo()
    key = (dep, prov)
    if key not in g["slug_prov"]:
        return HTMLResponse("Provincia no encontrada.", status_code=404)
    r = est.cargar_cache(g["slug_prov"][key])
    if not r:
        return HTMLResponse("Reporte no disponible.", status_code=404)
    return templates.TemplateResponse(request, "reportes/publico.html", _ctx_publico(request, r))


# --- PWA: service worker y manifest en la raiz ------------------------------
@app.get("/sw.js")
async def sw():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/distritos.json")
async def distritos():
    return FileResponse(STATIC_DIR / "distritos.json", media_type="application/json",
                        headers={"Cache-Control": "public, max-age=86400"})
