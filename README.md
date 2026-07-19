# Club de Contadores — WebApp (PWA) de pre-inscripción

Página de **pre-inscripción / waitlist** para el Club de Contadores de Perú Sistemas Pro
(`contadores.perusistemas.pro`). Captura leads de contadores/estudios contables y les
entrega valor real en pantalla: **los nuevos negocios (altas de RUC) de su distrito**.

Stack: **FastAPI + PostgreSQL (asyncpg) + Jinja2 + Vanilla JS**. PWA con service worker y
manifest. Mobile-first, **una sola vista sin scroll de página**, embudo por etapas.
es-PE neutro con tuteo. Tema oscuro verde-contador.

---

## Estructura

```
contadores/
├── app/
│   ├── main.py              FastAPI: rutas + API del embudo + PWA
│   ├── db.py                Acceso PostgreSQL (asyncpg) + MODO DEMO sin BD
│   ├── ruc.py               Validación de RUC (apis.net.pe → fallback formato)
│   ├── templates/index.html Embudo de 4 etapas (una sola vista)
│   └── static/
│       ├── css/styles.css   Tema oscuro, sin scroll de página
│       ├── js/app.js        Lógica del embudo, combo distritos, wa.me, push
│       ├── distritos.json   1893 distritos del Perú (ubigeo INEI)
│       ├── manifest.webmanifest
│       ├── sw.js            Service worker (versionar en cada deploy)
│       └── icons/           192 / 512 / maskable
├── sql/schema.sql           DDL para PGAdmin (NO Alembic)
├── requirements.txt
├── Procfile                 Comando de arranque (Railway)
└── .env.example
```

---

## El embudo (una etapa visible a la vez, sin scroll)

0. **Portada** — gancho + prueba social ("más de 800 estudios") + video + CTA.
1. **RUC + Distrito** — valida RUC (trae razón social) y elige distrito.
2. **Adelanto + contacto** — muestra el conteo real de nuevos negocios de los últimos
   meses del distrito; pide WhatsApp + email.
3. **Entrega + WhatsApp** — muestra **la lista real** de nuevos negocios en pantalla
   (spinner real) y botón **wa.me pre-cargado** (el contador toca enviar; honesto).

> La lista de la etapa 3 vive en un contenedor con **scroll interno propio**: la página
> nunca hace scroll (el header y el CTA quedan fijos, todo en una sola vista).

---

## Correr en local

```bash
cd contadores
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abre http://localhost:8000. **Sin `DATABASE_URL` arranca en MODO DEMO** (datos de
ejemplo para Miraflores y Santiago de Surco) — ideal para probar el embudo en el
viewport del celular. Prueba con DevTools → dispositivo iPhone/Android (~390px).

RUC de prueba (formato válido): `20601234501`. Distrito: escribe "mira" y elige
**Miraflores**.

---

## Deploy en Railway (drag-and-drop, sin git push)

1. Sube la carpeta `contadores/` como servicio (drag-and-drop / New → Deploy).
2. Railway detecta `requirements.txt` + `Procfile`. Comando de arranque:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Añade un plugin **PostgreSQL** → Railway inyecta `DATABASE_URL` automáticamente.
4. Variables de entorno (ver `.env.example`):
   - `APIS_NET_PE_TOKEN` — token de apis.net.pe (el mismo de alerta.pe). Sin él, el RUC
     se valida solo por formato.
   - `ESTUDIOS_TOTAL` — número de prueba social (empieza en 800, súbelo con el tiempo).
   - `VIDEO_URL` — URL de embed del video (opcional).
   - `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` — para push (opcional, ver abajo).
5. Apunta `contadores.perusistemas.pro` (CNAME) al dominio del servicio en Railway.

---

## Base de datos (PGAdmin, sin Alembic)

Ejecuta **`sql/schema.sql`** tal cual en la BD (crea `nuevos_negocios`,
`inscripciones`, `push_subscriptions` con sus índices).

### Carga manual inicial de `nuevos_negocios`

Los nuevos negocios **se cargan manual al inicio** (el importador XLSX viene después).
Inserta directo a la BD. El índice único en `ruc` + `ON CONFLICT (ruc) DO NOTHING`
evita duplicados:

```sql
INSERT INTO nuevos_negocios
  (ruc, razon_social, tipo, ciiu, giro, ubigeo, distrito, provincia, departamento,
   fecha_inscripcion, fecha_inicio_actividades, direccion, nombre_comercial)
VALUES
  ('20601234567','INVERSIONES EJEMPLO SAC','juridica','4711','Venta al por menor en bodegas',
   '150122','MIRAFLORES','LIMA','LIMA','2026-07-03','2026-07-10',
   'AV. EJEMPLO 123, MIRAFLORES','BODEGA EJEMPLO')
ON CONFLICT (ruc) DO NOTHING;
```

- **`ubigeo`**: código INEI de 6 dígitos (ver `app/static/distritos.json`). La app filtra
  por `ubigeo` (exacto) y cae a `distrito` por nombre si no lo tiene.
- **`fecha_inscripcion`**: fecha de alta del RUC — es lo que se agrupa por mes en el
  adelanto (etapa 2).

Los **leads** capturados quedan en `inscripciones` (nombre, RUC, distrito, WhatsApp,
email, origen). Ese es el activo. `origen` se puede rastrear con `?o=colegio|facebook|youtube`
en el enlace de la convocatoria.

---

## Push (opcional, preparado — no en el camino crítico)

El valor se entrega **en pantalla sin depender de push ni de WhatsApp**. Para activar
avisos 1-2 veces por semana:

1. Genera claves VAPID:
   ```bash
   python -c "from py_vapid import Vapid01; v=Vapid01(); v.generate_keys(); import base64;
   print('PUB', base64.urlsafe_b64encode(v.public_key.public_bytes_raw()).decode().rstrip('='))"
   ```
   (o usa cualquier generador VAPID; guarda pública y privada).
2. Setea `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` en Railway.
3. Las suscripciones se guardan en `push_subscriptions`. El envío masivo (con `pywebpush`)
   se agrega como script aparte cuando toque enviar la primera campaña.

---

## Configuración a revisar antes de publicar

- **Número de WhatsApp**: en `app/static/js/app.js` → `WA_NUMBER` (actualmente
  `51999888777`). Cambiar por el real del Club.
- **`sw.js`**: subir la versión de `CACHE` (`club-contadores-v1` → `-v2`…) en cada deploy
  para invalidar caché.
- **Copy**: todo en tuteo peruano neutro. Sub-promete: solo directorio + nuevos negocios
  + "más en camino". No anunciar herramientas que aún no existen.

---

## Lo que NO incluye (a propósito, para no sobre-construir)

Importador XLSX, directorio navegable completo de los 800+ estudios, las demás
herramientas (calculadoras, vencimientos, normas, radar), y la detección real del
WhatsApp vía PagoOK. Todo eso viene después sobre esta base.
