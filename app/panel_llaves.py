"""Panel de llaves de la API (/panel/llaves): crear, revocar, suspender, ajustar y ver consumo.

Lo protege el filtro de /panel/* (solo ADMIN_DNI con sesion por DNI). Ademas, toda accion
que cambia algo es un POST que solo se acepta desde el propio sitio (Origin/Referer del mismo
host): otra pagina no puede disparar acciones con la sesion del admin.

- La llave completa se muestra UNA vez, al crearla; en la base solo queda su huella.
- Revocar es definitivo; suspender se puede revertir (reactivar).
- Listar no crea nada: las tablas de la API se crean recien al emitir la primera llave.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import api_v1 as A, club, db, identidad
from . import padron as P
from . import verificador as V

router = APIRouter()
_PREFIJO = re.compile(r"^psp_live_[a-z0-9]{8}$")
NO_CACHE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}
ALCANCES_PANEL = [("ssco_representantes", "Representantes legales del SSCO (solo planes pagados)")]


def _t(tabla: str) -> str:
    return f"{V.ESQUEMA}.{tabla}"


async def _hay_tablas() -> bool:
    return bool(await db._pool.fetchval("SELECT to_regclass($1) IS NOT NULL", _t("api_llaves")))


def _mismo_sitio(request: Request) -> bool:
    """El POST viene de una pagina de este mismo host (defensa contra envios desde otra web)."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    origen = request.headers.get("origin") or request.headers.get("referer") or ""
    return bool(origen) and (urlparse(origen).hostname or "").lower() == host


async def _admin_dni(request: Request) -> str:
    p = await identidad.persona_actual(request)
    return p["dni"] if p else "?"


async def _listar() -> list[dict]:
    if not await _hay_tablas():
        return []
    mes = A._MES
    rows = await db._pool.fetch(f"""
        SELECT l.*, coalesce(m.unidades, 0) AS usada_mes,
               coalesce(u.llamadas, 0) AS llamadas_30d, coalesce(u.errores, 0) AS errores_30d
        FROM {_t('api_llaves')} l
        LEFT JOIN {_t('api_uso_mes')} m ON m.llave_id = l.id AND m.recurso = 'ruc' AND m.mes = {mes}
        LEFT JOIN (SELECT llave_id, count(*) AS llamadas, count(*) FILTER (WHERE http >= 400) AS errores
                   FROM {_t('api_uso')} WHERE creado_en > now() - interval '30 days' GROUP BY llave_id) u ON u.llave_id = l.id
        ORDER BY (l.estado = 'activa') DESC, l.creada_en DESC""")
    return [dict(r) for r in rows]


async def _pagina(request: Request, **extra):
    llaves = await _listar()
    return club.templates.TemplateResponse(request, "club/panel_llaves.html", {
        "s": await club.socio_actual(request), "inicio": club.inicio(request), "llaves": llaves,
        "esquema": V.ESQUEMA, "api_abierta": A.ABIERTA, "cuota_gratis": A.CUOTA_GRATIS_MES, "rpm_defecto": A.RPM_DEFECTO,
        "alcances_panel": ALCANCES_PANEL, **extra}, headers=NO_CACHE)


@router.get("/panel/llaves", response_class=HTMLResponse)
async def panel(request: Request, ok: str = ""):
    return await _pagina(request, aviso=ok[:120])


async def _form(request: Request) -> dict:
    f = await request.form()
    return {k: (f.getlist(k) if k == "alcances" else str(f.get(k) or "").strip()) for k in f.keys()}


def _entero(v: str, minimo: int, maximo: int) -> int | None:
    return int(v) if v.isdigit() and minimo <= int(v) <= maximo else None


@router.post("/panel/llaves/crear", response_class=HTMLResponse)
async def crear(request: Request):
    if not _mismo_sitio(request):
        return HTMLResponse("Acción no permitida.", status_code=403, headers=NO_CACHE)
    f = await _form(request)
    errores = []
    nombre = f.get("nombre", "")[:80]
    plan = f.get("plan") if f.get("plan") in ("gratis", "pago") else None
    cuota = _entero(f.get("cuota", ""), 0, 10_000_000) if f.get("cuota") else (A.CUOTA_GRATIS_MES if plan == "gratis" else None)
    rpm = _entero(f.get("rpm", ""), 1, 6000) if f.get("rpm") else A.RPM_DEFECTO
    ruc = f.get("cliente_ruc", "") or None
    if not nombre:
        errores.append("Ponle un nombre a la llave (para reconocerla después).")
    if not plan:
        errores.append("Elige el plan.")
    if cuota is None:
        errores.append("La cuota mensual es un número entre 0 y 10 000 000 (obligatoria en planes pagados).")
    if rpm is None:
        errores.append("Las consultas por minuto van de 1 a 6000.")
    if ruc and not P.RUC_RE.match(ruc):
        errores.append("El RUC del cliente tiene 11 dígitos.")
    alcances = ["ruc"] + [a for a, _ in ALCANCES_PANEL if a in (f.get("alcances") or [])]
    if plan == "gratis" and "ssco_representantes" in alcances:
        errores.append("El plan gratis no incluye los representantes legales del SSCO.")
    if errores:
        return await _pagina(request, errores=errores, previo=f)
    await A.crear_tablas(db._pool, V.ESQUEMA)
    llave, prefijo, huella = A.nueva_llave()
    await db._pool.execute(
        f"INSERT INTO {_t('api_llaves')} (prefijo, huella, nombre, cliente_ruc, plan_codigo, cuota_mes, rpm, alcances, creada_por) "
        f"VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        prefijo, huella, nombre, ruc, plan, cuota, rpm, alcances, "panel:" + await _admin_dni(request))
    return await _pagina(request, nueva={"llave": llave, "prefijo": prefijo, "nombre": nombre})


_ACCIONES = {
    "revocar": ("estado = 'revocada', revocada_en = now()", "estado <> 'revocada'", "Llave revocada (definitivo)."),
    "suspender": ("estado = 'suspendida'", "estado = 'activa'", "Llave suspendida."),
    "reactivar": ("estado = 'activa'", "estado = 'suspendida'", "Llave reactivada."),
}


@router.post("/panel/llaves/{prefijo}/{accion}")
async def accion(prefijo: str, accion: str, request: Request):
    if not _mismo_sitio(request):
        return HTMLResponse("Acción no permitida.", status_code=403, headers=NO_CACHE)
    if not _PREFIJO.match(prefijo) or not await _hay_tablas():
        return HTMLResponse("No encontramos esa llave.", status_code=404, headers=NO_CACHE)
    if accion in _ACCIONES:
        cambio, condicion, texto = _ACCIONES[accion]
        r = await db._pool.execute(f"UPDATE {_t('api_llaves')} SET {cambio} WHERE prefijo = $1 AND {condicion}", prefijo)
        aviso = texto if r.endswith(" 1") else "No se cambió: la llave no estaba en un estado que lo permita."
    elif accion == "ajustar":
        f = await _form(request)
        cuota, rpm = _entero(f.get("cuota", ""), 0, 10_000_000), _entero(f.get("rpm", ""), 1, 6000)
        if cuota is None or rpm is None:
            return RedirectResponse(f"/panel/llaves/{prefijo}?ok=" + "Cuota (0 a 10 000 000) y consultas por minuto (1 a 6000) deben ser números.", 303)
        plan = await db._pool.fetchval(f"SELECT plan_codigo FROM {_t('api_llaves')} WHERE prefijo = $1", prefijo)
        alcances = ["ruc"] + [a for a, _ in ALCANCES_PANEL if a in (f.get("alcances") or []) and plan != "gratis"]
        await db._pool.execute(f"UPDATE {_t('api_llaves')} SET cuota_mes = $2, rpm = $3, alcances = $4 WHERE prefijo = $1 AND estado <> 'revocada'",
                               prefijo, cuota, rpm, alcances)
        return RedirectResponse(f"/panel/llaves/{prefijo}?ok=Cambios guardados.", 303)
    else:
        return HTMLResponse("Acción desconocida.", status_code=404, headers=NO_CACHE)
    return RedirectResponse(f"/panel/llaves/{prefijo}?ok={aviso}", 303)


@router.get("/panel/llaves/{prefijo}", response_class=HTMLResponse)
async def detalle(prefijo: str, request: Request, ok: str = ""):
    if not _PREFIJO.match(prefijo) or not await _hay_tablas():
        return HTMLResponse("No encontramos esa llave.", status_code=404, headers=NO_CACHE)
    row = await db._pool.fetchrow(f"SELECT * FROM {_t('api_llaves')} WHERE prefijo = $1", prefijo)
    if not row:
        return HTMLResponse("No encontramos esa llave.", status_code=404, headers=NO_CACHE)
    llave = dict(row)
    cuota = await A.estado_cuota(llave)
    dias = [dict(r) for r in await db._pool.fetch(f"""
        SELECT (creado_en AT TIME ZONE 'America/Lima')::date AS dia, count(*) AS llamadas, sum(unidades) AS unidades,
               count(*) FILTER (WHERE http = 404) AS no_encontrados, count(*) FILTER (WHERE http = 422) AS invalidos,
               count(*) FILTER (WHERE http = 429) AS rechazados
        FROM {_t('api_uso')} WHERE llave_id = $1 AND creado_en > now() - interval '30 days'
        GROUP BY 1 ORDER BY 1 DESC""", llave["id"])]
    meses = [dict(r) for r in await db._pool.fetch(
        f"SELECT mes, unidades FROM {_t('api_uso_mes')} WHERE llave_id = $1 AND recurso = 'ruc' ORDER BY mes DESC LIMIT 12", llave["id"])]
    return club.templates.TemplateResponse(request, "club/panel_llave.html", {
        "s": await club.socio_actual(request), "inicio": club.inicio(request), "k": llave, "cuota": cuota, "dias": dias,
        "meses": meses, "aviso": ok[:120], "alcances_panel": ALCANCES_PANEL, "esquema": V.ESQUEMA}, headers=NO_CACHE)
