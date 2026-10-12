-- alter_v14: API propia (/api/v1). Se ejecuta con search_path = <esquema>, public, igual que
-- alter_v12 (prueba_padron para ensayar, public en produccion).

-- Una llave por integracion. Solo se guarda su huella (sha256): la llave completa se muestra
-- una vez, al crearla. `alcances` gobierna lo que la llave puede ver sin tocar codigo:
--   'ruc'                  consulta de RUC (todas)
--   'ssco_representantes'  representantes legales del SSCO (solo planes pagados, cliente identificado)
--   'dni'                  reservado: apagado hasta definir la base legal
CREATE TABLE IF NOT EXISTS api_llaves (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prefijo      text NOT NULL UNIQUE,                 -- 'psp_live_a1b2c3d4': visible, para reconocerla
    huella       text NOT NULL,                        -- sha256 de la llave completa
    nombre       text NOT NULL,                        -- "Hoja de proveedores - Estudio X"
    persona_id   uuid,                                 -- socio duenio (NULL: emitida por el admin)
    cliente_ruc  varchar(11),                          -- puente con la Central de Suscripciones
    plan_codigo  text NOT NULL DEFAULT 'gratis',
    cuota_mes    int  NOT NULL,                        -- consultas por mes (copia del plan)
    rpm          int  NOT NULL DEFAULT 60,             -- consultas por minuto
    alcances     text[] NOT NULL DEFAULT '{ruc}',
    estado       text NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'suspendida', 'revocada')),
    creada_en    timestamptz NOT NULL DEFAULT now(),
    creada_por   text,
    ultima_vez   timestamptz,
    revocada_en  timestamptz
);

-- Contador del mes: una fila por llave, recurso y mes (verificar la cuota = leer una fila).
CREATE TABLE IF NOT EXISTS api_uso_mes (
    llave_id  uuid NOT NULL REFERENCES api_llaves (id),
    recurso   text NOT NULL,                           -- 'ruc' | 'dni'
    mes       date NOT NULL,                           -- primer dia del mes
    unidades  int  NOT NULL DEFAULT 0,
    PRIMARY KEY (llave_id, recurso, mes)
);

-- Bitacora de cada llamada. A proposito NO guarda que RUC se consulto: solo conteos
-- ("no registramos a quien consultas").
CREATE TABLE IF NOT EXISTS api_uso (
    id         bigserial PRIMARY KEY,
    llave_id   uuid REFERENCES api_llaves (id),
    creado_en  timestamptz NOT NULL DEFAULT now(),
    recurso    text NOT NULL,
    unidades   int  NOT NULL,
    http       smallint NOT NULL,
    ms         int,
    ip         inet
);
CREATE INDEX IF NOT EXISTS ix_api_uso_llave ON api_uso (llave_id, creado_en);
