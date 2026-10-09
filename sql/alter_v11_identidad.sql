-- ============================================================================
-- alter_v11 — Identidad del Club por PERSONA (DNI) · Fase 1a (solo esquema).
-- Espejo del modelo Persona/Acceso de alerta.pe, con el RUC como destino del
-- acceso. ADITIVO: no borra ni modifica datos; club_socios solo gana una columna
-- (persona_id) para enlazar la migracion. Idempotente.
-- ============================================================================

-- La identidad que inicia sesion. Un DNI = una fila. Correo/WhatsApp son contacto,
-- nunca identidad. 'por_activar' = migrada desde club_socios, aun sin clave.
CREATE TABLE IF NOT EXISTS personas (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dni                  char(8) NOT NULL UNIQUE CHECK (dni ~ '^[0-9]{8}$'),
    nombre_completo      text,
    nombres              text,                     -- para el saludo ("Jorge Luis")
    apellido_paterno     text,
    apellido_materno     text,
    nombre_verificado    boolean NOT NULL DEFAULT false,   -- true = confirmado en RENIEC
    reniec_consultado_en timestamptz,
    correo               text,
    whatsapp             text,
    clave_hash           text,                     -- Argon2 (como alerta.pe)
    debe_cambiar_clave   boolean NOT NULL DEFAULT false,
    sesion_version       integer NOT NULL DEFAULT 1,       -- revocacion server-side (logout/cambio de clave)
    rol_sistema          text CHECK (rol_sistema IN ('soporte_global')),
    estado               text NOT NULL DEFAULT 'activa' CHECK (estado IN ('por_activar', 'activa', 'baja')),
    consentimiento_en    timestamptz,
    consentimiento_ver   text,
    activada_en          timestamptz,
    ultimo_login_at      timestamptz,
    baja_en              timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    -- Una persona ACTIVA tiene clave, correo y WhatsApp (ambos obligatorios).
    CONSTRAINT ck_persona_activa_completa CHECK (
        estado <> 'activa' OR (clave_hash IS NOT NULL AND correo IS NOT NULL AND whatsapp IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_personas_correo ON personas (lower(correo));

-- Persona -> RUC. El perfil (contador/empresario) va POR RUC (decision Fase 1).
--   relacion:     titular (RUC 10 propio) | representante (RUC 20 declarado)
--   verificacion: dni_en_ruc (RUC 10 = 10 + DNI + DV, instantanea) | declarado
--                 | verificado_ficha (Fase 2) | revocado
--   actividad:    contador segun CIIU 6920 (padron/api/por_confirmar) | no_aplica
CREATE TABLE IF NOT EXISTS accesos (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id           uuid NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    ruc                  varchar(11) NOT NULL CHECK (ruc ~ '^(10|15|17|20)[0-9]{9}$'),
    perfil               text NOT NULL CHECK (perfil IN ('contador', 'empresario')),
    relacion             text NOT NULL CHECK (relacion IN ('titular', 'representante')),
    verificacion         text NOT NULL CHECK (verificacion IN ('dni_en_ruc', 'declarado', 'verificado_ficha', 'revocado')),
    actividad            text CHECK (actividad IN ('padron', 'api', 'por_confirmar', 'no_aplica')),
    revisar              boolean NOT NULL DEFAULT false,
    es_principal         boolean NOT NULL DEFAULT false,   -- define el distrito del tablero
    razon_social         text,                              -- foto del padron/SUNAT al vincular
    nombre_comercial     text,
    ubigeo               varchar(6),
    distrito             text,
    -- Directorio y Nuevos Negocios son POR RUC (vienen de club_socios).
    directorio_optin     boolean NOT NULL DEFAULT false,
    directorio_optin_en  timestamptz,
    directorio_optin_ver text,
    slug                 text UNIQUE,
    especialidad1        text,
    especialidad2        text,
    suscriptor_id        bigint REFERENCES suscriptores(id),
    origen               text,
    club_socio_id        bigint REFERENCES club_socios(id),  -- traza de la migracion
    vigencia_inicio      date NOT NULL DEFAULT current_date,
    vigencia_fin         date,
    revocado_en          timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_acceso_persona_ruc UNIQUE (persona_id, ruc),
    CONSTRAINT ck_acceso_dni_en_ruc_es_ruc10 CHECK (verificacion <> 'dni_en_ruc' OR left(ruc, 2) = '10')
);
-- Un RUC 10 tiene UN solo titular verificado.
CREATE UNIQUE INDEX IF NOT EXISTS ux_acceso_titular_ruc ON accesos (ruc)
    WHERE relacion = 'titular' AND verificacion = 'dni_en_ruc';
-- Un solo RUC principal por persona.
CREATE UNIQUE INDEX IF NOT EXISTS ux_acceso_principal ON accesos (persona_id) WHERE es_principal;
CREATE INDEX IF NOT EXISTS ix_accesos_ruc ON accesos (ruc);
CREATE INDEX IF NOT EXISTS ix_accesos_directorio ON accesos (ubigeo)
    WHERE directorio_optin AND revocado_en IS NULL;

-- Limite de intentos de ingreso (el DNI es publico: sin limite se adivina la clave).
CREATE TABLE IF NOT EXISTS login_intentos (
    id         bigserial PRIMARY KEY,
    dni        char(8),
    ip         inet,
    exito      boolean NOT NULL,
    creado_en  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_login_intentos_dni ON login_intentos (dni, creado_en);
CREATE INDEX IF NOT EXISTS ix_login_intentos_ip  ON login_intentos (ip, creado_en);

-- Enlace de cada socio antiguo con su persona (club_socios queda en solo lectura).
ALTER TABLE club_socios ADD COLUMN IF NOT EXISTS persona_id uuid REFERENCES personas(id);
