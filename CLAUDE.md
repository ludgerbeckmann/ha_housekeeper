# CLAUDE.md – Projektkontext für Claude Code

Home-Assistant Custom Integration `ha_housekeeper` (Anzeigename
„Housekeeper“): mehrere Funktionen, jede als eigener Config-Entry mit
`function_type`. Aktuell: `mailbox` („Benachrichtigung Briefkasten“) und
`door_guard` („Türwächter“).
Arbeitsweise angelehnt an `ludgerbeckmann/ha_smart_ventilation`.

## Feste Arbeitsanweisungen

- **Vor jeder inhaltlichen Umsetzung zuerst eine kurze Zusammenfassung im
  Chat (betroffene Dateien, neue Optionen/Entitäten, Verhaltensänderung,
  getroffene Annahmen) posten und auf Bestätigung warten.**
- Nach Bestätigung: Branch → Commit → Push → PR → CI (hassfest, HACS,
  pytest) abwarten → Squash-Merge → Feature-Branch auf `main` zurücksetzen,
  ohne erneut nachzufragen.
- `manifest.json` `version` bei **jeder** Änderung anheben (SemVer); der
  Workflow `auto-release.yml` erstellt daraus Tag + Release.

## Architektur

- `const.py`: `FUNCTION_PLATFORMS` ist die Registry Funktionstyp → Plattformen.
  **Neue Funktion:** Typ-Konstante + Registry-Eintrag, Config-Flow-Schritt
  `async_step_<typ>`, Controller-Klasse, Plattformdateien, Übersetzungen
  (`selector.function_type.options.<typ>`), Setup/Unload in `__init__.py`.
- `mailbox.py` / `door_guard.py`: je ein Controller pro Funktion (Logik, Zustand
  in `Store`). Registry Typ → Controller in `__init__.py` (`CONTROLLERS`).
  Entitäten (`binary_sensor.py`, `sensor.py`, `button.py`, `switch.py`, Basis
  `FunctionEntity` in `entity.py`) spiegeln nur den Controller über ein
  Dispatcher-Signal; `binary_sensor.py`/`sensor.py` wählen per `isinstance`.
- `notify.py`: gemeinsame Benachrichtigungswege (`Notifier`) und `entry_opt()`.
  Ein in den Optionen auf `None` gesetzter Wert überdeckt den Wert aus den
  Daten (so lassen sich optionale Felder leeren, siehe `_with_cleared`).
- Türwächter-Regeln liegen als Liste in `options["rules"]` (Schlüssel
  `R_*` in `const.py`); der Options-Flow ist ein Menü und speichert Regeln
  sofort über `async_update_entry` (Eintrag lädt bei jeder Speicherung neu).
  Manuelle Bedienung = Schlosswechsel außerhalb des `OWN_ACTION_WINDOW`
  nach einem eigenen Befehl.
- Optionen (`entry.options`) haben Vorrang vor `entry.data`; Änderungen laden
  den Eintrag neu.
- iOS/Android-Aktion „Briefkasten geleert“: `data.actions` in der
  notify-Nachricht, Auswertung über das Event `mobile_app_notification_action`
  (Action-ID enthält die `entry_id`).

## Lektionen aus dem Referenz-Repo (gelten weiter)

- Kein ASCII-`{platzhalter}` in Texten von `strings.json`/`translations`
  (formatjs/hassfest) – Fullwidth-Klammern `｛x｝` verwenden.
- `manifest.json`-Schlüssel nach `domain`/`name` alphabetisch; `hacs.json`
  nur erlaubte Schlüssel.
- Nach Änderungen `pyflakes` + `pytest` (Python 3.13,
  `pytest-homeassistant-custom-component`) laufen lassen; `py_compile`
  erkennt fehlende Imports nicht.
- Entity-IDs entstehen aus den englischen Namen (`strings.json`).
- Beim Umbenennen/Ersetzen von Config-Feldern Migration in
  `async_setup_entry` ergänzen (bestehende Einträge werden nicht neu gespeichert).
