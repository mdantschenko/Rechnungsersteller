# Rechnungsersteller

Eine selbst gehostete Web-App für Nachhilfelehrer: Termine im Kalender
abhaken, daraus Rechnungen als PDF erzeugen und per E-Mail oder WhatsApp
verschicken. Gebaut für das Handy — als App auf dem Home-Bildschirm — und
genauso nutzbar am PC.

## Was sie kann

- **Kalender** in Monats-, Wochen- und Tagesansicht, mit wiederkehrenden
  Serien, Feiertagen und Schulferien
- **Wecker**: Die App schickt selbst Push-Mitteilungen vor jedem Termin und
  klingelt alle zwei Minuten weiter, bis sie beantwortet werden
- **Rechnungen** entstehen aus den abgehakten Stunden — automatisch zum
  Abrechnungsstichtag je Kunde oder manuell für einen frei gewählten
  Zeitraum, mit lückenloser Rechnungsnummernfolge
- **Versand** per E-Mail (mit Kopie in den Gesendet-Ordner) oder WhatsApp,
  Zahlungserinnerungen mit eigenem Anschreiben je Kunde
- **Einnahmen**-Übersicht nach Monaten: erhalten, noch zu erwarten, ohne
  Rechnung — plus ZIP-Export pro Jahr fürs Finanzamt
- **Import** alter Word-Rechnungen als Historie

Alles liegt in einer einzigen SQLite-Datei auf dem eigenen Server, hinter
einem Passwort; nichts verlässt die eigene Maschine.

## Selbst betreiben

Jede Installation gehört einer Person: eigener Server, eigene Datenbank,
eigenes Passwort. Gebraucht werden ein kleiner VPS mit Ubuntu (die
günstigste Stufe reicht) und eine (Sub-)Domain — HTTPS ist Pflicht, weil
Push-Mitteilungen und die Home-Bildschirm-App es verlangen.

Der komplette Weg von der frischen Maschine bis zur laufenden App steht in
[deploy/README.md](deploy/README.md); im Kern:

```powershell
.\deploy\upload.ps1 -Server root@DEINE.SERVER.IP
ssh root@DEINE.SERVER.IP
cd /opt/invoicing && INVOICING_DOMAIN=rechnungen.deine-domain.de bash deploy/install.sh
```

Zum Ausprobieren ohne Server läuft die App auch lokal:

```bash
uv sync
uv run python main.py set-password 'EIN-PASSWORT'
uv run python main.py serve
```

## Technik

FastAPI und SQLModel über SQLite, Alembic-Migrationen beim Start, PDFs aus
HTML über WeasyPrint (Linux) oder Chromium (Windows), Web Push mit eigenem
VAPID-Schlüssel. Ein Modul je Aufgabe:

![Abhängigkeitsgraph](dependency_graph.svg)

## Entwickeln

```bash
uv sync
uv run pytest
```

Vor jedem Commit läuft die Kette aus
[.pre-commit-config.yaml](.pre-commit-config.yaml): pytest, black, ruff,
radon, skylos, complexipy, pydeps und pyright.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
