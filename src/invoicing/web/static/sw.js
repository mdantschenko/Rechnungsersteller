self.addEventListener("push", function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (ignored) {}
  event.waitUntil(
    self.registration.showNotification(data.title || "Nachhilfe", {
      body: data.body || "",
      tag: data.tag || "wecker",
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});

function istErlaubt(pfad) {
  return self.APP_CACHE.erlaubtePfade.some(function (anfang) {
    return pfad.indexOf(anfang) === 0;
  });
}

function ablegen(anfrage, antwort) {
  return caches
    .open(self.APP_CACHE.geruest)
    .then(function (speicher) {
      return speicher.put(anfrage, antwort);
    })
    .catch(function () {});
}

function offlineSeite(adresse) {
  return caches.match(adresse).then(function (treffer) {
    if (treffer) return treffer;
    return new Response(self.APP_CACHE.offlineText, {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  });
}

function ausDemNetz(anfrage, ersatzAdresse) {
  return fetch(anfrage).catch(function () {
    return offlineSeite(ersatzAdresse);
  });
}

function geruestHolen(event, anfrage) {
  return caches.match(anfrage).then(function (treffer) {
    if (treffer) return treffer;
    return fetch(anfrage).then(function (antwort) {
      if (antwort && antwort.status === 200 && antwort.type === "basic") {
        event.waitUntil(ablegen(anfrage, antwort.clone()));
      }
      return antwort;
    });
  });
}

function alleVorladen(speicher, adressen) {
  return Promise.all(
    adressen.map(function (adresse) {
      return speicher.add(adresse);
    })
  );
}

function einzelnVorladen(speicher, adressen) {
  return Promise.allSettled(
    adressen.map(function (adresse) {
      return speicher.add(adresse);
    })
  );
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches
      .open(self.APP_CACHE.geruest)
      .then(function (speicher) {
        return alleVorladen(speicher, self.APP_CACHE.pflichtVorladen).then(
          function () {
            return einzelnVorladen(speicher, self.APP_CACHE.zusatzVorladen);
          }
        );
      })
      .then(function () {
        return self.skipWaiting();
      })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (namen) {
        return Promise.all(
          namen.map(function (name) {
            if (name === self.APP_CACHE.geruest) return Promise.resolve(false);
            return caches.delete(name);
          })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

function beantworten(event) {
  var anfrage = event.request;
  var adresse = new URL(anfrage.url);
  if (adresse.origin !== self.location.origin) return;
  if (anfrage.mode === "navigate") {
    if (anfrage.method === "GET") {
      event.respondWith(ausDemNetz(anfrage, self.APP_CACHE.offlineSeite));
      return;
    }
    event.respondWith(ausDemNetz(anfrage, self.APP_CACHE.offlineOhneSpeichern));
    return;
  }
  if (anfrage.method !== "GET") return;
  if (anfrage.headers.get("range")) return;
  if (!istErlaubt(adresse.pathname)) return;
  event.respondWith(geruestHolen(event, anfrage));
}

self.addEventListener("fetch", function (event) {
  if (!self.APP_CACHE) return;
  try {
    beantworten(event);
  } catch (ignored) {}
});
