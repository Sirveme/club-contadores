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
    # distrito, ruc, razon_social, tipo, giro, fecha_inscripcion, direccion, ciiu, regimen
    ("MIRAFLORES", "20601234501", "INVERSIONES AURORA SAC", "juridica",
     "Venta al por menor en bodegas", dt.date(2026, 7, 3),
     "AV. LARCO 345, MIRAFLORES", "4711", "Régimen General / MYPE"),
    ("MIRAFLORES", "20601234502", "ESTUDIO CONTABLE DELTA EIRL", "juridica",
     "Actividades de contabilidad y auditoria", dt.date(2026, 7, 8),
     "CALLE SCHELL 210, MIRAFLORES", "6920", "Régimen Especial (RER)"),
    ("MIRAFLORES", "10456789012", "QUISPE ROJAS MARIA ELENA", "natural",
     "Servicios de peluqueria", dt.date(2026, 7, 12), None, "9602", "RUS"),
    ("MIRAFLORES", "20601234503", "PANIFICADORA EL SOL SAC", "juridica",
     "Elaboracion de productos de panaderia", dt.date(2026, 6, 21),
     "AV. BENAVIDES 1200, MIRAFLORES", "1071", None),
    ("SANTIAGO DE SURCO", "20601234510", "TECH ANDINA SAC", "juridica",
     "Programacion informatica", dt.date(2026, 7, 5),
     "AV. EL POLO 500, SURCO", "6201", "Régimen General / MYPE"),
    ("SANTIAGO DE SURCO", "10556677889", "TORRES LEON JUAN CARLOS", "natural",
     "Servicios de transporte de carga", dt.date(2026, 7, 9), None, "4923", "Régimen Especial (RER)"),
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
    # mes_inscripcion es el campo COMUN ('YYYY-MM'); comparacion de texto ordena
    # cronologicamente. Ultimos 3 meses = actual + 2 previos.
    rows = await _pool.fetch(
        f"""
        SELECT mes_inscripcion AS mes, COUNT(*) AS n
        FROM nuevos_negocios
        WHERE {where}
          AND mes_inscripcion >= to_char((CURRENT_DATE - INTERVAL '2 months'), 'YYYY-MM')
        GROUP BY mes_inscripcion
        ORDER BY mes_inscripcion
        """,
        arg,
    )
    return _formatear_meses({r["mes"]: r["n"] for r in rows if r["mes"]})


async def lista_negocios(ubigeo: str, distrito: str, limit: int = 60) -> list[dict]:
    if demo_mode():
        out = []
        for n in _demo_negocios_por_distrito(distrito):
            out.append({
                "ruc": n[1], "razon_social": n[2], "tipo": n[3], "giro": n[4],
                "fecha_inscripcion": n[5].strftime("%d/%m/%Y"),
                "direccion": n[6], "ciiu": n[7], "regimen": n[8],
            })
        return out

    assert _pool is not None
    where, arg = _distrito_filter(ubigeo, distrito, alias="nn")
    # descripcion -> giro (lo que espera el frontend). Direccion armada por JOIN
    # a los catalogos SUNAT (tipo_via/tipo_zona -> denominacion). Naturales: los
    # campos de direccion son NULL, concat_ws los ignora y direccion queda "".
    rows = await _pool.fetch(
        f"""
        SELECT nn.ruc, nn.razon_social, nn.tipo, nn.ciiu,
               nn.descripcion AS giro, nn.nombre_comercial, nn.regimen,
               COALESCE(to_char(nn.fecha_inscripcion, 'DD/MM/YYYY'), nn.mes_inscripcion)
                   AS fecha_inscripcion,
               NULLIF(trim(concat_ws(' ',
                   v.denominacion, nn.nombre_via, nn.numero,
                   NULLIF(nn.interior, ''), z.denominacion, nn.nombre_zona
               )), '') AS direccion
        FROM nuevos_negocios nn
        LEFT JOIN cat_via  v ON v.codigo = nn.tipo_via
        LEFT JOIN cat_zona z ON z.codigo = nn.tipo_zona
        WHERE {where}
        ORDER BY nn.mes_inscripcion DESC NULLS LAST, nn.creado_en DESC
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
def _distrito_filter(ubigeo: str, distrito: str, alias: str = ""):
    """Prefiere ubigeo (exacto); cae a nombre de distrito (case-insensitive)."""
    p = f"{alias}." if alias else ""
    if ubigeo:
        return f"{p}ubigeo = $1", ubigeo
    return f"upper({p}distrito) = upper($1)", (distrito or "")


def _formatear_meses(buckets: dict[str, int]) -> list[dict]:
    meses_es = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]
    out = []
    for k in sorted(buckets):
        y, m = k.split("-")
        out.append({"mes": meses_es[int(m) - 1], "anio": y, "n": buckets[k]})
    return out
