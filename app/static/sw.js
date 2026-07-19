/* Club de Contadores — Service Worker. Versionar en cada deploy (CACHE vX). */
const CACHE = "club-contadores-v1";
const CORE = [
  "/",
  "/static/css/styles.css?v=1",
  "/static/js/app.js?v=1",
  "/manifest.webmanifest",
  "/distritos.json",
  "/static/icons/icon-192.png",
];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CORE).catch(() => {})));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // No cachear la API (datos frescos: conteos, lista, validacion).
  if (url.pathname.startsWith("/api/")) return;

  // Estaticos y assets: cache-first. Documento/otros: network-first con fallback.
  const isAsset = url.pathname.startsWith("/static/") ||
                  url.pathname === "/distritos.json" ||
                  url.pathname === "/manifest.webmanifest";
  if (isAsset) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => hit))
    );
  } else {
    e.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
    );
  }
});

/* Push: notificaciones 1-2 veces por semana mientras se construye. */
self.addEventListener("push", (e) => {
  let data = { title: "Club de Contadores", body: "Tienes nuevos negocios en tu distrito." };
  try { if (e.data) data = { ...data, ...e.data.json() }; } catch (_) {}
  e.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(clients.matchAll({ type: "window" }).then((list) => {
    for (const c of list) { if (c.url.includes(url) && "focus" in c) return c.focus(); }
    return clients.openWindow(url);
  }));
});
