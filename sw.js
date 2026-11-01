/* Service worker de Cible 10 m : rend l'application installable et utilisable hors ligne (au stand).
   A chaque nouvelle version de l'application, augmenter VERSION pour que les telephones la recuperent. */
var VERSION = "1.7.0";
var CACHE = "cible10m-" + VERSION;
var POLICES = "cible10m-polices";
var COQUILLE = [
  "./",
  "index.html",
  "manifest.webmanifest",
  "icon-192.png",
  "icon-512.png",
  "icon-maskable-512.png",
  "apple-touch-icon.png"
];

self.addEventListener("install", function (ev) {
  ev.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(COQUILLE); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (ev) {
  ev.waitUntil(caches.keys().then(function (cles) {
    return Promise.all(cles.filter(function (k) { return k !== CACHE && k !== POLICES; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (ev) {
  var req = ev.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);

  /* Polices Google : copie locale, rafraichie en arriere-plan */
  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    ev.respondWith(caches.open(POLICES).then(function (c) {
      return c.match(req).then(function (enCache) {
        var reseau = fetch(req).then(function (rep) { if (rep && (rep.ok || rep.type === "opaque")) c.put(req, rep.clone()); return rep; }).catch(function () { return enCache; });
        return enCache || reseau;
      });
    }));
    return;
  }
  if (url.origin !== self.location.origin) return;

  /* Page : reseau d'abord (pour recevoir les mises a jour), copie locale si pas de reseau */
  if (req.mode === "navigate") {
    ev.respondWith(fetch(req).then(function (rep) {
      var copie = rep.clone();
      caches.open(CACHE).then(function (c) { c.put("index.html", copie); });
      return rep;
    }).catch(function () {
      return caches.match("index.html", { ignoreSearch: true });
    }));
    return;
  }

  /* Le reste (icones, manifeste) : copie locale d'abord */
  ev.respondWith(caches.match(req, { ignoreSearch: true }).then(function (enCache) {
    return enCache || fetch(req).then(function (rep) {
      if (rep && rep.ok) { var copie = rep.clone(); caches.open(CACHE).then(function (c) { c.put(req, copie); }); }
      return rep;
    });
  }));
});
