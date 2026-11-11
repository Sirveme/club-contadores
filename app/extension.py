"""Puente entre la extension Ficha RUC y el Club: /extension/vincular?c=K7QM-4XPA

La extension, al terminar la prueba, ofrece "Regístrate aquí": abre /registro con
sig=/extension/vincular?c=<codigo>. Tras registrarse (o ingresar), el socio cae aqui y su cuenta
queda ANOTADA como solicitud de esa instalacion. NO activa nada: la activacion es manual (panel
/panel/llaves o `api_llave.py activar`) hasta que exista el registro automatico por el bot.

- Solo contadores: si la persona es solo empresario, se le dice que el Club de Empresarios esta
  por lanzarse (ya tenemos su dato) y no se anota la solicitud.
- No revela si el codigo existe ni a quien pertenece.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import api_v1 as A, club, db, identidad
from . import verificador as V

router = APIRouter()
NO_CACHE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}


@router.get("/extension/vincular", response_class=HTMLResponse)
async def vincular(request: Request, c: str = ""):
    codigo = A.codigo_normal(c)
    p = await identidad.persona_actual(request)
    if not p:
        sig = "/extension/vincular" + (f"?c={codigo}" if codigo else "")
        return RedirectResponse(f"/registro?para=contador&sig={quote(sig, safe='')}", status_code=303)
    perfiles = await identidad.perfiles_de(p["id"])
    caso = "sin_codigo"
    if "contador" not in perfiles:
        caso = "empresario"
    elif codigo and await db._pool.fetchval(                     # la prueba existe (alter_v16 aplicado)
            "SELECT 1 FROM information_schema.columns WHERE table_schema = $1 AND table_name = 'api_llaves' AND column_name = 'codigo'",
            V.ESQUEMA):
        await db._pool.execute(
            f"""UPDATE {V.ESQUEMA}.api_llaves SET solicitud_persona = $2, solicitud_en = now()
                WHERE codigo = $1 AND plan_codigo = 'prueba' AND estado = 'activa'
                  AND (solicitud_persona IS NULL OR solicitud_persona = $2)""", codigo, p["id"])
        caso = "recibida"                                  # igual exista o no: no se revela
    return club.templates.TemplateResponse(request, "club/extension_vincular.html", {
        "s": await club.socio_actual(request), "inicio": club.inicio(request), "caso": caso, "codigo": codigo}, headers=NO_CACHE)
