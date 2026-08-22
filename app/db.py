"""
Acceso a PostgreSQL con asyncpg.

Si no hay DATABASE_URL configurada, la app arranca en MODO DEMO usando un
pequeno dataset en memoria para poder probar el embudo en el celular sin BD.
En produccion (Railway) basta con setear DATABASE_URL.
"""
from __future__ import annotations

import os
import re
import json
import secrets
import datetime as dt
from typing import Optional

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_pool: Optional[asyncpg.Pool] = None


def demo_mode() -> bool:
    return not DATABASE_URL


def norm_whatsapp(raw: str | None) -> str | None:
    """WhatsApp válido = 9 dígitos que empiezan en 9. Devuelve el número o None
    (NUNCA cadena vacía). Se guarda NULL si viene vacío o con formato inválido."""
    d = "".join(c for c in (raw or "") if c.isdigit())
    return d if (len(d) == 9 and d.startswith("9")) else None


def limite_distritos(whatsapp: str | None) -> int:
    """Regla de negocio: 3 distritos si dejó WhatsApp válido; si no, 1."""
    return 3 if norm_whatsapp(whatsapp) else 1


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


# Padron DEMO (solo sin BD): un contador con data (Miraflores) y otro sin data.
_DEMO_PADRON = {
    "10111111111": {"razon_social": "CONTADOR DEMO CON DATA", "tipo": "natural",
                    "ubigeo": "150122", "distrito": "MIRAFLORES",
                    "provincia": "LIMA", "departamento": "LIMA"},
    "10999999999": {"razon_social": "CONTADOR DEMO SIN DATA", "tipo": "natural",
                    "ubigeo": "010504", "distrito": "COLCAMAR",
                    "provincia": "LUYA", "departamento": "AMAZONAS"},
}


# --- Ciclo de vida del pool -------------------------------------------------
async def connect() -> None:
    global _pool
    if demo_mode():
        return
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    await _asegurar_esquema()


async def _asegurar_esquema() -> None:
    """Provisiona tablas que crea la app (idempotente). La BD de Railway es
    persistente aunque el disco del contenedor sea efimero: aqui es seguro."""
    assert _pool is not None
    await _pool.execute(
        """
        CREATE TABLE IF NOT EXISTS avisos_uso (
            id          bigserial PRIMARY KEY,
            creado_en   timestamptz NOT NULL DEFAULT now(),
            nombre      text,
            institucion text,
            correo      text,
            uso         text,
            ambito      text,
            ip          inet,
            user_agent  text
        )
        """
    )
    # Landing /nuevos-negocios: captacion de suscriptores.
    await _pool.execute(
        """
        CREATE TABLE IF NOT EXISTS suscriptores (
            id                bigserial PRIMARY KEY,
            ruc               text NOT NULL,
            razon_social      text,
            es_contador       boolean NOT NULL DEFAULT false,
            distrito          text,
            correo            text NOT NULL,
            whatsapp          text,
            origen            text,
            consentimiento    boolean NOT NULL DEFAULT false,
            consentimiento_en timestamptz,
            token_baja        text NOT NULL,
            baja_en           timestamptz,
            ip                inet,
            user_agent        text,
            created_at        timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # Dedup: un RUC = una suscripcion; un correo = una suscripcion.
    await _pool.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_susc_ruc ON suscriptores (ruc)")
    await _pool.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_susc_correo ON suscriptores (lower(correo))")
    # Adelanto PRE-CALCULADO (una fila por distrito+mes): lectura instantanea,
    # sin JOIN contra nuevos_negocios en cada request. La puebla poblar_adelanto.py.
    await _pool.execute(
        """
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
    )


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# --- Padron de contadores (TAREA 3) -----------------------------------------
async def padron_lookup(ruc: str) -> dict | None:
    """Busca el RUC en contadores_padron. Devuelve dict con razon_social, tipo,
    ubigeo, distrito, provincia, departamento; o None si no esta en el padron."""
    ruc = (ruc or "").strip()
    if not ruc:
        return None
    if demo_mode():
        d = _DEMO_PADRON.get(ruc)
        return {"ruc": ruc, **d} if d else None
    assert _pool is not None
    row = await _pool.fetchrow(
        "SELECT ruc, razon_social, tipo, ubigeo, distrito, provincia, departamento "
        "FROM contadores_padron WHERE ruc = $1",
        ruc,
    )
    return dict(row) if row else None


async def log_no_listado(ruc: str, distrito: str | None, marca: str) -> None:
    """Registra un RUC a seguir: 'no_encontrado' (no esta en el padron) o
    'sin_data' (en el padron pero su distrito aun no tiene negocios). Upsert por
    RUC para no duplicar."""
    ruc = (ruc or "").strip()
    if not ruc or demo_mode():
        return
    assert _pool is not None
    await _pool.execute(
        """
        INSERT INTO contadores_no_listados (ruc, distrito_elegido, marca)
        VALUES ($1, $2, $3)
        ON CONFLICT (ruc) DO UPDATE SET
            distrito_elegido = EXCLUDED.distrito_elegido,
            marca = EXCLUDED.marca,
            actualizado_en = now()
        """,
        ruc, distrito, marca,
    )


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
    # TODOS los meses CON DATOS del distrito (no solo los ultimos 3): si se
    # limitaba a 3 meses, un distrito con data mas antigua (ej. Colcamar) devolvia
    # lista vacia, el selector de mes desaparecia y el usuario quedaba atrapado.
    # El panorama de la etapa 2 muestra solo los ultimos 3; el selector, todos.
    rows = await _pool.fetch(
        f"""
        SELECT mes_inscripcion AS mes, COUNT(*) AS n
        FROM nuevos_negocios
        WHERE {where} AND mes_inscripcion IS NOT NULL
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
            "giro": r["giro"], "ciiu": r["ciiu"], "regimen": r["regimen"],
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
    # Normalizacion al grabar: email en minusculas, distrito en MAYUSCULAS,
    # razon social/nombre en MAYUSCULAS (consistente con nuevos_negocios).
    if data.get("email"):
        data["email"] = data["email"].strip().lower()
    if data.get("distrito"):
        data["distrito"] = data["distrito"].strip().upper()
    for k in ("razon_social", "nombre"):
        if data.get(k):
            data[k] = data[k].strip().upper()
    # WhatsApp OPCIONAL: normaliza (9 dígitos, inicia en 9) o NULL — nunca "".
    data["whatsapp"] = norm_whatsapp(data.get("whatsapp"))
    # estado 'completo' = tiene CORREO (el WhatsApp ya no es requisito).
    estado = "completo" if data.get("email") else "parcial"
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
        -- El indice ux_inscrip_ruc es PARCIAL (WHERE ruc IS NOT NULL): la inferencia
        -- del ON CONFLICT DEBE repetir ese predicado, si no Postgres lanza
        -- "no unique or exclusion constraint matching the ON CONFLICT specification".
        ON CONFLICT (ruc) WHERE ruc IS NOT NULL DO UPDATE SET
            -- session_id: se conserva el de PRIMER contacto (no lo pisa otra sesion).
            session_id    = COALESCE(inscripciones.session_id, EXCLUDED.session_id),
            nombre        = COALESCE(EXCLUDED.nombre,       inscripciones.nombre),
            razon_social  = COALESCE(EXCLUDED.razon_social, inscripciones.razon_social),
            -- REGLA: un RUC = UN distrito. La MISMA sesion (mismo session_id) SI
            -- puede corregirlo (p.ej. si cayo en un distrito vacio y elige otro);
            -- una sesion DISTINTA no lo pisa (keep-first). Los multiples distritos
            -- son de la version de pago (S/ 15 c/u), aun no implementada.
            distrito = CASE WHEN inscripciones.session_id = EXCLUDED.session_id
                            THEN COALESCE(EXCLUDED.distrito, inscripciones.distrito)
                            ELSE COALESCE(inscripciones.distrito, EXCLUDED.distrito) END,
            ubigeo   = CASE WHEN inscripciones.session_id = EXCLUDED.session_id
                            THEN COALESCE(EXCLUDED.ubigeo, inscripciones.ubigeo)
                            ELSE COALESCE(inscripciones.ubigeo, EXCLUDED.ubigeo) END,
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


async def distrito_de_ruc(ruc: str) -> dict | None:
    """
    Distrito YA registrado para ese RUC (regla: un RUC = un distrito, el primero).
    La UI lo usa para fijar el distrito y no dejar cambiarlo en la version gratuita.
    """
    ruc = (ruc or "").strip()
    if not ruc or demo_mode():
        return None
    assert _pool is not None
    row = await _pool.fetchrow(
        "SELECT distrito, ubigeo FROM inscripciones WHERE ruc = $1 AND distrito IS NOT NULL",
        ruc,
    )
    if not row:
        return None
    return {"distrito": row["distrito"], "ubigeo": row["ubigeo"]}


async def acceso_distrito(ruc: str, ubigeo: str, distrito: str | None) -> dict:
    """GATE de acceso multi-distrito (fuente de verdad: inscripcion_distritos).

    Regla: límite = 3 si la inscripción dejó WhatsApp, 1 si no. Antes de ENTREGAR
    la data de un distrito, se verifica aquí (backend, no solo el front):
      - Si ya tiene ese distrito → permitido (no cuenta doble).
      - Si es nuevo y hay cupo   → lo registra y permite.
      - Si es nuevo y no hay cupo → BLOQUEADO (la UI ofrece agregar WhatsApp).
    Devuelve {ok, limite, usados, ya_tenia, motivo}. En demo o sin RUC, permite
    (no hay identidad que limitar)."""
    ruc = (ruc or "").strip()
    ubigeo = (ubigeo or "").strip()
    if demo_mode() or not ruc or not ubigeo:
        return {"ok": True, "limite": 1, "usados": 0, "ya_tenia": True, "motivo": None}
    assert _pool is not None
    insc = await _pool.fetchrow(
        "SELECT id, whatsapp FROM inscripciones WHERE ruc = $1", ruc)
    if not insc:
        # Sin inscripción aún (no debería pasar: se crea en etapa 1). No bloquear.
        return {"ok": True, "limite": 1, "usados": 0, "ya_tenia": True, "motivo": None}
    limite = limite_distritos(insc["whatsapp"])
    async with _pool.acquire() as con:
        async with con.transaction():
            ya = await con.fetchval(
                "SELECT 1 FROM inscripcion_distritos "
                "WHERE inscripcion_id = $1 AND ubigeo = $2", insc["id"], ubigeo)
            usados = await con.fetchval(
                "SELECT count(*) FROM inscripcion_distritos WHERE inscripcion_id = $1",
                insc["id"])
            if ya:
                return {"ok": True, "limite": limite, "usados": usados,
                        "ya_tenia": True, "motivo": None}
            if usados >= limite:
                return {"ok": False, "limite": limite, "usados": usados,
                        "ya_tenia": False, "motivo": "limite"}
            await con.execute(
                "INSERT INTO inscripcion_distritos (inscripcion_id, ubigeo, distrito) "
                "VALUES ($1, $2, $3) ON CONFLICT (inscripcion_id, ubigeo) DO NOTHING",
                insc["id"], ubigeo, (distrito or "").strip().upper() or None)
    return {"ok": True, "limite": limite, "usados": usados + 1,
            "ya_tenia": False, "motivo": None}


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


# --- Avisos de uso (formulario privado; NO publica nada) --------------------
AVISO_LIMITE_IP = 5   # maximo de avisos por IP en la ventana
AVISO_VENTANA_H = 1   # ventana en horas


async def guardar_aviso(data: dict) -> dict:
    """Guarda un aviso de uso. Devuelve {ok, motivo}. Antispam por IP: no acepta
    mas de AVISO_LIMITE_IP en AVISO_VENTANA_H horas desde la misma IP. El honeypot
    se filtra en la ruta, antes de llegar aqui."""
    if demo_mode():
        return {"ok": True, "demo": True}
    assert _pool is not None
    ip = (data.get("ip") or "").strip() or None
    if ip:
        recientes = await _pool.fetchval(
            "SELECT count(*) FROM avisos_uso "
            "WHERE ip = $1::inet AND creado_en > now() - ($2 || ' hours')::interval",
            ip, str(AVISO_VENTANA_H))
        if recientes and recientes >= AVISO_LIMITE_IP:
            return {"ok": False, "motivo": "limite"}
    await _pool.execute(
        """
        INSERT INTO avisos_uso (nombre, institucion, correo, uso, ambito, ip, user_agent)
        VALUES ($1,$2,$3,$4,$5,$6::inet,$7)
        """,
        (data.get("nombre") or "").strip()[:200] or None,
        (data.get("institucion") or "").strip()[:200] or None,
        (data.get("correo") or "").strip().lower()[:200] or None,
        (data.get("uso") or "").strip()[:2000] or None,
        (data.get("ambito") or "").strip()[:200] or None,
        ip,
        (data.get("user_agent") or "")[:400] or None,
    )
    return {"ok": True}


async def listar_avisos(limite: int = 200) -> list[dict]:
    if demo_mode():
        return []
    assert _pool is not None
    rows = await _pool.fetch(
        "SELECT id, creado_en, nombre, institucion, correo, uso, ambito, "
        "host(ip) AS ip FROM avisos_uso ORDER BY creado_en DESC LIMIT $1",
        int(limite))
    return [dict(r) for r in rows]


# --- Landing /nuevos-negocios (captacion; TODO local, cero llamadas externas) ---
SUSC_LIMITE_IP = 15   # maximo de suscripciones por IP en la ventana
SUSC_VENTANA_H = 1


async def nn_validar_ruc(ruc: str) -> dict:
    """Valida el RUC SOLO contra nuestras tablas (padron + nuevos_negocios).
    Devuelve el camino y los datos derivados (nunca los pide al usuario):
      A -> es contador (esta en contadores_padron): trae ubigeo/distrito.
      B -> existe en nuevos_negocios pero no es contador.
      C -> no esta en ninguna tabla."""
    ruc = (ruc or "").strip()
    if demo_mode():
        d = _DEMO_PADRON.get(ruc)
        if d:
            return {"camino": "A", "es_contador": True, "razon_social": d["razon_social"],
                    "distrito": d["distrito"], "ubigeo": d["ubigeo"]}
        return {"camino": "C", "es_contador": False, "razon_social": None,
                "distrito": None, "ubigeo": None}
    assert _pool is not None
    pad = await padron_lookup(ruc)
    if pad:
        return {"camino": "A", "es_contador": True,
                "razon_social": pad.get("razon_social"),
                "distrito": pad.get("distrito"), "ubigeo": pad.get("ubigeo")}
    row = await _pool.fetchrow(
        "SELECT razon_social, distrito, ubigeo FROM nuevos_negocios WHERE ruc = $1 LIMIT 1",
        ruc)
    if row:
        return {"camino": "B", "es_contador": False, "razon_social": row["razon_social"],
                "distrito": row["distrito"], "ubigeo": row["ubigeo"]}
    return {"camino": "C", "es_contador": False, "razon_social": None,
            "distrito": None, "ubigeo": None}


async def nn_adelanto(ubigeo: str) -> list[dict]:
    """Adelanto pre-calculado del distrito (por ubigeo de 6 digitos), del mes MAS
    reciente al mas antiguo. Lee de adelanto_nuevos_negocios: cero JOINs."""
    ubigeo = (ubigeo or "").strip()
    if not ubigeo or demo_mode():
        return []
    assert _pool is not None
    rows = await _pool.fetch(
        "SELECT mes, distrito, total_juridicas, muestra FROM adelanto_nuevos_negocios "
        "WHERE ubigeo = $1 ORDER BY mes DESC", ubigeo)
    out = []
    for r in rows:
        m = r["muestra"]
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except Exception:
                m = []
        out.append({"mes": r["mes"], "distrito": r["distrito"],
                    "total": r["total_juridicas"], "negocios": m or []})
    return out


async def nn_crear_suscriptor(data: dict) -> dict:
    """Alta de suscriptor. Dedup por RUC y por lower(correo) (indices unicos).
    Los campos de identidad (razon_social, es_contador, distrito) vienen de
    NUESTRAS tablas, no del usuario. Devuelve {ok, motivo, token_baja}."""
    if demo_mode():
        return {"ok": True, "demo": True, "token_baja": secrets.token_urlsafe(24)}
    assert _pool is not None
    ip = (data.get("ip") or "").strip() or None
    if ip:
        recientes = await _pool.fetchval(
            "SELECT count(*) FROM suscriptores "
            "WHERE ip = $1::inet AND created_at > now() - ($2 || ' hours')::interval",
            ip, str(SUSC_VENTANA_H))
        if recientes and recientes >= SUSC_LIMITE_IP:
            return {"ok": False, "motivo": "limite"}
    token = secrets.token_urlsafe(24)
    try:
        await _pool.execute(
            """
            INSERT INTO suscriptores
                (ruc, razon_social, es_contador, distrito, correo, whatsapp, origen,
                 consentimiento, consentimiento_en, token_baja, ip, user_agent)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8, now(), $9, $10::inet, $11)
            """,
            (data.get("ruc") or "").strip(),
            (data.get("razon_social") or None),
            bool(data.get("es_contador")),
            (data.get("distrito") or None),
            (data.get("correo") or "").strip().lower(),
            norm_whatsapp(data.get("whatsapp")),
            (data.get("origen") or None),
            bool(data.get("consentimiento")),
            token, ip, (data.get("user_agent") or "")[:400] or None)
    except asyncpg.UniqueViolationError as e:
        cn = (getattr(e, "constraint_name", "") or "").lower()
        return {"ok": False, "motivo": "dup_correo" if "correo" in cn else "dup_ruc"}
    return {"ok": True, "token_baja": token}


async def nn_baja(token: str) -> bool:
    """Marca la baja por token. True si el token existe (aunque ya estuviera de baja)."""
    token = (token or "").strip()
    if not token or demo_mode():
        return False
    assert _pool is not None
    row = await _pool.fetchrow(
        "UPDATE suscriptores SET baja_en = now() "
        "WHERE token_baja = $1 AND baja_en IS NULL RETURNING id", token)
    if row:
        return True
    return bool(await _pool.fetchval(
        "SELECT 1 FROM suscriptores WHERE token_baja = $1", token))


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
