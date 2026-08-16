const assert = require("node:assert");
const fs = require("node:fs");
const vm = require("node:vm");

const HERKUNFT = "https://rechnungen.example.com";

function volleAdresse(ziel) {
  return new URL(typeof ziel === "string" ? ziel : ziel.url, HERKUNFT).href;
}

function inhaltVon(adresse) {
  const zerlegt = new URL(adresse);
  if (zerlegt.pathname === "/offline") {
    return zerlegt.search ? "OFFLINE-OHNE-SPEICHERN" : "OFFLINE";
  }
  return "NETZ:" + zerlegt.pathname;
}

function netzAntwort(adresse) {
  return {
    url: adresse,
    status: 200,
    type: "basic",
    redirected: false,
    text: inhaltVon(adresse),
    headers: { get: () => null },
    clone() {
      return netzAntwort(adresse);
    },
  };
}

function baueWerkbank(script) {
  const gespeichert = new Map();
  const gehoert = {};
  const gezeigt = [];
  const geloescht = [];
  const netz = { steht: true, faellt: "" };
  const uebernommen = [];

  function Response(text, einstellungen) {
    const daten = einstellungen || {};
    this.text = text;
    this.status = daten.status || 200;
    this.type = "default";
    this.url = "";
    this.headers = { get: () => null };
  }

  function fetchen(ziel) {
    const adresse = volleAdresse(ziel);
    const faellt = netz.faellt && adresse.indexOf(netz.faellt) !== -1;
    if (!netz.steht || faellt) {
      return Promise.reject(new TypeError("Failed to fetch"));
    }
    return Promise.resolve(netzAntwort(adresse));
  }

  const speicher = {
    put(anfrage, antwort) {
      gespeichert.set(volleAdresse(anfrage), antwort);
      return Promise.resolve();
    },
    add(adresse) {
      return fetchen(adresse).then((antwort) => {
        gespeichert.set(volleAdresse(adresse), antwort);
      });
    },
    keys() {
      return Promise.resolve([...gespeichert.keys()]);
    },
    delete(anfrage) {
      return Promise.resolve(gespeichert.delete(volleAdresse(anfrage)));
    },
  };

  const caches = {
    open: () => Promise.resolve(speicher),
    match: (anfrage) => Promise.resolve(gespeichert.get(volleAdresse(anfrage))),
    keys: () => Promise.resolve(["rechnungen-geruest-vvorher"]),
    delete: (name) => {
      geloescht.push(name);
      return Promise.resolve(true);
    },
  };

  const self = {
    addEventListener(name, handler) {
      gehoert[name] = handler;
    },
    location: { origin: HERKUNFT },
    registration: {
      showNotification(titel, optionen) {
        gezeigt.push({ titel, optionen });
        return Promise.resolve();
      },
    },
    skipWaiting() {
      uebernommen.push(true);
      return Promise.resolve();
    },
    clients: { claim: () => Promise.resolve() },
  };

  const clients = { openWindow: () => Promise.resolve() };

  vm.runInNewContext(script, {
    self,
    caches,
    clients,
    fetch: fetchen,
    Response,
    URL,
  });

  return { gehoert, gespeichert, gezeigt, geloescht, netz, uebernommen };
}

function anfrage(pfad, einstellungen) {
  const daten = einstellungen || {};
  return {
    url: volleAdresse(pfad),
    method: daten.method || "GET",
    mode: daten.mode || "no-cors",
    headers: { get: () => null },
  };
}

function ereignis(zusatz) {
  const offen = [];
  const gebaut = Object.assign(
    {
      antwort: null,
      waitUntil(versprechen) {
        offen.push(versprechen);
      },
      respondWith(versprechen) {
        gebaut.antwort = versprechen;
      },
      erledigt() {
        return Promise.all(offen);
      },
    },
    zusatz
  );
  return gebaut;
}

async function installieren(werkbank) {
  const start = ereignis({});
  werkbank.gehoert.install(start);
  await start.erledigt();
}

async function schicken(werkbank, gesendet) {
  const lauf = ereignis({ request: gesendet });
  werkbank.gehoert.fetch(lauf);
  const antwort = lauf.antwort ? await lauf.antwort : null;
  await lauf.erledigt();
  return antwort;
}

const pruefungen = {
  async "handlers-are-registered"(werkbank) {
    for (const name of [
      "push",
      "notificationclick",
      "install",
      "activate",
      "fetch",
    ]) {
      assert.strictEqual(
        typeof werkbank.gehoert[name],
        "function",
        "handler missing: " + name
      );
    }
  },

  async "push-shows-a-notification"(werkbank) {
    const klingeln = ereignis({
      data: { json: () => ({ title: "Nachhilfe", body: "gleich" }) },
    });
    werkbank.gehoert.push(klingeln);
    await klingeln.erledigt();

    assert.strictEqual(werkbank.gezeigt.length, 1);
    assert.strictEqual(werkbank.gezeigt[0].titel, "Nachhilfe");
  },

  async "a-navigation-without-network-gets-the-offline-page"(werkbank) {
    await installieren(werkbank);
    werkbank.netz.steht = false;

    const antwort = await schicken(
      werkbank,
      anfrage("/kunden", { mode: "navigate" })
    );

    assert.ok(antwort, "the worker did not answer the navigation");
    assert.strictEqual(antwort.text, "OFFLINE");
  },

  async "a-post-without-network-says-nothing-was-saved"(werkbank) {
    await installieren(werkbank);
    werkbank.netz.steht = false;

    const antwort = await schicken(
      werkbank,
      anfrage("/termine/neu", { mode: "navigate", method: "POST" })
    );

    assert.ok(antwort, "the worker did not answer the form");
    assert.strictEqual(antwort.text, "OFFLINE-OHNE-SPEICHERN");
  },

  async "a-good-navigation-is-not-stored"(werkbank) {
    await installieren(werkbank);

    const antwort = await schicken(
      werkbank,
      anfrage("/kunden", { mode: "navigate" })
    );

    assert.strictEqual(antwort.text, "NETZ:/kunden");
    assert.ok(
      !werkbank.gespeichert.has(HERKUNFT + "/kunden"),
      "the page was stored on the device"
    );
  },

  async "a-missing-required-file-fails-the-install"(werkbank) {
    werkbank.netz.faellt = "/static/app.css";

    await assert.rejects(installieren(werkbank));
    assert.strictEqual(
      werkbank.uebernommen.length,
      0,
      "the half installed worker took over anyway"
    );
  },

  async "a-missing-icon-does-not-fail-the-install"(werkbank) {
    werkbank.netz.faellt = "/static/icon-32.png";

    await installieren(werkbank);

    assert.strictEqual(werkbank.uebernommen.length, 1);
    assert.ok(werkbank.gespeichert.has(HERKUNFT + "/offline"));
  },

  async "the-stylesheet-is-stored"(werkbank) {
    await installieren(werkbank);

    await schicken(werkbank, anfrage("/static/app.css"));

    assert.ok(
      werkbank.gespeichert.has(HERKUNFT + "/static/app.css"),
      "the stylesheet was not stored"
    );
  },
};

async function main() {
  const [, , ort, name] = process.argv;
  const pruefung = pruefungen[name];
  if (!pruefung) throw new Error("unknown check: " + name);
  await pruefung(baueWerkbank(fs.readFileSync(ort, "utf8")));
}

main().catch((fehler) => {
  console.error(fehler.stack || String(fehler));
  process.exit(1);
});
