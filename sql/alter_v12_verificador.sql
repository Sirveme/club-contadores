-- alter_v12: Verificador multi-padron. Se ejecuta con search_path = <esquema>, public
-- (prueba_padron para ensayar, public en produccion): las tablas quedan en el esquema
-- elegido y la vista se enlaza a ESAS tablas. La maestra (padron_reducido) y los anexos
-- (padron_anexos) los crea el cargador con el patron tabla nueva + renombrado atomico.

-- Catalogo: un padron = una fila. La pantalla y el Excel se arman leyendo esta tabla:
-- agregar un padron nuevo = una fila aqui + sus marcas, sin tocar el Verificador.
CREATE TABLE IF NOT EXISTS padrones (
    codigo     text PRIMARY KEY,                 -- 'ssco', 'contador', 'negocio_nuevo', ...
    nombre     text NOT NULL,                    -- "Sujeto Sin Capacidad Operativa"
    columna    text NOT NULL,                    -- encabezado corto en la tabla
    severidad  text NOT NULL CHECK (severidad IN ('alerta', 'aviso', 'info')),
    origen     text NOT NULL DEFAULT 'marcas' CHECK (origen IN ('marcas', 'vista')),
    corte      date,                             -- ultimo corte cargado
    orden      smallint NOT NULL DEFAULT 100,
    activo     boolean NOT NULL DEFAULT true
);
-- Frescura: cada padron tiene su propio corte y ritmo. El panel admin muestra "cargado hace
-- X dias" en verde / ambar / rojo segun estos umbrales (editables por fila, sin tocar codigo).
-- 'maestra' = padron base (listado y anexos): no es columna de semaforo del Verificador.
ALTER TABLE padrones ADD COLUMN IF NOT EXISTS umbral_ambar_dias smallint NOT NULL DEFAULT 30;
ALTER TABLE padrones ADD COLUMN IF NOT EXISTS umbral_rojo_dias  smallint NOT NULL DEFAULT 60;
ALTER TABLE padrones DROP CONSTRAINT IF EXISTS padrones_origen_check;
ALTER TABLE padrones ADD CONSTRAINT padrones_origen_check CHECK (origen IN ('marcas', 'vista', 'maestra'));

INSERT INTO padrones (codigo, nombre, columna, severidad, origen, orden, umbral_ambar_dias, umbral_rojo_dias) VALUES
    ('padron_reducido', 'Estado y condición (listado general)', 'Estado', 'info', 'maestra', 1, 7, 14),
    ('padron_anexos', 'Locales anexos', 'Anexos', 'info', 'maestra', 2, 30, 60),
    ('ssco', 'Sujeto Sin Capacidad Operativa', 'SSCO', 'alerta', 'marcas', 10, 35, 50),
    ('contador', 'Contador o estudio contable', 'Contador', 'info', 'vista', 80, 45, 75),
    ('negocio_nuevo', 'Negocio nuevo', 'Negocio nuevo', 'info', 'vista', 90, 40, 60)
ON CONFLICT (codigo) DO NOTHING;
-- Cortes de los padrones que ya existian (los cargadores los actualizan en cada corte nuevo).
UPDATE padrones SET corte = DATE '2026-09-17' WHERE codigo = 'contador' AND corte IS NULL;
UPDATE padrones SET corte = (SELECT max(fecha_inscripcion) FROM public.nuevos_negocios)
 WHERE codigo = 'negocio_nuevo' AND corte IS NULL;

-- Marcas vigentes: una fila por (RUC, padron). El detalle propio de cada padron en jsonb
-- (SSCO: resolucion, fechas, representantes con su documento tal cual lo publica SUNAT).
-- ruc es varchar(11), igual que en contadores_padron y nuevos_negocios: con el MISMO tipo en
-- las tres ramas de v_ruc_marcas, PostgreSQL empuja el filtro por RUC a cada rama y usa sus
-- indices (con tipos mezclados recorria las tablas completas).
CREATE TABLE IF NOT EXISTS ruc_marcas (
    ruc      varchar(11) NOT NULL,
    padron   text NOT NULL REFERENCES padrones (codigo),
    desde    date,
    corte    date NOT NULL,
    detalle  jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (ruc, padron)
);
CREATE INDEX IF NOT EXISTS ix_marcas_padron ON ruc_marcas (padron);

-- Historial: solo se agregan filas (quien entra, sale o cambia en cada corte).
CREATE TABLE IF NOT EXISTS ruc_marcas_hist (
    id         bigserial PRIMARY KEY,
    ruc        varchar(11) NOT NULL,
    padron     text NOT NULL REFERENCES padrones (codigo),
    evento     text NOT NULL CHECK (evento IN ('entra', 'sale', 'cambia')),
    corte      date NOT NULL,
    detalle    jsonb NOT NULL DEFAULT '{}',
    creado_en  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_marcas_hist_ruc ON ruc_marcas_hist (ruc, padron, corte);

-- Uso del Verificador: topes (por tanda y por IP al dia) y metricas.
CREATE TABLE IF NOT EXISTS verificador_uso (
    id          bigserial PRIMARY KEY,
    ip          inet,
    persona_id  uuid,
    rucs        int NOT NULL,
    origen      text NOT NULL,                   -- 'uno' | 'lista' | 'excel' | 'xlsx' | 'ssco_nombre'
    creado_en   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_vuso_ip_dia ON verificador_uso (ip, creado_en);

-- Contadores y Negocios nuevos se leen EN VIVO de sus tablas (no se copian): siempre al dia.
CREATE OR REPLACE VIEW v_ruc_marcas AS
    SELECT ruc, padron, desde, corte, detalle FROM ruc_marcas
    UNION ALL
    SELECT ruc, 'contador', NULL::date, NULL::date, '{}'::jsonb FROM public.contadores_padron
    UNION ALL
    SELECT ruc, 'negocio_nuevo', fecha_inscripcion, NULL::date,
           jsonb_build_object('mes', mes_inscripcion) FROM public.nuevos_negocios;
