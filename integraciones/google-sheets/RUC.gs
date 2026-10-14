/**
 * Perú Sistemas Pro · Funciones de RUC para Google Sheets
 *
 * INSTALACIÓN (una vez por hoja):
 *   1. En tu hoja: Extensiones → Apps Script.
 *   2. Borra lo que haya, pega TODO este archivo y guarda (icono del disquete).
 *   3. Vuelve a la hoja y recárgala: aparece el menú «Perú Sistemas Pro».
 *   4. Menú «Perú Sistemas Pro» → «Configurar llave» y pega tu llave (psp_live_…).
 *
 * USO:
 *   =RUC(A2)                    → "Activo · Habido · ⚠️ SSCO desde 18/09/2026"
 *   =RUC(A2; "estado")          → "Activo"   (campos: ver PSP_CAMPOS más abajo)
 *   =RUCS(A2:A200)              → tabla con encabezado: razón social, estado, condición, SSCO, distrito
 *   =RUCS(A2:A200; "estado,ssco,ssco_firme")
 *   =RUC_SALDO()                → "Usadas 37 de 100 este mes · reinicia 01/11/2026"
 *
 * Para muchos RUC usa =RUCS (una sola consulta por cada 100 RUC) en vez de copiar =RUC en
 * cada celda. Los resultados se guardan 6 horas en la hoja para no gastar consultas al recalcular.
 */

var PSP_API = 'https://club.perusistemas.pro/api/v1';
var PSP_CACHE_SEG = 21600;   // 6 horas
var PSP_LOTE = 100;          // RUC por consulta de lote
var PSP_VERSION = '1.0';

// Nombre que usas en la hoja → { campo de la API (formato plano), encabezado }
var PSP_CAMPOS = {
  resumen:                { api: null,                     titulo: 'Resumen' },
  razon_social:           { api: 'razon_social',           titulo: 'Razón social' },
  estado:                 { api: 'estado_nombre',          titulo: 'Estado' },
  condicion:              { api: 'condicion_nombre',       titulo: 'Condición' },
  semaforo:               { api: 'semaforo',               titulo: 'Semáforo' },
  distrito:               { api: 'distrito',               titulo: 'Distrito' },
  provincia:              { api: 'provincia',              titulo: 'Provincia' },
  departamento:           { api: 'departamento',           titulo: 'Departamento' },
  ubigeo:                 { api: 'ubigeo',                 titulo: 'Ubigeo' },
  domicilio:              { api: 'domicilio',              titulo: 'Domicilio fiscal' },
  ssco:                   { api: 'ssco',                   titulo: 'SSCO' },
  ssco_desde:             { api: 'ssco_desde',             titulo: 'SSCO desde' },
  ssco_emision:           { api: 'ssco_emision',           titulo: 'SSCO: emisión' },
  ssco_firme:             { api: 'ssco_firme',             titulo: 'SSCO: quedó firme' },
  ssco_publicacion:       { api: 'ssco_publicacion',       titulo: 'SSCO: publicación' },
  ssco_resolucion:        { api: 'ssco_resolucion',        titulo: 'SSCO: resolución' },
  contador:               { api: 'contador',               titulo: 'Contador' },
  negocio_nuevo:          { api: 'negocio_nuevo',          titulo: 'Negocio nuevo' },
  negocio_nuevo_inscrito: { api: 'negocio_nuevo_inscrito', titulo: 'Inscrito el' },
  anexos:                 { api: 'anexos_total',           titulo: 'Locales anexos' },
  datos_al:               { api: 'datos_al',               titulo: 'Datos al' }
};
var PSP_POR_DEFECTO = ['razon_social', 'estado', 'condicion', 'ssco', 'distrito'];

// ---------- Menú ----------
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Perú Sistemas Pro')
    .addItem('Configurar llave', 'pspConfigurarLlave')
    .addItem('Ver mi consumo', 'pspVerConsumo')
    .addToUi();
}

function pspConfigurarLlave() {
  var ui = SpreadsheetApp.getUi();
  var r = ui.prompt('Perú Sistemas Pro', 'Pega tu llave (empieza con psp_live_):', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  var llave = String(r.getResponseText() || '').trim();
  if (!/^psp_live_[a-z0-9]{8}_[A-Za-z0-9_-]{20,}$/.test(llave)) {
    ui.alert('Esa no parece una llave válida. Debe empezar con psp_live_.');
    return;
  }
  var resp = pspPedir_('get', '/yo', null, llave);
  if (resp.codigo !== 200) {
    ui.alert('No pudimos validar la llave: ' + pspMensajeError_(resp));
    return;
  }
  PropertiesService.getDocumentProperties().setProperty('PSP_LLAVE', llave);
  ui.alert('Llave guardada en esta hoja. ' + pspTextoSaldo_(resp.datos));
}

function pspVerConsumo() {
  SpreadsheetApp.getUi().alert(RUC_SALDO());
}

// ---------- Funciones de la hoja ----------
/**
 * Consulta un RUC: estado, condición, SSCO y más.
 * @param {string|number} ruc El RUC (11 dígitos), o la celda que lo tiene.
 * @param {string} campo Opcional: "estado", "condicion", "ssco", "ssco_firme", "distrito"… Vacío = resumen.
 * @return El dato pedido.
 * @customfunction
 */
function RUC(ruc, campo) {
  var nombre = String(campo || 'resumen').trim().toLowerCase();
  if (!PSP_CAMPOS[nombre]) return '#CAMPO? Usa: ' + Object.keys(PSP_CAMPOS).join(', ');
  var r = pspNormalizar_(ruc);
  if (r === '') return '';
  if (!/^(10|15|17|20)\d{9}$/.test(r)) return 'RUC inválido';
  var fila = pspDeCache_([r])[r];
  if (!fila) {
    var resp = pspPedir_('get', '/ruc/' + r + '?formato=plano');
    if (resp.codigo === 404 && resp.datos && resp.datos.error && resp.datos.error.codigo === 'ruc_no_encontrado') {
      fila = { ruc: r, encontrado: false };
    } else if (resp.codigo !== 200) {
      return pspMensajeError_(resp);
    } else {
      fila = resp.datos;
    }
    pspACache_([fila]);
  }
  return pspValor_(fila, nombre);
}

/**
 * Consulta muchos RUC de una vez y devuelve una tabla con encabezado.
 * @param {A2:A200} rango Celdas con los RUC (una columna).
 * @param {string} campos Opcional: "estado,condicion,ssco" (separados por coma). Vacío = razón social, estado, condición, SSCO y distrito.
 * @return Tabla: una fila por RUC, en el mismo orden.
 * @customfunction
 */
function RUCS(rango, campos) {
  var lista = pspAplanar_(rango);
  var nombres = campos ? String(campos).split(',').map(function (x) { return x.trim().toLowerCase(); }).filter(String) : PSP_POR_DEFECTO;
  for (var i = 0; i < nombres.length; i++) {
    if (!PSP_CAMPOS[nombres[i]]) return [['#CAMPO? "' + nombres[i] + '". Usa: ' + Object.keys(PSP_CAMPOS).join(', ')]];
  }
  var rucs = lista.map(pspNormalizar_);
  var validos = [];
  rucs.forEach(function (r) { if (/^(10|15|17|20)\d{9}$/.test(r) && validos.indexOf(r) < 0) validos.push(r); });
  var filas = pspDeCache_(validos);
  var faltan = validos.filter(function (r) { return !filas[r]; });
  for (var k = 0; k < faltan.length; k += PSP_LOTE) {
    var tanda = faltan.slice(k, k + PSP_LOTE);
    var resp = pspPedir_('post', '/ruc/lote?formato=plano', { rucs: tanda });
    if (resp.codigo !== 200) return [[pspMensajeError_(resp)]];
    resp.datos.resultados.forEach(function (f) { filas[f.ruc] = f; });
    pspACache_(resp.datos.resultados);
  }
  var tabla = [nombres.map(function (n) { return PSP_CAMPOS[n].titulo; })];
  rucs.forEach(function (r) {
    if (r === '') { tabla.push(nombres.map(function () { return ''; })); return; }
    if (!filas[r]) { tabla.push(nombres.map(function (n, j) { return j === 0 ? 'RUC inválido' : ''; })); return; }
    tabla.push(nombres.map(function (n) { return pspValor_(filas[r], n); }));
  });
  return tabla;
}

/**
 * Cuántas consultas te quedan este mes.
 * @return Texto con lo usado y la fecha de reinicio.
 * @customfunction
 */
function RUC_SALDO() {
  var resp = pspPedir_('get', '/yo');
  return resp.codigo === 200 ? pspTextoSaldo_(resp.datos) : pspMensajeError_(resp);
}

// ---------- Internas ----------
function pspLlave_() {
  return PropertiesService.getDocumentProperties().getProperty('PSP_LLAVE') || '';
}

function pspPedir_(metodo, ruta, cuerpo, llave) {
  llave = llave || pspLlave_();
  if (!llave) return { codigo: 0, datos: { error: { codigo: 'sin_llave' } } };
  var opciones = { method: metodo, muteHttpExceptions: true,
                   headers: { Authorization: 'Bearer ' + llave, 'X-Cliente': 'google-sheets/' + PSP_VERSION } };
  if (cuerpo) { opciones.contentType = 'application/json'; opciones.payload = JSON.stringify(cuerpo); }
  var r = UrlFetchApp.fetch(PSP_API + ruta, opciones);
  var datos = null;
  try { datos = JSON.parse(r.getContentText()); } catch (e) { datos = null; }
  return { codigo: r.getResponseCode(), datos: datos };
}

function pspMensajeError_(resp) {
  var e = (resp.datos && resp.datos.error) || {};
  switch (e.codigo) {
    case 'sin_llave': return '#SIN LLAVE: menú Perú Sistemas Pro → Configurar llave';
    case 'llave_invalida': return '#LLAVE INVÁLIDA';
    case 'llave_revocada': return '#LLAVE REVOCADA';
    case 'cuota_agotada': return 'Cuota agotada (reinicia ' + pspFechaTexto_(e.reinicio) + ')';
    case 'demasiado_rapido': return 'Muy rápido: reintenta en ' + (e.reintentar_en_segundos || 60) + ' s';
    case 'lote_muy_grande': return 'Demasiados RUC en un lote';
    case 'ruc_invalido': return 'RUC inválido';
    default: return '#ERROR ' + (resp.codigo || '') + (e.mensaje ? ': ' + e.mensaje : '');
  }
}

function pspNormalizar_(v) {
  if (v === null || v === undefined || v === '') return '';
  if (typeof v === 'number') return String(Math.round(v));
  return String(v).replace(/[\s.\-]/g, '');
}

function pspAplanar_(rango) {
  if (!Array.isArray(rango)) return [rango];
  var out = [];
  rango.forEach(function (fila) { if (Array.isArray(fila)) out.push(fila[0]); else out.push(fila); });
  return out;
}

function pspValor_(f, nombre) {
  if (!f.encontrado) return nombre === 'resumen' || nombre === 'estado' ? 'No figura' : '';
  if (nombre === 'resumen') {
    var t = f.estado_nombre + ' · ' + f.condicion_nombre;
    if (f.ssco) t += ' · ⚠️ SSCO desde ' + pspFechaTexto_(f.ssco_desde);
    return t;
  }
  var v = f[PSP_CAMPOS[nombre].api];
  if (v === true) return 'Sí';
  if (v === false || v === null || v === undefined) return nombre.indexOf('ssco') === 0 || nombre === 'contador' || nombre === 'negocio_nuevo' ? (v === false ? 'No' : '') : '';
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) {
    var p = v.split('-');
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  }
  return v;
}

function pspFechaTexto_(iso) {
  if (!iso) return '';
  var p = String(iso).split('-');
  return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : String(iso);
}

function pspTextoSaldo_(yo) {
  var c = yo.cuota;
  return 'Usadas ' + c.usada + ' de ' + c.limite + ' este mes · reinicia ' + pspFechaTexto_(c.reinicio);
}

function pspDeCache_(rucs) {
  var out = {};
  if (!rucs.length) return out;
  var cache = CacheService.getDocumentCache();
  var vals = cache.getAll(rucs.map(function (r) { return 'psp1:' + r; }));
  Object.keys(vals).forEach(function (k) {
    try { out[k.slice(5)] = JSON.parse(vals[k]); } catch (e) {}
  });
  return out;
}

function pspACache_(filas) {
  var cache = CacheService.getDocumentCache(), m = {};
  filas.forEach(function (f) { m['psp1:' + f.ruc] = JSON.stringify(f); });
  if (Object.keys(m).length) cache.putAll(m, PSP_CACHE_SEG);
}
