"""
Club de Contadores — WebApp (PWA) de pre-inscripcion.
Observatorio de Nuevos Negocios: observatorio.perusistemas.pro

Stack: FastAPI + PostgreSQL (asyncpg) + Jinja2 + Vanilla JS. Deploy Railway.
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
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

SITE_BASE = os.getenv("SITE_BASE", "https://observatorio.perusistemas.pro").rstrip("/")
# URL del registro ante la ANPD (placeholder editable hasta tener el archivo).
ANPD_REGISTRO_URL = os.getenv("ANPD_REGISTRO_URL", "#registro-anpd").strip()
_CORREO_RE = __import__("re").compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SITE_HOST = SITE_BASE.split("//", 1)[-1]  # dominio sin esquema, para citas
# Dominio anterior: se redirige con 301 permanente al nuevo (ver middleware abajo).
DOMINIO_ANTERIOR = os.getenv("DOMINIO_ANTERIOR", "contadores.perusistemas.pro").strip().lower()
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
templates.env.filters["miles"] = lambda n: f"{int(n):,}" if n is not None else ""   # 51,477
templates.env.filters["pct"] = lambda v: f"{v:.2f}" if v is not None else ""         # 2 decimales


# --- Redireccion 301 permanente del dominio anterior al nuevo ----------------
# El Observatorio se movio de contadores.perusistemas.pro a observatorio.perusistemas.pro.
# Cualquier peticion que llegue al host anterior (a /reportes*, /observatorio o
# /sitemap.xml) se redirige de forma PERMANENTE al nuevo dominio conservando la
# ruta y el query string, para no perder enlaces ya compartidos ni ranking SEO.
_RUTAS_REDIR = ("/reportes", "/observatorio", "/sitemap.xml")


@app.middleware("http")
async def redirigir_dominio_anterior(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host == DOMINIO_ANTERIOR and request.url.path.startswith(_RUTAS_REDIR):
        destino = f"{SITE_BASE}{request.url.path}"
        if request.url.query:
            destino += f"?{request.url.query}"
        return Response(status_code=301, headers={"Location": destino})
    return await call_next(request)


# --- Pagina (embudo, una sola vista) ----------------------------------------
# EMBUDO VIEJO (generacion anterior): RESPALDO no publico en /club-legacy.
# La raiz ahora sirve la landing de captacion (mas abajo). Nadie llega aqui por
# navegacion normal (no esta enlazado en ningun lado) y va con noindex.
@app.get("/club-legacy", response_class=HTMLResponse)
async def club_legacy(request: Request):
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
            f"altas de RUC ({per}). Observatorio de Nuevos Negocios — "
            f"{SITE_HOST}. Fuente: SUNAT. {url} "
            f"(consultado el {r.get('actualizado')}).")


def _cita_breve(r: dict, url: str) -> str:
    per = _periodo_txt(r["periodo"]["desde"], r["periodo"]["hasta"])
    terr = titulo(r["territorio"])
    return (f"Observatorio de Nuevos Negocios (Perú Sistemas): nuevos negocios en "
            f"{terr}, {per}. {url}")


def _cita_html(r: dict, url: str) -> str:
    terr = titulo(r["territorio"])
    return (f'&lt;a href="{url}"&gt;Nuevos negocios en {terr} — Observatorio de Nuevos '
            f'Negocios (Perú Sistemas)&lt;/a&gt;')


def _url_publica(r: dict) -> str:
    if r["nivel"] == "nacional":
        return f"{SITE_BASE}/reportes"
    if r["nivel"] == "departamento":
        return f"{SITE_BASE}/reportes/{r['slug']}"
    return f"{SITE_BASE}/reportes/{r['departamento_slug']}/{r['slug']}"


def _mapa(r: dict):
    """Mapa MANUAL (imagen que sube Duilio). Si no existe, no se renderiza."""
    if r["nivel"] == "nacional":
        rel = f"mapas/nacional-{r['periodo']['desde']}_{r['periodo']['hasta']}.webp"
    elif r["nivel"] == "departamento":
        rel = f"mapas/dep/{r['slug']}.webp"
    else:  # provincia -> reutiliza el mapa de su departamento
        rel = f"mapas/dep/{r['departamento_slug']}.webp"
    if (STATIC_DIR / rel).exists():
        return {"url": f"/static/{rel}", "abs": f"{SITE_BASE}/static/{rel}",
                "alt": f"Mapa de {titulo(r['territorio'])}"}
    return None


def _meta_publica(r: dict, url: str) -> dict:
    per = _periodo_txt(r["periodo"]["desde"], r["periodo"]["hasta"])
    terr, dep = titulo(r["territorio"]), titulo(r.get("departamento") or "")
    if r["nivel"] == "nacional":
        title = f"Nuevos negocios en el Perú: {r['total']} altas de RUC ({per})"
        desc = (f"En el Perú se registraron {r['total']} altas de RUC ({per}). "
                f"Ranking de departamentos, rubros (CIIU) y régimen tributario. Fuente: SUNAT.")
    elif r["nivel"] == "departamento":
        title = f"Nuevos negocios en {terr}: {r['total']} altas de RUC ({per})"
        desc = (f"En {terr} se registraron {r['total']} altas de RUC ({per}). "
                f"Ranking de provincias, rubros (CIIU) y régimen tributario. Fuente: SUNAT.")
    else:
        title = f"Nuevos negocios en {terr} ({dep}): {r['total']} altas ({per})"
        desc = (f"En {terr}, {dep}, se registraron {r['total']} altas de RUC "
                f"({per}). Distritos, rubros (CIIU) y régimen tributario. Fuente: SUNAT.")
    return {"title": f"{title} | Observatorio de Nuevos Negocios", "description": desc,
            "url": url, "image": f"{SITE_BASE}/static/icons/icon-512.png"}


def _ctx_publico(request, r):
    url = _url_publica(r)
    per = _periodo_txt(r["periodo"]["desde"], r["periodo"]["hasta"])
    # noindex a las PROVINCIAS con volumen bajo (<30). Los departamentos y el
    # nacional SIEMPRE se indexan. La pagina sigue accesible por enlace directo.
    noindex = r["nivel"] == "provincia" and r.get("volumen_bajo", False)
    meta = _meta_publica(r, url)
    mapa = _mapa(r)
    if mapa:  # si hay mapa, es la imagen de Open Graph de esa pagina
        meta["image"] = mapa["abs"]
    clave = est.clave_territorio(r)
    logos_ok = _logos_existentes(est.cargar_citas())
    return {"request": request, "r": r, "periodo_txt": per, "noindex": noindex,
            "meta": meta, "mapa": mapa, "cita": _cita(r, url),
            "cita_breve": _cita_breve(r, url), "cita_html": _cita_html(r, url),
            "analisis": est.cargar_analisis(clave), "analisis_foto": _foto_autor(),
            "historial": est.cargar_historial(clave),
            "citas": est.citas_priorizadas(clave), "logos_ok": logos_ok,
            "aviso_ambito": url}


def _logos_existentes(citas: list) -> dict:
    """{nombre_logo: True} solo para los archivos que existen en static/logos/."""
    out = {}
    for c in citas or []:
        logo = (c.get("logo") or "").strip()
        if logo and (STATIC_DIR / "logos" / logo).exists():
            out[logo] = True
    return out


def _foto_autor():
    return "/static/img/duilio.webp" if (STATIC_DIR / "img" / "duilio.webp").exists() else None


@app.get("/sitemap.xml")
async def sitemap():
    cons = est.cargar_consolidado() or {"reportes": {}}
    lastmod = cons.get("actualizado", "")
    urls = [f"{SITE_BASE}/reportes", f"{SITE_BASE}/observatorio"]  # nacional = /reportes
    for r in cons["reportes"].values():
        if r["nivel"] == "departamento":
            urls.append(f"{SITE_BASE}/reportes/{r['slug']}")           # siempre
        elif r["nivel"] == "provincia" and not r.get("volumen_bajo"):
            urls.append(f"{SITE_BASE}/reportes/{r['departamento_slug']}/{r['slug']}")  # solo con volumen
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        body.append(f"  <url><loc>{u}</loc>"
                    + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")


@app.get("/panel/reportes", response_class=HTMLResponse)
async def panel_reportes(request: Request):
    cons = est.cargar_consolidado()
    if not cons:
        return HTMLResponse("<p>No hay cache. Corre: python estadisticas.py --regen</p>", status_code=503)
    deps, provs_por_dep = [], {}
    for r in cons["reportes"].values():
        if r["nivel"] == "departamento":
            deps.append({"slug": r["slug"], "nombre": titulo(r["territorio"])})
        else:
            provs_por_dep.setdefault(r["departamento_slug"], []).append(
                {"slug": r["slug"], "nombre": titulo(r["territorio"])})
    for k in provs_por_dep:
        provs_por_dep[k].sort(key=lambda x: x["nombre"])
    meses = _meses_rango(cons["periodo"]["desde"], cons["periodo"]["hasta"])
    return templates.TemplateResponse(request, "reportes/panel.html", {
        "departamentos": sorted(deps, key=lambda x: x["nombre"]),
        "provincias_por_dep": provs_por_dep, "meses": meses, "periodo": cons["periodo"],
        "periodo_txt": _periodo_txt(cons["periodo"]["desde"], cons["periodo"]["hasta"])})


@app.get("/panel/reportes/resultado", response_class=HTMLResponse)
async def panel_resultado(request: Request, dep: str = "", prov: str = "",
                          desde: str = "", hasta: str = ""):
    g = est.geo()
    if not dep or dep not in g["slug_dep"]:
        return HTMLResponse('<p class="sub">Elige una región.</p>')
    cons = est.cargar_consolidado() or {}
    desde = desde or cons.get("periodo", {}).get("desde")
    hasta = hasta or cons.get("periodo", {}).get("hasta")
    if desde > hasta:
        desde, hasta = hasta, desde
    dep_pref = g["slug_dep"][dep]
    dep_nombre = g["departamentos"][dep_pref]["nombre"]
    try:
        if prov and (dep, prov) in g["slug_prov"]:
            prov_pref = g["slug_prov"][(dep, prov)]
            prov_nombre = g["provincias"][prov_pref]["nombre"]
            r = await est.generar_reporte_async(dep_nombre, prov_nombre, desde, hasta)
        else:
            r = await est.generar_reporte_async(dep_nombre, None, desde, hasta, nivel="departamento")
    except Exception:
        log.exception("panel_resultado fallo dep=%s prov=%s", dep, prov)
        return HTMLResponse('<p class="sub">No pude generar el reporte.</p>', status_code=500)
    return templates.TemplateResponse(request, "reportes/_resultado.html",
                                      {"r": r, "periodo_txt": _periodo_txt(desde, hasta)})


def _reporte_por_prefijo(prefijo: str):
    cons = est.cargar_consolidado()
    if not cons:
        return None
    for r in cons["reportes"].values():
        if r.get("prefijo_ubigeo") == prefijo:
            return r
    return None


def _csv_response(columnas, filas, filename):
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in columnas])
    for fila in filas:
        w.writerow([fila.get(k) for k, _ in columnas])
    contenido = "﻿" + buf.getvalue()   # BOM para Excel es-PE
    return Response(contenido, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/reportes/descargar")
async def reportes_descargar(prefijo: str = "", tipo: str = "principal"):
    """Construye el archivo AL VUELO desde el JSON consolidado (no hay CSV en disco)."""
    import re as _re
    if not _re.fullmatch(r"|\d{2}|\d{4}", prefijo):   # '' = nacional, 2 = depto, 4 = provincia
        return JSONResponse({"error": "prefijo invalido"}, status_code=400)
    r = _reporte_por_prefijo(prefijo)
    if not r:
        return JSONResponse({"error": "no existe"}, status_code=404)
    slug = ("peru" if r["nivel"] == "nacional" else
            r["slug"] if r["nivel"] == "departamento" else
            f"{r['departamento_slug']}-{r['slug']}")
    if tipo == "json":
        return Response(json.dumps(r, ensure_ascii=False, indent=2),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{slug}.json"'})
    if tipo == "rubros":
        cols = [("ciiu", "CIIU"), ("descripcion", "Descripcion"), ("n", "Altas"),
                ("pct", "%"), ("muestra_insuficiente", "MuestraInsuficiente")]
        return _csv_response(cols, r.get("top_rubros", []), f"{slug}-rubros.csv")
    if r["nivel"] == "nacional":
        cols = [("prefijo", "Ubigeo"), ("departamento", "Departamento"), ("n", "Altas"),
                ("pct", "%"), ("muestra_insuficiente", "MuestraInsuficiente")]
        return _csv_response(cols, r.get("ranking_departamentos", []), "peru-departamentos.csv")
    if r["nivel"] == "provincia":
        cols = [("ubigeo", "Ubigeo"), ("distrito", "Distrito"), ("n", "Altas"),
                ("pct", "%"), ("muestra_insuficiente", "MuestraInsuficiente")]
        return _csv_response(cols, r.get("top_distritos", []), f"{slug}-distritos.csv")
    cols = [("prefijo", "Ubigeo"), ("provincia", "Provincia"), ("n", "Altas"),
            ("pct", "%"), ("muestra_insuficiente", "MuestraInsuficiente")]
    return _csv_response(cols, r.get("ranking_provincias", []), f"{slug}-provincias.csv")


@app.get("/reportes", response_class=HTMLResponse)
async def reportes_nacional(request: Request):
    r = est.cargar_reporte("nacional")
    if not r:
        return HTMLResponse("Reporte no disponible. Corre: python estadisticas.py --regen",
                            status_code=503)
    return templates.TemplateResponse(request, "reportes/publico.html", _ctx_publico(request, r))


@app.get("/observatorio", response_class=HTMLResponse)
async def observatorio(request: Request):
    foto_rel = "img/duilio.webp"
    foto = f"/static/{foto_rel}" if (STATIC_DIR / foto_rel).exists() else None
    citas = est.cargar_citas()
    return templates.TemplateResponse(request, "reportes/observatorio.html",
                                      {"request": request, "foto": foto, "site_base": SITE_BASE,
                                       "equivalencias": est.tabla_equivalencias(),
                                       "citas": citas, "logos_ok": _logos_existentes(citas),
                                       "aviso_ambito": f"{SITE_BASE}/observatorio"})


# --- Aviso de uso (formulario privado; NO publica nada) ---------------------
AVISO_EMAIL_TO = os.getenv("AVISO_EMAIL_TO", "info@perusistemas.pro").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "no-reply@perusistemas.pro").strip()


def _client_ip(request: Request) -> str:
    """IP del cliente como texto validado (IPv4/IPv6) o "" si no es una IP. Railway
    va detras de proxy: se usa el primer X-Forwarded-For. Devolver solo IPs validas
    evita romper los INSERT con columna `inet` (p.ej. host 'testclient' en tests o
    un XFF malformado)."""
    import ipaddress
    xff = request.headers.get("x-forwarded-for", "")
    cand = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    try:
        return str(ipaddress.ip_address(cand)) if cand else ""
    except ValueError:
        return ""


def _enviar_aviso_email(data: dict) -> None:
    """Best-effort: si no hay SMTP configurado, no hace nada (el aviso ya quedo
    guardado en BD y visible en /panel/avisos). Nunca rompe el flujo del usuario."""
    if not SMTP_HOST:
        return
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = f"[Observatorio] Aviso de uso — {data.get('institucion') or 'sin institución'}"
    msg["From"] = SMTP_FROM
    msg["To"] = AVISO_EMAIL_TO
    if data.get("correo"):
        msg["Reply-To"] = data["correo"]
    msg.set_content(
        "Nuevo aviso de uso recibido en el Observatorio:\n\n"
        f"Nombre: {data.get('nombre') or '-'}\n"
        f"Institución: {data.get('institucion') or '-'}\n"
        f"Correo: {data.get('correo') or '-'}\n"
        f"Uso (enlace/descripción): {data.get('uso') or '-'}\n"
        f"Página: {data.get('ambito') or '-'}\n")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
        s.starttls()
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


@app.post("/api/aviso-uso")
async def api_aviso_uso(payload: dict, request: Request):
    # Honeypot: campo oculto que un humano nunca llena. Si viene con algo, se
    # descarta en silencio (respondemos ok para no darle pistas al bot).
    if (payload.get("empresa_web") or "").strip():
        return JSONResponse({"ok": True})
    correo = (payload.get("correo") or "").strip()
    uso = (payload.get("uso") or "").strip()
    if not correo or "@" not in correo or not uso:
        return JSONResponse({"ok": False, "error": "Indica un correo válido y el uso."},
                            status_code=422)
    data = {
        "nombre": payload.get("nombre"),
        "institucion": payload.get("institucion"),
        "correo": correo,
        "uso": uso,
        "ambito": payload.get("ambito"),
        "ip": _client_ip(request),
        "user_agent": request.headers.get("user-agent", ""),
    }
    try:
        res = await db.guardar_aviso(data)
    except Exception:
        log.exception("guardar_aviso fallo")
        return JSONResponse({"ok": False, "error": "No pudimos registrar el aviso."},
                            status_code=500)
    if not res.get("ok") and res.get("motivo") == "limite":
        return JSONResponse({"ok": False, "error": "Recibimos varios envíos desde tu red. "
                             "Intenta más tarde."}, status_code=429)
    try:
        await asyncio.to_thread(_enviar_aviso_email, data)
    except Exception:
        log.warning("aviso guardado pero el correo no salio (SMTP)", exc_info=True)
    return JSONResponse({"ok": True, "mensaje": "¡Gracias! Recibimos tu aviso; "
                         "te escribiremos si hace falta."})


@app.get("/panel/avisos", response_class=HTMLResponse)
async def panel_avisos(request: Request):
    try:
        avisos = await db.listar_avisos()
    except Exception:
        log.exception("listar_avisos fallo")
        avisos = []
    return templates.TemplateResponse(request, "reportes/avisos.html",
                                      {"request": request, "avisos": avisos,
                                       "demo": db.demo_mode()})


# ============================================================================
# LANDING /nuevos-negocios — captacion. Reconocimiento de RUC en DOS NIVELES:
#   1) contadores_padron (local, instantaneo).
#   2) si no esta -> apis.net.pe por CIIU 6920 (el padron SUNAT esta incompleto).
# La API SOLO se llama para RUCs no locales (minoria). Un fallo de API NUNCA
# rechaza: se deja continuar (fallback con distrito manual). El adelanto se
# consulta EN VIVO por UBIGEO (sin tabla pre-calculada).
# ============================================================================
# La landing de captacion es la HOME. Se sirve en la raiz (URL corta para el QR)
# y en /nuevos-negocios (alias, para no romper enlaces ya compartidos). Ambas
# capturan ?ref= (o ?origen=) para medir que volante convirtio.
@app.get("/", response_class=HTMLResponse)
@app.get("/nuevos-negocios", response_class=HTMLResponse)
async def nuevos_negocios(request: Request, ref: str = "", origen: str = ""):
    # La pagina pinta PRIMERO (paso 1 = solo el campo RUC). El RUC se consulta
    # al enviarlo (POST /api/nn/ruc); nada bloquea la carga inicial.
    # `ref` (del volante, ej. ?ref=asamblea) tiene prioridad sobre `origen`.
    campana = (ref or origen or "nuevos-negocios").strip()[:60] or "nuevos-negocios"
    return templates.TemplateResponse(request, "nuevos_negocios.html", {
        "request": request, "anpd_url": ANPD_REGISTRO_URL, "origen": campana})


async def _clasificar_ruc(ruc: str) -> dict:
    """Reconocimiento en dos niveles. Devuelve identidad derivada de fuentes
    OFICIALES (padron o API), nunca del usuario. camino: A=contador, B=empresario
    (no contador), C=general/fallback (no verificable -> distrito manual)."""
    pad = await db.padron_lookup(ruc)
    if pad:
        ubigeo = (pad.get("ubigeo") or "") or None
        return {"camino": "A", "es_contador": True, "verificado": True,
                "razon_social": pad.get("razon_social"), "ubigeo": ubigeo,
                "distrito": est.nombre_distrito(ubigeo) or titulo(pad.get("distrito") or "") or None,
                "necesita_distrito": not ubigeo, "fuente": "padron"}
    api = await ruc_mod.consultar_ruc_contador(ruc)
    estado = api.get("estado")
    if estado == "contador":
        ubigeo = api.get("ubigeo") or est.ubigeo_por_nombre(
            api.get("departamento"), api.get("provincia"), api.get("distrito"))
        return {"camino": "A", "es_contador": True, "verificado": True,
                "razon_social": api.get("razon_social"), "ubigeo": ubigeo,
                "distrito": est.nombre_distrito(ubigeo) or titulo(api.get("distrito") or "") or None,
                "necesita_distrito": not ubigeo, "fuente": "api"}
    if estado == "no_contador":
        return {"camino": "B", "es_contador": False, "verificado": True,
                "razon_social": api.get("razon_social"), "ubigeo": None,
                "distrito": None, "necesita_distrito": False, "fuente": "api"}
    # no_verificable (sin token / API caida / timeout / sin CIIU): NO rechazar.
    return {"camino": "C", "es_contador": False, "verificado": False,
            "razon_social": api.get("razon_social"), "ubigeo": None,
            "distrito": None, "necesita_distrito": True, "fuente": "fallback"}


@app.post("/api/nn/ruc")
async def api_nn_ruc(payload: dict):
    """Paso 2: reconoce el RUC (padron -> API) y devuelve el camino. Con UBIGEO
    conocido adjunta el adelanto EN VIVO del distrito."""
    ruc = (payload.get("ruc") or "").strip()
    if not ruc_mod.ruc_formato_valido(ruc):
        return JSONResponse({"ok": False, "error": "El RUC debe tener 11 dígitos."},
                            status_code=422)
    info = await _clasificar_ruc(ruc)
    resp = {"ok": True, "ruc": ruc, "camino": info["camino"],
            "es_contador": info["es_contador"], "verificado": info["verificado"],
            "necesita_distrito": info["necesita_distrito"],
            "razon_social": info.get("razon_social"),
            "distrito": info.get("distrito")}
    if info.get("ubigeo"):
        adelanto = await db.nn_adelanto(info["ubigeo"])
        for m in adelanto:  # etiqueta legible del mes ("julio 2026")
            y, mm = m["mes"].split("-")
            m["mes_label"] = f"{MESES_ES[int(mm)]} {y}"
        resp["adelanto"] = adelanto
    return JSONResponse(resp)


@app.post("/api/nn/suscribir")
async def api_nn_suscribir(payload: dict, request: Request):
    # Honeypot: campo oculto; si viene lleno, se descarta en silencio.
    if (payload.get("empresa_web") or "").strip():
        return JSONResponse({"ok": True})
    ruc = (payload.get("ruc") or "").strip()
    correo = (payload.get("correo") or "").strip()
    whatsapp = (payload.get("whatsapp") or "").strip()
    if not ruc_mod.ruc_formato_valido(ruc):
        return JSONResponse({"ok": False, "error": "RUC inválido."}, status_code=422)
    if not _CORREO_RE.match(correo):
        return JSONResponse({"ok": False, "error": "Indica un correo válido."}, status_code=422)
    if not db.norm_whatsapp(whatsapp):
        return JSONResponse({"ok": False, "error": "El WhatsApp debe tener 9 dígitos y empezar en 9."},
                            status_code=422)
    if not payload.get("consentimiento"):
        return JSONResponse({"ok": False, "error": "Debes aceptar recibir la información para continuar."},
                            status_code=422)
    # Identidad SIEMPRE derivada de fuentes oficiales (padron/API), no del usuario.
    # Se INSERTA SIEMPRE el RUC, sea o no contador (documenta faltantes del padron).
    info = await _clasificar_ruc(ruc)
    distrito = info.get("distrito")
    # Unica excepcion: fallback por API no verificable -> el usuario confirma su
    # distrito (no tenemos el dato oficial).
    if info.get("necesita_distrito") and not distrito:
        distrito = (payload.get("distrito") or "").strip()[:120] or None
    data = {
        "ruc": ruc, "razon_social": info.get("razon_social"),
        "es_contador": info["es_contador"], "distrito": distrito,
        "correo": correo, "whatsapp": whatsapp,
        "origen": (payload.get("origen") or "nuevos-negocios")[:60],
        "consentimiento": True,
        "ip": _client_ip(request), "user_agent": request.headers.get("user-agent", ""),
    }
    try:
        res = await db.nn_crear_suscriptor(data)
    except Exception:
        log.exception("nn_crear_suscriptor fallo")
        return JSONResponse({"ok": False, "error": "No pudimos registrarte. Intenta más tarde."},
                            status_code=500)
    if not res.get("ok"):
        motivo = res.get("motivo")
        if motivo == "dup_ruc":
            return JSONResponse({"ok": False, "error": "Este RUC ya está registrado."}, status_code=409)
        if motivo == "dup_correo":
            return JSONResponse({"ok": False, "error": "Este correo ya está registrado."}, status_code=409)
        if motivo == "limite":
            return JSONResponse({"ok": False, "error": "Recibimos varios registros desde tu red. "
                                 "Intenta más tarde."}, status_code=429)
        return JSONResponse({"ok": False, "error": "No pudimos registrarte."}, status_code=400)
    return JSONResponse({"ok": True, "mensaje": "Te enviaremos el link y tendrás acceso a la "
                         "información que buscas."})


@app.get("/nuevos-negocios/baja", response_class=HTMLResponse)
async def nuevos_negocios_baja(request: Request, token: str = ""):
    ok = await db.nn_baja(token)
    return templates.TemplateResponse(request, "nn_baja.html",
                                      {"request": request, "ok": ok})


@app.get("/reportes/{dep}", response_class=HTMLResponse)
async def reporte_departamento(request: Request, dep: str):
    r = est.cargar_reporte(dep)
    if not r or r.get("nivel") != "departamento":
        return HTMLResponse("Departamento no encontrado.", status_code=404)
    return templates.TemplateResponse(request, "reportes/publico.html", _ctx_publico(request, r))


@app.get("/reportes/{dep}/{prov}", response_class=HTMLResponse)
async def reporte_provincia(request: Request, dep: str, prov: str):
    r = est.cargar_reporte(f"{dep}/{prov}")
    if not r or r.get("nivel") != "provincia":
        return HTMLResponse("Provincia no encontrada.", status_code=404)
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
