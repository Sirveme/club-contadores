"""Vitrina de la extension Ficha RUC: tarjetas que rotan al pie de la ficha y de la tabla.

- Las tarjetas son solo DATOS (titulo, texto, emoji, colores, boton, enlace, orden, activo). La
  extension las pide en GET /api/v1/vitrina y las pinta con textContent; si el servidor no responde,
  usa las que trae en el paquete. Se editan en /panel/vitrina sin publicar otra version.
- Clics: el boton de la tarjeta abre GET /api/v1/vitrina/ir/{id}, que suma 1 al dia (hora de Lima)
  de esa tarjeta y redirige a su enlace con ?ref=ficha-ruc. Solo el conteo: sin RUC, sin IP, sin
  identificadores. Se ve en /panel/llaves junto a las metricas de las pruebas.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

REF = "ficha-ruc"
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
CLAVE_RE = re.compile(r"^[a-z0-9_-]{2,30}$")
_DIA = "(now() AT TIME ZONE 'America/Lima')::date"
CAMPOS = ("titulo", "texto", "emoji", "color1", "color2", "boton", "enlace")
LARGOS = {"titulo": 40, "texto": 70, "emoji": 8, "boton": 20, "enlace": 300}


def con_ref(url: str) -> str:
    """Agrega ref=ficha-ruc al enlace (respeta lo que ya traiga)."""
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "ref"] + [("ref", REF)]
    return urlunparse(p._replace(query=urlencode(q)))


def enlace_valido(url: str) -> bool:
    p = urlparse(url or "")
    return p.scheme == "https" and bool(p.hostname) and "." in p.hostname and not p.username and not p.password


def validar(datos: dict) -> tuple[dict, list[str]]:
    """-> (tarjeta limpia, errores). Solo texto plano y colores #rrggbb; enlaces https."""
    t = {k: str(datos.get(k) or "").strip() for k in CAMPOS}
    errores = []
    for k, n in LARGOS.items():
        if len(t[k]) > n:
            errores.append(f"«{k}» admite hasta {n} caracteres.")
    for k in ("titulo", "texto", "boton", "enlace"):
        if not t[k]:
            errores.append(f"Falta «{k}».")
    for k in ("color1", "color2"):
        if not COLOR_RE.match(t[k]):
            errores.append(f"«{k}» debe ser un color como #ff7a18.")
    if t["enlace"] and not enlace_valido(t["enlace"]):
        errores.append("El enlace debe empezar con https:// y tener un dominio.")
    try:
        t["orden"] = int(str(datos.get("orden") or "0").strip())
    except ValueError:
        errores.append("«orden» es un número.")
        t["orden"] = 0
    t["activo"] = str(datos.get("activo") or "").lower() in ("1", "true", "on", "si", "sí")
    return t, errores


def _publica(r) -> dict:
    return {"id": r["id"], "titulo": r["titulo"], "texto": r["texto"], "emoji": r["emoji"], "color1": r["color1"],
            "color2": r["color2"], "boton": r["boton"], "orden": r["orden"]}


async def tarjetas(pool, esquema: str, todas: bool = False) -> list[dict]:
    rows = await pool.fetch(f"SELECT * FROM {esquema}.vitrina_tarjetas {'' if todas else 'WHERE activo'} ORDER BY orden, id")
    return [dict(r) for r in rows] if todas else [_publica(r) for r in rows]


async def contar_clic(pool, esquema: str, tarjeta_id: int) -> str | None:
    """Suma 1 al dia de la tarjeta activa y devuelve su enlace con ref; None si no existe o esta apagada."""
    async with pool.acquire() as conn, conn.transaction():
        enlace = await conn.fetchval(f"SELECT enlace FROM {esquema}.vitrina_tarjetas WHERE id = $1 AND activo", tarjeta_id)
        if not enlace:
            return None
        await conn.execute(
            f"""INSERT INTO {esquema}.vitrina_clics (tarjeta_id, dia, clics) VALUES ($1, {_DIA}, 1)
                ON CONFLICT (tarjeta_id, dia) DO UPDATE SET clics = vitrina_clics.clics + 1""", tarjeta_id)
    return con_ref(enlace)


async def guardar(pool, esquema: str, tarjeta_id: int | None, t: dict, clave: str | None = None) -> None:
    if tarjeta_id:
        await pool.execute(
            f"""UPDATE {esquema}.vitrina_tarjetas SET titulo=$2, texto=$3, emoji=$4, color1=$5, color2=$6, boton=$7,
                enlace=$8, orden=$9, activo=$10, actualizado_en=now() WHERE id=$1""",
            tarjeta_id, t["titulo"], t["texto"], t["emoji"], t["color1"], t["color2"], t["boton"], t["enlace"], t["orden"], t["activo"])
    else:
        await pool.execute(
            f"""INSERT INTO {esquema}.vitrina_tarjetas (clave, titulo, texto, emoji, color1, color2, boton, enlace, orden, activo)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            clave, t["titulo"], t["texto"], t["emoji"], t["color1"], t["color2"], t["boton"], t["enlace"], t["orden"], t["activo"])


async def clics_resumen(pool, esquema: str, dias: int = 14) -> dict:
    """Clics por tarjeta y por dia (los ultimos `dias`, el mas reciente primero) y el total del periodo."""
    hoy = await pool.fetchval(f"SELECT {_DIA}")
    desde = hoy - timedelta(days=dias - 1)
    ts = await pool.fetch(f"SELECT id, titulo, activo FROM {esquema}.vitrina_tarjetas ORDER BY orden, id")
    conteo = {(r["tarjeta_id"], r["dia"]): r["clics"] for r in await pool.fetch(
        f"SELECT tarjeta_id, dia, clics FROM {esquema}.vitrina_clics WHERE dia BETWEEN $1 AND $2", desde, hoy)}
    filas = []
    for i in range(dias):
        d: date = hoy - timedelta(days=i)
        por = [conteo.get((t["id"], d), 0) for t in ts]
        filas.append({"dia": d, "por": por, "total": sum(por)})
    totales = [sum(f["por"][j] for f in filas) for j in range(len(ts))]
    return {"tarjetas": [dict(t) for t in ts], "dias": filas, "totales": totales, "total": sum(totales)}
