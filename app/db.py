"""
Acceso a PostgreSQL con asyncpg.

Si no hay DATABASE_URL configurada, la app arranca en MODO DEMO usando un
pequeno dataset en memoria para poder probar el embudo en el celular sin BD.
En produccion (Railway) basta con setear DATABASE_URL.
"""
from __future__ import annotations

import os
import re
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
     "AV. LARCO 345, MIRAFLORES", "4711", "Régimen General"),
    ("MIRAFLORES", "20601234502", "ESTUDIO CONTABLE DELTA EIRL", "juridica",
     "Actividades de contabilidad y auditoria", dt.date(2026, 7, 8),
     "CALLE SCHELL 210, MIRAFLORES", "6920", "Régimen MYPE Tributario (RMT)"),
    ("MIRAFLORES", "10456789012", "QUISPE ROJAS MARIA ELENA", "natural",
     "Servicios de peluqueria", dt.date(2026, 7, 12), None, "9602", "RUS"),
    ("MIRAFLORES", "20601234503", "PANIFICADORA EL SOL SAC", "juridica",
     "Elaboracion de productos de panaderia", dt.date(2026, 6, 21),
     "AV. BENAVIDES 1200, MIRAFLORES", "1071", None),
    ("SANTIAGO DE SURCO", "20601234510", "TECH ANDINA SAC", "juridica",
     "Programacion informatica", dt.date(2026, 7, 5),
     "AV. EL POLO 500, SURCO", "6201", "Régimen MYPE Tributario (RMT)"),
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


async def lista_negocios(ubigeo: str, distrito: str, mes: str = "",
                         limit: int = 500) -> list[dict]:
    """Lista de negocios del distrito. Si `mes` ('YYYY-MM') viene, filtra por ese
    mes (mismo filtro que el conteo -> el numero del panorama cuadra con la lista)."""
    if demo_mode():
        out = []
        for n in _demo_negocios_por_distrito(distrito):
            if mes and n[5].strftime("%Y-%m") != mes:
                continue
            out.append({
                "ruc": n[1], "razon_social": n[2], "tipo": n[3], "giro": n[4],
                "fecha_inscripcion": n[5].strftime("%d/%m/%Y"),
                "direccion": n[6], "ciiu": n[7], "regimen": n[8],
            })
        return out

    assert _pool is not None
    where, arg = _distrito_filter(ubigeo, distrito, alias="nn")
    args = [arg]
    mes_sql = ""
    if mes:
        args.append(mes)
        mes_sql = f"AND nn.mes_inscripcion = ${len(args)}"
    args.append(limit)
    limit_ph = f"${len(args)}"
    # Se traen las PARTES de la direccion + denominaciones; la direccion legible
    # (con via abreviada y limpia) se arma en Python (_construir_direccion).
    rows = await _pool.fetch(
        f"""
        SELECT nn.ruc, nn.razon_social, nn.tipo, nn.ciiu,
               nn.descripcion AS giro, nn.nombre_comercial, nn.regimen,
               COALESCE(to_char(nn.fecha_inscripcion, 'DD/MM/YYYY'), nn.mes_inscripcion)
                   AS fecha_inscripcion,
               v.denominacion AS via_den, nn.nombre_via, nn.numero, nn.interior,
               nn.numero_departamento, nn.mz, nn.numero_lote,
               z.denominacion AS zona_den, nn.nombre_zona
        FROM nuevos_negocios nn
        LEFT JOIN cat_via  v ON v.codigo = nn.tipo_via
        LEFT JOIN cat_zona z ON z.codigo = nn.tipo_zona
        WHERE {where} {mes_sql}
        ORDER BY nn.fecha_inscripcion DESC NULLS LAST, nn.creado_en DESC
        LIMIT {limit_ph}
        """,
        *args,
    )
    out = []
    for r in rows:
        out.append({
            "ruc": r["ruc"], "razon_social": r["razon_social"], "tipo": r["tipo"],
            "giro": r["giro"], "regimen": r["regimen"],
            "fecha_inscripcion": r["fecha_inscripcion"],
            "direccion": _construir_direccion(r),
        })
    return out


async def upsert_lead(data: dict) -> dict:
    """
    CAPTURA TEMPRANA PROGRESIVA. La IDENTIDAD del lead es el RUC (validado), NO el
    session_id: asi un mismo session_id que cambia de RUC NO pisa el registro de
    otro RUC (bug del "RUC que se chanca"). Se hace UPSERT por RUC; cada llamada
    trae un SUBCONJUNTO de campos (ej. solo whatsapp al blur); COALESCE evita pisar
    con NULL lo ya guardado y etapa_max sube con GREATEST. Se conserva el
    session_id de primer contacto. estado ('completo'/'parcial') es columna generada.
    Sin RUC no se guarda (no hay identidad todavia).
    """
    ruc = (data.get("ruc") or "").strip()
    estado = "completo" if (data.get("whatsapp") and data.get("email")) else "parcial"
    if not ruc:
        return {"estado": estado, "etapa_max": int(data.get("etapa") or 0), "guardado": False}
    if demo_mode():
        return {"estado": estado, "etapa_max": int(data.get("etapa") or 0), "guardado": True}

    assert _pool is not None
    row = await _pool.fetchrow(
        """
        INSERT INTO inscripciones
            (ruc, session_id, nombre, razon_social, distrito, ubigeo,
             whatsapp, email, origen, etapa_max, user_agent)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (ruc) DO UPDATE SET
            -- session_id: se conserva el de PRIMER contacto (no lo pisa otra sesion).
            session_id    = COALESCE(inscripciones.session_id, EXCLUDED.session_id),
            nombre        = COALESCE(EXCLUDED.nombre,       inscripciones.nombre),
            razon_social  = COALESCE(EXCLUDED.razon_social, inscripciones.razon_social),
            distrito      = COALESCE(EXCLUDED.distrito,     inscripciones.distrito),
            ubigeo        = COALESCE(EXCLUDED.ubigeo,       inscripciones.ubigeo),
            whatsapp      = COALESCE(EXCLUDED.whatsapp,     inscripciones.whatsapp),
            email         = COALESCE(EXCLUDED.email,        inscripciones.email),
            origen        = COALESCE(inscripciones.origen,  EXCLUDED.origen),
            etapa_max     = GREATEST(inscripciones.etapa_max, EXCLUDED.etapa_max),
            user_agent    = COALESCE(inscripciones.user_agent, EXCLUDED.user_agent),
            actualizado_en = now()
        RETURNING estado, etapa_max
        """,
        ruc, data.get("session_id"), data.get("nombre"),
        data.get("razon_social"), data.get("distrito"), data.get("ubigeo"),
        data.get("whatsapp"), data.get("email"), data.get("origen"),
        int(data.get("etapa") or 0), data.get("user_agent"),
    )
    return {"estado": row["estado"], "etapa_max": row["etapa_max"], "guardado": True}


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
        # 'ym' = clave 'YYYY-MM' para filtrar la lista por ese MISMO mes (conteo=lista).
        out.append({"ym": k, "mes": meses_es[int(m) - 1], "anio": y, "n": buckets[k]})
    return out


# Abreviaturas de tipo de via (el catalogo cat_via guarda el nombre completo;
# la VISTA abrevia). Denominaciones sin tilde, como estan en cat_via.
_VIA_ABREV = {
    "Avenida": "Av.", "Jiron": "Jr.", "Calle": "Cll.", "Pasaje": "Psj.",
    "Alameda": "Alm.", "Malecon": "Mal.", "Ovalo": "Ovalo", "Parque": "Pque.",
    "Plaza": "Plaza", "Carretera": "Carr.", "Block": "Blk.", "Otros": "",
}


def _cap(s):
    s = (s or "").strip()
    return " ".join(w.capitalize() for w in s.split()) if s else ""


def _construir_direccion(r) -> str | None:
    """Arma la direccion legible (juridicas) con via abreviada, limpiando
    guiones/vacios sobrantes (no deja 'S/N - -')."""
    via = _VIA_ABREV.get(r["via_den"], (r["via_den"] or "")) if r["via_den"] else ""
    partes = []
    l1 = " ".join(p for p in [via, _cap(r["nombre_via"])] if p).strip()
    num = (r["numero"] or "").strip()
    if num and num.upper() not in ("S/N", "SN", "0", "-"):
        l1 = f"{l1} {num}".strip()
    if l1:
        partes.append(l1)
    extras = []
    if r["interior"]:
        extras.append(f"Int. {r['interior']}")
    if r["numero_departamento"]:
        extras.append(f"Dpto. {r['numero_departamento']}")
    if r["mz"]:
        extras.append(f"Mz. {r['mz']}")
    if r["numero_lote"]:
        extras.append(f"Lt. {r['numero_lote']}")
    if extras:
        partes.append(" ".join(extras))
    if r["zona_den"] and r["zona_den"] != "Otros":
        z = f"{r['zona_den']} {_cap(r['nombre_zona'])}".strip()
        if z:
            partes.append(z)
    dire = ", ".join(p for p in partes if p and p.strip())
    dire = re.sub(r"\s*-\s*(?:-\s*)+", " ", dire)   # limpia "- -" sobrantes
    dire = re.sub(r"\s{2,}", " ", dire).strip(" ,-")
    return dire or None
