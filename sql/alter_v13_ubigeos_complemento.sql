-- alter_v13: 8 ubigeos que trae el padron de SUNAT y faltaban en cat_ubigeo.
-- Codificacion INEI (la de SUNAT, no la de RENIEC). Aprobados por Duilio el 2026-10-11.
--   180107 San Antonio (Ley 31216) y 130112 Alto Trujillo: distritos posteriores a 2018; nombres
--     segun los datos SUNAT de nuevos_negocios y los domicilios reales, verificados por Duilio.
--   090708, 160111, 160203, 160204, 160208, 160209: anexo de ubigeos SUNAT 2018
--     (anexoI-254-2018). Los cuatro de Alto Amazonas con su codigo antiguo, como SUNAT los mantiene
--     (hoy esos distritos estan en Datem del Maranon, 1607xx).
INSERT INTO cat_ubigeo (ubigeo, departamento, provincia, distrito) VALUES
    ('090708', 'HUANCAVELICA', 'TAYACAJA', 'HUANDO'),
    ('130112', 'LA LIBERTAD', 'TRUJILLO', 'ALTO TRUJILLO'),
    ('160111', 'LORETO', 'MAYNAS', 'YAQUERANA'),
    ('160203', 'LORETO', 'ALTO AMAZONAS', 'BARRANCA'),
    ('160204', 'LORETO', 'ALTO AMAZONAS', 'CAHUAPANAS'),
    ('160208', 'LORETO', 'ALTO AMAZONAS', 'MORONA'),
    ('160209', 'LORETO', 'ALTO AMAZONAS', 'PASTAZA'),
    ('180107', 'MOQUEGUA', 'MARISCAL NIETO', 'SAN ANTONIO')
ON CONFLICT (ubigeo) DO NOTHING;
