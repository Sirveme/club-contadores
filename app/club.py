"""
Club de Contadores — puerta unica (/club), registro, tablero de herramientas,
Directorio de Contadores (esqueleto) y Calculadora de IGV.

Reglas de la puerta (rol elegido + RUC):
  CONTADOR   en padron                 -> registro, reconocido (verificacion 'padron')
             no en padron, API 6920    -> registro, reconocido ('api')
             no en padron, RUC 20      -> orientar a empresario (puede continuar igual)
             no en padron, natural     -> registro 'por_confirmar' (marca informativa,
                                          revisar=true; NO restringe nada)
  EMPRESARIO en padron / API 6920      -> orientar al Club de Contadores (puede continuar)
             resto                     -> registro empresario ('no_aplica')
  "Escribenos" SOLO si el RUC es invalido o SUNAT dice que no existe. Si la API de
  SUNAT no responde (o no hay token) nunca se bloquea.

Identidad (nombre, distrito) SIEMPRE de fuentes oficiales (padron/API), nunca del
usuario. contadores_padron solo se LEE. El Directorio lista solo club_socios con
opt-in de directorio, nunca el padron.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from pathlib import Path

import asyncpg
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import db
from . import ruc as ruc_mod
from .club_herramientas import GANA, armar_tablero

import estadisticas as est  # raiz del proyecto (main.py la agrega a sys.path)

log = logging.getLogger("uvicorn.error")
router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent
SQL_ESQUEMA = BASE_DIR.parent / "sql" / "alter_v10_club.sql"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

COOKIE = "club_t"
COOKIE_DIAS = 180
CONSENT_VER = "club-2026-10-07"
DIRECTORIO_VER = "directorio-2026-10-07"
LIMITE_IP_HORA = 5
_CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MINUS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "EL", "EN"}
MESES_CORTOS = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "setiembre", "octubre", "noviembre", "diciembre"]

# Mismas variables (y defaults) que usa la landing de Nuevos Negocios en main.py.
ANPD_REGISTRO_URL = os.getenv("ANPD_REGISTRO_URL", "#registro-anpd").strip()
PSP_WHATSAPP = "".join(c for c in os.getenv("PSP_WHATSAPP", "938246208") if c.isdigit())
CLUB_HOST = os.getenv("CLUB_HOST", "club.perusistemas.pro").strip().lower()
CONTADORES_HOST = os.getenv("CONTADORES_HOST", "contadores.perusistemas.pro").strip().lower()
DOMINIO_RAIZ = "perusistemas.pro"
MSG_ESCRIBENOS = "No encontramos ese RUC en SUNAT. Revísalo o escríbenos y te ayudamos."


_SIGLAS = {"SAC", "SA", "SAA", "SRL", "EIRL", "SCRL", "SAS"}


def titulo(s: str | None) -> str:
    """Title Case peruano; siglas societarias en mayuscula ('S.A.C.', 'EIRL')."""
    out = []
    for i, w in enumerate((s or "").split()):
        if "." in w.strip(".") or w.upper().replace(".", "") in _SIGLAS:
            out.append(w.upper())
        elif i and w.upper() in _MINUS:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out)


templates.env.filters["titulo"] = titulo
templates.env.filters["miles"] = lambda n: f"{int(n):,}" if n is not None else ""


def nombre_saludo(ruc: str, razon: str | None, nombre_comercial: str | None) -> str:
    """Persona natural: SUNAT escribe 'APELLIDO1 APELLIDO2 NOMBRES' -> desde la 3a
    palabra ('Jorge Luis'). Juridica: nombre comercial o razon social."""
    if not ruc.startswith("20"):
        w = (razon or "").split()
        return titulo(" ".join(w[2:] if len(w) > 2 else w)) or "colega"
    return titulo(nombre_comercial or razon) or "colega"


def _pool() -> asyncpg.Pool:
    if db._pool is None:
        raise RuntimeError("El Club necesita base de datos (DATABASE_URL).")
    return db._pool


async def asegurar_esquema() -> None:
    if db._pool is not None:
        await db._pool.execute(SQL_ESQUEMA.read_text(encoding="utf-8"))


def _client_ip(request: Request) -> str | None:
    import ipaddress
    xff = request.headers.get("x-forwarded-for", "")
    cand = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    try:
        return str(ipaddress.ip_address(cand)) if cand else None
    except ValueError:
        return None


# --- Fuentes oficiales ------------------------------------------------------
async def padron(ruc: str) -> dict | None:
    row = await _pool().fetchrow(
        "SELECT ruc, razon_social, nombre_comercial, tipo, ciiu_tipo, ubigeo, distrito, "
        "provincia, departamento FROM contadores_padron WHERE ruc = $1", ruc)
    return dict(row) if row else None


async def consultar_api(ruc: str) -> dict:
    """SUNAT via apis.net.pe. estado: contador | no_contador | general | no_existe | error.
    'error' (sin token, caida, timeout) nunca bloquea al usuario."""
    if not ruc_mod.APIS_NET_PE_TOKEN:
        return {"estado": "error"}
    try:
        d = await ruc_mod._fetch_ruc_api(ruc)
    except RuntimeError as e:   # _fetch_ruc_api lanza RuntimeError("status N") en no-200
        return {"estado": "no_existe" if str(e) in ("status 404", "status 422") else "error"}
    except Exception as e:
        log.warning("club: RUC %s no verificable via API (%s)", ruc, type(e).__name__)
        return {"estado": "error"}
    razon = (d.get("razonSocial") or d.get("nombre") or "").strip()
    if not razon:
        return {"estado": "no_existe"}
    ciius = ruc_mod._extraer_ciiu(d)
    ubigeo = "".join(c for c in str(d.get("ubigeo") or "") if c.isdigit()) or None
    ubigeo = ubigeo.zfill(6)[-6:] if ubigeo else est.ubigeo_por_nombre(
        d.get("departamento"), d.get("provincia"), d.get("distrito"))
    info = {"razon_social": razon,
            "nombre_comercial": (d.get("nombreComercial") or "").strip() or None,
            "ubigeo": ubigeo, "distrito": est.nombre_distrito(ubigeo) or (d.get("distrito") or None)}
    if any(c.startswith(ruc_mod.CIIU_CONTADOR) for c in ciius):
        return {"estado": "contador", **info}
    return {"estado": "no_contador" if ciius else "general", **info}


async def clasificar(rol: str, ruc: str, continuar: bool = False) -> dict:
    """-> {accion: registro | orientar_empresario | orientar_contador | escribenos,
           verificacion, revisar, razon_social, nombre_comercial, ubigeo, distrito}"""
    if not ruc_mod.ruc_formato_valido(ruc):
        return {"accion": "escribenos", "motivo": "formato",
                "mensaje": "El RUC tiene 11 dígitos y empieza en 10, 15, 17 o 20."}
    p = await padron(ruc)
    if p:
        datos = {"razon_social": p["razon_social"], "nombre_comercial": p["nombre_comercial"],
                 "ubigeo": p["ubigeo"], "distrito": titulo(p["distrito"]) or None}
        if rol == "contador":
            return {"accion": "registro", "verificacion": "padron", "revisar": False, **datos}
        if not continuar:
            return {"accion": "orientar_contador", **datos}
        return {"accion": "registro", "verificacion": "no_aplica", "revisar": False, **datos}

    api = await consultar_api(ruc)
    if api["estado"] == "no_existe":
        return {"accion": "escribenos", "motivo": "no_existe", "mensaje": MSG_ESCRIBENOS}
    datos = {k: api.get(k) for k in ("razon_social", "nombre_comercial", "ubigeo")}
    datos["distrito"] = titulo(api.get("distrito")) or None
    if rol == "contador":
        if api["estado"] == "contador":
            return {"accion": "registro", "verificacion": "api", "revisar": False, **datos}
        if ruc.startswith("20") and not continuar:
            return {"accion": "orientar_empresario", **datos}
        return {"accion": "registro", "verificacion": "por_confirmar", "revisar": True, **datos}
    if api["estado"] == "contador" and not continuar:
        return {"accion": "orientar_contador", **datos}
    return {"accion": "registro", "verificacion": "no_aplica", "revisar": False, **datos}


# --- Socios -----------------------------------------------------------------
async def socio_por_token(token: str | None) -> dict | None:
    if not token or db._pool is None:
        return None
    row = await _pool().fetchrow(
        "SELECT s.*, su.token_baja AS nn_token FROM club_socios s "
        "LEFT JOIN suscriptores su ON su.id = s.suscriptor_id "
        "WHERE s.token = $1 AND s.baja_en IS NULL", token)
    return dict(row) if row else None


async def _slug_libre(base: str, ruc: str) -> str:
    s = est.slug(base)[:60].strip("-") or ruc
    if await _pool().fetchval("SELECT 1 FROM club_socios WHERE slug = $1", s):
        s = f"{s}-{ruc[-4:]}"
    return s


async def _enlazar_suscriptor(ruc: str, info: dict, correo: str, whatsapp: str | None,
                              ip: str | None, ua: str) -> int | None:
    """Reusa Nuevos Negocios: busca (o crea) la fila de suscriptores del RUC para que
    la tarjeta abra su /mi-distrito actual. Si no se puede (correo usado por otro
    RUC, limite por IP) el socio queda sin enlace; no bloquea el registro."""
    sid = await _pool().fetchval("SELECT id FROM suscriptores WHERE ruc = $1", ruc)
    if sid or not info.get("ubigeo"):
        return sid
    res = await db.nn_crear_suscriptor({
        "ruc": ruc, "razon_social": info.get("razon_social"),
        "nombre_comercial": info.get("nombre_comercial"), "es_contador": True,
        "distrito": info.get("distrito"), "ubigeo": info.get("ubigeo"),
        "correo": correo, "whatsapp": whatsapp, "origen": "club",
        "consentimiento": True, "ip": ip or "", "user_agent": ua})
    if not res.get("ok"):
        log.info("club: RUC %s sin enlace a suscriptores (%s)", ruc, res.get("motivo"))
        return None
    return await _pool().fetchval("SELECT id FROM suscriptores WHERE ruc = $1", ruc)


def _host(request: Request) -> str:
    return (request.headers.get("host") or "").split(":")[0].lower()


def inicio(request: Request) -> str:
    """Home del Club: '/' en club.perusistemas.pro; '/club' en cualquier otro host
    (contadores., Railway, localhost), donde '/' es la landing de Nuevos Negocios."""
    return "/" if _host(request) == CLUB_HOST else "/club"


def _ruta_segura(sig: str) -> str:
    return sig if sig.startswith("/") and not sig.startswith("//") else ""


def _destino(request: Request, rol: str, siguiente: str = "") -> str:
    """A donde va el socio al entrar: la pagina que pidio (ruta interna segura) o su inicio."""
    return _ruta_segura(siguiente) or (inicio(request) if rol == "contador" else "/empresario")


def _dominio_cookie(request: Request) -> str | None:
    """En *.perusistemas.pro la sesion vale para todos los subdominios (club. y
    contadores.): quien entra por uno sigue dentro en el otro."""
    return f".{DOMINIO_RAIZ}" if _host(request).endswith(f".{DOMINIO_RAIZ}") else None


def _con_cookie(resp, request: Request, token: str):
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, token, max_age=COOKIE_DIAS * 86400, httponly=True,
                    samesite="lax", secure=https, domain=_dominio_cookie(request))
    return resp


# --- Rutas y dominios ---------------------------------------------------------
# Rutas del Club SIN repetir "club": / (tablero) · /entrar · /igv · /directorio[/ubigeo]
#   · /c/{slug} · /perfil · /empresario · /salir.  Internamente el tablero vive en
#   /club; en club.perusistemas.pro se sirve en "/".
# URLs viejas (/club/tablero, /club/igv, /club/directorio, ...) -> 301 a las nuevas.
RUTAS_CLUB = ("/entrar", "/igv", "/directorio", "/c", "/perfil", "/empresario", "/salir")


def ruta_nueva(path: str, home: str) -> str | None:
    """URL vieja del Club -> nueva (None si no es una URL vieja)."""
    if path in ("/club/", "/club/tablero"):
        return home
    if path.startswith("/club/"):
        return path[len("/club"):]               # /club/igv -> /igv
    return None


def es_ruta_club(path: str) -> bool:
    return path == "/club" or path.startswith("/club/") or any(path == r or path.startswith(r + "/") for r in RUTAS_CLUB)


async def enrutar_por_dominio(request: Request, call_next):
    """club.perusistemas.pro/ -> tablero en la misma URL; URLs viejas -> 301 a las nuevas;
    contadores.perusistemas.pro/club* y rutas del Club -> 301 a club.perusistemas.pro.
    contadores.perusistemas.pro/ (Nuevos Negocios), /club-legacy, /reportes y APIs: sin cambios."""
    host, path = _host(request), request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    lectura = request.method in ("GET", "HEAD")
    if host == CLUB_HOST:
        if lectura:
            nueva = "/" if path == "/club" else ruta_nueva(path, "/")
            if nueva is not None:
                return RedirectResponse(nueva + query, status_code=301)
        if path == "/":
            request.scope["path"] = "/club"
    elif host == CONTADORES_HOST:
        if lectura and es_ruta_club(path):
            nueva = "/" if path == "/club" else (ruta_nueva(path, "/") or path)
            return RedirectResponse(f"https://{CLUB_HOST}{nueva}{query}", status_code=301)
    elif lectura:                                  # localhost / Railway
        nueva = ruta_nueva(path, "/club")
        if nueva is not None:
            return RedirectResponse(nueva + query, status_code=301)
    return await call_next(request)


# --- API: puerta y registro ---------------------------------------------------
def _publico(r: dict, rol: str, ruc: str) -> dict:
    out = {"ok": True, "accion": r["accion"], "rol": rol, "ruc": ruc}
    if r["accion"] == "escribenos":
        out["mensaje"] = r["mensaje"]
        return out
    out.update({"verificacion": r.get("verificacion"), "distrito": r.get("distrito"),
                "razon_social": titulo(r.get("razon_social")) or None,
                "nombre": nombre_saludo(ruc, r.get("razon_social"), r.get("nombre_comercial"))
                if r.get("razon_social") else None})
    return out


@router.post("/api/club/ruc")
async def api_club_ruc(payload: dict):
    rol = payload.get("rol")
    ruc = "".join(c for c in str(payload.get("ruc") or "") if c.isdigit())
    if rol not in ("contador", "empresario"):
        return JSONResponse({"ok": False, "error": "Elige si eres contador o empresario."}, status_code=422)
    if ruc_mod.ruc_formato_valido(ruc) and await _pool().fetchval(
            "SELECT 1 FROM club_socios WHERE ruc = $1 AND baja_en IS NULL", ruc):
        return JSONResponse({"ok": True, "accion": "ya_registrado", "ruc": ruc, "rol": rol})
    r = await clasificar(rol, ruc, bool(payload.get("continuar")))
    return JSONResponse(_publico(r, rol, ruc))


@router.post("/api/club/registro")
async def api_club_registro(payload: dict, request: Request):
    if (payload.get("empresa_web") or "").strip():          # honeypot
        return JSONResponse({"ok": True})
    rol = payload.get("rol")
    ruc = "".join(c for c in str(payload.get("ruc") or "") if c.isdigit())
    correo = (payload.get("correo") or "").strip().lower()
    wa_raw = (payload.get("whatsapp") or "").strip()
    whatsapp = db.norm_whatsapp(wa_raw)
    if rol not in ("contador", "empresario"):
        return JSONResponse({"ok": False, "error": "Elige si eres contador o empresario."}, status_code=422)
    if not _CORREO_RE.match(correo):
        return JSONResponse({"ok": False, "error": "Indica un correo válido."}, status_code=422)
    if wa_raw and not whatsapp:
        return JSONResponse({"ok": False, "error": "El WhatsApp tiene 9 dígitos y empieza en 9."}, status_code=422)
    if not payload.get("consentimiento"):
        return JSONResponse({"ok": False, "error": "Para entrar al Club necesitamos tu autorización."},
                            status_code=422)
    r = await clasificar(rol, ruc, bool(payload.get("continuar")))
    if r["accion"] != "registro":
        return JSONResponse({"ok": False, **_publico(r, rol, ruc)}, status_code=409)

    ip, ua = _client_ip(request), (request.headers.get("user-agent") or "")[:400]
    if ip and await _pool().fetchval(
            "SELECT count(*) FROM club_socios WHERE ip = $1::inet AND created_at > now() - interval '1 hour'",
            ip) >= LIMITE_IP_HORA:
        return JSONResponse({"ok": False, "error": "Recibimos varios registros desde tu red. Intenta más tarde."},
                            status_code=429)
    optin = rol == "contador" and bool(payload.get("directorio_optin"))
    token = secrets.token_urlsafe(32)
    slug = await _slug_libre(r.get("nombre_comercial") or r.get("razon_social") or ruc, ruc)
    sid = await _enlazar_suscriptor(ruc, r, correo, whatsapp, ip, ua) if rol == "contador" else None
    try:
        await _pool().execute(
            """
            INSERT INTO club_socios
              (ruc, rol, verificacion, revisar, razon_social, nombre_comercial, ubigeo, distrito,
               correo, whatsapp, consentimiento, consentimiento_en, consentimiento_ver, token,
               suscriptor_id, directorio_optin, directorio_optin_en, directorio_optin_ver, slug,
               origen, ip, user_agent)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, true, now(), $11, $12, $13,
                    $14, CASE WHEN $14 THEN now() END, CASE WHEN $14 THEN $15 END, $16,
                    $17, $18::inet, $19)
            """,
            ruc, rol, r["verificacion"], r["revisar"], r.get("razon_social"), r.get("nombre_comercial"),
            r.get("ubigeo"), r.get("distrito"), correo, whatsapp, CONSENT_VER, token, sid,
            optin, DIRECTORIO_VER, slug, (payload.get("origen") or "club")[:60], ip, ua or None)
    except asyncpg.UniqueViolationError:
        return JSONResponse({"ok": False, "accion": "ya_registrado",
                             "error": "Este RUC ya está en el Club."}, status_code=409)
    resp = JSONResponse({"ok": True, "link": _destino(request, rol, str(payload.get("siguiente") or ""))})
    return _con_cookie(resp, request, token)


@router.post("/api/club/reingresar")
async def api_club_reingresar(payload: dict, request: Request):
    """Ya registrado: vuelve a entrar con el correo con que se registro."""
    ruc = "".join(c for c in str(payload.get("ruc") or "") if c.isdigit())
    correo = (payload.get("correo") or "").strip().lower()
    row = await _pool().fetchrow(
        "SELECT token, rol FROM club_socios WHERE ruc = $1 AND lower(correo) = $2 AND baja_en IS NULL",
        ruc, correo)
    if not row:
        return JSONResponse({"ok": False, "error": "Ese correo no coincide con el registrado para este RUC."},
                            status_code=403)
    return _con_cookie(JSONResponse({"ok": True, "link": _destino(request, row["rol"], str(payload.get("siguiente") or ""))}),
                       request, row["token"])


@router.post("/api/club/perfil/directorio")
async def api_club_directorio_optin(payload: dict, request: Request):
    s = await socio_por_token(request.cookies.get(COOKIE))
    if not s or s["rol"] != "contador":
        return JSONResponse({"ok": False, "error": "Entra al Club para cambiar esto."}, status_code=401)
    optin = bool(payload.get("optin"))
    await _pool().execute(
        "UPDATE club_socios SET directorio_optin = $2, "
        "directorio_optin_en = CASE WHEN $2 THEN now() END, "
        "directorio_optin_ver = CASE WHEN $2 THEN $3 END WHERE id = $1",
        s["id"], optin, DIRECTORIO_VER)
    return JSONResponse({"ok": True, "optin": optin})


# --- Paginas ------------------------------------------------------------------
@router.get("/entrar", response_class=HTMLResponse)
async def club_entrar(request: Request, rol: str = "", ref: str = "", sig: str = ""):
    """Registro / ingreso con RUC. NO es la puerta del Club: lo pide cada herramienta
    'con tu cuenta'. `sig` = a donde volver despues de entrar."""
    s = await socio_por_token(request.cookies.get(COOKIE))
    if s:
        return RedirectResponse(_destino(request, s["rol"], sig), status_code=303)
    return templates.TemplateResponse(request, "club/puerta.html", {
        "s": None, "inicio": inicio(request), "rol": rol if rol in ("contador", "empresario") else "",
        "origen": (ref or "club")[:60], "sig": _ruta_segura(sig),
        "anpd_url": ANPD_REGISTRO_URL, "psp_whatsapp": PSP_WHATSAPP})


async def _nn_resumen(ubigeo: str | None) -> dict | None:
    """Portada de la vitrina: NEGOCIOS REALES (juridicas + personas con negocio; sin
    independientes sin empresa) del distrito, o de todo el Peru si ubigeo es None.
    Solo meses comparables (desde julio 2026: mayo/junio no traen el tipo de
    contribuyente). Cifra grande = mes mas reciente."""
    filas = [d for d in await db.nn_desglose(ubigeo) if d["comparable"]][:3]
    if not filas:
        return None
    meses = [{"mes": MESES_CORTOS[int(f["mes"][5:7])], "n": f["negocios"]} for f in reversed(filas)]
    tope = max(m["n"] for m in meses) or 1
    for m in meses:
        m["pct"] = max(4, round(100 * m["n"] / tope))
    u = filas[0]
    return {"meses": meses, "total": u["negocios"], "juridicas": u["juridicas"],
            "naturales": u["naturales_con_negocio"], "mes_largo": MESES[int(u["mes"][5:7])],
            "mes_dato": f"{MESES[int(u['mes'][5:7])]} {u['mes'][:4]}"}


@router.get("/club", response_class=HTMLResponse)
async def club_tablero(request: Request, t: str = ""):
    """TABLERO PUBLICO = home del Club. Sin sesion se ve todo y las gratis se usan;
    las 'con tu cuenta' llevan a /entrar. Con sesion: datos de su distrito."""
    home = inicio(request)
    if t:   # enlace antiguo con token -> cookie y URL limpia
        return _con_cookie(RedirectResponse(home, status_code=303), request, t)
    s = await socio_por_token(request.cookies.get(COOKIE))
    if s and s["rol"] != "contador":
        return RedirectResponse("/empresario", status_code=303)
    p = contadores_distrito = None
    entrar = f"/entrar?sig={home}"
    if s:
        await _pool().execute("UPDATE club_socios SET ultimo_acceso_en = now() WHERE id = $1", s["id"])
        p = await padron(s["ruc"])
        if s["ubigeo"]:
            contadores_distrito = await _pool().fetchval(
                "SELECT count(*) FROM contadores_padron WHERE ubigeo = $1 AND activo_corte_2026_09", s["ubigeo"])
        nn_url = f"/mi-distrito?t={s['nn_token']}" if s.get("nn_token") else "/nuevos-negocios?ref=club"
        nn = await _nn_resumen(s["ubigeo"]) if s["ubigeo"] else None
    else:
        nn_url = entrar
        nn = await _nn_resumen(None)            # todo el Peru
    secciones = armar_tablero({"digito": s["ruc"][-1] if s else "?",
                               "digito_txt": f" (el tuyo es {s['ruc'][-1]})" if s else "",
                               "ubigeo": (s or {}).get("ubigeo") or "150101", "nn_url": nn_url,
                               "distrito": (s or {}).get("distrito") or "tu distrito",
                               "mes_dato": nn["mes_dato"] if nn else "cada mes"},
                              con_sesion=bool(s), entrar=entrar)
    total = sum(len(c["herramientas"]) for c in secciones)
    ubic = ""
    if s:
        ubic = " · ".join(titulo(x) for x in ((p or {}).get("distrito") or s["distrito"],
                                              (p or {}).get("provincia"), (p or {}).get("departamento")) if x)
    return templates.TemplateResponse(request, "club/tablero.html", {
        "s": s, "p": p, "inicio": home, "entrar": entrar,
        "nombre": nombre_saludo(s["ruc"], s["razon_social"], s["nombre_comercial"]) if s else None,
        "ubic": ubic, "secciones": secciones, "gana": GANA, "nn": nn, "nn_url": nn_url,
        "contadores_distrito": contadores_distrito, "total": total,
        "activas": sum(c["activas"] for c in secciones)})


@router.get("/perfil")
async def club_perfil(request: Request):
    s = await socio_por_token(request.cookies.get(COOKIE))
    if not s:
        return RedirectResponse("/entrar?sig=/perfil", status_code=303)
    base = inicio(request) if s["rol"] == "contador" else "/empresario"
    return RedirectResponse(base + "#perfil", status_code=303)


@router.get("/empresario", response_class=HTMLResponse)
async def club_empresario(request: Request):
    s = await socio_por_token(request.cookies.get(COOKIE))
    if not s:
        return RedirectResponse("/entrar?rol=empresario&sig=/empresario", status_code=303)
    return templates.TemplateResponse(request, "club/empresario.html", {
        "s": s, "inicio": inicio(request), "nombre": nombre_saludo(s["ruc"], s["razon_social"], s["nombre_comercial"])})


@router.get("/igv", response_class=HTMLResponse)
async def club_igv(request: Request):
    """Gratis y SIN cuenta: no pide sesion."""
    s = await socio_por_token(request.cookies.get(COOKIE))
    return templates.TemplateResponse(request, "club/igv.html", {"s": s, "inicio": inicio(request)})


@router.get("/directorio", response_class=HTMLResponse)
async def club_directorio_inicio(request: Request, ubigeo: str = ""):
    s = await socio_por_token(request.cookies.get(COOKIE))
    destino = "".join(c for c in ubigeo if c.isdigit()) or (s or {}).get("ubigeo")
    if destino and est.nombre_distrito(destino):
        return RedirectResponse(f"/directorio/{destino}", status_code=303)
    return templates.TemplateResponse(request, "club/directorio.html", {
        "s": s, "inicio": inicio(request), "ubigeo": None, "filas": [], "distrito": None})


@router.get("/directorio/{ubigeo}", response_class=HTMLResponse)
async def club_directorio(request: Request, ubigeo: str):
    distrito = est.nombre_distrito(ubigeo)
    if not distrito:
        return RedirectResponse("/directorio", status_code=303)
    s = await socio_por_token(request.cookies.get(COOKIE))
    filas = [dict(r) for r in await _pool().fetch(
        "SELECT id, ruc, razon_social, nombre_comercial, especialidad1, especialidad2, distrito, slug "
        "FROM club_socios WHERE ubigeo = $1 AND rol = 'contador' AND directorio_optin "
        "AND baja_en IS NULL ORDER BY created_at", ubigeo)]
    for f in filas:
        f["nombre"] = titulo(f["nombre_comercial"] or f["razon_social"])
        f["yo"] = bool(s and s["id"] == f["id"])
    padron_n = await _pool().fetchval(
        "SELECT count(*) FROM contadores_padron WHERE ubigeo = $1 AND activo_corte_2026_09", ubigeo)
    return templates.TemplateResponse(request, "club/directorio.html", {
        "s": s, "inicio": inicio(request), "ubigeo": ubigeo, "distrito": titulo(distrito), "filas": filas,
        "padron_n": padron_n, "vacias": max(0, 8 - len(filas))})


@router.get("/c/{slug}", response_class=HTMLResponse)
async def club_mini_pagina(request: Request, slug: str):
    """Mini-pagina individual: ESQUELETO (se completa despues). Solo si dio opt-in."""
    row = await _pool().fetchrow(
        "SELECT razon_social, nombre_comercial, distrito, ubigeo, especialidad1, especialidad2 "
        "FROM club_socios WHERE slug = $1 AND directorio_optin AND baja_en IS NULL", slug)
    if not row:
        return HTMLResponse("No encontramos esta página.", status_code=404)
    s = await socio_por_token(request.cookies.get(COOKIE))
    return templates.TemplateResponse(request, "club/mini.html", {
        "s": s, "inicio": inicio(request), "c": dict(row),
        "nombre": titulo(row["nombre_comercial"] or row["razon_social"])})


@router.get("/salir")
async def club_salir(request: Request):
    resp = RedirectResponse(inicio(request), status_code=303)
    resp.delete_cookie(COOKIE)                       # cookie antigua (solo este host)
    if _dominio_cookie(request):
        resp.delete_cookie(COOKIE, domain=_dominio_cookie(request))
    return resp
