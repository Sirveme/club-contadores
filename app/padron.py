"""Padron Reducido de SUNAT: reglas compartidas por la carga y el Verificador.

Formato real (diagnostico del 2026-10-11 sobre el corte 2026-10-10):
- Latin-1, separador "|" con un "|" final extra, fin de linea LF.
- Listado general: 15 columnas. El domicilio viene partido en 10 columnas y los
  encabezados de zona estan cruzados: "CODIGO DE ZONA" trae el TIPO (URB., A.H.)
  y "TIPO DE ZONA" trae el NOMBRE.
- Locales anexos: 12 columnas, con OTRO orden (el kilometro va despues del numero).
- Algunas filas traen el pipe escapado como "\\|" dentro de un campo.
- "-" y "----" significan vacio. Estado y condicion vienen truncados a 20 caracteres.
"""
from __future__ import annotations

import re

def partir(linea: str) -> list[str]:
    """Campos de una linea sin el pipe final. La barra invertida escapa al caracter que
    sigue: "\\|" es un pipe dentro del campo y "\\\\" una barra literal (por eso
    "CHAVEZ\\\\|A" son dos campos). Casi ninguna linea trae barras: camino rapido."""
    linea = linea.rstrip("\r\n")
    if "\\" not in linea:
        return (linea[:-1] if linea.endswith("|") else linea).split("|")
    campos, actual, i = [], [], 0
    while i < len(linea):
        ch = linea[i]
        if ch == "\\" and i + 1 < len(linea):
            actual.append(linea[i + 1])
            i += 2
            continue
        if ch == "|":
            campos.append("".join(actual))
            actual = []
        else:
            actual.append(ch)
        i += 1
    if actual:
        campos.append("".join(actual))
    return campos


def razon_social(v: str) -> str:
    """Sin espacios ni barras sueltas en los bordes ('RUTHERFORD S.A.\\' -> 'RUTHERFORD S.A.')."""
    return (v or "").strip().strip("\\").strip()


def vacio(v: str | None) -> str:
    """'-', '----' y restos de escapes ('|' o '\\' en los bordes) cuentan como vacio."""
    v = (v or "").strip().strip("|\\").strip()
    return "" if v in ("", "-", "--", "---", "----") else v


# Domicilio en el formato en que SUNAT lo muestra:
#   "AV. JOSE PARDO NRO. 916 INT. 801 URB. MIRAFLORES - LIMA - LIMA - MIRAFLORES"
def componer_domicilio(tipo_via, nombre_via, tipo_zona, nombre_zona, numero, interior,
                       lote, dpto, manzana, km, ubigeo_nombres: tuple[str, str, str] | None) -> str | None:
    via = " ".join(x for x in (vacio(tipo_via), vacio(nombre_via)) if x)
    partes = [via] if via else []
    for etiqueta, v in (("NRO.", numero), ("KM.", km), ("MZA.", manzana), ("LOTE.", lote),
                        ("INT.", interior), ("DPTO.", dpto)):
        if vacio(v):
            partes.append(f"{etiqueta} {vacio(v)}")
    zona = " ".join(x for x in (vacio(tipo_zona), vacio(nombre_zona)) if x)
    if zona:
        partes.append(zona)
    if not partes:
        return None
    texto = " ".join(partes)
    if ubigeo_nombres and all(ubigeo_nombres):
        texto += " - " + " - ".join(ubigeo_nombres)
    return texto


# Ubigeos que trae el padron y no estan en cat_ubigeo (POR CONFIRMAR con Duilio antes de
# agregarlos al catalogo). Codificacion INEI, la que usa SUNAT (no la de RENIEC).
#   090708, 160111, 160203, 160204, 160208, 160209: anexo de ubigeos SUNAT 2018
#     (sunat.gob.pe/legislacion/superin/2018/anexoI-254-2018.pdf). SUNAT mantiene los cuatro
#     de Alto Amazonas con su codigo antiguo (hoy Datem del Maranon, 1607xx).
#   130112, 180107: distritos posteriores a 2018; nombres segun los propios datos SUNAT de
#     nuevos_negocios y confirmados por los domicilios reales (Barrio 3A/3B de Alto Trujillo;
#     Ciudad Nueva y Alto Tiwinza de San Antonio, Moquegua).
UBIGEOS_COMPLEMENTO = {
    "090708": ("HUANCAVELICA", "TAYACAJA", "HUANDO"),
    "130112": ("LA LIBERTAD", "TRUJILLO", "ALTO TRUJILLO"),
    "160111": ("LORETO", "MAYNAS", "YAQUERANA"),
    "160203": ("LORETO", "ALTO AMAZONAS", "BARRANCA"),
    "160204": ("LORETO", "ALTO AMAZONAS", "CAHUAPANAS"),
    "160208": ("LORETO", "ALTO AMAZONAS", "MORONA"),
    "160209": ("LORETO", "ALTO AMAZONAS", "PASTAZA"),
    "180107": ("MOQUEGUA", "MARISCAL NIETO", "SAN ANTONIO"),
}


# Columnas por archivo (indices despues de partir()).
#   listado: RUC|RAZON|ESTADO|CONDICION|UBIGEO|TIPO VIA|NOMBRE VIA|COD ZONA(=tipo)|TIPO ZONA(=nombre)|
#            NUMERO|INTERIOR|LOTE|DEPARTAMENTO|MANZANA|KILOMETRO
#   anexo:   RUC|UBIGEO|TIPO VIA|NOMBRE VIA|COD ZONA(=tipo)|TIPO ZONA(=nombre)|NUMERO|KILOMETRO|
#            INTERIOR|LOTE|DEPARTAMENTO|MANZANA
def domicilio_listado(c: list[str], ubis: dict) -> str | None:
    return componer_domicilio(c[5], c[6], c[7], c[8], c[9], c[10], c[11], c[12], c[13], c[14],
                              ubis.get(vacio(c[4])))


def domicilio_anexo(c: list[str], ubis: dict) -> str | None:
    return componer_domicilio(c[2], c[3], c[4], c[5], c[6], c[8], c[9], c[10], c[11], c[7],
                              ubis.get(vacio(c[1])))


# Semaforos. 'verde' | 'amarillo' | 'rojo' | 'gris' (gris = sin RUC formal / no aplica).
ESTADOS = {
    "ACTIVO": ("Activo", "verde"),
    "SUSPENSION TEMPORAL": ("Suspensión temporal", "amarillo"),
    "PENDIENTE DE INI. DE": ("Pendiente de inicio de actividades", "amarillo"),
    "BAJA DE OFICIO": ("Baja de oficio", "rojo"),
    "BAJA DEFINITIVA": ("Baja definitiva", "rojo"),
    "BAJA PROV. POR OFICI": ("Baja provisional por oficio", "rojo"),
    "BAJA PROVISIONAL": ("Baja provisional", "rojo"),
    "BAJA NO ACTIV. SISEV": ("Baja por no activación", "rojo"),
    "BAJA MULT.INSCR. Y O": ("Baja por inscripción múltiple", "rojo"),
    "NUM. INTERNO IDENTIF": ("Sin RUC formal (número interno)", "gris"),
    "INHABILITADO-VENT.UN": ("Inhabilitado", "gris"),
    "OTROS OBLIGADOS": ("Otros obligados", "gris"),
    "ANULACION - ERROR SU": ("Anulado", "gris"),
    "ANULACION - ACTO ILI": ("Anulado", "gris"),
    "ANUL.PROVI.-ACTO ILI": ("Anulado provisionalmente", "gris"),
}
CONDICIONES = {
    "HABIDO": ("Habido", "verde"),
    "NO HABIDO": ("No habido", "rojo"),
    "NO HALLADO": ("No hallado", "amarillo"),
    "NO HALLADO SE MUDO D": ("No hallado: se mudó de domicilio", "amarillo"),
    "NO HALLADO DESTINATA": ("No hallado: destinatario desconocido", "amarillo"),
    "NO HALLADO CERRADO": ("No hallado: cerrado", "amarillo"),
    "NO HALLADO OTROS MOT": ("No hallado: otros motivos", "amarillo"),
    "NO HALLADO RECHAZADO": ("No hallado: rechazado", "amarillo"),
    "NO HALLADO NRO.PUERT": ("No hallado: número de puerta no existe", "amarillo"),
    "NO HALLADO NO EXISTE": ("No hallado: dirección no existe", "amarillo"),
    "NO HALLADO FALLECIO": ("No hallado: falleció", "amarillo"),
    "PENDIENTE": ("Pendiente", "amarillo"),
    "POR VERIFICAR": ("Por verificar", "amarillo"),
    "NO APLICABLE": ("No aplica", "gris"),
    "": ("Sin dato", "gris"),
}

RUC_RE = re.compile(r"^(10|15|17|20)\d{9}$")
_PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def ruc_dv_ok(ruc: str) -> bool:
    """Digito verificador (modulo 11) del RUC."""
    r = 11 - sum(int(d) * p for d, p in zip(ruc[:10], _PESOS)) % 11
    return {10: 0, 11: 1}.get(r, r) == int(ruc[10])


ORDEN_SEMAFORO = {"rojo": 0, "amarillo": 1, "gris": 2, "verde": 3}


def semaforo_fila(estado: str, condicion: str) -> str:
    """El peor de los dos semaforos (rojo > amarillo > gris > verde)."""
    a = ESTADOS.get(estado, ("", "gris"))[1]
    b = CONDICIONES.get(condicion, ("", "gris"))[1]
    return min(a, b, key=ORDEN_SEMAFORO.__getitem__)
