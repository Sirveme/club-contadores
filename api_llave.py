"""Llaves de la API (/api/v1), por comando. La llave completa se muestra UNA sola vez.

  python api_llave.py crear --nombre "Hoja de proveedores - Estudio X" [--plan gratis|pago]
         [--cuota N] [--ruc 20XXXXXXXXX] [--alcance ssco_representantes] [--esquema prueba_padron]
  python api_llave.py listar   [--esquema ...]
  python api_llave.py revocar psp_live_a1b2c3d4   [--esquema ...]
  python api_llave.py alcances psp_live_a1b2c3d4 ruc ssco_representantes   [--esquema ...]
  python api_llave.py activar K7QM-4XPA [--nombre "Juan Pérez García"]   [--esquema ...]
  python api_llave.py pruebas   [--esquema ...]

activar: la prueba de la extension Ficha RUC con ese codigo (el que la persona escribe por WhatsApp)
pasa a acceso permanente; la extension lo detecta sola. pruebas: emitidas por dia y en que estado van.

--esquema: public (produccion, por defecto) o prueba_padron (ensayo). El plan 'pago' incluye el
alcance 'ssco_representantes'; el gratis no. La cuota por defecto del plan gratis sale de
API_CUOTA_GRATIS_MES.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.dirname(os.path.abspath(__file__))


def url_bd() -> str:
    for l in open(os.path.join(RAIZ, ".env"), encoding="utf-8"):
        m = re.match(r"^DATABASE_URL=(.+)", l.strip())
        if m:
            return m[1].strip().strip('"')
    raise SystemExit("Falta DATABASE_URL en .env")


async def main(a):
    import asyncpg
    from app import api_v1 as A
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", a.esquema):
        raise SystemExit("esquema inválido")
    conn = await asyncpg.connect(url_bd())
    try:
        await A.crear_tablas(conn, a.esquema)
        t = f"{a.esquema}.api_llaves"
        if a.cmd == "crear":
            alcances = ["ruc"] + (["ssco_representantes"] if a.plan == "pago" else [])
            for x in a.alcance or []:
                if x not in A.ALCANCES:
                    raise SystemExit(f"alcance desconocido: {x} (válidos: {', '.join(A.ALCANCES)})")
                if x == "dni":
                    raise SystemExit("El alcance 'dni' está apagado hasta definir su base legal.")
                if x not in alcances:
                    alcances.append(x)
            cuota = a.cuota if a.cuota is not None else A.CUOTA_GRATIS_MES
            llave, prefijo, huella = A.nueva_llave()
            await conn.execute(
                f"INSERT INTO {t} (prefijo, huella, nombre, cliente_ruc, plan_codigo, cuota_mes, rpm, alcances, creada_por) "
                f"VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'comando')",
                prefijo, huella, a.nombre, a.ruc, a.plan, cuota, A.RPM_DEFECTO, alcances)
            print(f"Llave creada en {a.esquema}: {a.nombre!r} · plan {a.plan} · {cuota} consultas/mes · alcances {alcances}")
            print("Guárdala ahora: no se vuelve a mostrar.\n")
            print(llave)
        elif a.cmd == "listar":
            for r in await conn.fetch(f"SELECT prefijo, nombre, plan_codigo, cuota_mes, alcances, estado, creada_en, ultima_vez "
                                      f"FROM {t} ORDER BY creada_en"):
                print(f"{r['prefijo']}  {r['estado']:10} {r['plan_codigo']:7} {r['cuota_mes']:>7}/mes  {list(r['alcances'])}  "
                      f"{r['nombre']!r}  creada {r['creada_en']:%d/%m/%Y}  última {r['ultima_vez']:%d/%m/%Y %H:%M}" if r["ultima_vez"]
                      else f"{r['prefijo']}  {r['estado']:10} {r['plan_codigo']:7} {r['cuota_mes']:>7}/mes  {list(r['alcances'])}  "
                           f"{r['nombre']!r}  creada {r['creada_en']:%d/%m/%Y}  sin uso")
        elif a.cmd == "revocar":
            r = await conn.execute(f"UPDATE {t} SET estado = 'revocada', revocada_en = now() WHERE prefijo = $1 AND estado <> 'revocada'",
                                   a.prefijo)
            print("revocada" if r.endswith("1") else "no hay una llave activa con ese prefijo")
        elif a.cmd == "alcances":
            malos = [x for x in a.lista if x not in A.ALCANCES or x == "dni"]
            if malos:
                raise SystemExit(f"alcances no permitidos: {malos}")
            r = await conn.execute(f"UPDATE {t} SET alcances = $2 WHERE prefijo = $1", a.prefijo, a.lista)
            print("alcances actualizados" if r.endswith("1") else "no hay una llave con ese prefijo")
        elif a.cmd == "activar":
            fila = await A.activar_instalacion(conn, a.esquema, a.codigo, nombre=a.nombre)
            print(f"Acceso permanente activado: {fila['codigo']} · {fila['nombre']!r} · {fila['cuota_mes']} consultas/mes"
                  if fila else "No hay una prueba vigente con ese código (revisa que esté bien escrito, o ya fue activada).")
        elif a.cmd == "pruebas":
            r = await A.pruebas_resumen(conn, a.esquema)
            print(f"En prueba {r['en_prueba']} · vencidas {r['vencidas']} · registradas esperando activación {r['por_activar']}"
                  f" · activadas {r['activadas']}")
            print("  " + " | ".join(["día"] + [t for _, t in A.METRICAS]))
            for d in r["dias"]:
                print(f"  {d['dia']:%d/%m/%Y} | " + " | ".join(str(d[k]) for k, _ in A.METRICAS))
            for f in await conn.fetch(f"SELECT codigo, solicitud_en FROM {t} WHERE plan_codigo = 'prueba' AND solicitud_persona IS NOT NULL "
                                      f"AND estado = 'activa' ORDER BY solicitud_en"):
                print(f"  por activar: {f['codigo']}  (se registró el {f['solicitud_en']:%d/%m/%Y %H:%M})")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crear"); c.add_argument("--nombre", required=True)
    c.add_argument("--plan", choices=["gratis", "pago"], default="gratis"); c.add_argument("--cuota", type=int)
    c.add_argument("--ruc"); c.add_argument("--alcance", action="append")
    sub.add_parser("listar")
    r = sub.add_parser("revocar"); r.add_argument("prefijo")
    al = sub.add_parser("alcances"); al.add_argument("prefijo"); al.add_argument("lista", nargs="+")
    ac = sub.add_parser("activar"); ac.add_argument("codigo"); ac.add_argument("--nombre")
    sub.add_parser("pruebas")
    for p in sub.choices.values():
        p.add_argument("--esquema", default="public")
    asyncio.run(main(ap.parse_args()))
