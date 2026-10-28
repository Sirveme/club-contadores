"""Landing de VENTA del Conversor SIRE (contadores.perusistemas.pro/sire-club). La herramienta sigue
en /sire; esta es la pagina que venden los videos y lleva a la suscripcion del Club (Pro / Premium).

Todo lo que Duilio cambia seguido vive en app/contenido/sire-club.json (testimonios, FAQ, planes,
numeros, destino de los botones, la pieza de demo): se agrega sin tocar codigo. Se relee al cambiar
el archivo; si queda mal escrito, se sigue usando la ultima version buena.

Numeros (marquesina y barra de cupos): se muestra el MAYOR entre el valor del archivo (la lista que
ya existe fuera del sistema) y el conteo real de contadores inscritos en el Club. No se suman, para
no contar dos veces a quien estaba en la lista y luego se inscribio. Nada crece ni baja solo: la
barra solo avanza cuando hay inscritos reales.

Botones: todos pasan por destino_cta(). Hoy abren WhatsApp con el mensaje del plan; para PagoOK basta
cambiar cta.destino a "pago" y poner cta.pago_url en el archivo.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import club

router = APIRouter()
RUTA = "/sire-club"
CONTENIDO = Path(__file__).resolve().parent / "contenido" / "sire-club.json"
BASE = {"numeros": {"lista": 0, "tope": 300, "ciudades": []}, "cta": {"destino": "whatsapp", "mensajes": {}},
        "demo": {}, "calculadora": {"minutos_con_herramienta": 5}, "caja": [], "planes": [], "testimonios": [], "faq": []}
_cache: dict = {"mtime": None, "datos": BASE}
_conteo: dict = {"en": 0.0, "datos": None}
CONTEO_SEG = 300


def contenido() -> dict:
    """El JSON editable; se relee solo si cambio. Mal escrito -> la ultima version buena."""
    try:
        mtime = CONTENIDO.stat().st_mtime
        if mtime != _cache["mtime"]:
            datos = json.loads(CONTENIDO.read_text(encoding="utf-8"))
            _cache.update(mtime=mtime, datos={**BASE, **datos})
    except (OSError, ValueError) as e:
        club.log.error("sire-club: no se pudo leer %s (%s); sigue la ultima version buena", CONTENIDO.name, e)
    return _cache["datos"]


def destino_cta(plan: str, c: dict | None = None) -> str:
    """La UNICA URL de destino de los botones (plan: club, pro o premium)."""
    cta = (c or contenido())["cta"]
    if cta.get("destino") == "pago" and cta.get("pago_url"):
        return cta["pago_url"].replace("{plan}", quote(plan))
    msg = (cta.get("mensajes") or {}).get(plan) or (cta.get("mensajes") or {}).get("club") or ""
    return f"https://wa.me/51{club.PSP_WHATSAPP}" + (f"?text={quote(msg)}" if msg else "")


async def _inscritos(prefijos: list[str]) -> dict | None:
    """Contadores inscritos de verdad en el Club (total y por prefijo de ubigeo). Solo conteos."""
    if time.monotonic() - _conteo["en"] < CONTEO_SEG and _conteo["datos"] is not None:
        return _conteo["datos"]
    sql = """
      SELECT ubigeo FROM club_socios WHERE rol = 'contador' AND baja_en IS NULL AND persona_id IS NULL
      UNION ALL
      SELECT a.ubigeo FROM accesos a JOIN personas p ON p.id = a.persona_id
      WHERE a.perfil = 'contador' AND a.revocado_en IS NULL AND p.estado <> 'baja'"""
    try:
        ubigeos = [r["ubigeo"] or "" for r in await club._pool().fetch(sql)]
        datos = {"total": len(ubigeos), "por": {p: sum(u.startswith(p) for u in ubigeos) for p in prefijos}}
    except Exception as e:                       # sin base: se muestran los valores del archivo
        club.log.warning("sire-club: sin conteo real (%s)", e)
        return None
    _conteo.update(en=time.monotonic(), datos=datos)
    return datos


async def numeros(c: dict) -> dict:
    n = c["numeros"]
    ciudades = [x for x in n.get("ciudades") or [] if x.get("nombre")]
    real = await _inscritos([x["ubigeo"] for x in ciudades if x.get("ubigeo")])
    total = max(int(n.get("lista") or 0), (real or {}).get("total") or 0)
    tope = max(1, int(n.get("tope") or 300))
    quedan = max(0, tope - total)
    return {"total": total, "tope": tope, "quedan": quedan, "lleno": quedan == 0,
            "pct": min(100, max(3, round(100 * total / tope))),
            "ciudades": [{"nombre": x["nombre"],
                          "n": max(int(x.get("n") or 0), ((real or {}).get("por") or {}).get(x.get("ubigeo"), 0))}
                         for x in ciudades]}


def _csp(demo: dict) -> str:
    marco = " frame-src https://www.youtube-nocookie.com;" if demo.get("tipo") == "youtube" else " frame-src 'none';"
    return ("default-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self'; "
            "style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self';" + marco +
            " object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


@router.get(RUTA, response_class=HTMLResponse)
async def pagina(request: Request):
    if club._host(request) == club.CLUB_HOST:        # su casa es contadores.perusistemas.pro
        return RedirectResponse(f"https://{club.CONTADORES_HOST}{RUTA}", status_code=301)
    c = contenido()
    resp = club.templates.TemplateResponse(request, "club/sire_venta.html", {
        "c": c, "num": await numeros(c), "cta": lambda plan: destino_cta(plan, c),
        "anpd_url": club.ANPD_REGISTRO_URL, "foto": club.FOTO_GARANTE})
    resp.headers["Content-Security-Policy"] = _csp(c.get("demo") or {})
    resp.headers["Cache-Control"] = "no-cache"
    return resp
