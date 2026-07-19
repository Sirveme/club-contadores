"""
Validacion de RUC.

Intenta consultar apis.net.pe (misma API que alerta.pe) para traer/confirmar
la razon social. Si no hay token o la API falla, cae a una validacion de
FORMATO (11 digitos, prefijo valido) para NO bloquear la captura del lead.
"""
from __future__ import annotations

import os
import httpx

APIS_NET_PE_TOKEN = os.getenv("APIS_NET_PE_TOKEN", "").strip()
APIS_NET_PE_URL = os.getenv(
    "APIS_NET_PE_URL", "https://api.apis.net.pe/v2/sunat/ruc"
)


def ruc_formato_valido(ruc: str) -> bool:
    ruc = (ruc or "").strip()
    if not (ruc.isdigit() and len(ruc) == 11):
        return False
    # Prefijos SUNAT validos: 10 (persona natural), 15/17 (extranjeros/otros),
    # 20 (persona juridica).
    return ruc[:2] in ("10", "15", "17", "20")


def tipo_por_ruc(ruc: str) -> str:
    return "juridica" if ruc.startswith("20") else "natural"


async def validar_ruc(ruc: str) -> dict:
    """
    Devuelve:
      { ok: bool, ruc, razon_social, tipo, direccion, distrito,
        fuente: 'api'|'formato', error? }
    """
    ruc = (ruc or "").strip()
    if not ruc_formato_valido(ruc):
        return {"ok": False, "error": "El RUC debe tener 11 digitos y empezar en 10, 15, 17 o 20."}

    tipo = tipo_por_ruc(ruc)

    if APIS_NET_PE_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    APIS_NET_PE_URL,
                    params={"numero": ruc},
                    headers={
                        "Authorization": f"Bearer {APIS_NET_PE_TOKEN}",
                        "Accept": "application/json",
                    },
                )
            if r.status_code == 200:
                d = r.json()
                razon = (d.get("razonSocial") or d.get("nombre") or "").strip()
                if razon:
                    return {
                        "ok": True,
                        "ruc": ruc,
                        "razon_social": razon,
                        "tipo": tipo,
                        "direccion": (d.get("direccion") or "").strip() or None,
                        "distrito": (d.get("distrito") or "").strip() or None,
                        "fuente": "api",
                    }
        except Exception:
            # Cae a validacion por formato: no quemamos el lead por un timeout.
            pass

    # Fallback por formato: valido pero sin razon social confirmada.
    return {
        "ok": True,
        "ruc": ruc,
        "razon_social": None,
        "tipo": tipo,
        "direccion": None,
        "distrito": None,
        "fuente": "formato",
    }
