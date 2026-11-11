// Service worker minimal : rend l'interface installable et disponible au démarrage même si le réseau tarde.
// Stratégie « réseau d'abord » : la version du serveur est toujours préférée ; seul le squelette est mis en cache.
const CACHE = "smarthome-shell-v22";
const SHELL = [
  "./",
  "index.html",
  "style.css?v=18",
  "app.js?v=18",
  "recorder.js",
  "recorder-worklet.js",
  "icon.svg",
  "icon-192.png",
  "icon-512.png",
  "manifest.webmanifest?v=18",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Jamais de cache pour l'API, la santé du service ou si nocache demandé
  if (
    event.request.method !== "GET" ||
    url.origin !== location.origin ||
    url.pathname.startsWith("/api/") ||
    url.pathname === "/health" ||
    url.searchParams.has("nocache") ||
    url.searchParams.has("clean")
  ) {
    return;
  }
  event.respondWith(
    fetch(event.request, { cache: "no-cache" })
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request)),
  );
});
