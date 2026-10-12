"""Verificador multi-padron (club.perusistemas.pro/verificador).

Pega un RUC o una lista y devuelve, por RUC, el estado y la condicion de domicilio con
su semaforo, mas una columna por cada padron del catalogo (`padrones`): SSCO, contador,
negocio nuevo... Agregar un padron = una fila en `padrones` + sus marcas; esta pantalla
no cambia.

Reglas:
- El padron general (18 M) se consulta SOLO por RUC. La busqueda por NOMBRE existe
  unicamente dentro del SSCO (lista publica y finita, publicada para el cotejo).
- Sin pistas de la fuente: se muestra "Datos al dd/mm/aaaa", nunca el nombre de la fuente.
- Topes desde el dia uno (por tanda y por IP al dia), configurables.

Configuracion (variables de entorno):
  VERIFICADOR_ABIERTO=1                 sin esto, /verificador dice "muy pronto"
  VERIFICADOR_ESQUEMA=public            prueba_padron para ensayar
  VERIFICADOR_MAX_TANDA=50  VERIFICADOR_MAX_DIA_IP=500
  VERIFICADOR_LISTA_REQUIERE_CUENTA=0   1 = la lista pide sesion (1 RUC siempre libre)
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import club, db
from . import padron as P

router = APIRouter()
ABIERTO = os.getenv("VERIFICADOR_ABIERTO", "0").strip() == "1"
ESQUEMA = os.getenv("VERIFICADOR_ESQUEMA", "public").strip()
if not re.fullmatch(r"[a-z_][a-z0-9_]*", ESQUEMA):
    raise RuntimeError("VERIFICADOR_ESQUEMA invalido")
MAX_TANDA = int(os.getenv("VERIFICADOR_MAX_TANDA", "50") or 50)
MAX_DIA_IP = int(os.getenv("VERIFICADOR_MAX_DIA_IP", "500") or 500)
LISTA_REQUIERE_CUENTA = os.getenv("VERIFICADOR_LISTA_REQUIERE_CUENTA", "0").strip() == "1"
ANEXOS_MUESTRA = 5
_RUC11 = re.compile(r"(?<!\d)\d{11}(?!\d)")


def extraer_rucs(texto: str) -> tuple[list[str], list[str]]:
    """RUC de un texto pegado (saltos, comas, espacios, tabs de Excel), sin repetir y en
    el orden en que vinieron. -> (rucs, descartados: 11 digitos que no son RUC)."""
    vistos, rucs, malos = set(), [], []
    for t in _RUC11.findall(texto or ""):
        if t in vistos:
            continue
        vistos.add(t)
        (rucs if P.RUC_RE.match(t) else malos).append(t)
    return rucs, malos


def _fecha(d) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


async def _catalogo(conn) -> list[dict]:
    return [dict(r) for r in await conn.fetch(
        f"SELECT codigo, nombre, columna, severidad, origen, corte, orden, umbral_ambar_dias, umbral_rojo_dias "
        f"FROM {ESQUEMA}.padrones WHERE activo ORDER BY orden")]


async def consultar(rucs: list[str], iso: bool = False, anexos_max: int = ANEXOS_MUESTRA) -> dict:
    """Una fila por RUC (en el orden pedido) + las columnas del catalogo + los cortes.
    iso=True devuelve las fechas como AAAA-MM-DD (API); por defecto dd/mm/aaaa (pantalla)."""
    _fecha = (lambda d: d.isoformat() if d else None) if iso else globals()["_fecha"]
    async with db._pool.acquire() as conn:
        cat = await _catalogo(conn)
        filas = {r["ruc"]: dict(r) for r in await conn.fetch(
            f"SELECT p.ruc, p.razon_social, p.estado, p.condicion, p.ubigeo, p.domicilio, "
            f"u.departamento, u.provincia, u.distrito FROM {ESQUEMA}.padron_reducido p "
            f"LEFT JOIN public.cat_ubigeo u ON u.ubigeo = p.ubigeo WHERE p.ruc = ANY($1::text[])", rucs)}
        marcas: dict[str, dict] = {}
        for r in await conn.fetch(f"SELECT ruc, padron, desde, detalle FROM {ESQUEMA}.v_ruc_marcas "
                                  f"WHERE ruc = ANY($1::text[])", rucs):
            marcas.setdefault(r["ruc"], {})[r["padron"]] = {
                "desde": _fecha(r["desde"]), "detalle": json.loads(r["detalle"]) if r["detalle"] else {}}
        anexos: dict[str, dict] = {}
        for r in await conn.fetch(
                f"SELECT ruc, count(*) OVER (PARTITION BY ruc) AS n, domicilio, "
                f"row_number() OVER (PARTITION BY ruc ORDER BY domicilio) AS i "
                f"FROM {ESQUEMA}.padron_anexos WHERE ruc = ANY($1::text[])", rucs):
            a = anexos.setdefault(r["ruc"], {"n": r["n"], "lista": []})
            if r["i"] <= anexos_max:
                a["lista"].append(r["domicilio"])
    columnas = [c for c in cat if c["origen"] in ("marcas", "vista")]
    alerta = {c["codigo"] for c in columnas if c["severidad"] == "alerta"}
    out = []
    for ruc in rucs:
        f = filas.get(ruc)
        m = marcas.get(ruc, {})
        if not f:
            out.append({"ruc": ruc, "encontrado": False, "semaforo": "gris", "marcas": m})
            continue
        e_nom, e_sem = P.ESTADOS.get(f["estado"], (f["estado"].title(), "gris"))
        c_nom, c_sem = P.CONDICIONES.get(f["condicion"], (f["condicion"].title(), "gris"))
        sem = P.semaforo_fila(f["estado"], f["condicion"])
        if alerta & m.keys():
            sem = "rojo"
        out.append({"ruc": ruc, "encontrado": True, "razon_social": f["razon_social"],
                    "estado": {"valor": f["estado"], "nombre": e_nom, "semaforo": e_sem},
                    "condicion": {"valor": f["condicion"], "nombre": c_nom, "semaforo": c_sem},
                    "domicilio": f["domicilio"], "semaforo": sem, "marcas": m,
                    "ubigeo": (f["ubigeo"] or "").strip() or None,
                    "distrito": ({"distrito": f["distrito"], "provincia": f["provincia"], "departamento": f["departamento"]}
                                 if f["distrito"] else None),
                    "anexos": anexos.get(ruc, {"n": 0, "lista": []})})
    maestra = next((c for c in cat if c["codigo"] == "padron_reducido"), None)
    return {"filas": out,
            "columnas": [{"codigo": c["codigo"], "columna": c["columna"], "nombre": c["nombre"],
                          "severidad": c["severidad"], "corte": _fecha(c["corte"])} for c in columnas],
            "datos_al": _fecha(maestra["corte"]) if maestra else None}


async def _uso_hoy(ip: str | None) -> int:
    if not ip:
        return 0
    return await db._pool.fetchval(
        f"SELECT coalesce(sum(rucs), 0) FROM {ESQUEMA}.verificador_uso "
        f"WHERE ip = $1::inet AND creado_en > date_trunc('day', now())", ip)


async def _registrar(ip, persona_id, n: int, origen: str):
    await db._pool.execute(
        f"INSERT INTO {ESQUEMA}.verificador_uso (ip, persona_id, rucs, origen) VALUES ($1::inet, $2, $3, $4)",
        ip or None, persona_id, n, origen)


def _cerrado():
    return JSONResponse({"ok": False, "error": "El Verificador estará disponible muy pronto."}, status_code=403)


@router.post("/api/verificador")
async def api_verificar(payload: dict, request: Request):
    if not ABIERTO:
        return _cerrado()
    rucs, malos = extraer_rucs(str(payload.get("texto") or ""))
    if not rucs:
        return JSONResponse({"ok": False, "error": "No encontramos ningún RUC. Un RUC tiene 11 dígitos y empieza "
                                                   "en 10, 15, 17 o 20.", "descartados": malos}, status_code=422)
    s = await club.socio_actual(request)
    if len(rucs) > 1 and LISTA_REQUIERE_CUENTA and not s:
        return JSONResponse({"ok": False, "accion": "entrar",
                             "error": "Para verificar una lista, entra a tu cuenta. Un RUC suelto no la necesita."},
                            status_code=401)
    recortados = rucs[MAX_TANDA:]
    rucs = rucs[:MAX_TANDA]
    ip = club._client_ip(request)
    if await _uso_hoy(ip) + len(rucs) > MAX_DIA_IP:
        return JSONResponse({"ok": False, "error": f"Llegaste al tope de hoy ({MAX_DIA_IP} RUC). "
                                                   "Vuelve mañana o escríbenos por WhatsApp."}, status_code=429)
    res = await consultar(rucs)
    await _registrar(ip, (s or {}).get("persona_id"), len(rucs), "uno" if len(rucs) == 1 else "lista")
    return JSONResponse({"ok": True, **res, "descartados": malos, "recortados": len(recortados),
                         "tope_tanda": MAX_TANDA})


@router.post("/api/verificador/ssco")
async def api_ssco_nombre(payload: dict, request: Request):
    """Busqueda por NOMBRE del representante o razon social, SOLO dentro del SSCO."""
    if not ABIERTO:
        return _cerrado()
    q = re.sub(r"\s+", " ", str(payload.get("q") or "")).strip().upper()
    if len(q) < 4:
        return JSONResponse({"ok": False, "error": "Escribe al menos 4 letras del nombre."}, status_code=422)
    ip = club._client_ip(request)
    if await _uso_hoy(ip) + 1 > MAX_DIA_IP:
        return JSONResponse({"ok": False, "error": f"Llegaste al tope de hoy ({MAX_DIA_IP})."}, status_code=429)
    patron = "%" + q.replace("\\", "").replace("%", "").replace("_", " ") + "%"
    rows = await db._pool.fetch(
        f"""SELECT ruc, desde, detalle FROM {ESQUEMA}.ruc_marcas m
            WHERE padron = 'ssco' AND (upper(detalle->>'razon_social') LIKE $1 OR EXISTS (
                  SELECT 1 FROM jsonb_array_elements(m.detalle->'representantes') r
                  WHERE upper(r->>'nombre') LIKE $1))
            ORDER BY desde DESC NULLS LAST LIMIT 21""", patron)
    await _registrar(ip, None, 1, "ssco_nombre")
    corte = await db._pool.fetchval(f"SELECT corte FROM {ESQUEMA}.padrones WHERE codigo = 'ssco'")
    return JSONResponse({"ok": True, "ssco_al": _fecha(corte), "mas": len(rows) > 20, "resultados": [
        {"ruc": r["ruc"], "desde": _fecha(r["desde"]), **json.loads(r["detalle"])} for r in rows[:20]]})


@router.get("/verificador", response_class=HTMLResponse)
async def pagina(request: Request):
    s = await club.socio_actual(request)
    ctx = {"s": s, "inicio": club.inicio(request)}
    if not ABIERTO:
        return club.templates.TemplateResponse(request, "club/pronto.html",
                                               {**ctx, "que": "El Verificador", "sig": "", "psp_whatsapp": club.PSP_WHATSAPP})
    async with db._pool.acquire() as conn:
        cat = await _catalogo(conn)
    maestra = next((c for c in cat if c["codigo"] == "padron_reducido"), None)
    ssco = next((c for c in cat if c["codigo"] == "ssco"), None)
    return club.templates.TemplateResponse(request, "club/verificador.html", {
        **ctx, "tope": MAX_TANDA, "datos_al": _fecha(maestra["corte"]) if maestra else None,
        "ssco_al": _fecha(ssco["corte"]) if ssco else None})


club.templates.env.globals["verificador_abierto"] = lambda: ABIERTO


def tarjeta_tablero() -> dict | None:
    """Cambios para encender la tarjeta SSCO del tablero como Verificador (solo si esta abierto)."""
    if not ABIERTO:
        return None
    return {"ssco": {"estado": "activa", "url": "/verificador", "nombre": "Verificador de RUC",
                     "sub": "SSCO, no habidos y bajas, de un tiro", "cta": "Verificar ahora", "efecto": "escribe",
                     "ben": "Pega tus RUC y mira al instante quién es SSCO, no habido o está de baja.",
                     "frases": ["SSCO con su resolución", f"Hasta {MAX_TANDA} RUC por vez", "Sin crear cuenta",
                                "Filtra y ordena al vuelo"]}}


# --- Frescura (panel admin; /panel/* ya exige ADMIN_DNI) ---------------------------------
def frescura(cat: list[dict], hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    out = []
    for c in cat:
        dias = (hoy - c["corte"]).days if c["corte"] else None
        if dias is None:
            sem = "rojo"
        elif dias >= c["umbral_rojo_dias"]:
            sem = "rojo"
        elif dias >= c["umbral_ambar_dias"]:
            sem = "ambar"
        else:
            sem = "verde"
        out.append({**c, "dias": dias, "semaforo": sem, "corte_txt": _fecha(c["corte"]) or "sin cargar"})
    return out


@router.get("/panel/frescura", response_class=HTMLResponse)
async def panel_frescura(request: Request):
    async with db._pool.acquire() as conn:
        cat = await _catalogo(conn)
    return club.templates.TemplateResponse(request, "club/frescura.html", {
        "s": await club.socio_actual(request), "inicio": club.inicio(request), "filas": frescura(cat),
        "esquema": ESQUEMA})
