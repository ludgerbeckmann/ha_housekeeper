# CLAUDE.md – Projektkontext für Claude Code

Home-Assistant Custom Integration `ha_housekeeper` (Anzeigename
„Housekeeper“): mehrere Funktionen, jede als eigener Config-Entry mit
`function_type`. Aktuell: `mailbox` („Benachrichtigung Briefkasten“) und
`door_guard` („Türwächter“) `doorbell` („Türklingel“) und `pool_pump` („Poolpumpe“, portiert aus
`ludgerbeckmann/ha_pool_manager`).
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
- Türklingel-Profile liegen als Liste in `options["profiles"]` (Schlüssel `P_*`
  in `const.py`). `in_window()`/`assign_players()` in `doorbell.py` sind reine
  Funktionen (Fenster über Mitternacht gehören zum Starttag, ein Player wird
  nur vom ersten passenden Profil bedient). Push über `Notifier`, Audio über
  `async_safe_call`. Löschzeitpunkt (`clear_at`) wird im `Store` gehalten.
- `pool_pump.py`: Controller (Port von `PoolManager`). `pool_schedule.py` und
  `pool_dry_run.py` sind reine Logik ohne HA-Imports und unverändert aus dem
  Ursprungsprojekt. Der Controller ist der einzige mit `async def async_stop`
  (speichert den Zustand); `__init__.async_unload_entry` wartet darauf, falls
  das Ergebnis awaitable ist. Die Aktion `run_pump` wird in `async_setup`
  registriert und wirkt auf alle `PoolPumpController`.
- Poolpumpe: Geschaltet wird nur beim Wechsel des Soll-Zustands
  (`_last_desired`), eine nicht erreichbare Pumpe bleibt in `_pending`,
  Trockenlauf-Alarm ist ein Latch, ohne Zeitfenster greift der Zeitplan nie ein.
  „Zeitplan aktiv“ liegt im `Store` (nicht RestoreEntity), wird in `async_start`
  geladen. Optionale Entitäten (Trockenlauf) werden per `remove_unconfigured()`
  aus der Registry entfernt, wenn kein Leistungssensor gesetzt ist; ein
  geleerter Sensor steht als `None` in den Optionen.
- Entity-IDs folgen den englischen Namen, z. B. `switch.<name>_doorbell_active`.
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
