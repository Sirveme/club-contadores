"""Conversor SIRE (contadores.perusistemas.pro/sire). Fase 1: Compras, TXT -> Excel, MODO LOCAL.

La conversion ocurre en el navegador (app/static/js/sire/): el archivo y sus montos nunca llegan a
este servidor. Esta pagina solo sirve la pantalla, con una politica de seguridad (CSP) que impide al
navegador conectarse a otro dominio. Estructura y reglas: app/static/sire/sire-spec.json.

  SIRE_ABIERTO=1   sin esto, "muy pronto" (el admin la ve igual, para probarla)

Capacidades: "convertir" es gratis y sin cuenta. "riesgo" (cruce del proveedor, requiere cuenta) y
"servidor" (modo servidor) quedan listas para gatearse por suscripcion; en esta fase estan apagadas.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import club

router = APIRouter()
ABIERTO = os.getenv("SIRE_ABIERTO", "0").strip() == "1"
# El navegador solo puede conectarse a este mismo sitio: ni el archivo ni nada sale a terceros (las
# fuentes tambien se sirven desde aqui: app/static/fonts/plex/).
CSP = ("default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def capacidades(s: dict | None) -> dict:
    """Que puede usar esta persona. Fase 1: solo convertir. Cuando exista la suscripcion del grupo de
    herramientas, aqui se decide (sin tocar la pantalla)."""
    return {"convertir": True, "riesgo": False, "servidor": False, "con_cuenta": bool(s)}


def tarjeta_tablero() -> dict | None:
    """Enciende la tarjeta "SIRE" del tablero (nivel gratis) cuando el conversor esta abierto."""
    if not ABIERTO:
        return None
    return {"sire": {"estado": "activa", "nivel": "gratis", "url": "/sire", "nombre": "Conversor SIRE",
                     "sub": "La propuesta de compras, en un Excel legible", "cta": "Convertir ahora",
                     "ben": "Sube el ZIP o el TXT de la propuesta y te devolvemos un Excel con columnas con nombre, errores marcados y totales.",
                     "frases": ["Se procesa en tu equipo", "Corrige punto y coma", "Totales por tipo", "Cuadra con el resumen"]}}


@router.get("/sire", response_class=HTMLResponse)
async def pagina(request: Request):
    host = club._host(request)
    if host == club.CLUB_HOST:                       # su casa es contadores.perusistemas.pro
        q = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"https://{club.CONTADORES_HOST}/sire{q}", status_code=301)
    s = await club.socio_actual(request)
    from . import identidad
    if not ABIERTO and not await identidad.es_admin(request):
        return club.templates.TemplateResponse(request, "club/pronto.html", {
            "s": s, "inicio": club.inicio(request), "que": "El Conversor SIRE", "sig": "", "psp_whatsapp": club.PSP_WHATSAPP})
    resp = club.templates.TemplateResponse(request, "club/sire.html", {
        "s": s, "inicio": club.inicio(request), "capacidades": capacidades(s)})
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-cache"
    return resp
