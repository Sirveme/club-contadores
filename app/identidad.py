"""
Identidad del Club por PERSONA (DNI) — Fase 1b: backend (sin pantallas).

Modelo (sql/alter_v11_identidad.sql): personas (un DNI = una fila) y accesos
(persona -> RUC, con perfil contador/empresario POR RUC). Espejo de alerta.pe.

- RENIEC en vivo (apis.net.pe /v2/reniec/dni), SIN cache: DNI<->nombre es dato
  personal; no se acumula una base de nombres. La consulta publica devuelve el
  nombre ENMASCARADO; el registro vuelve a consultar del lado del servidor.
- Claves con Argon2. Sesion = cookie firmada (HMAC-SHA256) {pid, sv, exp}, 30 dias;
  en cada visita sv se compara con personas.sesion_version -> salir y cambiar clave
  cierran la sesion en TODOS los dispositivos (revocacion server-side).
- Limite de intentos de ingreso: 5 fallidos / 15 min por DNI y por IP.
- RUC 10 = '10' + DNI + DV: si coincide con el DNI, titular verificado al instante;
  si es de otra persona, se rechaza. RUC 20/15/17: declarado (por verificar, Fase 2).
- El REGISTRO queda cerrado hasta tener el consentimiento legal actualizado
  (IDENTIDAD_REGISTRO_ABIERTO=1 lo abre). Ingresar/salir/cambiar clave funcionan
  para personas ya activas.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time

import asyncpg
import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import club, db
from . import ruc as ruc_mod

log = logging.getLogger("uvicorn.error")
router = APIRouter()

COOKIE = "club_id"
DURACION = 30 * 86400                      # Fase 1. Con Facturalo (Fase 2) se acorta.
SECRETO = os.getenv("SESION_SECRET", "").strip()
REGISTRO_ABIERTO = os.getenv("IDENTIDAD_REGISTRO_ABIERTO", "0").strip() == "1"
CONSENT_VER = os.getenv("IDENTIDAD_CONSENT_VER", "identidad-pendiente-legal").strip()
APIS_DNI_URL = os.getenv("APIS_NET_PE_DNI_URL", "https://api.apis.net.pe/v2/reniec/dni").strip()
INTENTOS_MAX, INTENTOS_VENTANA_MIN = 5, 15
_CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ph = PasswordHasher()
PESOS_RUC = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


# --- RUC / DNI -----------------------------------------------------------------
def dv_ruc(primeros10: str) -> int:
    r = 11 - sum(int(d) * p for d, p in zip(primeros10, PESOS_RUC)) % 11
    return {10: 0, 11: 1}.get(r, r)


def ruc_valido(ruc: str) -> bool:
    return len(ruc) == 11 and ruc.isdigit() and ruc[:2] in ("10", "15", "17", "20") \
        and dv_ruc(ruc[:10]) == int(ruc[10])


def ruc10_de_dni(dni: str) -> str:
    """RUC 10 que corresponde a un DNI (para sugerirlo al registrarse)."""
    base = "10" + dni
    return base + str(dv_ruc(base))


def dni_valido(dni: str) -> bool:
    return len(dni) == 8 and dni.isdigit()


def solo_digitos(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def clave_problema(clave: str, clave2: str, dni: str) -> str | None:
    if clave != clave2:
        return "Las dos claves no coinciden."
    if len(clave) < 8:
        return "La clave debe tener al menos 8 caracteres."
    if clave == dni or len(set(clave)) == 1:
        return "Elige una clave distinta de tu DNI y que no sea un solo carácter repetido."
    return None


# --- RENIEC (en vivo, sin cache) -------------------------------------------------
async def _fetch_dni(dni: str) -> dict:
    """apis.net.pe RENIEC. Aislada para poder simularla en pruebas."""
    async with httpx.AsyncClient(timeout=8.0) as cli:
        r = await cli.get(APIS_DNI_URL, params={"numero": dni},
                          headers={"Authorization": f"Bearer {ruc_mod.APIS_NET_PE_TOKEN}",
                                   "Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"status {r.status_code}")
    return r.json() or {}


async def consultar_dni(dni: str) -> dict:
    """-> {estado: ok|no_existe|error, nombres, apellido_paterno, apellido_materno, nombre_completo}.
    Nunca lanza. 'error' (sin token / caida) no bloquea: se escribe el nombre a mano."""
    out = {"estado": "error", "nombres": None, "apellido_paterno": None,
           "apellido_materno": None, "nombre_completo": None}
    if not ruc_mod.APIS_NET_PE_TOKEN:
        return out
    try:
        d = await _fetch_dni(dni)
    except RuntimeError as e:
        out["estado"] = "no_existe" if str(e) in ("status 404", "status 422") else "error"
        return out
    except Exception as e:
        log.warning("identidad: RENIEC no respondio para un DNI (%s)", type(e).__name__)
        return out
    nombres = (d.get("nombres") or "").strip() or None
    ap, am = (d.get("apellidoPaterno") or "").strip() or None, (d.get("apellidoMaterno") or "").strip() or None
    if not nombres:
        out["estado"] = "no_existe"
        return out
    out.update(estado="ok", nombres=nombres, apellido_paterno=ap, apellido_materno=am,
               nombre_completo=(d.get("nombreCompleto") or " ".join(x for x in (nombres, ap, am) if x)).strip())
    return out


def enmascarar(r: dict) -> str | None:
    """'JORGE LUIS SANTANA S.' — basta para que la persona se reconozca, sin exponer
    el nombre completo de un DNI cualquiera."""
    if r.get("estado") != "ok":
        return None
    am = r.get("apellido_materno")
    return " ".join(x for x in (r["nombres"], r.get("apellido_paterno"), f"{am[0]}." if am else None) if x)


# --- Sesion firmada --------------------------------------------------------------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def crear_token(persona_id, sv: int) -> str:
    if not SECRETO:
        raise RuntimeError("Falta SESION_SECRET: no se emiten sesiones sin secreto.")
    cuerpo = _b64(json.dumps({"pid": str(persona_id), "sv": sv, "exp": int(time.time()) + DURACION},
                             separators=(",", ":")).encode())
    firma = _b64(hmac.new(SECRETO.encode(), cuerpo.encode(), hashlib.sha256).digest())
    return f"{cuerpo}.{firma}"


def leer_token(token: str | None) -> dict | None:
    if not token or not SECRETO or token.count(".") != 1:
        return None
    cuerpo, firma = token.split(".")
    esperada = _b64(hmac.new(SECRETO.encode(), cuerpo.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(firma, esperada):
        return None
    try:
        p = json.loads(_unb64(cuerpo))
    except Exception:
        return None
    if not isinstance(p, dict) or p.get("exp", 0) < time.time() or "sv" not in p or "pid" not in p:
        return None
    return p


def _con_sesion(resp, request: Request, persona_id, sv: int):
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, crear_token(persona_id, sv), max_age=DURACION, httponly=True,
                    samesite="lax", secure=https, domain=club._dominio_cookie(request))
    return resp


def _sin_sesion(resp, request: Request):
    resp.delete_cookie(COOKIE)
    if club._dominio_cookie(request):
        resp.delete_cookie(COOKIE, domain=club._dominio_cookie(request))
    return resp


async def persona_actual(request: Request) -> dict | None:
    """Persona con sesion valida: firma + vencimiento + sesion_version vigente +
    estado activa. Cualquier falla -> None (sin sesion)."""
    p = leer_token(request.cookies.get(COOKIE))
    if not p or db._pool is None:
        return None
    try:
        row = await db._pool.fetchrow(
            "SELECT * FROM personas WHERE id = $1::uuid AND estado = 'activa' AND baja_en IS NULL", p["pid"])
    except Exception:
        return None
    if not row or row["sesion_version"] != p["sv"]:
        return None
    return dict(row)


# --- Limite de intentos ----------------------------------------------------------
async def _bloqueado(dni: str, ip: str | None) -> bool:
    q = ("SELECT count(*) FROM login_intentos WHERE NOT exito AND creado_en > now() - make_interval(mins => $2) "
         "AND {} = $1")
    if await db._pool.fetchval(q.format("dni"), dni, INTENTOS_VENTANA_MIN) >= INTENTOS_MAX:
        return True
    return bool(ip) and await db._pool.fetchval(q.format("ip") + "::inet", ip, INTENTOS_VENTANA_MIN) >= INTENTOS_MAX


async def _registrar_intento(dni: str, ip: str | None, exito: bool) -> None:
    await db._pool.execute("INSERT INTO login_intentos (dni, ip, exito) VALUES ($1, $2::inet, $3)", dni, ip, exito)


# --- Accesos ---------------------------------------------------------------------
async def _slug_libre(base: str, ruc: str) -> str:
    from estadisticas import slug as hacer_slug
    s = hacer_slug(base)[:60].strip("-") or ruc
    ocupado = "SELECT 1 FROM accesos WHERE slug = $1 UNION ALL SELECT 1 FROM club_socios WHERE slug = $1"
    if await db._pool.fetchval(ocupado, s):
        s = f"{s}-{ruc[-4:]}"
    return s


async def vincular_ruc(conn, persona: dict, ruc: str, perfil: str, directorio_optin: bool,
                       correo: str, whatsapp: str, ip: str | None, ua: str) -> dict:
    """Crea el Acceso persona->RUC. -> {ok, acceso_id} o {ok: False, error}."""
    if not ruc_valido(ruc):
        return {"ok": False, "error": "Ese RUC no es válido. Revisa los 11 dígitos."}
    if ruc.startswith("10"):
        if ruc[2:10] != persona["dni"]:
            return {"ok": False, "motivo": "ruc10_ajeno",
                    "error": "Ese RUC 10 pertenece a otra persona: un RUC 10 se forma con el DNI de su titular. "
                             "Registra tu propio RUC o continúa sin RUC."}
        relacion, verificacion = "titular", "dni_en_ruc"
    else:
        relacion, verificacion = "representante", "declarado"
    # Actividad contable y datos del RUC: mismas fuentes que la puerta actual (padron -> API).
    r = await club.clasificar("contador", ruc, continuar=True)
    if perfil == "contador":
        actividad = r.get("verificacion") if r.get("verificacion") in ("padron", "api") else "por_confirmar"
    else:
        actividad = "no_aplica"
    sid = None
    if perfil == "contador" and r.get("ubigeo"):
        sid = await club._enlazar_suscriptor(ruc, r, correo, whatsapp, ip, ua)
    principal = not await conn.fetchval("SELECT 1 FROM accesos WHERE persona_id = $1 AND es_principal", persona["id"])
    optin = perfil == "contador" and directorio_optin
    try:
        aid = await conn.fetchval(
            """
            INSERT INTO accesos (persona_id, ruc, perfil, relacion, verificacion, actividad, revisar, es_principal,
                                 razon_social, nombre_comercial, ubigeo, distrito, directorio_optin, directorio_optin_en,
                                 directorio_optin_ver, slug, suscriptor_id, origen)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, CASE WHEN $13 THEN now() END,
                    CASE WHEN $13 THEN $14 END, $15, $16, 'identidad')
            RETURNING id
            """, persona["id"], ruc, perfil, relacion, verificacion, actividad, actividad == "por_confirmar", principal,
            r.get("razon_social"), r.get("nombre_comercial"), r.get("ubigeo"), r.get("distrito"), optin,
            club.DIRECTORIO_VER, await _slug_libre(r.get("nombre_comercial") or r.get("razon_social") or ruc, ruc), sid)
    except asyncpg.UniqueViolationError:
        return {"ok": False, "error": "Ese RUC ya está vinculado a tu cuenta (o a su titular)."}
    return {"ok": True, "acceso_id": aid}


# --- Endpoints -------------------------------------------------------------------
@router.post("/api/id/dni")
async def api_dni(payload: dict, request: Request):
    """Paso 1 del registro: reconoce el DNI. Nombre enmascarado + si ya tiene cuenta
    + su RUC 10 sugerido. Limitado por IP (no es un buscador de nombres). Cerrado,
    igual que el registro, hasta tener el consentimiento legal actualizado."""
    if not REGISTRO_ABIERTO:
        return JSONResponse({"ok": False, "error": "El registro con DNI estará disponible muy pronto."}, status_code=403)
    dni = solo_digitos(payload.get("dni"))
    if not dni_valido(dni):
        return JSONResponse({"ok": False, "error": "El DNI tiene 8 dígitos."}, status_code=422)
    ip = club._client_ip(request)
    if ip and await db._pool.fetchval(
            "SELECT count(*) FROM login_intentos WHERE ip = $1::inet AND dni IS NULL "
            "AND creado_en > now() - interval '1 hour'", ip) >= 30:
        return JSONResponse({"ok": False, "error": "Demasiadas consultas. Intenta en un rato."}, status_code=429)
    await db._pool.execute("INSERT INTO login_intentos (dni, ip, exito) VALUES (NULL, $1::inet, true)", ip)
    p = await db._pool.fetchrow("SELECT estado FROM personas WHERE dni = $1", dni)
    if p and p["estado"] == "activa":
        return JSONResponse({"ok": True, "accion": "ya_registrado"})
    if p and p["estado"] == "por_activar":
        return JSONResponse({"ok": True, "accion": "activar"})
    r = await consultar_dni(dni)
    if r["estado"] == "no_existe":
        return JSONResponse({"ok": False, "error": "RENIEC no reconoce ese DNI. Revísalo."}, status_code=404)
    return JSONResponse({"ok": True, "accion": "registro", "nombre": enmascarar(r),
                         "reniec": r["estado"] == "ok", "ruc10_sugerido": ruc10_de_dni(dni)})


def _sin_secreto():
    return JSONResponse({"ok": False, "error": "El ingreso con DNI aún no está configurado."}, status_code=503)


@router.post("/api/id/registro")
async def api_registro(payload: dict, request: Request):
    if not SECRETO:
        return _sin_secreto()
    if not REGISTRO_ABIERTO:
        return JSONResponse({"ok": False, "error": "El registro con DNI estará disponible muy pronto."}, status_code=403)
    if (payload.get("empresa_web") or "").strip():          # honeypot
        return JSONResponse({"ok": True})
    dni = solo_digitos(payload.get("dni"))
    clave, clave2 = str(payload.get("clave") or ""), str(payload.get("clave2") or "")
    correo = (payload.get("correo") or "").strip().lower()
    whatsapp = db.norm_whatsapp(payload.get("whatsapp"))
    perfil = payload.get("perfil")
    ruc = solo_digitos(payload.get("ruc"))
    if not dni_valido(dni):
        return JSONResponse({"ok": False, "error": "El DNI tiene 8 dígitos."}, status_code=422)
    if (problema := clave_problema(clave, clave2, dni)):
        return JSONResponse({"ok": False, "error": problema}, status_code=422)
    if not _CORREO_RE.match(correo):
        return JSONResponse({"ok": False, "error": "Indica un correo válido."}, status_code=422)
    if not whatsapp:
        return JSONResponse({"ok": False, "error": "El WhatsApp tiene 9 dígitos y empieza en 9."}, status_code=422)
    if perfil not in ("contador", "empresario"):
        return JSONResponse({"ok": False, "error": "Elige si eres contador o empresario."}, status_code=422)
    if not payload.get("consentimiento"):
        return JSONResponse({"ok": False, "error": "Para registrarte necesitamos tu autorización."}, status_code=422)
    if perfil == "empresario" and not ruc:
        return JSONResponse({"ok": False, "error": "Indica el RUC de tu negocio o empresa."}, status_code=422)
    existe = await db._pool.fetchrow("SELECT estado FROM personas WHERE dni = $1", dni)
    if existe:
        accion = "activar" if existe["estado"] == "por_activar" else "ya_registrado"
        return JSONResponse({"ok": False, "accion": accion, "error": "Ya tienes cuenta: ingresa con tu DNI y clave."},
                            status_code=409)
    r = await consultar_dni(dni)                            # del lado del servidor, nunca del cliente
    if r["estado"] == "no_existe":
        return JSONResponse({"ok": False, "error": "RENIEC no reconoce ese DNI. Revísalo."}, status_code=422)
    verificado = r["estado"] == "ok"
    nombre = r["nombre_completo"] if verificado else (str(payload.get("nombre") or "").strip()[:120] or None)
    if not nombre:
        return JSONResponse({"ok": False, "error": "Escribe tu nombre completo."}, status_code=422)
    ip, ua = club._client_ip(request), (request.headers.get("user-agent") or "")[:400]
    async with db._pool.acquire() as conn, conn.transaction():
        persona = dict(await conn.fetchrow(
            """
            INSERT INTO personas (dni, nombre_completo, nombres, apellido_paterno, apellido_materno, nombre_verificado,
                                  reniec_consultado_en, correo, whatsapp, clave_hash, estado, consentimiento_en,
                                  consentimiento_ver, activada_en, ultimo_login_at)
            VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $6 THEN now() END, $7, $8, $9, 'activa', now(), $10, now(), now())
            RETURNING *
            """, dni, nombre, r["nombres"], r["apellido_paterno"], r["apellido_materno"], verificado,
            correo, whatsapp, _ph.hash(clave), CONSENT_VER))
        if ruc:
            res = await vincular_ruc(conn, persona, ruc, perfil, bool(payload.get("directorio_optin")),
                                     correo, whatsapp, ip, ua)
            if not res["ok"]:
                raise _Rechazo(res)
    resp = JSONResponse({"ok": True, "link": club._destino(request, perfil, str(payload.get("siguiente") or ""))})
    return _con_sesion(resp, request, persona["id"], persona["sesion_version"])


class _Rechazo(Exception):
    def __init__(self, res):
        self.res = res


async def manejar_rechazo(request: Request, exc: _Rechazo):
    """El registro se deshace entero si el RUC no se puede vincular (p. ej. RUC 10 ajeno)."""
    return JSONResponse(exc.res, status_code=422)


@router.post("/api/id/ingresar")
async def api_ingresar(payload: dict, request: Request):
    if not SECRETO:
        return _sin_secreto()
    dni = solo_digitos(payload.get("dni"))
    clave = str(payload.get("clave") or "")
    ip = club._client_ip(request)
    if not dni_valido(dni):
        return JSONResponse({"ok": False, "error": "El DNI tiene 8 dígitos."}, status_code=422)
    if await _bloqueado(dni, ip):
        return JSONResponse({"ok": False, "error": f"Demasiados intentos. Espera {INTENTOS_VENTANA_MIN} minutos "
                                                   "o escríbenos por WhatsApp para recuperar tu clave."},
                            status_code=429)
    p = await db._pool.fetchrow("SELECT * FROM personas WHERE dni = $1 AND baja_en IS NULL", dni)
    if p and p["estado"] == "por_activar":
        return JSONResponse({"ok": False, "accion": "activar",
                             "error": "Tu cuenta viene del registro anterior: crea tu clave para activarla."},
                            status_code=409)
    ok = False
    if p and p["estado"] == "activa" and p["clave_hash"]:
        try:
            ok = _ph.verify(p["clave_hash"], clave)
        except (VerifyMismatchError, InvalidHashError, Exception):
            ok = False
    await _registrar_intento(dni, ip, ok)
    if not ok:
        return JSONResponse({"ok": False, "error": "DNI o clave incorrectos."}, status_code=401)
    await db._pool.execute("UPDATE personas SET ultimo_login_at = now() WHERE id = $1", p["id"])
    perfil = await db._pool.fetchval(
        "SELECT perfil FROM accesos WHERE persona_id = $1 ORDER BY es_principal DESC LIMIT 1", p["id"]) or "contador"
    resp = JSONResponse({"ok": True, "debe_cambiar_clave": p["debe_cambiar_clave"],
                         "link": club._destino(request, perfil, str(payload.get("siguiente") or ""))})
    return _con_sesion(resp, request, p["id"], p["sesion_version"])


@router.post("/api/id/salir")
async def api_salir(request: Request):
    """Cierra la sesion en TODOS los dispositivos (sube sesion_version)."""
    await cerrar_sesion_persona(request)
    return _sin_sesion(JSONResponse({"ok": True, "link": club.inicio(request)}), request)


@router.post("/api/id/cambiar-clave")
async def api_cambiar_clave(payload: dict, request: Request):
    p = await persona_actual(request)
    if not p:
        return JSONResponse({"ok": False, "error": "Ingresa para cambiar tu clave."}, status_code=401)
    actual, nueva, nueva2 = (str(payload.get(k) or "") for k in ("actual", "nueva", "nueva2"))
    try:
        ok = _ph.verify(p["clave_hash"], actual)
    except (VerifyMismatchError, InvalidHashError, Exception):
        ok = False
    if not ok:
        return JSONResponse({"ok": False, "error": "Tu clave actual no es correcta."}, status_code=401)
    if (problema := clave_problema(nueva, nueva2, p["dni"])):
        return JSONResponse({"ok": False, "error": problema}, status_code=422)
    sv = await db._pool.fetchval(
        "UPDATE personas SET clave_hash = $2, debe_cambiar_clave = false, sesion_version = sesion_version + 1, "
        "updated_at = now() WHERE id = $1 RETURNING sesion_version", p["id"], _ph.hash(nueva))
    # Este dispositivo sigue dentro (nueva cookie); los demas quedan fuera.
    return _con_sesion(JSONResponse({"ok": True}), request, p["id"], sv)


@router.get("/api/id/yo")
async def api_yo(request: Request):
    p = await persona_actual(request)
    if not p:
        return JSONResponse({"ok": False}, status_code=401)
    accesos = [dict(r) for r in await db._pool.fetch(
        "SELECT ruc, perfil, relacion, verificacion, actividad, es_principal, distrito, directorio_optin "
        "FROM accesos WHERE persona_id = $1 AND revocado_en IS NULL ORDER BY es_principal DESC, created_at", p["id"])]
    return JSONResponse({"ok": True, "dni": p["dni"], "nombres": p["nombres"], "nombre_verificado": p["nombre_verificado"],
                         "debe_cambiar_clave": p["debe_cambiar_clave"], "accesos": accesos})


# --- Sesion de persona vista por el Club (lectura doble, Fase 1c) ----------------
async def socio_desde_persona(request: Request) -> dict | None:
    """Persona con sesion -> los mismos campos que usa el Club para un socio, a partir
    de su acceso PRINCIPAL. Sin RUC vinculado: contador sin distrito (por confirmar)."""
    p = await persona_actual(request)
    if not p:
        return None
    a = await db._pool.fetchrow(
        "SELECT a.*, su.token_baja AS nn_token FROM accesos a LEFT JOIN suscriptores su ON su.id = a.suscriptor_id "
        "WHERE a.persona_id = $1 AND a.revocado_en IS NULL ORDER BY a.es_principal DESC, a.created_at LIMIT 1", p["id"])
    a = dict(a) if a else {}
    act = a.get("actividad")
    return {
        "fuente": "persona", "id": str(a["id"]) if a else str(p["id"]), "persona_id": str(p["id"]),
        "acceso_id": str(a["id"]) if a else None, "dni": p["dni"], "rol": a.get("perfil") or "contador",
        "ruc": a.get("ruc"), "razon_social": a.get("razon_social") or p["nombre_completo"],
        "nombre_comercial": a.get("nombre_comercial"), "ubigeo": a.get("ubigeo"),
        "distrito": club.titulo(a.get("distrito")) or None,
        "verificacion": act if act in ("padron", "api") else ("no_aplica" if act == "no_aplica" else "por_confirmar"),
        "nn_token": a.get("nn_token"), "directorio_optin": bool(a.get("directorio_optin")), "slug": a.get("slug"),
        "correo": p["correo"], "whatsapp": p["whatsapp"], "debe_cambiar_clave": p["debe_cambiar_clave"],
        "nombre_saludo": club.titulo(p["nombres"]) if p["nombres"] else
        club.nombre_saludo(a.get("ruc") or "10", p["nombre_completo"], None),
    }


async def cerrar_sesion_persona(request: Request) -> None:
    """Sube sesion_version: la sesion muere en TODOS los dispositivos."""
    p = await persona_actual(request)
    if p:
        await db._pool.execute("UPDATE personas SET sesion_version = sesion_version + 1, updated_at = now() "
                               "WHERE id = $1", p["id"])


# --- Pantallas (1c) ---------------------------------------------------------------
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: E402


def _ctx(request: Request, **k):
    return {"s": None, "inicio": club.inicio(request), "psp_whatsapp": club.PSP_WHATSAPP,
            "anpd_url": club.ANPD_REGISTRO_URL, "sig": club._ruta_segura(str(request.query_params.get("sig") or "")), **k}


@router.get("/registro", response_class=HTMLResponse)
async def pagina_registro(request: Request):
    if not REGISTRO_ABIERTO:
        return club.templates.TemplateResponse(request, "club/pronto.html", _ctx(request, que="El registro con DNI"))
    if await persona_actual(request):
        return RedirectResponse(club.inicio(request), status_code=303)
    return club.templates.TemplateResponse(request, "club/registro.html", _ctx(request, consent_ver=CONSENT_VER))


@router.get("/ingresar", response_class=HTMLResponse)
async def pagina_ingresar(request: Request):
    if not REGISTRO_ABIERTO:
        return club.templates.TemplateResponse(request, "club/pronto.html", _ctx(request, que="El ingreso con DNI"))
    if await persona_actual(request):
        return RedirectResponse(club.inicio(request), status_code=303)
    return club.templates.TemplateResponse(request, "club/ingresar.html", _ctx(request))


@router.get("/cambiar-clave", response_class=HTMLResponse)
async def pagina_cambiar_clave(request: Request):
    p = await persona_actual(request)
    if not p:
        return RedirectResponse("/ingresar?sig=/cambiar-clave", status_code=303)
    return club.templates.TemplateResponse(request, "club/cambiar_clave.html",
                                           _ctx(request, obligatoria=p["debe_cambiar_clave"]))
