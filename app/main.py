"""
Club de Contadores — WebApp (PWA) de pre-inscripcion.
contadores.perusistemas.pro

Stack: FastAPI + PostgreSQL (asyncpg) + Jinja2 + Vanilla JS. Deploy Railway.
"""
from __future__ import annotations

import os
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .ruc import validar_ruc

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Prueba social configurable (irá subiendo). NO poner 1600.
ESTUDIOS_TOTAL = os.getenv("ESTUDIOS_TOTAL", "800")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VIDEO_URL = os.getenv("VIDEO_URL", "").strip()  # embed opcional (YouTube/otro)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Club de Contadores", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
@app.post("/api/validar-ruc")
async def api_validar_ruc(payload: dict):
    ruc = str(payload.get("ruc", "")).strip()
    res = await validar_ruc(ruc)
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
        return JSONResponse({"ok": False}, status_code=200)  # nunca bloquear la UI
    return {"ok": True, **res}


@app.get("/api/negocios")
async def api_negocios(distrito: str = "", ubigeo: str = "", mes: str = ""):
    # `mes` ('YYYY-MM') usa el MISMO filtro que /api/conteo -> el numero cuadra.
    negocios = await db.lista_negocios(ubigeo.strip(), distrito.strip(), mes.strip())
    return {"negocios": negocios, "total": len(negocios), "mes": mes}


@app.post("/api/push/subscribe")
async def api_push_subscribe(payload: dict):
    sub = payload.get("subscription") or {}
    try:
        await db.guardar_push(sub, (payload.get("ruc") or None), (payload.get("distrito") or None))
    except Exception:
        return JSONResponse({"ok": False}, status_code=500)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True, "demo": db.demo_mode()}


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
