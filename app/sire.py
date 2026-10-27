"""Conversor SIRE (contadores.perusistemas.pro/sire). Fase 1: Compras, TXT -> Excel, MODO LOCAL.

La conversion ocurre en el navegador (app/static/js/sire/): el archivo y sus montos nunca llegan a
este servidor. Esta pagina solo sirve la pantalla, con una politica de seguridad (CSP) que impide al
navegador conectarse a otro dominio. Estructura y reglas: app/static/sire/sire-spec.json.

  SIRE_ABIERTO=1   sin esto, "muy pronto" (el admin la ve igual, para probarla)

Capacidades: "convertir" es gratis y sin cuenta. "riesgo" (cruce del proveedor, requiere cuenta) y
"servidor" (modo servidor) quedan listas para gatearse por suscripcion; en esta fase estan apagadas.

Actividad del generador (POST /api/sire/actividad): lo UNICO que sale del navegador es el RUC del
generador, en el cuerpo (no en la URL, para que no quede en los logs de acceso). Devuelve sus marcas
de las listas publicas y la ficha informativa de cada sector, sin nombrar la fuente ("datos al dd/mm").
No se guarda que RUC se consulto: solo cuenta para el tope diario por IP, igual que el Verificador.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import club, identidad

router = APIRouter()
ABIERTO = os.getenv("SIRE_ABIERTO", "0").strip() == "1"
# El navegador solo puede conectarse a este mismo sitio: ni el archivo ni nada sale a terceros (las
# fuentes tambien se sirven desde aqui: app/static/fonts/plex/).
CSP = ("default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def capacidades(s: dict | None) -> dict:
    """Que puede usar esta persona. Fase 1: solo convertir. Cuando exista la suscripcion del grupo de
    herramientas, aqui se decide (sin tocar la pantalla)."""
    return {"convertir": True, "riesgo": False, "servidor": False, "con_cuenta": bool(s)}


def tarjeta_tablero() -> dict | None:
    """Enciende la tarjeta "SIRE" del tablero (nivel gratis) cuando el conversor esta abierto."""
    if not ABIERTO:
        return None
    return {"sire": {"estado": "activa", "nivel": "gratis", "url": "/sire", "nombre": "Conversor SIRE",
                     "sub": "La propuesta de compras, en un Excel legible", "cta": "Convertir ahora",
                     "ben": "Sube el ZIP o el TXT de la propuesta y te devolvemos un Excel con columnas con nombre, errores marcados y totales.",
                     "frases": ["Se procesa en tu equipo", "Corrige punto y coma", "Totales por tipo", "Cuadra con el resumen"]}}


# --- Actividad / marcas del generador ----------------------------------------------------------------
# Ficha informativa por marca: sector (por lo que es, sin la fuente) y particularidades tributarias.
# Texto orientativo, no calculo. Las marcas sin ficha se muestran solo con su nombre.
FICHAS = {
    "productor_minero": ("Minería", [
        "Su venta de metal a un fabricante nacional de joyas inscrito se considera exportación (DL 1552): no lleva IGV y da derecho al saldo a favor del exportador.",
        "Debe comunicar la entrega del metal dentro de 5 días; las joyas deben embarcarse dentro de 60 días hábiles.",
        "Las ventas de minerales pueden estar sujetas a detracciones: revisa el bien en el anexo que corresponde."]),
    "fabricante_joyas": ("Joyería", [
        "El metal que le vende un productor minero inscrito se trata como exportación del productor (DL 1552): esa compra no lleva IGV.",
        "Debe confirmar la recepción del metal y embarcar las joyas dentro de 60 días hábiles desde la entrega."]),
    "exportador_servicios": ("Comercio exterior", [
        "La exportación de servicios no está gravada con el IGV y da derecho al saldo a favor del exportador.",
        "Para el destino de tus compras, la exportación cuenta como operación gravada (casilla 107; 110 solo si también tienes ventas no gravadas)."]),
    "exportador_sin_garantia": ("Comercio exterior", [
        "Figura en la lista de exportadores sin garantía para la devolución del saldo a favor.",
        "El saldo a favor del exportador se ve en las casillas 106 y 127 del Formulario 621."]),
    "percepcion_hidrocarburos": ("Combustibles", [
        "Como agente de percepción en la venta de combustibles, cobra la percepción del IGV a sus clientes.",
        "Declara lo percibido en el formulario de percepciones."]),
    "imprenta_autorizada": ("Imprenta", [
        "Imprenta autorizada para imprimir comprobantes de pago físicos.",
        "Cada trabajo de impresión de comprobantes debe estar autorizado antes de entregarse."]),
    "taxfree_vigente": ("Turismo · Tax Free", [
        "Establecimiento que puede vender a turistas con devolución del IGV (Tax Free)."]),
    "taxfree_excluido": ("Turismo · Tax Free", ["Fue excluido del régimen Tax Free."]),
    "renuncia_exoneracion_apendice_i": ("Agro y alimentos", [
        "Renunció a la exoneración del IGV de los bienes del Apéndice I: sus ventas de esos bienes están gravadas.",
        "Por eso sus compras para esas ventas sí dan crédito fiscal (destino gravado)."]),
    "agente_retencion": (None, [
        "Retiene el 3% del IGV a sus proveedores y les entrega el comprobante de retención.",
        "No retiene a proveedores que son buenos contribuyentes u otros agentes de retención."]),
    "buen_contribuyente": (None, ["Sus proveedores agentes de retención no le retienen el IGV."]),
    "percepcion_venta_interna": (None, [
        "Cobra la percepción del IGV a sus clientes en la venta de los bienes del régimen.",
        "Sus clientes la usan como pago a cuenta (casilla de percepciones del Formulario 621)."]),
    "exceptuada_percepcion": (None, ["No se le cobra percepción del IGV en sus compras."]),
    "deuda_coactiva": (None, ["Tiene deuda en cobranza coactiva: puede haber embargos sobre sus cuentas o cobros."]),
    "ssco_vinculada": (None, ["Está vinculada a un sujeto sin capacidad operativa: revisa sus operaciones con él."]),
    "ssco": (None, ["Mientras figure como sujeto sin capacidad operativa, sus clientes no pueden usar el crédito fiscal de sus comprobantes."]),
    "spot_no_aplica_ilima": (None, ["Lista antigua (2013) de detracciones: no describe la situación actual."]),
    "spot_ingreso_fondos": (None, ["Lista antigua (2015-2016) de detracciones: no describe la situación actual."]),
}


async def _marcas(ruc: str) -> tuple[list[dict], str | None]:
    """Marcas del RUC (listas publicas + SSCO) y la fecha de corte mas reciente (dd/mm/aaaa)."""
    from . import api_v1, db, verificador
    pad, corte = await api_v1.padrones_de([ruc])
    marcas = list((pad or {}).get(ruc, []))
    fila = await db._pool.fetchrow(f"SELECT desde FROM {verificador.ESQUEMA}.v_ruc_marcas WHERE ruc = $1 AND padron = 'ssco'", ruc)
    if fila:
        marcas.insert(0, {"codigo": "ssco", "nombre": "Sujeto sin capacidad operativa", "tipo": "riesgo",
                          "desde": fila["desde"].isoformat() if fila["desde"] else None, "historico": False})
    al = f"{corte[8:10]}/{corte[5:7]}/{corte[:4]}" if corte else None
    return marcas, al


@router.post("/api/sire/actividad")
async def api_actividad(payload: dict, request: Request):
    if not ABIERTO and not await identidad.es_admin(request):
        return JSONResponse({"ok": False, "error": "El Conversor SIRE estará disponible muy pronto."}, status_code=403)
    ruc = str(payload.get("ruc") or "").strip()
    if not identidad.ruc_valido(ruc):
        return JSONResponse({"ok": False, "error": "RUC no válido."}, status_code=422)
    from . import verificador
    ip = club._client_ip(request)
    if await verificador._uso_hoy(ip) + 1 > verificador.MAX_DIA_IP:          # mismo tope diario por IP
        return JSONResponse({"ok": False, "error": "Llegaste al tope de consultas de hoy."}, status_code=429)
    marcas, al = await _marcas(ruc)
    s = await club.socio_actual(request)
    await verificador._registrar(ip, (s or {}).get("persona_id"), 1, "sire")      # cuenta, sin el RUC
    sectores, out = [], []
    for m in marcas:
        sector, notas = FICHAS.get(m["codigo"], (None, []))
        if sector and sector not in sectores:
            sectores.append(sector)
        out.append({"codigo": m["codigo"], "nombre": m["nombre"], "tipo": m["tipo"], "historico": m.get("historico", False),
                    "desde": m.get("desde"), "sector": sector, "notas": notas})
    out.sort(key=lambda m: (m["historico"], m["sector"] is None, m["tipo"] != "riesgo"))
    resp = JSONResponse({"ok": True, "sectores": sectores, "marcas": out, "datos_al": al})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/sire", response_class=HTMLResponse)
async def pagina(request: Request):
    host = club._host(request)
    if host == club.CLUB_HOST:                       # su casa es contadores.perusistemas.pro
        q = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"https://{club.CONTADORES_HOST}/sire{q}", status_code=301)
    s = await club.socio_actual(request)
    if not ABIERTO and not await identidad.es_admin(request):
        return club.templates.TemplateResponse(request, "club/pronto.html", {
            "s": s, "inicio": club.inicio(request), "que": "El Conversor SIRE", "sig": "", "psp_whatsapp": club.PSP_WHATSAPP})
    resp = club.templates.TemplateResponse(request, "club/sire.html", {
        "s": s, "inicio": club.inicio(request), "capacidades": capacidades(s)})
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-cache"
    return resp
