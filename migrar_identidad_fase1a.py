#!/usr/bin/env python3
"""
migrar_identidad_fase1a.py — Fase 1a de la identidad por PERSONA (DNI) del Club.

1) Crea el esquema (sql/alter_v11_identidad.sql): personas, accesos, login_intentos
   y club_socios.persona_id. Aditivo e idempotente.
2) Migra cada socio de club_socios a una Persona 'por_activar' (sin clave) + su
   Acceso al RUC, conservando opt-in de Directorio, slug, especialidades y el enlace
   a Nuevos Negocios (suscriptor_id). club_socios no se modifica (solo persona_id).
   - RUC 10: el DNI sale del propio RUC (10 + DNI + digito verificador) y el acceso
     queda titular / dni_en_ruc (verificado por calculo).
   - Otros RUC: no se puede deducir el DNI -> se reporta; se resuelve al activar.
3) Verifica campo por campo y que nada mas cambio (club_socios, suscriptores, padron).

  python migrar_identidad_fase1a.py --dry-run    # todo en una transaccion + ROLLBACK
  python migrar_identidad_fase1a.py --aplicar    # lo mismo + COMMIT
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SQL = BASE / "sql" / "alter_v11_identidad.sql"
PESOS_RUC = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
# Columnas de club_socios que deben pasar INTACTAS al acceso.
CAMPOS_ACCESO = ["ruc", "razon_social", "nombre_comercial", "ubigeo", "distrito", "directorio_optin",
                 "directorio_optin_en", "directorio_optin_ver", "slug", "especialidad1", "especialidad2",
                 "suscriptor_id", "origen", "revisar"]


def dv_ruc(primeros10: str) -> int:
    """Digito verificador SUNAT (modulo 11)."""
    r = 11 - sum(int(d) * p for d, p in zip(primeros10, PESOS_RUC)) % 11
    return {10: 0, 11: 1}.get(r, r)


def ruc_valido(ruc: str) -> bool:
    return len(ruc) == 11 and ruc.isdigit() and dv_ruc(ruc[:10]) == int(ruc[10])


def dni_de_ruc10(ruc: str) -> str | None:
    """RUC 10 = '10' + DNI (8) + DV. Devuelve el DNI solo si el RUC es valido."""
    return ruc[2:10] if ruc.startswith("10") and ruc_valido(ruc) else None


ORIGINAL_SOCIOS = ("SELECT md5(string_agg(row(id, ruc, rol, verificacion, revisar, razon_social, nombre_comercial, "
                   "ubigeo, distrito, correo, whatsapp, token, suscriptor_id, directorio_optin, directorio_optin_en, "
                   "directorio_optin_ver, slug, especialidad1, especialidad2, origen, baja_en)::text, '' ORDER BY id)) "
                   "FROM club_socios")
HUELLAS = {
    "club_socios (columnas originales)": ORIGINAL_SOCIOS,
    "suscriptores": "SELECT count(*) || ' / ' || md5(string_agg(s::text, '' ORDER BY id)) FROM suscriptores s",
    "contadores_padron": "SELECT count(*) || ' / ' || md5(string_agg(p::text, '' ORDER BY ruc)) FROM contadores_padron p",
}


async def migrar(conn) -> list[dict]:
    socios = [dict(r) for r in await conn.fetch("SELECT * FROM club_socios WHERE baja_en IS NULL ORDER BY id")]
    informe = []
    for s in socios:
        dni = dni_de_ruc10(s["ruc"])
        if not dni:
            informe.append({"socio": s["id"], "ruc": s["ruc"], "resultado": "SIN DNI deducible: se pide al activar"})
            continue
        pid = await conn.fetchval(
            """
            INSERT INTO personas (dni, nombre_completo, nombre_verificado, correo, whatsapp, estado,
                                  consentimiento_en, consentimiento_ver)
            VALUES ($1, $2, false, $3, $4, 'por_activar', $5, $6)
            ON CONFLICT (dni) DO UPDATE SET updated_at = now()
            RETURNING id
            """, dni, s["razon_social"], s["correo"], s["whatsapp"], s["consentimiento_en"], s["consentimiento_ver"])
        actividad = s["verificacion"] if s["verificacion"] in ("padron", "api", "por_confirmar", "no_aplica") else None
        await conn.execute(
            """
            INSERT INTO accesos (persona_id, ruc, perfil, relacion, verificacion, actividad, revisar, es_principal,
                                 razon_social, nombre_comercial, ubigeo, distrito, directorio_optin, directorio_optin_en,
                                 directorio_optin_ver, slug, especialidad1, especialidad2, suscriptor_id, origen,
                                 club_socio_id, vigencia_inicio)
            VALUES ($1, $2, $3, 'titular', 'dni_en_ruc', $4, $5, true, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                    $16, $17, $18, $19::date)
            ON CONFLICT (persona_id, ruc) DO NOTHING
            """, pid, s["ruc"], s["rol"], actividad, s["revisar"], s["razon_social"], s["nombre_comercial"],
            s["ubigeo"], s["distrito"], s["directorio_optin"], s["directorio_optin_en"], s["directorio_optin_ver"],
            s["slug"], s["especialidad1"], s["especialidad2"], s["suscriptor_id"], s["origen"], s["id"],
            s["created_at"].date())
        await conn.execute("UPDATE club_socios SET persona_id = $1 WHERE id = $2", pid, s["id"])
        informe.append({"socio": s["id"], "ruc": s["ruc"], "dni": dni, "persona_id": pid, "socio_datos": s})
    return informe


async def verificar(conn, informe) -> list[str]:
    fallos = []
    for i in informe:
        if "persona_id" not in i:
            continue
        s = i["socio_datos"]
        p = await conn.fetchrow("SELECT * FROM personas WHERE id = $1", i["persona_id"])
        a = await conn.fetchrow("SELECT * FROM accesos WHERE persona_id = $1 AND ruc = $2", i["persona_id"], s["ruc"])
        print(f"\n  ── Socio #{s['id']}  RUC {s['ruc']}  ({s['rol']}) ──")
        print(f"     PERSONA  dni={p['dni']}  estado={p['estado']}  clave={'(ninguna)' if p['clave_hash'] is None else 'SI'}"
              f"  sesion_version={p['sesion_version']}  nombre='{p['nombre_completo']}' (verificado RENIEC: {p['nombre_verificado']})")
        print(f"              correo={'SI' if p['correo'] else 'NO'}  whatsapp={'SI' if p['whatsapp'] else 'NO (se pide al activar)'}")
        print(f"     ACCESO   perfil={a['perfil']}  relacion={a['relacion']}  verificacion={a['verificacion']}"
              f"  actividad={a['actividad']}  principal={a['es_principal']}")
        print(f"              distrito={a['distrito']} ({a['ubigeo']})  directorio_optin={a['directorio_optin']}"
              f"  slug={a['slug']}  suscriptor_id(Nuevos Negocios)={a['suscriptor_id']}")
        for campo in CAMPOS_ACCESO:
            if a[campo] != s[campo]:
                fallos.append(f"socio {s['id']}: {campo} {s[campo]!r} -> {a[campo]!r}")
        for campo in ("correo", "whatsapp"):
            if p[campo] != s[campo]:
                fallos.append(f"socio {s['id']}: persona.{campo} distinto")
        if p["estado"] != "por_activar" or p["clave_hash"] is not None:
            fallos.append(f"socio {s['id']}: la persona deberia quedar por_activar y sin clave")
        if a["perfil"] != s["rol"]:
            fallos.append(f"socio {s['id']}: perfil distinto del rol")
        if await conn.fetchval("SELECT persona_id FROM club_socios WHERE id = $1", s["id"]) != i["persona_id"]:
            fallos.append(f"socio {s['id']}: club_socios.persona_id no enlazado")
        if s["suscriptor_id"]:
            tok = await conn.fetchval("SELECT token_baja FROM suscriptores WHERE id = $1", a["suscriptor_id"])
            print(f"              /mi-distrito sigue accesible por su suscriptor: {'SI' if tok else 'NO'}")
            if not tok:
                fallos.append(f"socio {s['id']}: suscriptor de Nuevos Negocios no encontrado")
    return fallos


async def main(aplicar: bool):
    import asyncpg
    for linea in (BASE / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("DATABASE_URL="):
            os.environ.setdefault("DATABASE_URL", linea.split("=", 1)[1].strip().strip('"'))
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        # 0) El algoritmo del digito verificador, contra TODOS los RUC 10 del padron.
        rucs10 = [r["ruc"] for r in await conn.fetch("SELECT ruc FROM contadores_padron WHERE ruc LIKE '10%'")]
        malos = [r for r in rucs10 if not ruc_valido(r)]
        print(f"Digito verificador RUC (modulo 11): {len(rucs10) - len(malos):,} de {len(rucs10):,} RUC 10 del padron validos"
              f"{'' if not malos else f' | NO validos: {malos[:5]}'}")
        if len(malos) > len(rucs10) * 0.001:
            raise SystemExit("El algoritmo no coincide con el padron: se detiene.")

        antes = {k: await conn.fetchval(q) for k, q in HUELLAS.items()}
        existen = await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' "
                                      "AND table_name IN ('personas', 'accesos', 'login_intentos')")
        print(f"Tablas de identidad existentes antes: {existen}")
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(SQL.read_text(encoding="utf-8"))
            informe = await migrar(conn)
            print(f"\nSocios en club_socios: {len(informe)}")
            for i in informe:
                if "persona_id" not in i:
                    print(f"  - socio {i['socio']} RUC {i['ruc']}: {i['resultado']}")
            fallos = await verificar(conn, informe)
            despues = {k: await conn.fetchval(q) for k, q in HUELLAS.items()}
            print("\n  Huellas (deben ser identicas):")
            for k in HUELLAS:
                igual = antes[k] == despues[k]
                print(f"     {k:34} {'IGUAL' if igual else 'CAMBIO'}")
                if not igual:
                    fallos.append(f"cambio inesperado en {k}")
            print(f"\n  personas: {await conn.fetchval('SELECT count(*) FROM personas')}  |  accesos: "
                  f"{await conn.fetchval('SELECT count(*) FROM accesos')}  |  login_intentos: "
                  f"{await conn.fetchval('SELECT count(*) FROM login_intentos')}")
            if fallos:
                print("\nFALLOS:", *fallos, sep="\n  - ")
                raise SystemExit("Verificacion fallida: ROLLBACK")
            print("\nVerificacion: TODO OK")
            if aplicar:
                await tr.commit()
                print("COMMIT hecho.")
            else:
                await tr.rollback()
                print("DRY-RUN: ROLLBACK (no se escribio nada).")
        except BaseException:
            if not tr.is_completed():
                await tr.rollback()
            raise
        quedan = await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' "
                                     "AND table_name IN ('personas', 'accesos', 'login_intentos')")
        col = await conn.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_name = 'club_socios' "
                                  "AND column_name = 'persona_id'")
        print(f"Despues: tablas de identidad = {quedan}, club_socios.persona_id = {'existe' if col else 'no existe'}")
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--aplicar", action="store_true")
    asyncio.run(main(ap.parse_args().aplicar))
