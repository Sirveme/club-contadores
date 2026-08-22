#!/usr/bin/env python3
"""
poblar_adelanto.py - Pre-calcula la tabla adelanto_nuevos_negocios que lee la
landing /nuevos-negocios. Objetivo: respuesta INSTANTANEA (sin JOIN contra
nuevos_negocios en cada request) bajo ~100 consultas casi simultaneas.

Por cada distrito (ubigeo de 6 digitos) dentro de los prefijos indicados y cada
mes disponible en nuevos_negocios, guarda:
  - total_juridicas: conteo REAL de personas juridicas del distrito-mes (para el
    texto "5 de 47").
  - muestra: las 5 juridicas mas recientes (razon_social real; nunca naturales).

Idempotente (UPSERT por ubigeo+mes). Re-correr al cargar julio o al ampliar
distritos:  python poblar_adelanto.py --prefijos 1601
            python poblar_adelanto.py --prefijos 1601,1501 --n 5
Sin argumentos usa el prefijo 1601 (Maynas / Iquitos) y muestra de 5.

TODO local contra la BD de Railway; cero llamadas externas.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def cargar_dotenv() -> None:
    env = BASE / ".env"
    if not env.exists():
        return
    for linea in env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


DDL = """
CREATE TABLE IF NOT EXISTS adelanto_nuevos_negocios (
    ubigeo          text NOT NULL,
    mes             text NOT NULL,
    distrito        text,
    total_juridicas integer NOT NULL DEFAULT 0,
    muestra         jsonb NOT NULL DEFAULT '[]'::jsonb,
    actualizado_en  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ubigeo, mes)
)
"""


async def poblar(database_url: str, prefijos: list[str], n: int) -> None:
    import asyncpg
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(DDL)
        meses = [r["mes"] for r in await conn.fetch(
            "SELECT DISTINCT mes_inscripcion mes FROM nuevos_negocios "
            "WHERE mes_inscripcion IS NOT NULL ORDER BY mes DESC")]
        print(f"Meses disponibles: {', '.join(meses) or '(ninguno)'}")

        total_filas = 0
        for pref in prefijos:
            # Totales reales por distrito-mes (solo juridicas).
            totales = await conn.fetch(
                """
                SELECT left(ubigeo,6) u, max(distrito) distrito,
                       mes_inscripcion mes, count(*) tot
                FROM nuevos_negocios
                WHERE tipo = 'juridica' AND ubigeo IS NOT NULL
                      AND left(ubigeo, length($1)) = $1
                      AND mes_inscripcion IS NOT NULL
                GROUP BY 1, 3
                """, pref)
            # Muestra: top N juridicas por distrito-mes (mas recientes primero).
            filas = await conn.fetch(
                """
                SELECT u, distrito, mes, ruc, razon_social, fecha FROM (
                  SELECT left(ubigeo,6) u, distrito, mes_inscripcion mes,
                         ruc, razon_social,
                         to_char(fecha_inscripcion,'DD/MM/YYYY') fecha,
                         row_number() OVER (
                           PARTITION BY left(ubigeo,6), mes_inscripcion
                           ORDER BY fecha_inscripcion DESC NULLS LAST, ruc) rn
                  FROM nuevos_negocios
                  WHERE tipo = 'juridica' AND ubigeo IS NOT NULL
                        AND left(ubigeo, length($1)) = $1
                        AND mes_inscripcion IS NOT NULL
                        AND razon_social IS NOT NULL AND razon_social <> ''
                ) s
                WHERE rn <= $2
                ORDER BY u, mes DESC, rn
                """, pref, n)

            muestras: dict[tuple, list] = {}
            for f in filas:
                muestras.setdefault((f["u"], f["mes"]), []).append(
                    {"razon_social": f["razon_social"], "ruc": f["ruc"], "fecha": f["fecha"]})

            for t in totales:
                key = (t["u"], t["mes"])
                await conn.execute(
                    """
                    INSERT INTO adelanto_nuevos_negocios
                        (ubigeo, mes, distrito, total_juridicas, muestra, actualizado_en)
                    VALUES ($1,$2,$3,$4,$5::jsonb, now())
                    ON CONFLICT (ubigeo, mes) DO UPDATE SET
                        distrito = EXCLUDED.distrito,
                        total_juridicas = EXCLUDED.total_juridicas,
                        muestra = EXCLUDED.muestra,
                        actualizado_en = now()
                    """,
                    t["u"], t["mes"], t["distrito"], t["tot"],
                    json.dumps(muestras.get(key, []), ensure_ascii=False))
                total_filas += 1
                print(f"  {t['u']} {t['distrito']:<22} {t['mes']}: "
                      f"{len(muestras.get(key, []))} de {t['tot']}")

        print(f"OK. {total_filas} filas distrito-mes pobladas para prefijos "
              f"{', '.join(prefijos)}.")
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Puebla adelanto_nuevos_negocios.")
    ap.add_argument("--prefijos", default="1601",
                    help="Prefijos de ubigeo separados por coma (def: 1601 = Maynas/Iquitos).")
    ap.add_argument("--n", type=int, default=5, help="Tamano de la muestra por distrito-mes.")
    ap.add_argument("--database-url", default="")
    args = ap.parse_args()

    cargar_dotenv()
    database_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("Falta DATABASE_URL (env, .env o --database-url).")
    prefijos = [p.strip() for p in args.prefijos.split(",") if p.strip()]
    asyncio.run(poblar(database_url, prefijos, args.n))


if __name__ == "__main__":
    main()
