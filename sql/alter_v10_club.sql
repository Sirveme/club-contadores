-- ============================================================================
-- alter_v10 — Club de Contadores: socios (tabla NUEVA, separada de
-- inscripciones legacy y de suscriptores). Idempotente: la app la ejecuta al
-- arrancar (app/club.py -> asegurar_esquema).
-- Relacion con el padron SOLO por ruc (sin FK): contadores_padron no se toca.
-- ============================================================================
CREATE TABLE IF NOT EXISTS club_socios (
    id               bigserial PRIMARY KEY,
    ruc              varchar(11) NOT NULL UNIQUE,
    rol              text NOT NULL CHECK (rol IN ('contador', 'empresario')),
    -- padron: en contadores_padron | api: SUNAT confirma CIIU 6920 |
    -- por_confirmar: dice ser contador sin 6920 (marca informativa, NO restringe) |
    -- no_aplica: empresario
    verificacion     text NOT NULL CHECK (verificacion IN ('padron', 'api', 'por_confirmar', 'no_aplica')),
    revisar          boolean NOT NULL DEFAULT false,      -- cola interna de revision
    revisado_en      timestamptz,
    razon_social     text,                                -- del padron/API, nunca del usuario
    nombre_comercial text,
    ubigeo           varchar(6),
    distrito         text,
    correo           text NOT NULL,
    whatsapp         text,
    consentimiento     boolean NOT NULL,
    consentimiento_en  timestamptz NOT NULL,
    consentimiento_ver text NOT NULL,                     -- version del texto aceptado
    token            text NOT NULL UNIQUE,                -- secrets.token_urlsafe: acceso al tablero
    suscriptor_id    bigint REFERENCES suscriptores(id),  -- su pagina de Nuevos Negocios (/mi-distrito)
    -- Directorio de Contadores: opt-in APARTE del consentimiento general (Ley 29733).
    directorio_optin     boolean NOT NULL DEFAULT false,
    directorio_optin_en  timestamptz,
    directorio_optin_ver text,
    slug                 text UNIQUE,                     -- /club/c/{slug}
    especialidad1        text,
    especialidad2        text,
    origen           text,
    ip               inet,
    user_agent       text,
    ultimo_acceso_en timestamptz,
    baja_en          timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_club_revisar    ON club_socios (created_at) WHERE revisar;
CREATE INDEX IF NOT EXISTS ix_club_correo     ON club_socios (lower(correo));
CREATE INDEX IF NOT EXISTS ix_club_directorio ON club_socios (ubigeo) WHERE directorio_optin AND baja_en IS NULL;
