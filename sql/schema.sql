-- ============================================================================
-- Club de Contadores — contadores.perusistemas.pro
-- DDL para PGAdmin (NO Alembic). Ejecutar tal cual en la BD de Railway.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) nuevos_negocios
--    Directorio de altas de RUC por distrito/mes. SE POBLA MANUAL al inicio.
--    (Duilio carga directo a la BD; el importador XLSX viene despues.)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nuevos_negocios (
    id                       BIGSERIAL PRIMARY KEY,
    ruc                      VARCHAR(11) NOT NULL,
    razon_social             TEXT        NOT NULL,
    tipo                     VARCHAR(10),               -- 'natural' | 'juridica'
    ciiu                     VARCHAR(10),               -- codigo CIIU
    giro                     TEXT,                      -- descripcion del CIIU
    ubigeo                   VARCHAR(6),                -- codigo INEI del distrito
    distrito                 TEXT        NOT NULL,
    provincia                TEXT,
    departamento             TEXT,
    fecha_inscripcion        DATE,                      -- fecha de alta del RUC (filtro por mes)
    fecha_inicio_actividades DATE,
    direccion                TEXT,                      -- solo juridicas
    tributo                  TEXT,
    nombre_comercial         TEXT,
    creado_en                TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indice unico en RUC: usar ON CONFLICT (ruc) DO NOTHING al insertar para
-- evitar duplicados (casi imposible que se repita: el filtro es fecha de
-- inscripcion por mes).
CREATE UNIQUE INDEX IF NOT EXISTS ux_nuevos_negocios_ruc ON nuevos_negocios (ruc);

-- Indices de consulta: por distrito y por mes de inscripcion.
CREATE INDEX IF NOT EXISTS ix_nn_distrito ON nuevos_negocios (departamento, provincia, distrito);
CREATE INDEX IF NOT EXISTS ix_nn_ubigeo   ON nuevos_negocios (ubigeo);
CREATE INDEX IF NOT EXISTS ix_nn_fecha    ON nuevos_negocios (fecha_inscripcion);

-- ----------------------------------------------------------------------------
-- 2) inscripciones  (EL LEAD — el activo capturado)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inscripciones (
    id             BIGSERIAL PRIMARY KEY,
    nombre         TEXT,                                -- nombre del estudio/contador
    ruc            VARCHAR(11),
    razon_social   TEXT,
    distrito       TEXT,                                -- distrito de interes
    ubigeo         VARCHAR(6),
    whatsapp       VARCHAR(20),
    email          TEXT,
    origen         VARCHAR(30),                         -- colegio | facebook | youtube | directo
    user_agent     TEXT,
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Un mismo RUC puede volver; guardamos cada toque pero de-duplicamos por
-- RUC+distrito con un indice unico parcial (permite RUC nulo).
CREATE UNIQUE INDEX IF NOT EXISTS ux_inscrip_ruc_distrito
    ON inscripciones (ruc, distrito)
    WHERE ruc IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_inscrip_fecha ON inscripciones (creado_en);

-- ----------------------------------------------------------------------------
-- 3) push_subscriptions  (para notificaciones push 1-2 veces por semana)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          BIGSERIAL PRIMARY KEY,
    endpoint    TEXT NOT NULL,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    ruc         VARCHAR(11),
    distrito    TEXT,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_push_endpoint ON push_subscriptions (endpoint);

-- ----------------------------------------------------------------------------
-- CARGA MANUAL DE EJEMPLO (nuevos_negocios). Ajusta distrito/ubigeo/fechas.
-- ----------------------------------------------------------------------------
-- INSERT INTO nuevos_negocios
--   (ruc, razon_social, tipo, ciiu, giro, ubigeo, distrito, provincia, departamento,
--    fecha_inscripcion, fecha_inicio_actividades, direccion, nombre_comercial)
-- VALUES
--   ('20601234567','INVERSIONES EJEMPLO SAC','juridica','4711','Venta al por menor en bodegas',
--    '150122','MIRAFLORES','LIMA','LIMA','2026-07-03','2026-07-10',
--    'AV. EJEMPLO 123, MIRAFLORES','BODEGA EJEMPLO')
-- ON CONFLICT (ruc) DO NOTHING;
