#!/usr/bin/env python3
"""
soporte_clave.py — Recuperación de clave por SOPORTE (Fase 1: no hay correo en prod).

Cuando una persona escribe por WhatsApp porque olvidó su clave: confirma su
identidad por WhatsApp y corre este script. Genera una clave temporal, obliga a
cambiarla al ingresar y CIERRA todas sus sesiones abiertas (sesion_version + 1).
La clave temporal se muestra solo en esta terminal: envíasela por WhatsApp.

  python soporte_clave.py 05200879
"""
from __future__ import annotations

import asyncio
import os
import secrets
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


async def main(dni: str):
    import asyncpg
    from argon2 import PasswordHasher
    for linea in (BASE / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("DATABASE_URL="):
            os.environ.setdefault("DATABASE_URL", linea.split("=", 1)[1].strip().strip('"'))
    if not (len(dni) == 8 and dni.isdigit()):
        sys.exit("El DNI tiene 8 dígitos.")
    temporal = "Club-" + secrets.token_urlsafe(6)
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        p = await conn.fetchrow("SELECT nombre_completo, estado, whatsapp FROM personas WHERE dni = $1", dni)
        if not p:
            sys.exit("No hay ninguna persona con ese DNI.")
        if p["estado"] != "activa":
            sys.exit(f"La cuenta está '{p['estado']}': no se restablece (si es 'por_activar', que active su cuenta).")
        await conn.execute(
            "UPDATE personas SET clave_hash = $2, debe_cambiar_clave = true, sesion_version = sesion_version + 1, "
            "updated_at = now() WHERE dni = $1", dni, PasswordHasher().hash(temporal))
    finally:
        await conn.close()
    print(f"Clave restablecida para {p['nombre_completo']} (WhatsApp {p['whatsapp']}).")
    print(f"Clave temporal: {temporal}")
    print("Al ingresar se le pedirá cambiarla. Todas sus sesiones abiertas se cerraron.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1].strip()))
