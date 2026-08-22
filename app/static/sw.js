/* KILL SWITCH — Service Worker auto-destructivo.
 *
 * El embudo viejo (generacion anterior) registro este SW con scope "/" y cacheo
 * "/" (su propio shell). Ahora la raiz sirve la landing nueva, que NO usa SW.
 * Para que ningun visitante con el SW viejo instalado reciba cache rancio ni la
 * home quede secuestrada, esta version:
 *   1) toma control de inmediato (skipWaiting + clients.claim),
 *   2) BORRA todas las cachees,
 *   3) se DESREGISTRA a si mismo,
 *   4) recarga las pestañas abiertas para que carguen la home fresca sin SW.
 *
 * El navegador re-descarga /sw.js al navegar/actualizar, asi que todo cliente que
 * tenia el SW viejo migra a este y queda limpio. La landing no vuelve a registrar
 * ningun SW, de modo que no se reinstala nada.
 */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    try {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    } catch (e) { /* noop */ }
    try {
      await self.registration.unregister();
    } catch (e) { /* noop */ }
    try {
      await self.clients.claim();
      const clients = await self.clients.matchAll({ type: "window" });
      for (const client of clients) {
        client.navigate(client.url);  // recarga cada pestaña -> home fresca, sin SW
      }
    } catch (e) { /* noop */ }
  })());
});

/* Mientras este SW siga activo un instante, NUNCA sirvas desde cache: siempre red,
 * para no devolver el shell viejo del embudo por "/". */
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request).catch(() => new Response("", { status: 504 })));
});
