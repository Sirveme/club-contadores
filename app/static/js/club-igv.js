/* Calculadora de IGV (Club de Contadores). Aritmetica en CENTIMOS enteros con
   redondeo half-up, para que base + IGV = total al centimo, siempre.
   Tasa general 18% (IGV 16% + IPM 2%). */
(function (raiz) {
  // a/b redondeado half-up, con enteros no negativos.
  const divRed = (a, b) => Math.floor((2 * a + b) / (2 * b));

  function leerMonto(txt) {
    let s = String(txt || "").replace(/[sS]\/|\s/g, "");
    if (s.includes(",") && s.includes(".")) s = s.replace(/,/g, "");          // 1,180.50
    else if (/,\d{1,2}$/.test(s)) s = s.replace(",", ".");                     // 1180,5
    else s = s.replace(/,/g, "");                                              // 1,180
    if (!/^\d+(\.\d{0,2})?$/.test(s)) return null;
    const [ent, dec = ""] = s.split(".");
    return Number(ent) * 100 + Number((dec + "00").slice(0, 2));               // centimos
  }

  // incluido=true: el monto es el TOTAL (precio con IGV). false: es la BASE.
  function calcIGV(centimos, incluido, tasa = 18) {
    if (incluido) {
      const total = centimos, base = divRed(total * 100, 100 + tasa);
      return { base, igv: total - base, total };
    }
    const base = centimos, igv = divRed(base * tasa, 100);
    return { base, igv, total: base + igv };
  }

  const soles = c => "S/ " + (c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const api = { leerMonto, calcIGV, soles };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  raiz.ClubIGV = api;

  // --- UI ---
  const $ = id => document.getElementById(id);
  let incluido = true;
  function pintar() {
    const c = leerMonto($("monto").value);
    $("lblMonto").textContent = incluido ? "Monto con IGV (total)" : "Monto sin IGV (valor de venta)";
    if (c === null) { ["rBase", "rIgv", "rTot"].forEach(id => $(id).textContent = "—");
      $("igvMsg").textContent = $("monto").value.trim() ? "Escribe un monto válido, por ejemplo 1180 o 1,180.50." : ""; return; }
    const r = calcIGV(c, incluido);
    $("rBase").textContent = soles(r.base); $("rIgv").textContent = soles(r.igv); $("rTot").textContent = soles(r.total);
    $("igvMsg").textContent = "";
  }
  document.querySelectorAll(".modo button").forEach(b => b.onclick = () => {
    incluido = b.dataset.incluido === "1";
    document.querySelectorAll(".modo button").forEach(x => x.setAttribute("aria-pressed", x === b));
    pintar();
  });
  $("monto").oninput = pintar;
  pintar();
})(typeof window !== "undefined" ? window : globalThis);
