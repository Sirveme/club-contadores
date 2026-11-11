-- alter_v16: prueba gratis de la extension Ficha RUC (15 dias por instalacion). Se ejecuta despues
-- de alter_v14, con search_path = <esquema>, public. Idempotente.
--
-- Una prueba es una fila mas de api_llaves (plan 'prueba', con vence_en): la cuota, el ritmo y la
-- bitacora funcionan igual que con cualquier llave. El VENCIMIENTO se controla aqui, en el servidor:
-- borrar los datos de la extension no reinicia la prueba de esa instalacion.
ALTER TABLE api_llaves ADD COLUMN IF NOT EXISTS instalacion       uuid;         -- UUID que genera la extension la 1a vez
ALTER TABLE api_llaves ADD COLUMN IF NOT EXISTS codigo            text;         -- 'K7QM-4XPA': el que la persona dicta por WhatsApp
ALTER TABLE api_llaves ADD COLUMN IF NOT EXISTS vence_en          timestamptz;  -- NULL = acceso permanente
ALTER TABLE api_llaves ADD COLUMN IF NOT EXISTS ip_alta           text;         -- sha256 de la IP que la pidio (tope por IP/dia)
ALTER TABLE api_llaves ADD COLUMN IF NOT EXISTS solicitud_persona uuid;         -- socio que se registro desde la extension
ALTER TABLE api_llaves ADD COLUMN IF NOT EXISTS solicitud_en      timestamptz;
ALTER TABLE api_llaves ADD COLUMN IF NOT EXISTS activada_en       timestamptz;  -- paso de prueba a permanente
CREATE UNIQUE INDEX IF NOT EXISTS ux_api_llaves_instalacion ON api_llaves (instalacion) WHERE instalacion IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_api_llaves_codigo ON api_llaves (codigo) WHERE codigo IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_api_llaves_ip_alta ON api_llaves (ip_alta, creada_en) WHERE ip_alta IS NOT NULL;
