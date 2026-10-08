"""
Tablero del Club de Contadores: lista de herramientas (UNICO lugar donde se
agregan, se activan o se cambian de nivel).

  estado : "activa" (funciona, tocable) | "pronto" (visible, "Muy pronto")
  nivel  : "gratis" (sin cuenta) | "cuenta" (gratis con registro) | "premium" (de pago)
  sub    : subtitulo corto (que es)
  ben    : beneficio que invita (que hace por ti)
  frases : textos que ROTAN en la esquina de la tarjeta (CSS). Solo hechos
           verificables de la herramienta; nada de popularidad inventada.
  icono  : clave de ICONOS (trazos SVG 24x24)
  efecto : opcional, como entra la frase: "escribe" | "sube" | "fade". Sin el
           campo, la vitrina reparte los tres entre las tarjetas.

La vitrina (home del Club) agrupa por nivel y pone las activas primero. El tablero es
PUBLICO: las 'gratis' se usan sin cuenta; las 'cuenta' llevan a /entrar si no hay sesion;
las 'premium' piden suscripcion.
`mejora` apunta al id de la version de pago.
"""
from __future__ import annotations

NIVELES = [
    {"id": "gratis",  "kicker": "Gratis · sin cuenta",   "t1": "Empieza",    "t2": "gratis",
     "sub": "Úsalo ya, sin registrarte."},
    {"id": "cuenta",  "kicker": "Con tu cuenta · gratis", "t1": "Profundiza", "t2": "con tu cuenta",
     "sub": "Gratis al registrarte en el Club."},
    {"id": "premium", "kicker": "Premium · de pago",      "t1": "Escala",     "t2": "tu estudio",
     "sub": "Para crecer y atender más clientes."},
]

HERRAMIENTAS = [
    # --- Gratis -------------------------------------------------------------
    {"id": "igv", "nivel": "gratis", "estado": "activa", "icono": "calc", "url": "/igv",
     "nombre": "Calculadora de IGV", "efecto": "escribe", "sub": "Separa o agrega el 18%, al céntimo",
     "ben": "Cuadra tus comprobantes en segundos.", "cta": "Usar ahora",
     "frases": ["Al céntimo, sin descuadres", "Con IGV o sin IGV", "Sin crear cuenta", "Tasa general 18%"]},
    {"id": "calc", "nivel": "gratis", "estado": "pronto", "icono": "pct",
     "nombre": "Más calculadoras", "sub": "Detracciones, percepciones y TIM",
     "ben": "Deja de buscar tablas y porcentajes.",
     "frases": ["Detracciones por anexo", "Intereses moratorios (TIM)"]},
    {"id": "venc", "nivel": "gratis", "estado": "pronto", "icono": "cal",
     "nombre": "Vencimientos", "sub": "Cronograma por último dígito, con feriados",
     "ben": "Mira qué vence y cuándo según el último dígito de tu RUC{digito_txt}.",
     "frases": ["Por último dígito del RUC", "Incluye feriados"]},
    {"id": "ssco", "nivel": "gratis", "estado": "pronto", "icono": "shield",
     "nombre": "SSCO", "sub": "Sujetos Sin Capacidad Operativa",
     "ben": "Revisa al proveedor antes de usar su crédito fiscal.",
     "frases": ["Cuida el crédito fiscal", "Antes de pagar al proveedor"]},
    {"id": "ruc", "nivel": "gratis", "estado": "pronto", "icono": "search",
     "nombre": "Consulta RUC", "sub": "Por número o por razón social",
     "ben": "Estado, condición y domicilio en un solo lugar.",
     "frases": ["Busca por razón social", "Estado y condición"]},
    {"id": "emitir", "nivel": "gratis", "estado": "pronto", "icono": "doc",
     "nombre": "Emitir", "sub": "Boleta o factura suelta, sin cuenta",
     "ben": "Emite hoy mismo, sin instalar nada.",
     "frases": ["Boleta o factura", "Sin instalar nada"]},
    {"id": "mini", "nivel": "gratis", "estado": "pronto", "icono": "user",
     "nombre": "Mini-página", "sub": "Tu estudio en el Directorio",
     "ben": "Que los empresarios de {distrito} te encuentren.",
     "frases": ["Visible en tu distrito", "Tu estudio, con tu nombre"]},
    # --- Con tu cuenta ------------------------------------------------------
    {"id": "nn", "nivel": "cuenta", "estado": "activa", "icono": "chart", "url": "{nn_url}", "mejora": "nn2",
     "nombre": "Nuevos Negocios", "sub": "Altas SUNAT de tu distrito, cada mes", "efecto": "sube",
     "ben": "Quiénes se inscribieron en SUNAT en tu distrito. Llega antes que nadie.", "cta": "Ver mi distrito",
     "frases": ["Datos SUNAT de {mes_dato}", "Con actividad y fecha de alta", "Solo tu distrito", "Descárgalo en CSV"]},
    {"id": "verif", "nivel": "cuenta", "estado": "pronto", "icono": "check",
     "nombre": "Verificar comprobantes", "sub": "Validez de facturas y boletas en SUNAT",
     "ben": "Descarta comprobantes falsos antes de registrarlos.",
     "frases": ["Facturas y boletas", "Antes de registrar compras"]},
    {"id": "push", "nivel": "cuenta", "estado": "pronto", "icono": "bell",
     "nombre": "Alertas de vencimientos", "sub": "Avisos en tu celular",
     "ben": "Te avisamos antes de que venza cada obligación.",
     "frases": ["Aviso en tu celular", "Por cada cliente"]},
    {"id": "fact", "nivel": "cuenta", "estado": "pronto", "icono": "doc", "mejora": "factx",
     "nombre": "Facturalo", "sub": "Facturación para contadores",
     "ben": "Tus series y tus clientes en una sola cuenta.",
     "frases": ["Tus series, tus clientes", "Hecho para contadores"]},
    {"id": "via", "nivel": "cuenta", "estado": "pronto", "icono": "pin",
     "nombre": "RUCs por distrito + vía", "sub": "Contribuyentes de una calle o avenida",
     "ben": "Prospecta cuadra por cuadra.",
     "frases": ["Calle por calle", "Prospección en tu zona"]},
    {"id": "ubigeo", "nivel": "cuenta", "estado": "pronto", "icono": "layers",
     "nombre": "RUCs por ubigeo", "sub": "Padrón por código de ubigeo",
     "ben": "Exporta tu zona y planifica tus visitas.",
     "frases": ["Ubigeo {ubigeo}", "Exportable"]},
    # --- Premium ------------------------------------------------------------
    {"id": "alerta", "nivel": "premium", "estado": "activa", "icono": "inbox", "url": "https://alerta.pe/contadores",
     "nombre": "alerta.pe", "efecto": "fade", "sub": "Buzón SUNAT y SUNAFIL de tus clientes", "precio": "S/25",
     "precio_det": "hasta 10 RUC · S/5 cada RUC adicional",
     "ben": "Entérate de cada notificación antes que tu cliente.", "cta": "Conocer alerta.pe",
     "frases": ["SUNAT y SUNAFIL juntos", "Aviso apenas llega", "No marca como leído", "Hasta 10 RUC por S/25"]},
    {"id": "nn2", "nivel": "premium", "estado": "pronto", "icono": "chart",
     "nombre": "Nuevos Negocios · 2+ distritos", "sub": "Los vecinos o toda tu provincia",
     "ben": "Multiplica tu cartera de prospectos.",
     "frases": ["Distritos vecinos", "Toda tu provincia"]},
    {"id": "sire", "nivel": "premium", "estado": "pronto", "icono": "grid",
     "nombre": "SIRE", "sub": "Registros de ventas y compras",
     "ben": "Descarga, compara y concilia sin hojas sueltas.",
     "frases": ["Ventas y compras", "Concilia con SUNAT"]},
    {"id": "factx", "nivel": "premium", "estado": "pronto", "icono": "docs",
     "nombre": "Facturalo ilimitado", "sub": "Sin límite y varias empresas",
     "ben": "Factura para todos tus clientes desde una cuenta.",
     "frases": ["Sin límite de comprobantes", "Varias empresas"]},
    {"id": "web", "nivel": "premium", "estado": "pronto", "icono": "globe",
     "nombre": "Sitio Web · Estudio", "sub": "Tu web profesional",
     "ben": "Un sitio completo con tu marca, más allá de la mini-página.",
     "frases": ["Con tu marca", "Más que una mini-página"]},
]

# Productos para OFRECER a tus clientes (no son herramientas que usa el contador).
# estado: "pronto" | "despues" (mas adelante) | "activa"
GANA = [
    {"id": "teatiendo", "nombre": "TeAtiendo", "estado": "pronto",
     "desc": "Bot de WhatsApp con IA para los negocios que asesoras: responde a sus clientes 24/7, "
             "agenda y cobra, con la API oficial de Meta."},
    {"id": "pagook", "nombre": "PagoOK", "estado": "pronto",
     "desc": "Valida al instante los pagos por Yape y Plin que recibe tu cliente."},
    {"id": "quevendi", "nombre": "QueVendi", "estado": "despues",
     "desc": "Punto de venta para el negocio de tu cliente: ventas, caja y tickets."},
]

# Iconos de linea (24x24, stroke). Clave -> contenido del <svg>.
ICONOS = {
    "calc": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 12h.01M12 12h.01M16 12h.01M8 16h.01M12 16h.01M16 16h.01"/>',
    "pct": '<path d="M19 5 5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>',
    "cal": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M8 14h3v3H8z"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4"/>',
    "doc": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/>',
    "docs": '<path d="M9 3h7l4 4v11H9z"/><path d="M5 7v14h11"/>',
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.5 4-5 7-5s5.8 1.5 7 5"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "check": '<path d="M7 3h10v18l-5-3-5 3z"/><path d="m9.5 10 2 2 3.5-3.5"/>',
    "bell": '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
    "pin": '<path d="M12 21s-6-5.5-6-11a6 6 0 1 1 12 0c0 5.5-6 11-6 11z"/><circle cx="12" cy="10" r="2.2"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "inbox": '<path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 2h6l1-2h5"/>',
    "grid": '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M3 9h18M3 14h18M9 4v16"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
}


def armar_tablero(valores: dict, con_sesion: bool = True, entrar: str = "/entrar") -> list[dict]:
    """Secciones de la vitrina (una por nivel), activas primero, con los marcadores
    {digito}/{ubigeo}/{nn_url}/{distrito}/{mes_dato} rellenados con datos del socio."""
    def fmt(s: str) -> str:
        for k, v in valores.items():
            s = s.replace("{" + k + "}", str(v))
        return s

    por_id: dict[str, dict] = {}
    secciones = []
    for n in NIVELES:
        hs = [dict(h) for h in HERRAMIENTAS if h["nivel"] == n["id"]]
        hs.sort(key=lambda h: 0 if h["estado"] == "activa" else 1)   # estable
        for h in hs:
            for k in ("sub", "ben", "url"):
                if h.get(k):
                    h[k] = fmt(h[k])
            h["frases"] = [fmt(f) for f in h.get("frases", [])][:4]
            # Acceso segun nivel: gratis = libre; cuenta = pide RUC si no hay sesion;
            # premium = pide suscripcion (alerta.pe la gestiona en su propio sitio).
            if h["estado"] == "activa" and h["nivel"] == "cuenta" and not con_sesion:
                h["url"], h["cta"], h["requiere"] = entrar, "Entrar con tu RUC", "cuenta"
            elif h["estado"] == "activa" and h["nivel"] == "premium":
                h["requiere"] = "pago"
            h["externa"] = (h.get("url") or "").startswith("http")
            h["svg"] = ICONOS.get(h.get("icono"), ICONOS["doc"])
            por_id[h["id"]] = h
        secciones.append({**n, "herramientas": hs,
                          "activas": sum(1 for h in hs if h["estado"] == "activa")})
    # Ritmo propio por tarjeta: duracion por frase, desfase y efecto distintos, para
    # que nunca cambien todas a la vez. Desfase negativo = arranca ya a mitad de ciclo.
    i = 0
    for s in secciones:
        for h in s["herramientas"]:
            if h.get("mejora") in por_id:
                h["mejora_nombre"] = por_id[h["mejora"]]["nombre"]
            n = max(1, len(h["frases"]))
            # Las "Muy pronto" van mas lentas: el ojo encuentra primero las activas.
            h["ritmo"] = round(RITMOS[i % len(RITMOS)] * (1 if h["estado"] == "activa" else LENTO_PRONTO), 2)
            h["desfase"] = round(-((i * DESFASE) % (n * h["ritmo"])), 2)
            h["efecto"] = h.get("efecto") or EFECTOS[i % len(EFECTOS)]
            i += 1
    return secciones


RITMOS = [3.4, 2.6, 4.2, 3.0, 3.8]      # segundos por frase
DESFASE = 1.3                            # segundos entre una tarjeta y la siguiente
LENTO_PRONTO = 1.6                       # multiplicador de ritmo para las "Muy pronto"
EFECTOS = ["sube", "fade", "sube", "fade", "escribe"]   # escribir llama mucho: 1 de cada 5
