#!/usr/bin/env python3
"""
modo_grabacion.py — Levanta el Club en LOCAL para grabar, sin tocar producción.

La app usa la BD real (DATABASE_URL del .env) pero con
search_path = grabacion_club, public:
  - LEE de producción lo que se muestra: contadores_padron, nuevos_negocios,
    cat_ubigeo, ... (no se modifica nada de eso).
  - ESCRIBE solo en copias vacías dentro del esquema grabacion_club: todo
    registro, socio, suscriptor o aviso hecho durante la grabación queda ahí.
Al terminar, `borrar` elimina el esquema y no queda rastro.

Uso (desde C:\\perusistemas\\contadores):
  python modo_grabacion.py levantar     # crea el esquema si falta y abre http://localhost:8000/club
  python modo_grabacion.py estado       # qué hay en el esquema de grabación
  python modo_grabacion.py borrar       # elimina el esquema (y lo registrado al grabar)
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ESQUEMA = "grabacion_club"
PUERTO = os.getenv("PUERTO", "8000")
# Tablas en las que la app ESCRIBE. Las que la app crea sola al arrancar
# (suscriptores, avisos_uso, club_socios, personas, accesos, login_intentos) nacen vacías en el esquema; las demás
# se copian aquí (solo estructura) para que ningún INSERT llegue a producción.
COPIAR = ["inscripciones", "inscripcion_distritos", "contadores_no_listados", "push_subscriptions"]
ESCRITURA = COPIAR + ["suscriptores", "avisos_uso", "club_socios", "personas", "accesos", "login_intentos"]


def leer_env() -> dict:
    env = {}
    for linea in (BASE / ".env").read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    if not env.get("DATABASE_URL"):
        sys.exit("Falta DATABASE_URL en .env (Railway > ContadoresBD > Variables > DATABASE_PUBLIC_URL).")
    return env


async def crear(url: str) -> None:
    import asyncpg
    c = await asyncpg.connect(url)
    try:
        await c.execute(f"CREATE SCHEMA IF NOT EXISTS {ESQUEMA}")
        for t in COPIAR:
            if await c.fetchval("SELECT to_regclass($1)", f"{ESQUEMA}.{t}"):
                continue
            await c.execute(f"CREATE TABLE {ESQUEMA}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)")
            # Las columnas serial apuntan a secuencias de public: se cambian por una propia.
            for col, dflt in await c.fetch(
                    "SELECT column_name, column_default FROM information_schema.columns "
                    "WHERE table_schema = $1 AND table_name = $2 AND column_default LIKE 'nextval(%'", ESQUEMA, t):
                seq = f"{ESQUEMA}.{t}_{col}_seq"
                await c.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq}")
                await c.execute(f"ALTER TABLE {ESQUEMA}.{t} ALTER COLUMN {col} SET DEFAULT nextval('{seq}')")
                await c.execute(f"ALTER SEQUENCE {seq} OWNED BY {ESQUEMA}.{t}.{col}")
    finally:
        await c.close()


async def estado(url: str) -> None:
    import asyncpg
    c = await asyncpg.connect(url)
    try:
        if not await c.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = $1", ESQUEMA):
            print(f"No existe el esquema {ESQUEMA}.")
            return
        for t in ESCRITURA:
            n = await c.fetchval(f"SELECT count(*) FROM {ESQUEMA}.{t}") if await c.fetchval(
                "SELECT to_regclass($1)", f"{ESQUEMA}.{t}") else None
            print(f"  {ESQUEMA}.{t:24} {'(aún no creada)' if n is None else f'{n} filas'}")
    finally:
        await c.close()


async def borrar(url: str) -> None:
    import asyncpg
    c = await asyncpg.connect(url)
    try:
        await c.execute(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE")
        print(f"Esquema {ESQUEMA} eliminado. Producción no se tocó.")
    finally:
        await c.close()


def main():
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    env = leer_env()
    url = env["DATABASE_URL"]
    if accion == "borrar":
        asyncio.run(borrar(url))
    elif accion == "estado":
        asyncio.run(estado(url))
    elif accion == "levantar":
        asyncio.run(crear(url))
        sep = "&" if "?" in url else "?"
        entorno = {**os.environ, **env, "DATABASE_URL": f"{url}{sep}search_path={ESQUEMA},public"}
        print(f"Modo grabación: lee producción, escribe solo en {ESQUEMA}.")
        print(f"Abre  http://localhost:{PUERTO}/club   (Ctrl+C para detener)")
        subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                        "--port", PUERTO], cwd=BASE, env=entorno)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
