/* Verificador de RUC: consulta, tabla con semaforos, filtros y orden en vivo, detalle por fila.
   Sin dependencias. Las columnas de padrones vienen del servidor (catalogo), no estan fijas aqui. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const RUC = /(?<!\d)(10|15|17|20)\d{9}(?!\d)/g;
  const ORDEN = { rojo: 0, amarillo: 1, gris: 2, verde: 3 };
  let datos = null, filtro = "todos", orden = { col: "semaforo", asc: true };

  const contar = () => {
    const n = new Set($("rucs").value.match(RUC) || []).size;
    $("cuenta").textContent = n ? `${n} RUC detectado${n === 1 ? "" : "s"}` : "";
  };
  $("rucs").addEventListener("input", contar);

  const msg = (el, html, tipo) => { $(el).innerHTML = html ? `<div class="msg ${tipo || "info"}">${html}</div>` : ""; };

  function chip(sem, texto) { return `<span class="chip-sem ${sem}"><s class="sem ${sem}"></s>${esc(texto)}</span>`; }

  function grupo(f) {
    if (f.semaforo === "rojo") return "alerta";
    if (f.semaforo === "amarillo") return "aviso";
    if (f.semaforo === "verde") return "ok";
    return "otro";
  }

  function celdaMarca(f, c) {
    const m = (f.marcas || {})[c.codigo];
    const l = `data-l="${esc(c.columna)}"`;
    if (!m) return `<td class="ver-marca no" ${l}>—</td>`;
    if (c.severidad === "alerta") return `<td class="ver-marca" ${l}>${chip("rojo", c.columna)}</td>`;
    const extra = c.codigo === "negocio_nuevo" && m.detalle && m.detalle.mes ? ` · ${m.detalle.mes}` : "";
    return `<td class="ver-marca" ${l}>${chip("info", "Sí" + extra)}</td>`;
  }

  // Texto de una fila para copiar o compartir. Sin nombrar la fuente.
  function lineaRuc(f) {
    if (!f.encontrado) return `RUC ${f.ruc} — no figura`;
    const s = (f.marcas || {}).ssco;
    return `RUC ${f.ruc} — ${f.razon_social} — ${f.estado.nombre} · ${f.condicion.nombre}` +
      (s ? ` — ⚠️ SSCO desde ${s.desde || fechaCorta((s.detalle || {}).firme)}` : "");
  }

  function acciones(f) {
    return `<div class="ver-acc" role="group" aria-label="Compartir este RUC">
      <button type="button" data-copiar="${f.ruc}">Copiar</button>
      <button type="button" data-compartir="${f.ruc}">Compartir</button>
      <a href="https://wa.me/?text=${encodeURIComponent(lineaRuc(f))}" target="_blank" rel="noopener">WhatsApp</a></div>`;
  }

  function lineaTiempo(d) {
    const pasos = [["emision", "Emisión de la resolución"], ["firme", "Quedó firme"], ["publicacion", "Publicación en la lista"]];
    return `<ol class="linea-tiempo">${pasos.map(([k, t]) =>
      `<li class="${k === "firme" ? "clave" : ""}"><b>${esc(fechaCorta(d[k]))}</b><span>${t}</span></li>`).join("")}</ol>`;
  }

  function detalle(f) {
    const partes = [acciones(f)];
    if (!f.encontrado) return partes[0] + `<p>Este RUC no figura en nuestros datos. Revisa que esté bien escrito.</p>`;
    if (f.domicilio) partes.push(`<p><b>Domicilio fiscal:</b> ${esc(f.domicilio)}</p>`);
    const nn = (f.marcas || {}).negocio_nuevo;
    if (nn && nn.desde) partes.push(`<p><b>Inscrito el</b> ${esc(nn.desde)}</p>`);
    const s = (f.marcas || {}).ssco;
    if (s) {
      const d = s.detalle || {};
      const reps = (d.representantes || []).map((r) =>
        `<li>${esc(r.nombre)} · <span class="mono">${esc(r.tipo)} ${esc(r.doc)}</span></li>`).join("");
      partes.push(`<div class="ssco-det"><b>Sujeto Sin Capacidad Operativa</b> · ${esc(d.resolucion || "")}
        ${lineaTiempo(d)}
        ${d.firme ? `<p class="aviso-riesgo">Si operaste con este contribuyente después de que la resolución quedó firme
          (<b>${esc(fechaCorta(d.firme))}</b>), revisa el sustento de esas operaciones.</p>` : ""}
        ${reps ? `<p><b>Representante legal:</b></p><ul>${reps}</ul>` : ""}</div>`);
    }
    const a = f.anexos || { n: 0, lista: [] };
    if (a.n) {
      const mas = a.n > a.lista.length ? `<li class="faint">y ${(a.n - a.lista.length).toLocaleString("es-PE")} más</li>` : "";
      partes.push(`<p><b>${a.n.toLocaleString("es-PE")} local${a.n === 1 ? "" : "es"} anexo${a.n === 1 ? "" : "s"}:</b></p>
        <ul>${a.lista.map((x) => `<li>${esc(x)}</li>`).join("")}${mas}</ul>`);
    }
    return partes.join("") || `<p>Sin más datos para este RUC.</p>`;
  }

  function fechaCorta(iso) { return iso ? iso.split("-").reverse().join("/") : "—"; }

  function pintar() {
    if (!datos) return;
    const q = $("buscar").value.trim().toUpperCase();
    const cols = datos.columnas;
    $("cab").innerHTML = [["ruc", "RUC"], ["razon_social", "Razón social"], ["estado", "Estado"], ["condicion", "Condición"], ["distrito", "Distrito"]]
      .concat(cols.map((c) => [c.codigo, c.columna]))
      .map(([k, t]) => `<th><button type="button" data-col="${k}">${esc(t)}${orden.col === k ? (orden.asc ? " ▴" : " ▾") : ""}</button></th>`).join("");
    let filas = datos.filas.slice();
    const g = { alerta: 0, aviso: 0, ok: 0 };
    filas.forEach((f) => { const k = grupo(f); if (k in g) g[k]++; });
    $("nTodos").textContent = filas.length; $("nAlerta").textContent = g.alerta; $("nAviso").textContent = g.aviso; $("nOk").textContent = g.ok;
    if (filtro !== "todos") filas = filas.filter((f) => grupo(f) === filtro);
    if (q) filas = filas.filter((f) => f.ruc.includes(q) || (f.razon_social || "").toUpperCase().includes(q)
                                   || ((f.distrito || {}).distrito || "").toUpperCase().includes(q));
    const val = (f) => {
      const c = orden.col;
      if (c === "semaforo") return ORDEN[f.semaforo] ?? 9;
      if (c === "estado" || c === "condicion") return f[c] ? f[c].nombre : "~";
      if (c === "ruc" || c === "razon_social") return f[c] || "~";
      if (c === "distrito") return (f.distrito || {}).distrito || "~";
      return (f.marcas || {})[c] ? 0 : 1;
    };
    filas.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * (orden.asc ? 1 : -1); });
    $("cuerpo").innerHTML = filas.map((f) => {
      const est = f.encontrado ? chip(f.estado.semaforo, f.estado.nombre) : chip("gris", "No figura");
      const con = f.encontrado ? chip(f.condicion.semaforo, f.condicion.nombre) : "";
      const u = f.distrito;
      const dis = u ? `<span class="ver-dist" title="Ubigeo ${esc(f.ubigeo)} · ${esc(u.departamento)} / ${esc(u.provincia)} / ${esc(u.distrito)}">${esc(u.distrito)}</span>`
                    : `<span class="faint">—</span>`;
      return `<tr class="fila ${f.semaforo}" data-ruc="${f.ruc}" tabindex="0" aria-expanded="false">
          <td class="mono ruc" data-l="RUC">${f.ruc}</td><td class="rs" data-l="Razón social">${esc(f.razon_social || "")}</td>
          <td data-l="Estado">${est}</td><td data-l="Condición">${con}</td><td data-l="Distrito">${dis}</td>${cols.map((c) => celdaMarca(f, c)).join("")}</tr>
        <tr class="det" hidden><td colspan="${5 + cols.length}">${detalle(f)}</td></tr>`;
    }).join("") || `<tr><td colspan="${5 + cols.length}" class="faint">Ningún RUC con ese filtro.</td></tr>`;
  }

  async function copiar(texto, boton) {
    try { await navigator.clipboard.writeText(texto); }
    catch (x) { const t = document.createElement("textarea"); t.value = texto; document.body.appendChild(t); t.select();
                document.execCommand("copy"); t.remove(); }
    if (boton) { const o = boton.textContent; boton.textContent = "Copiado ✓"; setTimeout(() => { boton.textContent = o; }, 1600); }
  }
  const fila = (ruc) => datos.filas.find((f) => f.ruc === ruc);

  $("cuerpo").addEventListener("click", async (e) => {
    const bc = e.target.closest("[data-copiar]"), bs = e.target.closest("[data-compartir]");
    if (bc) { copiar(lineaRuc(fila(bc.dataset.copiar)), bc); return; }
    if (bs) {
      const texto = lineaRuc(fila(bs.dataset.compartir));
      if (navigator.share) { try { await navigator.share({ text: texto }); } catch (x) { /* cancelado */ } }
      else window.open("https://wa.me/?text=" + encodeURIComponent(texto), "_blank", "noopener");
      return;
    }
    if (e.target.closest(".ver-acc")) return;
    const tr = e.target.closest("tr.fila"); if (!tr) return;
    const det = tr.nextElementSibling; det.hidden = !det.hidden; tr.setAttribute("aria-expanded", String(!det.hidden));
  });
  $("cuerpo").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("tr.fila")) e.target.click(); });
  $("cab").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-col]"); if (!b) return;
    const c = b.dataset.col; orden = { col: c, asc: orden.col === c ? !orden.asc : true }; pintar();
  });
  document.querySelectorAll(".ver-filtros button[data-f]").forEach((b) => b.addEventListener("click", () => {
    filtro = b.dataset.f;
    document.querySelectorAll(".ver-filtros button[data-f]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    pintar();
  }));
  $("buscar").addEventListener("input", pintar);
  $("bCopiarTodo").addEventListener("click", (e) => {
    const visibles = [...document.querySelectorAll("#cuerpo tr.fila")].map((tr) => fila(tr.dataset.ruc));
    copiar(visibles.map(lineaRuc).join("\n") + (datos.datos_al ? `\nDatos al ${datos.datos_al}` : ""), e.currentTarget);
  });

  $("fVer").addEventListener("submit", async (e) => {
    e.preventDefault();
    msg("vMsg", "");
    $("bVer").disabled = true; $("estadoTxt").textContent = "Verificando…";
    let r, d = {};
    try {
      r = await fetch("/api/verificador", { method: "POST", headers: { "Content-Type": "application/json" },
                                            body: JSON.stringify({ texto: $("rucs").value }) });
      d = await r.json();
    } catch (x) { d = { error: "No pudimos conectar. Revisa tu internet e intenta de nuevo." }; }
    $("bVer").disabled = false; $("estadoTxt").textContent = "Listo";
    if (!r || !r.ok || !d.ok) { msg("vMsg", esc(d.error || "No pudimos verificar."), "err"); return; }
    datos = d; filtro = "todos"; orden = { col: "semaforo", asc: true };
    document.querySelectorAll(".ver-filtros button[data-f]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.f === "todos")));
    $("buscar").value = "";
    const avisos = [];
    if (d.recortados) avisos.push(`Verificamos los primeros ${d.tope_tanda}; quedaron ${d.recortados} para otra tanda.`);
    if (d.descartados && d.descartados.length) avisos.push(`${d.descartados.length} número(s) de 11 dígitos no son RUC: ${d.descartados.slice(0, 5).map(esc).join(", ")}.`);
    if (avisos.length) msg("vMsg", avisos.join(" "), "info");
    const alertas = d.filas.filter((f) => f.semaforo === "rojo").length;
    $("resumen").textContent = `${d.filas.length} RUC · ${alertas} con alerta${d.datos_al ? " · datos al " + d.datos_al : ""}`;
    $("resultado").hidden = false;
    pintar();
    $("resultado").scrollIntoView({ behavior: "smooth", block: "start" });
  });

  $("fSsco").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("bSsco").disabled = true;
    let r, d = {};
    try {
      r = await fetch("/api/verificador/ssco", { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify({ q: $("qSsco").value }) });
      d = await r.json();
    } catch (x) { d = { error: "No pudimos conectar." }; }
    $("bSsco").disabled = false;
    if (!r || !r.ok || !d.ok) { $("rSsco").innerHTML = `<div class="msg err">${esc(d.error || "No pudimos buscar.")}</div>`; return; }
    if (!d.resultados.length) { $("rSsco").innerHTML = `<div class="msg ok">Ese nombre no figura en la lista SSCO${d.ssco_al ? " al " + esc(d.ssco_al) : ""}.</div>`; return; }
    const cuantas = d.mas ? `Más de 20 coincidencias en la lista SSCO; mostramos las primeras 20. Escribe más letras para afinar.`
      : `${d.resultados.length} coincidencia${d.resultados.length === 1 ? "" : "s"} en la lista SSCO:`;
    $("rSsco").innerHTML = `<div class="msg err">${cuantas}</div>` +
      d.resultados.map((x) => `<div class="ssco-det"><b class="mono">${esc(x.ruc)}</b> ${esc(x.razon_social)}
        <br><small>SSCO desde ${esc(x.desde || "—")} · ${esc(x.resolucion || "")}</small>
        <ul>${(x.representantes || []).map((p) => `<li>${esc(p.nombre)} · <span class="mono">${esc(p.tipo)} ${esc(p.doc)}</span></li>`).join("")}</ul></div>`).join("");
  });
})();
