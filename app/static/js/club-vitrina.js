/* Vitrina del Club: efecto "maquina de escribir" de las etiquetas vivas (.rota.ef-escribe).
   Los otros efectos (sube, fade) son CSS puro. Cada tarjeta usa su propio ritmo
   (data-ritmo, segundos por frase) y desfase (data-desfase), igual que en CSS. */
(function () {
  const quieto = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const espera = ms => new Promise(r => setTimeout(r, ms));

  document.querySelectorAll(".vitrina .rota.ef-escribe").forEach(rota => {
    const frases = [...rota.querySelectorAll(".f")].map(f => f.textContent);
    if (!frases.length) return;
    const esc = document.createElement("span");
    esc.className = "esc";
    esc.textContent = frases[0];           // visible desde el primer cuadro
    rota.appendChild(esc);
    if (quieto || frases.length < 2) return;

    const ritmo = (parseFloat(rota.dataset.ritmo) || 3.4) * 1000;
    const desfase = Math.abs(parseFloat(rota.dataset.desfase) || 0) * 1000 % ritmo;
    (async function ciclo() {
      await espera(ritmo - desfase);       // la primera frase ya esta escrita
      for (let i = 1; ; i = (i + 1) % frases.length) {
        const txt = frases[i], t0 = Date.now();
        while (esc.textContent.length) {   // borra rapido
          esc.textContent = esc.textContent.slice(0, -1);
          await espera(18);
        }
        for (let k = 1; k <= txt.length; k++) {   // escribe letra a letra
          esc.textContent = txt.slice(0, k);
          await espera(55);
        }
        await espera(Math.max(600, ritmo - (Date.now() - t0)));
      }
    })();
  });
})();
