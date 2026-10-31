// Service worker minimal : rend l'interface installable et disponible au démarrage même si le réseau tarde.
// Stratégie « réseau d'abord » : la version du serveur est toujours préférée ; seul le squelette est mis en cache.
const CACHE = "smarthome-shell-v3";
const SHELL = ["./", "index.html", "style.css", "app.js", "recorder.js", "recorder-worklet.js", "icon.svg", "manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Jamais de cache pour l'API, la santé du service ou tout ce qui n'est pas une lecture du squelette
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname === "/health") {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request)),
  );
});
