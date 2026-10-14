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
  API_MAX_LOTE=100             RUC distintos y validos por lote
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

from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
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

GUIA = """
Consulta de RUC con semáforos: **estado** del contribuyente, **condición de domicilio**, **SSCO**
(con la fecha en que la resolución quedó firme), contador, negocio nuevo, distrito y domicilio.
Solo lectura. Se consulta únicamente por RUC.

## Autenticación
Cada integración usa su llave, en la cabecera:

    Authorization: Bearer psp_live_xxxxxxxx_…

(también se acepta `X-API-Key: psp_live_…`). La llave **nunca** va en la URL. Usa el botón
**Authorize** de esta página para probar con la tuya.

## Cuota y ritmo
- Cada llave tiene una cuota de consultas por mes calendario (hora de Lima) y un tope por minuto.
- Consume **una consulta por cada RUC válido**, se encuentre o no. No consumen: la llave inválida,
  el RUC mal formado, el exceso de ritmo ni la cuota agotada.
- En el lote, la cuota se descuenta **todo o nada**: si no alcanza, no se procesa nada.
- Toda respuesta trae `X-Cuota-Limite`, `X-Cuota-Usada`, `X-Cuota-Restante` y `X-Cuota-Reinicio`.
- No registramos **qué** RUC consultas: solo cuántas consultas haces.

## Errores
Siempre `{"error": {"codigo": "…", "mensaje": "…"}}`:

| HTTP | codigo | Cuándo |
|---|---|---|
| 401 | `llave_invalida` | Falta la llave o no es válida |
| 403 | `llave_revocada`, `sin_alcance` | Llave revocada o suspendida; o sin permiso para ese recurso |
| 404 | `ruc_no_encontrado` | El RUC es válido pero no figura (consume) |
| 413 | `lote_muy_grande` | Más RUC distintos que el tope del lote |
| 422 | `ruc_invalido`, `sin_rucs_validos`, `solicitud_invalida` | Formato incorrecto (no consume) |
| 429 | `cuota_agotada` (trae `reinicio`), `demasiado_rapido` (trae `Retry-After`) | Cuota del mes o ritmo |

## Formatos
- Por defecto, JSON anidado. `?formato=plano` lo devuelve en un solo nivel (`estado_nombre`,
  `ssco_firme`, `distrito`…), ideal para hojas de cálculo.
- Las fechas van como `AAAA-MM-DD`. `datos_al` y `cortes` dicen a qué fecha corresponde cada dato.

## Google Sheets
Descarga el script en [`/api/v1/sheets/RUC.gs`](sheets/RUC.gs): en tu hoja, *Extensiones → Apps
Script*, pégalo y guarda. Luego el menú *Perú Sistemas Pro → Configurar llave*. Funciones:
`=RUC(A2)`, `=RUC(A2; "estado")`, `=RUCS(A2:A200)` y `=RUC_SALDO()`.
"""
SCRIPT_SHEETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "integraciones", "google-sheets", "RUC.gs")

app = FastAPI(
    title="API Perú Sistemas Pro", version="1.0", description=GUIA,
    contact={"name": "Perú Sistemas Pro", "url": "https://club.perusistemas.pro"},
    servers=[{"url": "/api/v1"}],
    docs_url=None, redoc_url=None, openapi_url="/openapi.json")

# Tema oscuro de la documentacion (colores del Club, sepia). Nunca fondo blanco.
_CSS_DOCS = """
body{background:#14110e;margin:0}
.swagger-ui{color:#e8e1d6;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.swagger-ui .wrapper{max-width:1180px}
.swagger-ui .info{margin:28px 0}
.swagger-ui .info .title,.swagger-ui .info h1,.swagger-ui .info h2,.swagger-ui .info h3,.swagger-ui .info h4,
.swagger-ui .info p,.swagger-ui .info li,.swagger-ui .info table,.swagger-ui .info td,.swagger-ui .info th,
.swagger-ui .opblock-tag,.swagger-ui .opblock .opblock-summary-path,.swagger-ui .opblock .opblock-summary-description,
.swagger-ui .opblock-description-wrapper p,.swagger-ui .opblock-title_normal p,.swagger-ui .response-col_status,
.swagger-ui .response-col_description,.swagger-ui .parameter__name,.swagger-ui .parameter__type,.swagger-ui label,
.swagger-ui .tab li,.swagger-ui .responses-inner h4,.swagger-ui .responses-inner h5,.swagger-ui .opblock-section-header h4,
.swagger-ui table thead tr th,.swagger-ui table thead tr td,.swagger-ui .servers-title,.swagger-ui .scheme-container label,
.swagger-ui .dialog-ux .modal-ux-header h3,.swagger-ui .dialog-ux .modal-ux-content p,.swagger-ui .dialog-ux .modal-ux-content h4,
.swagger-ui .auth-container h4,.swagger-ui .auth-container label,.swagger-ui .markdown p,.swagger-ui .renderedMarkdown p,
.swagger-ui .markdown li,.swagger-ui .renderedMarkdown li,.swagger-ui .response-control-media-type__title,
.swagger-ui .parameters-col_description,.swagger-ui .model,.swagger-ui .model-title,.swagger-ui .prop-type{color:#e8e1d6}
.swagger-ui .info a,.swagger-ui a.nostyle,.swagger-ui .markdown a,.swagger-ui .renderedMarkdown a{color:#7cc4e4}
.swagger-ui .info .title small{background:#3a3128}.swagger-ui .info .title small.version-stamp{background:#6c8f3c}
.swagger-ui code,.swagger-ui .markdown code,.swagger-ui .renderedMarkdown code,.swagger-ui .info code{background:#2a231c;color:#e6b673;border-radius:3px}
.swagger-ui .info pre,.swagger-ui .markdown pre{background:#0f0d0b;border:1px solid #3a3128}
.swagger-ui .info table td,.swagger-ui .info table th,.swagger-ui table tbody tr td{border-color:#3a3128;color:#d8cfc2}
.swagger-ui .scheme-container{background:#1d1915;box-shadow:none;border:1px solid #3a3128}
.swagger-ui .opblock-tag{border-bottom-color:#3a3128}
.swagger-ui .opblock{background:#1a1612;border-color:#3a3128;box-shadow:none}
.swagger-ui .opblock .opblock-section-header{background:#211c17;box-shadow:none}
.swagger-ui .opblock.opblock-get{border-color:#3d6f86;background:#16191a}
.swagger-ui .opblock.opblock-post{border-color:#4f7a3a;background:#161a14}
.swagger-ui .opblock-body pre.microlight,.swagger-ui .highlight-code>.microlight{background:#0f0d0b!important}
.swagger-ui input[type=text],.swagger-ui input[type=password],.swagger-ui textarea,.swagger-ui select{background:#0f0d0b;color:#e8e1d6;border:1px solid #3a3128}
.swagger-ui .btn{color:#e8e1d6;border-color:#5a4c3d;background:transparent;box-shadow:none}
.swagger-ui .btn.authorize{color:#9bd17a;border-color:#9bd17a}.swagger-ui .btn.authorize svg{fill:#9bd17a}
.swagger-ui .btn.execute{background:#3d6f86;border-color:#3d6f86}
.swagger-ui .dialog-ux .modal-ux{background:#1d1915;border:1px solid #3a3128}
.swagger-ui .dialog-ux .modal-ux-header{border-bottom-color:#3a3128}
.swagger-ui .dialog-ux .backdrop-ux{background:rgba(0,0,0,.7)}
.swagger-ui .arrow,.swagger-ui .expand-operation svg,.swagger-ui .authorization__btn svg,.swagger-ui .opblock-control-arrow svg{fill:#d8cfc2}
.swagger-ui .responses-table .response,.swagger-ui .parameters-container,.swagger-ui .responses-wrapper{background:transparent}
.swagger-ui .tab li button.tablinks{color:#e8e1d6}
.swagger-ui section.models{border-color:#3a3128}
"""


@app.get("/docs", include_in_schema=False)
async def documentacion():
    from fastapi.openapi.docs import get_swagger_ui_html
    html = get_swagger_ui_html(openapi_url="/api/v1/openapi.json", title="API Perú Sistemas Pro · Documentación",
                               swagger_ui_parameters={"defaultModelsExpandDepth": -1, "tryItOutEnabled": True,
                                                      "syntaxHighlight": {"theme": "monokai"}})
    cuerpo = html.body.decode("utf-8").replace("</head>", f"<meta name=\"color-scheme\" content=\"dark\"><style>{_CSS_DOCS}</style></head>", 1)
    return HTMLResponse(cuerpo, headers={"Cache-Control": "public, max-age=600"})


def _openapi():
    """Esquema con las dos formas de enviar la llave (boton Authorize de la documentacion)."""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    esq = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes,
                      contact=app.contact, servers=app.servers)
    esq.setdefault("components", {})["securitySchemes"] = {
        "llave": {"type": "http", "scheme": "bearer", "description": "Tu llave: psp_live_…"},
        "x_api_key": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}
    for ruta, metodos in esq.get("paths", {}).items():
        for op in metodos.values():
            if not ruta.startswith("/sheets"):
                op["security"] = [{"llave": []}, {"x_api_key": []}]
    app.openapi_schema = esq
    return esq


app.openapi = _openapi


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
_EJ_ERROR = lambda codigo, mensaje: {"application/json": {"example": {"error": {"codigo": codigo, "mensaje": mensaje}}}}
_EJ_RUC = {"ruc": "20607011274", "encontrado": True, "razon_social": "INVERSIONES NUEVA LINEA E.I.R.L.",
           "estado": {"codigo": "ACTIVO", "nombre": "Activo", "semaforo": "verde"},
           "condicion": {"codigo": "HABIDO", "nombre": "Habido", "semaforo": "verde"}, "semaforo": "rojo",
           "ubigeo": "080106", "departamento": "CUSCO", "provincia": "CUSCO", "distrito": "SANTIAGO",
           "domicilio": "CAL. TARAPACA MZA. C LOTE. 1 URB. PRIMAVERA - CUSCO - CUSCO - SANTIAGO",
           "marcas": {"ssco": {"desde": "2026-09-18", "resolucion": "Resolución de Intendencia N.º 094-024-0004915",
                               "emision": "2026-09-03", "firme": "2026-09-18", "publicacion": "2026-09-30"},
                      "contador": None, "negocio_nuevo": None},
           "anexos": {"total": 0}, "datos_al": "2026-10-10",
           "cortes": {"ssco": "2026-09-30", "contador": "2026-09-17", "negocio_nuevo": "2026-08-31"}}
_RESP_COMUNES = {
    401: {"description": "Llave inválida", "content": _EJ_ERROR("llave_invalida", "Falta la llave o no es válida.")},
    403: {"description": "Llave revocada o sin alcance", "content": _EJ_ERROR("llave_revocada", "Esta llave está revocada o suspendida.")},
    429: {"description": "Cuota agotada o demasiado rápido", "content": {"application/json": {"example": {"error": {
        "codigo": "cuota_agotada", "mensaje": "Llegaste a tu cuota del mes (100 consultas). Se reinicia el 2026-11-01.",
        "reinicio": "2026-11-01", "restante": 0, "solicitadas": 1}}}}}}


@app.get("/ruc/{ruc}", summary="Consulta un RUC", tags=["RUC"], responses={
    200: {"description": "El RUC con sus semáforos. Los representantes legales del SSCO solo van en planes pagados.",
          "content": {"application/json": {"example": _EJ_RUC}}},
    404: {"description": "RUC válido que no figura (consume)", "content": _EJ_ERROR("ruc_no_encontrado", "Ese RUC no figura en nuestros datos.")},
    422: {"description": "RUC mal formado (no consume)", "content": _EJ_ERROR("ruc_invalido", "Un RUC tiene 11 dígitos y empieza en 10, 15, 17 o 20.")},
    **_RESP_COMUNES})
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


class Lote(BaseModel):
    rucs: list[Any] = Field(..., description="RUC como texto o como número (p. ej. desde una hoja de cálculo).",
                            examples=[["20607011274", 20100047218]])


def _normalizar(valor) -> str:
    """Un RUC venga como texto o como numero (las hojas de calculo mandan 20607011274.0)."""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor if valor is not None else "").strip()


@app.post("/ruc/lote", summary="Consulta varios RUC de una vez", tags=["RUC"], responses={
    200: {"description": "Un resultado por RUC válido distinto, en el orden recibido.", "content": {"application/json": {"example": {
        "resultados": [_EJ_RUC, {"ruc": "20999999990", "encontrado": False}], "no_validos": [{"valor": "123", "motivo": "ruc_invalido"}],
        "resumen": {"solicitados": 3, "validos": 2, "encontrados": 1, "no_encontrados": 1, "con_alerta": 1},
        "datos_al": "2026-10-10", "cortes": {"ssco": "2026-09-30", "contador": "2026-09-17", "negocio_nuevo": "2026-08-31"}}}}},
    413: {"description": "Demasiados RUC distintos", "content": _EJ_ERROR("lote_muy_grande", "Envía hasta 100 RUC distintos por lote.")},
    422: {"description": "Ningún RUC válido o cuerpo mal formado", "content": _EJ_ERROR("sin_rucs_validos", "El lote no trae ningún RUC válido.")},
    **_RESP_COMUNES})
async def ruc_lote(cuerpo: Lote, request: Request, formato: str = ""):
    """Hasta API_MAX_LOTE RUC distintos por llamada, en el orden en que llegan (los repetidos
    cuentan una vez). Consume una consulta por cada RUC valido, encuentre o no; los no
    validos se devuelven aparte y no consumen. Si la cuota no alcanza para todo el lote, no
    se procesa nada (429). `?formato=plano` aplana cada resultado."""
    t0 = time.monotonic()
    llave = await autenticar(request)
    if "ruc" not in llave["alcances"]:
        raise ErrorApi(403, "sin_alcance", "Tu llave no incluye la consulta de RUC.")
    try:
        ritmo(llave)
    except ErrorApi as e:
        await bitacora(request, llave, "ruc", 0, e.http, t0)
        raise
    if len(cuerpo.rucs) > MAX_LOTE * 5:
        await bitacora(request, llave, "ruc", 0, 413, t0)
        raise ErrorApi(413, "lote_muy_grande", f"Envía hasta {MAX_LOTE} RUC por lote.", maximo=MAX_LOTE)
    validos, vistos, no_validos = [], set(), []
    for v in cuerpo.rucs:
        x = _normalizar(v)
        if not P.RUC_RE.match(x):
            no_validos.append({"valor": x[:20], "motivo": "ruc_invalido"})
        elif x not in vistos:
            vistos.add(x)
            validos.append(x)
    if len(validos) > MAX_LOTE:
        await bitacora(request, llave, "ruc", 0, 413, t0)
        raise ErrorApi(413, "lote_muy_grande", f"Envía hasta {MAX_LOTE} RUC distintos por lote (llegaron {len(validos)}).",
                       _cab_cuota(await estado_cuota(llave)), maximo=MAX_LOTE, recibidos=len(validos))
    if not validos:
        await bitacora(request, llave, "ruc", 0, 422, t0)
        raise ErrorApi(422, "sin_rucs_validos", "El lote no trae ningún RUC válido (11 dígitos, empieza en 10, 15, 17 o 20).",
                       _cab_cuota(await estado_cuota(llave)), no_validos=no_validos[:20])
    try:
        cuota = await consumir(llave, len(validos))
    except ErrorApi as e:
        await bitacora(request, llave, "ruc", 0, e.http, t0)
        raise
    datos = await V.consultar(validos, iso=True, anexos_max=0)
    resultados = []
    for f in datos["filas"]:
        r = _ruc_json(f, llave, datos, False) if f["encontrado"] else {"ruc": f["ruc"], "encontrado": False}
        resultados.append(_plano(r) if formato == "plano" else r)
    encontrados = [f for f in datos["filas"] if f["encontrado"]]
    out = {"resultados": resultados, "no_validos": no_validos,
           "resumen": {"solicitados": len(cuerpo.rucs), "validos": len(validos), "encontrados": len(encontrados),
                       "no_encontrados": len(validos) - len(encontrados),
                       "con_alerta": sum(1 for f in encontrados if f["semaforo"] == "rojo")},
           "datos_al": datos["datos_al"], "cortes": {c["codigo"]: c["corte"] for c in datos["columnas"]}}
    await bitacora(request, llave, "ruc", len(validos), 200, t0)
    return JSONResponse(out, headers={**SIN_CACHE, **_cab_cuota(cuota)})


@app.get("/sheets/RUC.gs", summary="Script para Google Sheets", tags=["Google Sheets"],
         response_class=PlainTextResponse, responses={200: {"content": {"text/plain": {}}}})
async def script_sheets():
    """El archivo de Apps Script con `=RUC()`, `=RUCS()` y `=RUC_SALDO()`. Pégalo en
    *Extensiones → Apps Script* de tu hoja. No necesita llave para descargarlo."""
    return PlainTextResponse(open(SCRIPT_SHEETS, encoding="utf-8").read(), headers={
        "Content-Disposition": 'inline; filename="RUC.gs"', "Cache-Control": "public, max-age=3600"})


@app.get("/yo", summary="Tu llave: plan, cuota y consumo", tags=["Cuenta"], responses={
    200: {"content": {"application/json": {"example": {"llave": "psp_live_a1b2c3d4", "nombre": "Hoja de proveedores", "plan": "gratis",
          "alcances": ["ruc"], "consultas_por_minuto": 60,
          "cuota": {"limite": 100, "usada": 37, "restante": 63, "reinicio": "2026-11-01"}}}}}, 401: _RESP_COMUNES[401]})
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
