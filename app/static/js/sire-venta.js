// Landing de venta del Conversor SIRE: calculadora (solo con los números que ingresa la persona) y barra
// CTA fija, que aparece cuando el botón del inicio sale de la pantalla.
(function () {
  var calc = document.getElementById("calc");
  if (calc) {
    var cli = document.getElementById("cli"), min = document.getElementById("min");
    var horas = document.getElementById("horas"), etiqueta = document.getElementById("horasL");
    var conHerramienta = +calc.dataset.minHerramienta || 5;
    var calcular = function () {
      if (cli.value === "" || min.value === "") {
        horas.textContent = "—";
        etiqueta.textContent = "Ingresa tus dos números para ver el estimado";
        return;
      }
      var h = Math.max(0, (+min.value || 0) - conHerramienta) * Math.max(0, +cli.value || 0) / 60;
      horas.textContent = h > 0 ? h.toLocaleString("es-PE", { maximumFractionDigits: 1 }) : "0";
      etiqueta.textContent = "horas al mes que podrías recuperar (estimado con tus datos)";
    };
    cli.addEventListener("input", calcular);
    min.addEventListener("input", calcular);
    calcular();
  }

  var barra = document.getElementById("sticky"), hero = document.getElementById("ctaHero");
  if (barra && hero) {
    // Solo cuando el botón del inicio ya quedó arriba (pasado); un salto de golpe también cuenta.
    var revisar = function () { barra.classList.toggle("oculta", hero.getBoundingClientRect().bottom > 0); };
    addEventListener("scroll", revisar, { passive: true });
    addEventListener("resize", revisar);
    revisar();
  }
})();
