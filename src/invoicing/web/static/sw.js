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

function beginntMitEinem(pfad, anfaenge) {
  return anfaenge.some(function (anfang) {
    return pfad.indexOf(anfang) === 0;
  });
}

function istStatik(pfad) {
  return beginntMitEinem(pfad, self.APP_CACHE.statikPfade);
}

function istGesperrt(pfad) {
  if (istStatik(pfad)) return false;
  if (beginntMitEinem(pfad, self.APP_CACHE.niemalsPfade)) return true;
  return self.APP_CACHE.niemalsEndungen.some(function (endung) {
    return pfad.slice(-endung.length) === endung;
  });
}

function pfadVon(antwort) {
  if (!antwort || !antwort.url) return "";
  return new URL(antwort.url).pathname;
}

function istSpeicherwuerdig(antwort) {
  if (!antwort || antwort.status !== 200 || antwort.redirected) return false;
  if (antwort.type !== "basic") return false;
  var art = antwort.headers.get("content-type") || "";
  if (art.indexOf("text/html") !== 0) return false;
  var pfad = pfadVon(antwort);
  return pfad !== "" && !istGesperrt(pfad);
}

function zeigtAnmeldung(antwort) {
  if (!antwort) return false;
  if (antwort.redirected) return true;
  return pfadVon(antwort).indexOf(self.APP_CACHE.anmeldePfad) === 0;
}

function seiteAblegen(anfrage, antwort) {
  return caches.open(self.APP_CACHE.seiten).then(function (speicher) {
    return speicher
      .put(anfrage, antwort)
      .then(function () {
        return speicher.keys();
      })
      .then(function (schluessel) {
        var zuviel = schluessel.length - self.APP_CACHE.seitenGrenze;
        var aufraeumen = [];
        for (var i = 0; i < zuviel; i++) {
          aufraeumen.push(speicher.delete(schluessel[i]));
        }
        return Promise.all(aufraeumen);
      });
  });
}

function statikHolen(event, anfrage) {
  return caches.match(anfrage).then(function (treffer) {
    if (treffer) return treffer;
    return fetch(anfrage).then(function (antwort) {
      if (antwort && antwort.status === 200 && antwort.type === "basic") {
        var kopie = antwort.clone();
        event.waitUntil(
          caches.open(self.APP_CACHE.statik).then(function (speicher) {
            return speicher.put(anfrage, kopie);
          })
        );
      }
      return antwort;
    });
  });
}

function offlineSeite() {
  return caches.match(self.APP_CACHE.offlineSeite).then(function (treffer) {
    if (treffer) return treffer;
    return new Response(self.APP_CACHE.offlineText, {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  });
}

function nurAusDemNetz(anfrage) {
  return fetch(anfrage).catch(function () {
    return offlineSeite();
  });
}

function seiteAusDemNetz(event, anfrage) {
  return fetch(anfrage).then(function (antwort) {
    if (zeigtAnmeldung(antwort)) {
      event.waitUntil(caches.delete(self.APP_CACHE.seiten));
      return antwort;
    }
    if (istSpeicherwuerdig(antwort)) {
      event.waitUntil(seiteAblegen(anfrage, antwort.clone()));
    }
    return antwort;
  });
}

function nachDemZeitLimit(treffer) {
  return new Promise(function (fertig) {
    setTimeout(function () {
      fertig(treffer);
    }, self.APP_CACHE.netzZeitLimitMs);
  });
}

function seiteHolen(event, anfrage) {
  var ausDemNetz = seiteAusDemNetz(event, anfrage);
  event.waitUntil(ausDemNetz.catch(function () {}));
  return caches
    .match(anfrage, { ignoreVary: true })
    .then(function (treffer) {
      if (!treffer) {
        return ausDemNetz.catch(function () {
          return offlineSeite();
        });
      }
      return Promise.race([
        ausDemNetz.catch(function () {
          return treffer;
        }),
        nachDemZeitLimit(treffer),
      ]);
    });
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches
      .open(self.APP_CACHE.statik)
      .then(function (speicher) {
        return Promise.allSettled(
          self.APP_CACHE.vorladen.map(function (adresse) {
            return speicher.add(adresse);
          })
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
            if (
              name === self.APP_CACHE.statik ||
              name === self.APP_CACHE.seiten
            ) {
              return Promise.resolve(false);
            }
            return caches.delete(name);
          })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

self.addEventListener("message", function (event) {
  if (event.data && event.data.typ === self.APP_CACHE.leerenBotschaft) {
    event.waitUntil(caches.delete(self.APP_CACHE.seiten));
  }
});

self.addEventListener("fetch", function (event) {
  var anfrage = event.request;
  if (anfrage.method !== "GET") return;
  if (anfrage.headers.get("range")) return;
  var adresse = new URL(anfrage.url);
  if (adresse.origin !== self.location.origin) return;
  if (istStatik(adresse.pathname)) {
    event.respondWith(statikHolen(event, anfrage));
    return;
  }
  if (anfrage.mode !== "navigate") return;
  if (istGesperrt(adresse.pathname)) {
    event.respondWith(nurAusDemNetz(anfrage));
    return;
  }
  event.respondWith(seiteHolen(event, anfrage));
});
