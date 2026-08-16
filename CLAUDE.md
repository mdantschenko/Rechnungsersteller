# Arbeitsregeln für dieses Projekt

## Sprache

Einfache, klare Sprache in Antworten, Doku und Commit-Bodys. Kein Fachjargon,
wenn ein normales Wort reicht.

## Objektorientiert arbeiten (OOP)

- Funktionen gehören in Klassen. Eine Klasse bündelt die Funktionen, die
  zusammengehören — so sieht man sofort, was zusammenarbeitet und in welcher
  Reihenfolge etwas passiert.
- Nur wenn eine Klasse technisch im Weg steht, bleibt es eine freie Funktion
  (zum Beispiel bei Parallelisierung).
- FastAPI-Routen bleiben Funktionen (das verlangt das Framework), aber die
  Logik dahinter steckt in Klassen.
- Höchstens eine Klasse pro Datei. Ausnahmen sind nur die Sammeldateien
  unten und `src/invoicing/storage/models.py` (alle Datenbank-Tabellen an
  einem Ort).

## Feste Ablageorte

- `src/invoicing/constant.py` — ALLE Konstanten. Auch eine Konstante, die
  nur in einer Datei benutzt wird, steht hier.
- `src/invoicing/data_classes.py` — ALLE Dataclasses.
  (Datenbank-Modelle sind keine Dataclasses, die bleiben in
  `storage/models.py`.)
- `src/invoicing/utils.py` — Hilfsfunktionen, besonders alles, was an
  mehreren Stellen gebraucht wird.

## Namen

Variablen, Funktionen, Klassen, Dateien und Ordner heißen so, dass man am
Namen allein schon erkennt, was drinsteckt oder was passiert. Lieber ein
langer, sprechender Name als ein kurzer, den man nachschlagen muss.

## Qualität

- Vor jedem Commit läuft die Kette aus `.pre-commit-config.yaml`
  (pytest, black, ruff, radon, skylos, complexipy, pydeps, pyright).
- Tests mit `uv run pytest`.

## Commits

Ein Thema pro Commit. Englischer Betreff mit Scope (zum Beispiel
`fix(web): …`), im Body steht das Warum.
