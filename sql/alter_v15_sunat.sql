-- alter_v15: padrones publicos de SUNAT (sunat.gob.pe/padronesnotificaciones), esquema propio.
-- Base: el schema.sql de la extension (relevado 19/10/2026), con estos cambios:
--   * ruc varchar(11) + CHECK de 11 digitos (no char(11)): el MISMO tipo que ruc_marcas,
--     padron_reducido y nuevos_negocios, para que el filtro por RUC baje a cada rama de la
--     vista v_ruc_padrones y use su indice (con char(11) habria casteo y barrido completo).
--   * indice por RUC en TODAS las tablas (faltaba donde la clave empieza por otra columna).
--   * sin afiliados_see (no hay datos: el ZIP de SUNAT da 404) ni ssco (el SSCO vive en el
--     Verificador, ruc_marcas; la vista lo lee de alli: una sola fuente).
--   * cargas: traza de cada archivo cargado (filas, huella, corte).
-- Lo corre cargar_sunat.py con search_path = <esquema> SOLO (prueba_sunat o sunat; nunca
-- public): los nombres sin esquema quedan en el esquema elegido.

-- 1) Padrones "RUC | Nombre | A partir del | Resolucion" (5 en una tabla, columna padron)
CREATE TABLE IF NOT EXISTS padron_rs (
    padron        varchar(40) NOT NULL CHECK (padron IN ('AGENTE_RETENCION', 'BUEN_CONTRIBUYENTE',
                      'PERCEPCION_HIDROCARBUROS', 'PERCEPCION_VENTA_INTERNA', 'RENUNCIA_EXONERACION_APENDICE_I')),
    ruc           varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social  text        NOT NULL,
    fecha_desde   date,
    resolucion    varchar(40),
    cargado_en    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (padron, ruc)                    -- tambien sirve de indice por padron
);
CREATE INDEX IF NOT EXISTS ix_padron_rs_ruc ON padron_rs (ruc);

-- 2) Imprentas autorizadas SOL
CREATE TABLE IF NOT EXISTS imprentas_autorizadas (
    ruc           varchar(11) PRIMARY KEY CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social  text        NOT NULL,
    direccion     text,
    departamento  varchar(60),
    provincia     varchar(60),
    distrito      varchar(60),
    telefonos     varchar(120),
    fax           varchar(60),
    cargado_en    timestamptz NOT NULL DEFAULT now()
);

-- 3) EIRL y sociedades cuyos titulares o socios son SSCO - resumen
CREATE TABLE IF NOT EXISTS ssco_vinculadas (
    item              int,
    ruc               varchar(11) PRIMARY KEY CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social      text        NOT NULL,
    cant_rep_legales  int,
    cant_supuestos    int,
    cant_ssco_origen  int,
    fecha_publicacion date,
    cargado_en        timestamptz NOT NULL DEFAULT now()
);

-- 4) Mismo padron - detalle (1 fila por titular/representante/SSCO de origen)
CREATE TABLE IF NOT EXISTS ssco_vinculadas_detalle (
    id                       bigserial   PRIMARY KEY,
    item                     int,
    ruc                      varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social             text,
    titular_nombre           text,
    titular_tipo_doc         varchar(40),
    titular_num_doc          varchar(15),
    rep_legal_nombre         text,
    rep_legal_tipo_doc       varchar(40),
    rep_legal_num_doc        varchar(15),
    supuesto_inclusion       text,
    ssco_razon_social        text,
    ssco_ruc                 varchar(11) CHECK (ssco_ruc ~ '^[0-9]{11}$'),
    fecha_limite_restriccion date,                  -- emision de BV/NC/ND electronicas
    fecha_publicacion        date,
    cargado_en               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sscovd_ruc ON ssco_vinculadas_detalle (ruc);
CREATE INDEX IF NOT EXISTS ix_sscovd_ssco_ruc ON ssco_vinculadas_detalle (ssco_ruc);

-- 5) Contribuyentes con mayor deuda en cobranza coactiva
CREATE TABLE IF NOT EXISTS deuda_coactiva (
    nro               int,
    ruc               varchar(11) PRIMARY KEY CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social      text        NOT NULL,
    nombre_comercial  text,
    dependencia       varchar(60),
    monto_deuda       numeric(18,2),
    cant_rep_legales  int,
    cargado_en        timestamptz NOT NULL DEFAULT now()
);

-- 6) Entidades exceptuadas de la percepcion del IGV (trimestral)
CREATE TABLE IF NOT EXISTS exceptuadas_percepcion (
    periodo       varchar(20) NOT NULL,             -- ej. 'Setiembre2026'
    nro           int,
    ruc           varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social  text,
    tipo          varchar(40),
    cargado_en    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (periodo, ruc)
);
CREATE INDEX IF NOT EXISTS ix_exceptuadas_ruc ON exceptuadas_percepcion (ruc);

-- 7) Intendencia Lima - no estarian aplicando detracciones (HISTORICO 2013)
CREATE TABLE IF NOT EXISTS spot_no_aplica_ilima (
    ord           int,
    ruc           varchar(11) PRIMARY KEY CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social  text,
    cargado_en    timestamptz NOT NULL DEFAULT now()
);

-- 8) Ingreso como recaudacion de fondos de detracciones (HISTORICO 2015-2016; repite RUC)
CREATE TABLE IF NOT EXISTS spot_ingreso_fondos (
    id                 bigserial   PRIMARY KEY,
    ruc                varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    nro_cuenta         varchar(15),
    resolucion         varchar(15),
    fecha_notificacion date,
    monto_ingreso      numeric(18,2),
    nro_orden          varchar(15),
    mes_ejecucion      char(6),                     -- MMAAAA
    causal             text,
    cargado_en         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_spot_fondos_ruc ON spot_ingreso_fondos (ruc);

-- 9) Registro de Exportadores de Servicios
CREATE TABLE IF NOT EXISTS exportadores_servicios (
    nro                  int,
    ruc                  varchar(11) PRIMARY KEY CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social         text,
    dependencia          varchar(80),
    fecha_inscripcion    date,
    descripcion_servicio text,
    cargado_en           timestamptz NOT NULL DEFAULT now()
);

-- 10) Exportadores que no requieren garantias (devolucion tipo 01)
CREATE TABLE IF NOT EXISTS exportadores_sin_garantia (
    ruc            varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social   text,
    vigencia_desde date        NOT NULL,
    vigencia_hasta date,
    cargado_en     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ruc, vigencia_desde)
);

-- 11) Relacion de contribuyentes RS 295-2018/SUNAT
CREATE TABLE IF NOT EXISTS rs295_2018 (
    nro           int         PRIMARY KEY,
    expediente    varchar(40),
    ruc           varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social  text,
    cargado_en    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_rs295_ruc ON rs295_2018 (ruc);

-- 12) Productores Mineros y Fabricantes Nacionales de Joyas (DL 1552)
CREATE TABLE IF NOT EXISTS registro_dl1552 (
    tipo               varchar(20) NOT NULL CHECK (tipo IN ('PRODUCTOR_MINERO', 'FABRICANTE_JOYAS')),
    ruc                varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social       text,
    nro_inscripcion    varchar(10),
    fecha_presentacion date,
    cargado_en         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tipo, ruc)
);
CREATE INDEX IF NOT EXISTS ix_dl1552_ruc ON registro_dl1552 (ruc);

-- 13) TaxFree - establecimientos (REA). VIGENTE: fecha = incorporacion; EXCLUIDO: exclusion
CREATE TABLE IF NOT EXISTS taxfree_establecimientos (
    estado              varchar(10) NOT NULL CHECK (estado IN ('VIGENTE', 'EXCLUIDO')),
    ruc                 varchar(11) NOT NULL CHECK (ruc ~ '^[0-9]{11}$'),
    razon_social        text,
    nro_solicitud       int,
    fecha               date,
    nro_resolucion      varchar(15),
    nro_inscripcion_rea int,
    cargado_en          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (estado, ruc)
);
CREATE INDEX IF NOT EXISTS ix_taxfree_ruc ON taxfree_establecimientos (ruc);

-- 14) CPE con anotaciones judiciales (Plataforma Factoring)
CREATE TABLE IF NOT EXISTS cpe_anotaciones_judiciales (
    id                       bigserial   PRIMARY KEY,
    entidad_solicitante      text,
    organo                   text,
    documento                text,
    fecha_documento          text,              -- texto libre en la fuente: '09/06/2025 y 14/07/2025'
    expediente               text,
    fecha_expediente         text,
    tipo_comprobante         varchar(30),
    serie                    varchar(4),
    numero                   varchar(10),
    fecha_emision            date,
    ruc_emisor               varchar(11) CHECK (ruc_emisor ~ '^[0-9]{11}$'),
    razon_social_emisor      text,
    ruc_adquiriente          varchar(11) CHECK (ruc_adquiriente ~ '^[0-9]{11}$'),
    razon_social_adquiriente text,
    tipo_anotacion           text,
    cargado_en               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_cpe_ruc_emisor ON cpe_anotaciones_judiciales (ruc_emisor);
CREATE INDEX IF NOT EXISTS ix_cpe_ruc_adquiriente ON cpe_anotaciones_judiciales (ruc_adquiriente);

-- Traza de cada carga (un archivo = una fila por carga)
CREATE TABLE IF NOT EXISTS cargas (
    id          bigserial   PRIMARY KEY,
    archivo     text        NOT NULL,
    tabla       text        NOT NULL,
    filas       int         NOT NULL,
    corte       date        NOT NULL,           -- fecha del ZIP descargado de SUNAT
    huella_zip  char(64)    NOT NULL,           -- sha256 del ZIP
    reparados   int         NOT NULL DEFAULT 0, -- textos corregidos (doble codificacion, comillas)
    cargado_en  timestamptz NOT NULL DEFAULT now()
);

-- Vista base de la futura "ficha del RUC": en que padrones esta un RUC. Una fila por
-- (RUC, padron). Todas las ramas con ruc varchar(11): WHERE ruc = $1 usa el indice de cada una.
--   historico = true: listas viejas (2013/2016) que NO describen la situacion actual.
--   detalle: solo datos del padron; SIN documentos de personas (titulares, representantes).
--   SSCO: del Verificador (public.ruc_marcas), la fuente oficial ya cargada; no se duplica.
CREATE OR REPLACE VIEW v_ruc_padrones AS
    SELECT ruc, lower(padron) AS padron, fecha_desde AS desde, false AS historico,
           jsonb_build_object('resolucion', resolucion) AS detalle
      FROM padron_rs
    UNION ALL
    SELECT ruc, 'deuda_coactiva', NULL::date, false,
           jsonb_build_object('monto_deuda', monto_deuda, 'dependencia', dependencia, 'puesto', nro)
      FROM deuda_coactiva
    UNION ALL
    SELECT ruc, 'exceptuada_percepcion', NULL::date, false, jsonb_build_object('periodo', periodo, 'tipo', tipo)
      FROM exceptuadas_percepcion
    UNION ALL
    SELECT ruc, 'exportador_servicios', fecha_inscripcion, false,
           jsonb_build_object('servicio', descripcion_servicio, 'dependencia', dependencia)
      FROM exportadores_servicios
    UNION ALL
    SELECT ruc, 'exportador_sin_garantia', vigencia_desde, false, jsonb_build_object('hasta', vigencia_hasta)
      FROM exportadores_sin_garantia
    UNION ALL
    SELECT ruc, lower(tipo), fecha_presentacion, false, jsonb_build_object('inscripcion', nro_inscripcion)
      FROM registro_dl1552
    UNION ALL
    SELECT ruc, 'taxfree_' || lower(estado), fecha, false, jsonb_build_object('resolucion', nro_resolucion)
      FROM taxfree_establecimientos
    UNION ALL
    SELECT ruc, 'imprenta_autorizada', NULL::date, false, jsonb_build_object('distrito', distrito, 'provincia', provincia)
      FROM imprentas_autorizadas
    UNION ALL
    SELECT ruc, 'ssco_vinculada', fecha_publicacion, false,
           jsonb_build_object('supuestos', cant_supuestos, 'ssco_origen', cant_ssco_origen)
      FROM ssco_vinculadas
    UNION ALL
    SELECT ruc, 'rs295_2018', NULL::date, false, jsonb_build_object('expediente', expediente)
      FROM rs295_2018
    UNION ALL
    SELECT ruc_emisor, 'cpe_anotacion_judicial', fecha_emision, false,
           jsonb_build_object('rol', 'emisor', 'comprobante', serie || '-' || numero, 'anotacion', tipo_anotacion)
      FROM cpe_anotaciones_judiciales WHERE ruc_emisor IS NOT NULL
    UNION ALL
    SELECT ruc_adquiriente, 'cpe_anotacion_judicial', fecha_emision, false,
           jsonb_build_object('rol', 'adquiriente', 'comprobante', serie || '-' || numero, 'anotacion', tipo_anotacion)
      FROM cpe_anotaciones_judiciales WHERE ruc_adquiriente IS NOT NULL
    UNION ALL
    SELECT ruc, 'spot_no_aplica_ilima', NULL::date, true, '{}'::jsonb
      FROM spot_no_aplica_ilima
    UNION ALL
    SELECT ruc, 'spot_ingreso_fondos', max(fecha_notificacion), true,
           jsonb_build_object('ingresos', count(*), 'monto_total', sum(monto_ingreso))
      FROM spot_ingreso_fondos GROUP BY ruc
    UNION ALL
    SELECT ruc, 'ssco', (detalle->>'firme')::date, false,
           jsonb_build_object('resolucion', detalle->>'resolucion', 'publicacion', detalle->>'publicacion')
      FROM public.ruc_marcas WHERE padron = 'ssco';
