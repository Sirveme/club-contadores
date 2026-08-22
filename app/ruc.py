"""
Validacion de RUC contra el PADRON de SUNAT (apis.net.pe, la misma que alerta.pe).

REGLA (z-8): la validacion REALMENTE bloquea. El flujo depende del resultado de la
API: si SUNAT no reconoce el RUC, NO se deja avanzar ni se inserta el lead.

  - RUC existe            -> ok=True + razon_social (se muestra como confirmacion)
  - RUC no existe (404)   -> ok=False, motivo='no_encontrado'  (mensaje amable)
  - No se pudo verificar  -> ok=False, motivo='no_verificable' (API caida / sin token)
                             ...salvo que RUC_VALIDACION_ESTRICTA=0 (modo permisivo).

IMPORTANTE: sin APIS_NET_PE_TOKEN no se puede verificar contra SUNAT. En modo
estricto (por defecto) eso BLOQUEA los registros: hay que setear el token en
Railway. Se avisa con un WARNING al arrancar.
"""
from __future__ import annotations

import os
import logging

import httpx

log = logging.getLogger("uvicorn.error")

APIS_NET_PE_TOKEN = os.getenv("APIS_NET_PE_TOKEN", "").strip()
APIS_NET_PE_URL = os.getenv(
    "APIS_NET_PE_URL", "https://api.apis.net.pe/v2/sunat/ruc"
)
# Estricto por defecto: si no se puede confirmar contra SUNAT, no pasa.
RUC_VALIDACION_ESTRICTA = os.getenv("RUC_VALIDACION_ESTRICTA", "1").lower() not in (
    "0", "false", "no",
)

MSG_NO_ENCONTRADO = "No encontramos ese RUC en SUNAT, por favor revísalo."
MSG_NO_VERIFICABLE = ("No pudimos verificar tu RUC en este momento. "
                      "Vuelve a intentarlo en unos segundos.")


def validacion_activa() -> bool:
    """True si realmente se puede consultar el padron de SUNAT."""
    return bool(APIS_NET_PE_TOKEN)


def aviso_config() -> None:
    if not APIS_NET_PE_TOKEN:
        log.warning(
            "APIS_NET_PE_TOKEN NO configurado: no se puede validar el RUC contra SUNAT. "
            "Con RUC_VALIDACION_ESTRICTA=%s los registros %s.",
            "1" if RUC_VALIDACION_ESTRICTA else "0",
            "quedaran BLOQUEADOS" if RUC_VALIDACION_ESTRICTA else "pasaran sin verificar",
        )


def ruc_formato_valido(ruc: str) -> bool:
    ruc = (ruc or "").strip()
    if not (ruc.isdigit() and len(ruc) == 11):
        return False
    # Prefijos SUNAT validos: 10 (natural), 15/17 (otros), 20 (juridica).
    return ruc[:2] in ("10", "15", "17", "20")


def tipo_por_ruc(ruc: str) -> str:
    return "juridica" if ruc.startswith("20") else "natural"


def _permisivo(ruc: str, tipo: str) -> dict:
    """Solo si RUC_VALIDACION_ESTRICTA=0: deja pasar sin confirmar en SUNAT."""
    return {"ok": True, "ruc": ruc, "razon_social": None, "tipo": tipo,
            "direccion": None, "distrito": None, "fuente": "formato"}


def _bloquear(motivo: str, mensaje: str) -> dict:
    return {"ok": False, "error": mensaje, "motivo": motivo}


async def validar_ruc(ruc: str) -> dict:
    ruc = (ruc or "").strip()
    if not ruc_formato_valido(ruc):
        return _bloquear("formato",
                         "El RUC debe tener 11 dígitos y empezar en 10, 15, 17 o 20.")

    tipo = tipo_por_ruc(ruc)

    # Sin token no hay forma de consultar el padron.
    if not APIS_NET_PE_TOKEN:
        log.warning("RUC %s no verificable: falta APIS_NET_PE_TOKEN.", ruc)
        if RUC_VALIDACION_ESTRICTA:
            return _bloquear("no_verificable", MSG_NO_VERIFICABLE)
        return _permisivo(ruc, tipo)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                APIS_NET_PE_URL,
                params={"numero": ruc},
                headers={"Authorization": f"Bearer {APIS_NET_PE_TOKEN}",
                         "Accept": "application/json"},
            )
    except Exception as e:
        log.warning("RUC %s: fallo consultando SUNAT (%s: %s)", ruc, type(e).__name__, e)
        if RUC_VALIDACION_ESTRICTA:
            return _bloquear("no_verificable", MSG_NO_VERIFICABLE)
        return _permisivo(ruc, tipo)

    # 404/422 -> SUNAT no lo reconoce: BLOQUEA.
    if r.status_code in (404, 422):
        return _bloquear("no_encontrado", MSG_NO_ENCONTRADO)

    if r.status_code == 200:
        try:
            d = r.json() or {}
        except Exception:
            d = {}
        razon = (d.get("razonSocial") or d.get("nombre") or "").strip()
        if not razon:
            # 200 pero sin razon social = no esta en el padron.
            return _bloquear("no_encontrado", MSG_NO_ENCONTRADO)
        return {
            "ok": True,
            "ruc": ruc,
            "razon_social": razon,
            "tipo": tipo,
            "direccion": (d.get("direccion") or "").strip() or None,
            "distrito": (d.get("distrito") or "").strip() or None,
            "estado": (d.get("estado") or "").strip() or None,
            "condicion": (d.get("condicion") or "").strip() or None,
            "fuente": "api",
        }

    # 401/403/429/5xx -> problema del servicio, no del RUC.
    log.warning("RUC %s: SUNAT respondio %s", ruc, r.status_code)
    if RUC_VALIDACION_ESTRICTA:
        return _bloquear("no_verificable", MSG_NO_VERIFICABLE)
    return _permisivo(ruc, tipo)


# ============================================================================
# CONSULTA para la landing /nuevos-negocios: NO bloquea; clasifica contador por
# CIIU (6920 principal o secundario). Un fallo de API NUNCA rechaza (fallback).
# ============================================================================
CIIU_CONTADOR = "6920"  # Actividades de contabilidad, teneduria y auditoria


async def _fetch_ruc_api(ruc: str) -> dict:
    """Golpea apis.net.pe y devuelve el JSON (dict) crudo. Lanza en fallo/no-200.
    Aislada a proposito: en pruebas se reemplaza para simular la API."""
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            APIS_NET_PE_URL, params={"numero": ruc},
            headers={"Authorization": f"Bearer {APIS_NET_PE_TOKEN}",
                     "Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"status {r.status_code}")
    return r.json() or {}


def _extraer_ciiu(d: dict) -> list[str]:
    """Extrae codigos CIIU del JSON (tolerante a las varias formas de apis.net.pe)."""
    out: list[str] = []

    def add(v):
        s = "".join(c for c in str(v or "") if c.isdigit())
        if s:
            out.append(s)

    for k in ("ciiu", "CIIU", "actividadEconomica", "codigoCiiu"):
        if d.get(k):
            add(d[k])
    for k in ("actividadesEconomicas", "ciiuList", "ciius"):
        val = d.get(k)
        if isinstance(val, list):
            for it in val:
                if isinstance(it, dict):
                    add(it.get("ciiu") or it.get("codigo") or it.get("cod"))
                else:
                    add(it)
    return out


async def consultar_ruc_contador(ruc: str) -> dict:
    """Para la landing. Devuelve estado:
       'contador'      -> API confirma CIIU 6920 (principal o secundario)
       'no_contador'   -> API trae CIIU y ninguno es 6920
       'no_verificable'-> sin token / API caida / timeout / 404 / sin CIIU util
                          (NUNCA rechaza: el llamador deja continuar con fallback)
    """
    ruc = (ruc or "").strip()
    base = {"estado": "no_verificable", "razon_social": None, "distrito": None,
            "provincia": None, "departamento": None, "ubigeo": None, "ciiu": []}
    if not APIS_NET_PE_TOKEN:
        return base
    try:
        d = await _fetch_ruc_api(ruc)
    except Exception as e:
        log.warning("nn: RUC %s no verificable via API (%s)", ruc, type(e).__name__)
        return base

    razon = (d.get("razonSocial") or d.get("nombre") or "").strip()
    if not razon:
        return base
    ciius = _extraer_ciiu(d)
    ubigeo = "".join(c for c in str(d.get("ubigeo") or "") if c.isdigit()) or None
    if ubigeo:
        ubigeo = ubigeo.zfill(6)[-6:]
    info = {"razon_social": razon,
            "distrito": (d.get("distrito") or "").strip() or None,
            "provincia": (d.get("provincia") or "").strip() or None,
            "departamento": (d.get("departamento") or "").strip() or None,
            "ubigeo": ubigeo, "ciiu": ciius}
    if any(c.startswith(CIIU_CONTADOR) for c in ciius):
        return {"estado": "contador", **info}
    if ciius:
        return {"estado": "no_contador", **info}
    # 200 con razon social pero sin CIIU util -> no podemos clasificar: fallback.
    return {"estado": "no_verificable", **info}
