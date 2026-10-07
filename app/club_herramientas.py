"""
Tablero del Club de Contadores: lista de herramientas (UNICO lugar donde se
agregan, se activan o se cambian de nivel).

  estado: "activa" (funciona, tocable) | "pronto" (visible, atenuada, "Muy pronto")
  nivel : "gratis" (sin cuenta) | "cuenta" (gratis con registro) | "premium" (de pago)

El nivel decide la COLUMNA del tablero (A/B/C) y su color; la direccion de celda
(A1, B2...) se calcula sola: activas primero, luego en el orden de esta lista.
`mejora` apunta al id de la version de pago ("mas en C2").
"""
from __future__ import annotations

NIVELES = [
    {"id": "gratis",  "letra": "A", "nombre": "Gratis",        "sub": "Sin cuenta. Úsalo ya."},
    {"id": "cuenta",  "letra": "B", "nombre": "Con tu cuenta", "sub": "Gratis al registrarte."},
    {"id": "premium", "letra": "C", "nombre": "Premium",       "sub": "De pago, para escalar."},
]

HERRAMIENTAS = [
    # --- A · Gratis ---------------------------------------------------------
    {"id": "igv", "nivel": "gratis", "estado": "activa", "nombre": "Calculadora de IGV",
     "fn": "=IGV(monto; incluido)", "url": "/club/igv",
     "desc": "Separa o agrega el IGV de 18% en un monto, al céntimo."},
    {"id": "calc", "nivel": "gratis", "estado": "pronto", "nombre": "Más calculadoras",
     "fn": "=DETRACCION(monto; anexo)",
     "desc": "Detracciones, percepciones y TIM."},
    {"id": "venc", "nivel": "gratis", "estado": "pronto", "nombre": "Vencimientos",
     "fn": "=VENCIMIENTO({digito})",
     "desc": "Cronograma por último dígito del RUC, con feriados. Tu dígito: {digito}."},
    {"id": "ssco", "nivel": "gratis", "estado": "pronto", "nombre": "SSCO", "fn": "=SSCO(ruc)",
     "desc": "Sujetos Sin Capacidad Operativa: revisa a un proveedor antes de usar su crédito fiscal."},
    {"id": "ruc", "nivel": "gratis", "estado": "pronto", "nombre": "Consulta RUC",
     "fn": "=RUC(numero; razon_social)",
     "desc": "Busca por número o por razón social: estado, condición, domicilio y actividad."},
    {"id": "emitir", "nivel": "gratis", "estado": "pronto", "nombre": "Emitir", "fn": "=EMITIR(boleta)",
     "desc": "Emite una boleta o factura electrónica suelta, sin crear cuenta."},
    {"id": "mini", "nivel": "gratis", "estado": "pronto", "nombre": "Mini-página", "fn": "=MI.PAGINA(estudio)",
     "desc": "La página de tu estudio, visible en el Directorio para empresarios de tu distrito."},
    # --- B · Con tu cuenta --------------------------------------------------
    {"id": "nn", "nivel": "cuenta", "estado": "activa", "nombre": "Nuevos Negocios",
     "fn": "=NUEVOS.NEGOCIOS(distrito)", "url": "{nn_url}", "mejora": "nn2",
     "desc": "Quiénes se inscribieron en SUNAT en tu distrito: clientes potenciales antes que nadie."},
    {"id": "verif", "nivel": "cuenta", "estado": "pronto", "nombre": "Verificar comprobantes",
     "fn": "=VALIDAR.CPE(serie; numero)",
     "desc": "Confirma en SUNAT que una factura o boleta recibida es válida."},
    {"id": "push", "nivel": "cuenta", "estado": "pronto", "nombre": "Alertas de vencimientos",
     "fn": "=AVISAR(vencimiento)",
     "desc": "Aviso push en tu celular antes de que venza cada obligación de tus clientes."},
    {"id": "fact", "nivel": "cuenta", "estado": "pronto", "nombre": "Facturalo", "fn": "=FACTURAR(cliente)",
     "mejora": "factx",
     "desc": "Facturación electrónica para contadores, con tus series y tus clientes."},
    {"id": "via", "nivel": "cuenta", "estado": "pronto", "nombre": "RUCs por distrito + vía",
     "fn": "=RUCS.VIA(distrito; via)",
     "desc": "Todos los contribuyentes de una calle o avenida de tu distrito."},
    {"id": "ubigeo", "nivel": "cuenta", "estado": "pronto", "nombre": "RUCs por ubigeo",
     "fn": "=RUCS.UBIGEO({ubigeo})",
     "desc": "Padrón de contribuyentes por código de ubigeo, exportable."},
    # --- C · Premium --------------------------------------------------------
    {"id": "alerta", "nivel": "premium", "estado": "activa", "nombre": "alerta.pe",
     "fn": "=BUZON.SUNAT(clientes)", "url": "https://alerta.pe/contadores",
     "desc": "Vigila el Buzón SUNAT y SUNAFIL de tus clientes y te avisa apenas llega una notificación."},
    {"id": "nn2", "nivel": "premium", "estado": "pronto", "nombre": "Nuevos Negocios · 2+ distritos",
     "fn": "=NUEVOS.NEGOCIOS(distritos)",
     "desc": "Los distritos vecinos o toda tu provincia, en un solo reporte."},
    {"id": "sire", "nivel": "premium", "estado": "pronto", "nombre": "SIRE", "fn": "=SIRE(periodo)",
     "desc": "Registros de ventas y compras electrónicos: descarga, compara y concilia."},
    {"id": "factx", "nivel": "premium", "estado": "pronto", "nombre": "Facturalo ilimitado",
     "fn": "=FACTURAR(*)",
     "desc": "Comprobantes sin límite y varias empresas desde una cuenta."},
    {"id": "web", "nivel": "premium", "estado": "pronto", "nombre": "Sitio Web - Estudio",
     "fn": "=SITIO.WEB(estudio)",
     "desc": "Un sitio web completo para tu estudio, un paso más allá de la mini-página."},
]

# Productos para OFRECER a tus clientes (no son herramientas que usa el contador).
# estado: "pronto" | "despues" (mas adelante) | "activa"
GANA = [
    {"id": "teatiendo", "nombre": "TeAtiendo", "fn": "=TEATIENDO(cliente)", "estado": "pronto",
     "desc": "Bot de WhatsApp con IA para los negocios que asesoras: responde a sus clientes 24/7, "
             "agenda y cobra, con la API oficial de Meta."},
    {"id": "pagook", "nombre": "PagoOK", "fn": "=PAGOOK(cliente)", "estado": "pronto",
     "desc": "Valida al instante los pagos por Yape y Plin que recibe tu cliente."},
    {"id": "quevendi", "nombre": "QueVendi", "fn": "=QUEVENDI(cliente)", "estado": "despues",
     "desc": "Punto de venta para el negocio de tu cliente: ventas, caja y tickets."},
]


def armar_tablero(valores: dict) -> list[dict]:
    """Columnas del tablero, con direcciones de celda resueltas y los marcadores
    {digito}/{ubigeo}/{nn_url} rellenados con datos del socio."""
    def fmt(s: str) -> str:
        for k, v in valores.items():
            s = s.replace("{" + k + "}", str(v))
        return s

    por_id: dict[str, dict] = {}
    columnas = []
    for n in NIVELES:
        hs = [dict(h) for h in HERRAMIENTAS if h["nivel"] == n["id"]]
        hs.sort(key=lambda h: 0 if h["estado"] == "activa" else 1)   # estable
        for i, h in enumerate(hs, 1):
            h["dir"] = f"{n['letra']}{i}"
            for k in ("fn", "desc", "url"):
                if h.get(k):
                    h[k] = fmt(h[k])
            h["externa"] = (h.get("url") or "").startswith("http")
            por_id[h["id"]] = h
        columnas.append({**n, "herramientas": hs,
                         "activas": sum(1 for h in hs if h["estado"] == "activa")})
    for c in columnas:
        for h in c["herramientas"]:
            if h.get("mejora") in por_id:
                h["mejora_dir"] = por_id[h["mejora"]]["dir"]
    return columnas
