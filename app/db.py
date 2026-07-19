"""
Acceso a PostgreSQL con asyncpg.

Si no hay DATABASE_URL configurada, la app arranca en MODO DEMO usando un
pequeno dataset en memoria para poder probar el embudo en el celular sin BD.
En produccion (Railway) basta con setear DATABASE_URL.
"""
from __future__ import annotations

import os
import datetime as dt
from typing import Optional

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_pool: Optional[asyncpg.Pool] = None


def demo_mode() -> bool:
    return not DATABASE_URL


# --- Datos DEMO (solo cuando no hay DATABASE_URL) ---------------------------
_DEMO_NEGOCIOS = [
    # distrito, ruc, razon_social, tipo, giro, fecha_inscripcion, direccion
    ("MIRAFLORES", "20601234501", "INVERSIONES AURORA SAC", "juridica",
     "Venta al por menor en bodegas", dt.date(2026, 7, 3),
     "AV. LARCO 345, MIRAFLORES", "4711"),
    ("MIRAFLORES", "20601234502", "ESTUDIO CONTABLE DELTA EIRL", "juridica",
     "Actividades de contabilidad y auditoria", dt.date(2026, 7, 8),
     "CALLE SCHELL 210, MIRAFLORES", "6920"),
    ("MIRAFLORES", "10456789012", "QUISPE ROJAS MARIA ELENA", "natural",
     "Servicios de peluqueria", dt.date(2026, 7, 12), None, "9602"),
    ("MIRAFLORES", "20601234503", "PANIFICADORA EL SOL SAC", "juridica",
     "Elaboracion de productos de panaderia", dt.date(2026, 6, 21),
     "AV. BENAVIDES 1200, MIRAFLORES", "1071"),
    ("SANTIAGO DE SURCO", "20601234510", "TECH ANDINA SAC", "juridica",
     "Programacion informatica", dt.date(2026, 7, 5),
     "AV. EL POLO 500, SURCO", "6201"),
    ("SANTIAGO DE SURCO", "10556677889", "TORRES LEON JUAN CARLOS", "natural",
     "Servicios de transporte de carga", dt.date(2026, 7, 9), None, "4923"),
]


def _demo_negocios_por_distrito(distrito: str):
    d = (distrito or "").strip().upper()
    return [n for n in _DEMO_NEGOCIOS if n[0] == d]


# --- Ciclo de vida del pool -------------------------------------------------
async def connect() -> None:
    global _pool
    if demo_mode():
        return
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# --- Consultas del embudo ---------------------------------------------------
async def conteo_por_mes(ubigeo: str, distrito: str) -> list[dict]:
    """Conteo de nuevos negocios de los ultimos 3 meses para el distrito."""
    if demo_mode():
        negocios = _demo_negocios_por_distrito(distrito)
        buckets: dict[str, int] = {}
        for n in negocios:
            buckets[n[5].strftime("%Y-%m")] = buckets.get(n[5].strftime("%Y-%m"), 0) + 1
        return _formatear_meses(buckets)

    assert _pool is not None
    where, arg = _distrito_filter(ubigeo, distrito)
    rows = await _pool.fetch(
        f"""
        SELECT to_char(date_trunc('month', fecha_inscripcion), 'YYYY-MM') AS mes,
               COUNT(*) AS n
        FROM nuevos_negocios
        WHERE {where}
          AND fecha_inscripcion >= (CURRENT_DATE - INTERVAL '3 months')
        GROUP BY 1 ORDER BY 1
        """,
        arg,
    )
    return _formatear_meses({r["mes"]: r["n"] for r in rows})


async def lista_negocios(ubigeo: str, distrito: str, limit: int = 60) -> list[dict]:
    if demo_mode():
        out = []
        for n in _demo_negocios_por_distrito(distrito):
            out.append({
                "ruc": n[1], "razon_social": n[2], "tipo": n[3], "giro": n[4],
                "fecha_inscripcion": n[5].strftime("%d/%m/%Y"),
                "direccion": n[6], "ciiu": n[7],
            })
        return out

    assert _pool is not None
    where, arg = _distrito_filter(ubigeo, distrito)
    rows = await _pool.fetch(
        f"""
        SELECT ruc, razon_social, tipo, ciiu, giro, direccion,
               to_char(fecha_inscripcion, 'DD/MM/YYYY') AS fecha_inscripcion
        FROM nuevos_negocios
        WHERE {where}
        ORDER BY fecha_inscripcion DESC NULLS LAST
        LIMIT $2
        """,
        arg, limit,
    )
    return [dict(r) for r in rows]


async def guardar_inscripcion(data: dict) -> None:
    if demo_mode():
        return
    assert _pool is not None
    await _pool.execute(
        """
        INSERT INTO inscripciones
            (nombre, ruc, razon_social, distrito, ubigeo, whatsapp, email, origen, user_agent)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (ruc, distrito) WHERE ruc IS NOT NULL
        DO UPDATE SET whatsapp = EXCLUDED.whatsapp,
                      email    = EXCLUDED.email,
                      creado_en = now()
        """,
        data.get("nombre"), data.get("ruc"), data.get("razon_social"),
        data.get("distrito"), data.get("ubigeo"), data.get("whatsapp"),
        data.get("email"), data.get("origen"), data.get("user_agent"),
    )


async def guardar_push(sub: dict, ruc: str | None, distrito: str | None) -> None:
    if demo_mode():
        return
    assert _pool is not None
    keys = sub.get("keys", {})
    await _pool.execute(
        """
        INSERT INTO push_subscriptions (endpoint, p256dh, auth, ruc, distrito)
        VALUES ($1,$2,$3,$4,$5)
        ON CONFLICT (endpoint) DO UPDATE SET ruc = EXCLUDED.ruc, distrito = EXCLUDED.distrito
        """,
        sub.get("endpoint"), keys.get("p256dh"), keys.get("auth"), ruc, distrito,
    )


# --- Helpers ----------------------------------------------------------------
def _distrito_filter(ubigeo: str, distrito: str):
    """Prefiere ubigeo (exacto); cae a nombre de distrito en mayusculas."""
    if ubigeo:
        return "ubigeo = $1", ubigeo
    return "upper(distrito) = upper($1)", (distrito or "")


def _formatear_meses(buckets: dict[str, int]) -> list[dict]:
    meses_es = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]
    out = []
    for k in sorted(buckets):
        y, m = k.split("-")
        out.append({"mes": meses_es[int(m) - 1], "anio": y, "n": buckets[k]})
    return out
