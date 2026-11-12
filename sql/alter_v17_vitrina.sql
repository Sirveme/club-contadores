-- alter_v17: vitrina de la extension Ficha RUC (tarjetas al pie de la ficha y de la tabla). Se ejecuta
-- despues de alter_v16, con search_path = <esquema>, public. Idempotente.
--
-- Las tarjetas son SOLO DATOS (titulo, texto, emoji, colores, enlace, orden, activo): la extension las
-- pinta con textContent y nunca ejecuta nada que venga de aqui. Se editan desde /panel/vitrina.
-- No se borran: se desactivan (si no, la semilla de abajo las volveria a crear).
CREATE TABLE IF NOT EXISTS vitrina_tarjetas (
    id              serial PRIMARY KEY,
    clave           text NOT NULL UNIQUE,              -- 'psp', 'teatiendo'... (identifica la tarjeta)
    orden           int  NOT NULL DEFAULT 0,
    activo          boolean NOT NULL DEFAULT true,
    titulo          text NOT NULL,
    texto           text NOT NULL,
    emoji           text NOT NULL DEFAULT '',
    color1          text NOT NULL,                     -- #rrggbb (degradado de -> a)
    color2          text NOT NULL,
    boton           text NOT NULL,
    enlace          text NOT NULL,                     -- https://... (se le agrega ?ref=ficha-ruc al salir)
    actualizado_en  timestamptz NOT NULL DEFAULT now()
);

-- Clics por tarjeta y por DIA (hora de Lima). Solo el conteo: sin RUC, sin IP, sin identificadores.
CREATE TABLE IF NOT EXISTS vitrina_clics (
    tarjeta_id  int  NOT NULL REFERENCES vitrina_tarjetas (id),
    dia         date NOT NULL,
    clics       int  NOT NULL DEFAULT 0,
    PRIMARY KEY (tarjeta_id, dia)
);

INSERT INTO vitrina_tarjetas (clave, orden, titulo, texto, emoji, color1, color2, boton, enlace) VALUES
    ('psp',       10, 'Perú Sistemas Pro', '¿Necesitas un sistema a medida?',          '💡', '#ff7a18', '#d6246e', 'Escríbenos', 'https://wa.me/51967317946'),
    ('teatiendo', 20, 'TeAtiendo',         'Tu WhatsApp atiende solo, 24/7',           '🤖', '#6a3df0', '#a347e8', 'Conócelo',   'https://teatiendo.pro'),
    ('quevendi',  30, 'QueVendi',          'Vende y factura con tu voz',               '🎤', '#0fb5ae', '#1f7ae0', 'Pruébalo',   'https://quevendi.pro'),
    ('iasinmiedo',40, 'Curso IA sin Miedo','Solo para miembros del Club',              '🎓', '#ff6b6b', '#f0932b', 'Ver el curso','https://iasinmiedo.pro'),
    ('alertape',  50, 'alerta.pe',         'Que no se te pase ninguna notificación',   '🔔', '#e94057', '#8a2387', 'Conócelo',   'https://alerta.pe')
ON CONFLICT (clave) DO NOTHING;
