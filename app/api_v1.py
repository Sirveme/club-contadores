"""API propia (/api/v1): lo que el Verificador consulta, con llave y en JSON limpio.

Es una sub-aplicacion montada en /api/v1: tiene su propia documentacion (/api/v1/docs)
y sus propios errores, siempre {"error": {"codigo", "mensaje"}}.

- Solo lectura. Se consulta SOLO por RUC (nunca por nombre).
- Llave por cliente: Authorization: Bearer psp_live_...  (o X-API-Key). Nunca en la URL.
  En la base solo esta su huella sha256; la llave se muestra una vez, al crearla.
- `alcances` de la llave gobiernan lo que ve: los representantes legales del SSCO solo van
  con el alcance 'ssco_representantes' (planes pagados). 'dni' queda reservado y apagado.
- Sin pistas de la fuente: las respuestas llevan `datos_al` y `cortes`, y la resolucion va
  sin su sufijo de entidad.

Configuracion:
  API_ABIERTA=1                sin esto, todo /api/v1 responde 404
  API_CUOTA_GRATIS_MES=100     cuota por defecto del plan gratis (provisional)
  API_RPM_DEFECTO=60           consultas por minuto por llave
  API_MAX_LOTE=100             (el lote llega en el paso 3)
Usa el esquema del Verificador (VERIFICADOR_ESQUEMA).

Cada llamada autenticada: ritmo -> validar -> descontar cuota -> consultar -> bitacora.
- La cuota es por llave, recurso y mes calendario (hora de Lima), y se descuenta de forma
  atomica (una sola sentencia): dos pedidos simultaneos nunca pasan del limite.
- Consume cuota todo pedido valido, encuentre o no el RUC. No consumen: llave invalida,
  RUC mal formado, exceso de ritmo ni cuota agotada.
- La bitacora (api_uso) guarda cuando, cuanto y con que resultado; NUNCA que RUC se consulto.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import club, db
from . import padron as P
from . import verificador as V

log = logging.getLogger("uvicorn.error")
ABIERTA = os.getenv("API_ABIERTA", "0").strip() == "1"
CUOTA_GRATIS_MES = int(os.getenv("API_CUOTA_GRATIS_MES", "100") or 100)
RPM_DEFECTO = int(os.getenv("API_RPM_DEFECTO", "60") or 60)
MAX_LOTE = int(os.getenv("API_MAX_LOTE", "100") or 100)
ANEXOS_MAX = 100
ALCANCES = ("ruc", "ssco_representantes", "dni")
SQL_V14 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql", "alter_v14_api.sql")
_LLAVE_RE = re.compile(r"^(psp_live_[a-z0-9]{8})_[A-Za-z0-9_-]{20,}$")
_SUFIJO_ENTIDAD = re.compile(r"\s*/\s*SUNAT\s*$", re.I)
SIN_CACHE = {"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex"}

app = FastAPI(
    title="API Perú Sistemas Pro", version="1.0",
    description="Consulta de RUC con semáforos: estado, condición de domicilio, SSCO y más. "
                "Autenticación con llave: `Authorization: Bearer psp_live_…`.",
    docs_url="/docs", redoc_url=None, openapi_url="/openapi.json")


class ErrorApi(Exception):
    def __init__(self, http: int, codigo: str, mensaje: str, cabeceras: dict | None = None, **extra):
        self.http, self.codigo, self.mensaje, self.extra = http, codigo, mensaje, extra
        self.cabeceras = cabeceras or {}


def _error(http: int, codigo: str, mensaje: str, cabeceras: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"error": {"codigo": codigo, "mensaje": mensaje, **extra}}, status_code=http,
                        headers={**SIN_CACHE, **(cabeceras or {})})


@app.exception_handler(ErrorApi)
async def _h_error(request: Request, e: ErrorApi):
    return _error(e.http, e.codigo, e.mensaje, e.cabeceras, **e.extra)


@app.exception_handler(StarletteHTTPException)
async def _h_http(request: Request, e: StarletteHTTPException):
    return _error(e.status_code, "no_encontrado" if e.status_code == 404 else "error", str(e.detail))


@app.exception_handler(RequestValidationError)
async def _h_validacion(request: Request, e: RequestValidationError):
    return _error(422, "solicitud_invalida", "La solicitud no tiene el formato esperado.")


@app.middleware("http")
async def _cerrada(request: Request, call_next):
    """Con API_ABIERTA cerrada no existe nada bajo /api/v1 (ni su documentacion)."""
    if not ABIERTA:
        return _error(404, "no_encontrado", "No encontrado.")
    return await call_next(request)


# --- Llaves ------------------------------------------------------------------------------
def nueva_llave() -> tuple[str, str, str]:
    """-> (llave completa, prefijo visible, huella). La llave completa no se guarda."""
    prefijo = "psp_live_" + secrets.token_hex(4)
    llave = f"{prefijo}_{secrets.token_urlsafe(24)}"
    return llave, prefijo, hashlib.sha256(llave.encode()).hexdigest()


def _llave_de(request: Request) -> str:
    a = request.headers.get("authorization", "")
    if a[:7].lower() == "bearer ":
        return a[7:].strip()
    return request.headers.get("x-api-key", "").strip()


async def autenticar(request: Request) -> dict:
    """La llave del pedido, viva. Cualquier falla -> ErrorApi 401/403 (sin dar pistas)."""
    llave = _llave_de(request)
    m = _LLAVE_RE.match(llave)
    if not m:
        raise ErrorApi(401, "llave_invalida", "Falta la llave o no es válida. Envíala en la cabecera "
                                              "Authorization: Bearer <tu llave>.")
    row = await db._pool.fetchrow(f"SELECT * FROM {V.ESQUEMA}.api_llaves WHERE prefijo = $1", m.group(1))
    if not row or not hmac.compare_digest(row["huella"], hashlib.sha256(llave.encode()).hexdigest()):
        raise ErrorApi(401, "llave_invalida", "Falta la llave o no es válida. Envíala en la cabecera "
                                              "Authorization: Bearer <tu llave>.")
    if row["estado"] != "activa":
        raise ErrorApi(403, "llave_revocada", "Esta llave está revocada o suspendida.")
    return dict(row)


# --- Ritmo, cuota y bitacora -------------------------------------------------------------
_ventanas: dict[str, deque] = {}        # llave -> instantes de sus ultimos pedidos (60 s)


def ritmo(llave: dict) -> None:
    """Tope de pedidos por minuto de la llave. En memoria: vale mientras haya una sola
    instancia del servicio. No consume cuota."""
    ahora, v = time.monotonic(), _ventanas.setdefault(str(llave["id"]), deque())
    while v and ahora - v[0] >= 60:
        v.popleft()
    if len(v) >= llave["rpm"]:
        espera = max(1, int(60 - (ahora - v[0])) + 1)
        raise ErrorApi(429, "demasiado_rapido", f"Vas muy rápido: tu llave permite {llave['rpm']} consultas por minuto.",
                       {"Retry-After": str(espera)}, reintentar_en_segundos=espera)
    v.append(ahora)


_MES = "date_trunc('month', now() AT TIME ZONE 'America/Lima')::date"


async def estado_cuota(llave: dict, recurso: str = "ruc") -> dict:
    row = await db._pool.fetchrow(
        f"SELECT coalesce((SELECT unidades FROM {V.ESQUEMA}.api_uso_mes WHERE llave_id = $1 AND recurso = $2 AND mes = {_MES}), 0) AS usada, "
        f"({_MES} + interval '1 month')::date AS reinicio", llave["id"], recurso)
    return {"limite": llave["cuota_mes"], "usada": row["usada"], "restante": max(0, llave["cuota_mes"] - row["usada"]),
            "reinicio": row["reinicio"].isoformat()}


def _cab_cuota(c: dict) -> dict:
    return {"X-Cuota-Limite": str(c["limite"]), "X-Cuota-Usada": str(c["usada"]),
            "X-Cuota-Restante": str(c["restante"]), "X-Cuota-Reinicio": c["reinicio"]}


async def consumir(llave: dict, unidades: int, recurso: str = "ruc") -> dict:
    """Descuenta `unidades` de la cuota del mes en UNA sentencia (atomica). Si no caben, no
    descuenta nada y lanza 429. -> estado de la cuota tras descontar."""
    usada = None
    if unidades <= llave["cuota_mes"]:
        usada = await db._pool.fetchval(
            f"""INSERT INTO {V.ESQUEMA}.api_uso_mes AS u (llave_id, recurso, mes, unidades) VALUES ($1, $2, {_MES}, $3)
                ON CONFLICT (llave_id, recurso, mes) DO UPDATE SET unidades = u.unidades + $3
                WHERE u.unidades + $3 <= $4 RETURNING unidades""", llave["id"], recurso, unidades, llave["cuota_mes"])
    c = await estado_cuota(llave, recurso)
    if usada is None:
        raise ErrorApi(429, "cuota_agotada",
                       f"Llegaste a tu cuota del mes ({c['limite']} consultas). Se reinicia el {c['reinicio']}.",
                       _cab_cuota(c), reinicio=c["reinicio"], restante=c["restante"], solicitadas=unidades)
    return c


async def bitacora(request: Request, llave: dict, recurso: str, unidades: int, http: int, t0: float) -> None:
    """Deja el rastro de la llamada (sin el RUC) y marca el ultimo uso de la llave."""
    try:
        async with db._pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {V.ESQUEMA}.api_uso (llave_id, recurso, unidades, http, ms, ip) VALUES ($1, $2, $3, $4, $5, $6::inet)",
                llave["id"], recurso, unidades, http, int((time.monotonic() - t0) * 1000), club._client_ip(request) or None)
            await conn.execute(f"UPDATE {V.ESQUEMA}.api_llaves SET ultima_vez = now() WHERE id = $1", llave["id"])
    except Exception:
        log.exception("api_v1: no se pudo escribir la bitacora")


# --- Formato de salida -------------------------------------------------------------------
def _ruc_json(f: dict, llave: dict, datos: dict, con_anexos: bool) -> dict:
    """Una fila de verificador.consultar() en el formato publico de la API."""
    m = f.get("marcas") or {}
    marcas: dict = {}
    for col in datos["columnas"]:
        cod, x = col["codigo"], m.get(col["codigo"])
        if not x:
            marcas[cod] = None
        elif cod == "ssco":
            d = x["detalle"]
            s = {"desde": x["desde"], "resolucion": _SUFIJO_ENTIDAD.sub("", d.get("resolucion") or "") or None,
                 "emision": d.get("emision"), "firme": d.get("firme"), "publicacion": d.get("publicacion")}
            if "ssco_representantes" in llave["alcances"]:
                s["representantes"] = [{"tipo": r.get("tipo"), "doc": r.get("doc"), "nombre": r.get("nombre")}
                                       for r in d.get("representantes") or []]
            marcas[cod] = s
        elif cod == "negocio_nuevo":
            marcas[cod] = {"inscrito": x["desde"], "mes": (x["detalle"] or {}).get("mes")}
        else:
            marcas[cod] = {"desde": x["desde"]} if x["desde"] else True
    u = f.get("distrito") or {}
    out = {"ruc": f["ruc"], "encontrado": True, "razon_social": f["razon_social"],
           "estado": {"codigo": f["estado"]["valor"], "nombre": f["estado"]["nombre"], "semaforo": f["estado"]["semaforo"]},
           "condicion": {"codigo": f["condicion"]["valor"] or None, "nombre": f["condicion"]["nombre"],
                         "semaforo": f["condicion"]["semaforo"]},
           "semaforo": f["semaforo"], "ubigeo": f.get("ubigeo"), "departamento": u.get("departamento"),
           "provincia": u.get("provincia"), "distrito": u.get("distrito"), "domicilio": f.get("domicilio"),
           "marcas": marcas, "anexos": {"total": f["anexos"]["n"]},
           "datos_al": datos["datos_al"], "cortes": {c["codigo"]: c["corte"] for c in datos["columnas"]}}
    if con_anexos:
        out["anexos"]["lista"] = f["anexos"]["lista"]
        out["anexos"]["truncado"] = f["anexos"]["n"] > len(f["anexos"]["lista"])
    return out


def _plano(d: dict) -> dict:
    """Todo en un solo nivel (para hojas de calculo): estado_nombre, ssco_firme, ..."""
    out: dict = {}
    for k, v in d.items():
        if k == "marcas":
            for cod, x in v.items():
                out[cod] = bool(x)
                if isinstance(x, dict):
                    for kk, vv in x.items():
                        if not isinstance(vv, (list, dict)):
                            out[f"{cod}_{kk}"] = vv
        elif k == "cortes":
            for cod, vv in v.items():
                out[f"corte_{cod}"] = vv
        elif isinstance(v, dict):
            for kk, vv in v.items():
                if not isinstance(vv, (list, dict)):
                    out[f"{k}_{kk}"] = vv
        else:
            out[k] = v
    return out


# --- Endpoints ---------------------------------------------------------------------------
@app.get("/ruc/{ruc}", summary="Consulta un RUC", tags=["RUC"])
async def ruc(ruc: str, request: Request, anexos: int = 0, formato: str = ""):
    """Estado, condición de domicilio, distrito, domicilio y marcas (SSCO con sus fechas,
    contador, negocio nuevo) de un RUC. `?anexos=1` agrega los locales anexos (hasta 100) y
    `?formato=plano` devuelve todo en un solo nivel."""
    t0 = time.monotonic()
    llave = await autenticar(request)
    if "ruc" not in llave["alcances"]:
        raise ErrorApi(403, "sin_alcance", "Tu llave no incluye la consulta de RUC.")
    try:
        ritmo(llave)
    except ErrorApi as e:
        await bitacora(request, llave, "ruc", 0, e.http, t0)
        raise
    ruc = ruc.strip()
    if not P.RUC_RE.match(ruc):
        await bitacora(request, llave, "ruc", 0, 422, t0)
        raise ErrorApi(422, "ruc_invalido", "Un RUC tiene 11 dígitos y empieza en 10, 15, 17 o 20.",
                       _cab_cuota(await estado_cuota(llave)), ruc=ruc[:20])
    try:
        cuota = await consumir(llave, 1)
    except ErrorApi as e:
        await bitacora(request, llave, "ruc", 0, e.http, t0)
        raise
    datos = await V.consultar([ruc], iso=True, anexos_max=ANEXOS_MAX if anexos else 0)
    f = datos["filas"][0]
    cab = {**SIN_CACHE, **_cab_cuota(cuota)}
    if not f["encontrado"]:
        await bitacora(request, llave, "ruc", 1, 404, t0)
        raise ErrorApi(404, "ruc_no_encontrado", "Ese RUC no figura en nuestros datos.", _cab_cuota(cuota), ruc=ruc,
                       datos_al=datos["datos_al"])
    out = _ruc_json(f, llave, datos, bool(anexos))
    await bitacora(request, llave, "ruc", 1, 200, t0)
    return JSONResponse(_plano(out) if formato == "plano" else out, headers=cab)


@app.get("/yo", summary="Tu llave: plan, cuota y consumo", tags=["Cuenta"])
async def yo(request: Request):
    """Plan, alcances y cuota del mes de la llave con que llamas. No consume cuota."""
    llave = await autenticar(request)
    cuota = await estado_cuota(llave)
    return JSONResponse({"llave": llave["prefijo"], "nombre": llave["nombre"], "plan": llave["plan_codigo"],
                         "alcances": list(llave["alcances"]), "consultas_por_minuto": llave["rpm"], "cuota": cuota},
                        headers={**SIN_CACHE, **_cab_cuota(cuota)})


async def asegurar_esquema():
    """Crea las tablas de la API en el esquema del Verificador. Solo con la API abierta: asi
    ninguna otra ejecucion (pruebas, cargas) crea tablas en produccion por accidente."""
    if not ABIERTA or db._pool is None:
        return
    try:
        await crear_tablas(db._pool, V.ESQUEMA)
    except Exception:
        log.exception("api_v1: no se pudieron crear las tablas de la API")


async def crear_tablas(pool_o_conn, esquema: str):
    sql = open(SQL_V14, encoding="utf-8").read()
    if hasattr(pool_o_conn, "acquire"):
        async with pool_o_conn.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL search_path TO {esquema}, public")
            await conn.execute(sql)
    else:
        async with pool_o_conn.transaction():
            await pool_o_conn.execute(f"SET LOCAL search_path TO {esquema}, public")
            await pool_o_conn.execute(sql)
