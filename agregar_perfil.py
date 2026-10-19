#!/usr/bin/env python3
"""
agregar_perfil.py — Suma un perfil (contador o empresario) a una persona que ya tiene cuenta,
sobre uno de sus RUC. Así una persona con los dos perfiles ve "¿A dónde vas hoy?" al ingresar.

Por defecto es ENSAYO (no escribe nada): muestra la persona, sus accesos y lo que se crearía.
Con --aplicar lo crea. Requiere el Paso 2 del acceso desplegado (un RUC con los dos perfiles).

  python agregar_perfil.py 12345678 contador                 # ensayo, sobre su RUC principal
  python agregar_perfil.py 12345678 contador --ruc 10123456781
  python agregar_perfil.py 12345678 contador --aplicar

El perfil nuevo entra SIN Directorio (la persona lo activa en Mi perfil si quiere). Si es
contador y su RUC tiene distrito, se enlaza a Nuevos Negocios como en el registro normal.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


async def main(dni: str, perfil: str, ruc: str | None, aplicar: bool):
    for linea in (BASE / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("DATABASE_URL="):
            os.environ.setdefault("DATABASE_URL", linea.split("=", 1)[1].strip().strip('"'))
    import asyncpg
    from app import db, club, identidad
    db._pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        if not await db._pool.fetchval("SELECT 1 FROM pg_constraint WHERE conname = 'uq_acceso_persona_ruc_perfil' "
                                       "AND conrelid = 'accesos'::regclass"):
            sys.exit("La base aún no admite un RUC con los dos perfiles: primero despliega el Paso 2 del acceso.")
        p = await db._pool.fetchrow("SELECT * FROM personas WHERE dni = $1 AND baja_en IS NULL", dni)
        if not p:
            sys.exit("No hay ninguna persona con ese DNI.")
        accesos = await db._pool.fetch("SELECT ruc, perfil, es_principal, directorio_optin FROM accesos "
                                       "WHERE persona_id = $1 AND revocado_en IS NULL ORDER BY es_principal DESC, created_at",
                                       p["id"])
        print(f"Persona: DNI {dni} · {p['nombre_completo']} · cuenta {p['estado']}")
        for a in accesos:
            print(f"  acceso: RUC {a['ruc']} · {a['perfil']}{' · principal' if a['es_principal'] else ''}"
                  f"{' · en Directorio' if a['directorio_optin'] else ''}")
        if p["estado"] != "activa":
            sys.exit("La cuenta no está activa: primero debe activarla (crear su clave).")
        if not ruc:
            if not accesos:
                sys.exit("No tiene RUC vinculado: indica uno con --ruc.")
            ruc = accesos[0]["ruc"]
        if any(a["ruc"] == ruc and a["perfil"] == perfil for a in accesos):
            sys.exit(f"Ya tiene el perfil {perfil} sobre el RUC {ruc}: no hay nada que hacer.")
        r = await club.clasificar("contador", ruc, continuar=True)
        nn = await db._pool.fetchval("SELECT 1 FROM suscriptores WHERE ruc = $1", ruc)
        print(f"Se crearía: RUC {ruc} · perfil {perfil} · {r.get('razon_social') or 'sin razón social'}"
              f" · {r.get('distrito') or 'sin distrito'} · SIN Directorio")
        if perfil == "contador":
            act = r.get("verificacion") if r.get("verificacion") in ("padron", "api") else "por_confirmar"
            print(f"  actividad contable: {act}"
                  + ("" if act != "por_confirmar" else " (el RUC no figura como contador: queda por revisar)"))
            if r.get("ubigeo"):
                print("  Nuevos Negocios: " + ("ya enlazado a su suscripción" if nn else
                                               f"se suscribe con su correo {p['correo']} (puede darse de baja)"))
        if not aplicar:
            print("\nENSAYO: no se escribió nada. Para crearlo, repite con --aplicar.")
            return
        async with db._pool.acquire() as conn:
            async with conn.transaction():
                x = await identidad.vincular_ruc(conn, dict(p), ruc, perfil, False, p["correo"], p["whatsapp"],
                                                 None, "agregar_perfil.py")
        if not x.get("ok"):
            sys.exit("No se pudo: " + x.get("error", "error desconocido"))
        print(f"\nListo: perfil {perfil} agregado. Al ingresar verá \"¿A dónde vas hoy?\".")
    finally:
        await db._pool.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dni")
    ap.add_argument("perfil", choices=["contador", "empresario"])
    ap.add_argument("--ruc")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    if not (len(a.dni) == 8 and a.dni.isdigit()):
        sys.exit("El DNI tiene 8 dígitos.")
    asyncio.run(main(a.dni, a.perfil, a.ruc, a.aplicar))
