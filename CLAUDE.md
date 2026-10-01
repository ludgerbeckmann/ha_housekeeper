# CLAUDE.md – Projektkontext für Claude Code

Home-Assistant Custom Integration `ha_housekeeper` (Anzeigename
„Home Assistant Hausmeister“; die Domain und der Repo-Name bleiben `ha_housekeeper`, sonst gehen bestehende
Einträge verloren): mehrere Funktionen, jede als eigener Config-Entry mit
`function_type`. Aktuell: `mailbox` („Benachrichtigung Briefkasten“) und
`door_guard` („Türwächter“), `doorbell` („Türklingel“), `pool_pump` („Poolsteuerung“,
portiert aus `ludgerbeckmann/ha_pool_manager`) `knx_sonos` („KNX/Sonos-Connector“) `updater` („Home Assistant Updater“) `task_planner` („Aufgabenplaner“) und `alarm_clock` („Wecker“).
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

- **Einstellungsdialoge** liegen im Paket `flows/`: `common.py` (Hilfen wie `_notify_fields`,
  `_sections_schema`, `_mobile_selector`, Basisklasse `OptionsBase` mit `_menu`/`_save`/`done`) und
  je Funktion ein Modul (`mailbox.py`, `door_guard.py`, `doorbell.py`, `pool.py`, `knx.py`,
  `updater.py`, `planner.py`, `alarm.py`) mit Formularen, Prüfungen und einer Options-Klasse
  (`MailboxOptions` usw.) mit den Dialogschritten. `config_flow.py` enthält nur den
  `HousekeeperConfigFlow` (Funktionstyp wählen, Eintrag anlegen) und den
  `HousekeeperOptionsFlow`, der alle Options-Klassen zusammensetzt. Neue Funktion = neues Modul in
  `flows/` plus Eintrag in `config_flow.py`.

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
  nur vom ersten passenden Profil bedient). Ein Profil hat Zeitfenster, **Ton** (optional,
  `players`/`mode`/TTS/Medien/`volume`) und **Push** (`mobile_enabled`, `mobile_targets`, `message`,
  `clear_after_hours`); ein Profil braucht Ton oder Push. Der Push steht **nur im Profil**, nicht
  im Eintrag: `assign_push()` liefert alle passenden Profile gleichberechtigt, jedes Ziel nur einmal
  (erstes Profil); je Profil ein eigener `Notifier` (`_notifier_for(targets)`). Löschzeitpunkte stehen
  je Profil im `Store` (`clears`, älteres `clear_at` = Schlüssel `*`). `__init__._migrate_doorbell_push`
  übernimmt den Push älterer Einträge einmalig als ganztägiges Profil „Benachrichtigung“ ohne Ton und
  setzt die Eintragswerte auf `None`. Der Profil-Dialog ist **ein** Formular mit den Abschnitten
  `timing`, `sound`, `notifications` (`profile_basic`). Audio über `async_safe_call`.
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
- `knx_sonos.py` / `knx_codec.py`: Der Connector nutzt die **offizielle KNX-Integration**
  (kein eigener Bus): Eingang über das Ereignis `knx_event` (nur `direction: Incoming`,
  `GroupValueWrite`; die Rohdaten aus `data` werden in `knx_codec.py` selbst dekodiert:
  1.001 Integer, 5.001 Byte*100/255, 17.001 Byte+1, 3.007 Bit 3 = heller/lauter,
  Schrittcode 0 = Stopp), Ausgang über `knx.send` mit `type` `1.001`/`5.001`/`16.001`
  (Text wird vorher auf 14 Zeichen gekürzt, sonst lehnt xknx ab). Adressen werden per
  `knx.event_register` angemeldet (gilt nur zur Laufzeit, daher beim Start, nach
  `event_knx_reloaded` und alle 5 Minuten neu). Lesetelegramme auf Rückmeldeadressen
  werden mit `response: true` beantwortet. Befehle und Rückmeldungen liegen als Listen
  in `options["commands"]`/`options["status"]` (Schlüssel `K_*`). `mute_set` hat keine
  Bedingung (folgt dem Wert). Der Übersetzungsschlüssel des Schalters ist
  `connector_active` (nicht `active`, der gehört zur Türklingel). **Mehrere Lautsprecher =
  Profile** in `options["speakers"]` (Schlüssel `id`, `name`, `player`, `max_volume`,
  `volume_step`, `stop_instead_of_pause`); Befehle/Rückmeldungen tragen `K_PROFILE` und haben
  eigene Adressen. `speaker_profiles()` bildet für ältere Einträge (nur `player` und Co. im
  Eintrag) ein Profil „Standard“ (id `default`); `profile_for()` löst ein Profil auf, ohne
  Angabe gilt das erste. Lautstärkegrenze, Schritt und „stoppen statt pausieren“ kommen aus
  dem Profil, der Controller beobachtet alle Player. Löschen eines Profils ist blockiert,
  solange Befehle/Rückmeldungen es nutzen. Menüeinträge: `add/edit/delete_speaker`
  (nicht `*_profile`, das gehört zur Türklingel).
- `updater.py`: Zeitpläne in `options["schedules"]` (Schlüssel `U_*`), je Zeitplan eigene
  Zielliste (`update`-Entitäten), Modus (melden/installieren) und Sicherung. Installiert
  wird über `update.install` **nacheinander**; Supervisor, Core und OS (Entity-IDs in
  `CRITICAL_ORDER`) immer zuletzt, nach einem Fehler ausgelassen, höchstens ein Neustart
  (`RESTARTING`) pro Lauf. Die Installation läuft als eigene Task hinter `asyncio.shield`
  und wird bei Zeitüberschreitung nie abgebrochen. Vor Core/OS wird `pending` im `Store`
  gesichert; `_async_finalize_pending` meldet nach dem Neustart das Ergebnis (wartet bis
  zu 10 Minuten auf die Entität). `backup` wird nur gesetzt, wenn die Entität
  `UpdateEntityFeature.BACKUP` (8) unterstützt. Ein Zeitplan wählt **Komponenten**
  (`U_COMPONENTS`: core, supervisor, os, addons, esphome, other) und/oder einzelne
  Entitäten (`U_TARGETS`); `resolve_targets()` bildet die Vereinigung bei **jedem Lauf**
  neu (Zuordnung über die Plattform in der Entity-Registry: `hassio` = Add-ons, `esphome`
  = Geräte, sonst „other“; Core/Supervisor/OS über ihre Entity-IDs; deaktivierte
  Entitäten zählen nicht). Der Listener hört auf alle `update.*`-Zustandsänderungen. Die **Benachrichtigung ist je
  Zeitplan** (die sechs Schlüssel aus `NOTIFY_KEYS` stehen flach im Zeitplan, Formular mit den
  Abschnitten `timing`, `actions`, `notifications`); `_notifier_for(schedule)` nimmt nur die
  Werte des Zeitplans, ältere Zeitpläne ohne `mobile_enabled` nutzen die des Eintrags als
  Rückfall (deshalb darf `upd_general` kein `_with_cleared` nutzen), „Jetzt prüfen“ die
  Vereinigung (`union_notify()`), der Neustartbericht den Zeitplan aus `pending["schedule_id"]`.
  Der Eintrag selbst hat nur Name und `timeout_minutes`. **Auslöser je Zeitplan** (`trigger`: `time` Standard, `on_available`): Bei `on_available`
  reagiert `_on_target_change` auf `became_available()` (Wechsel auf „on“ oder neue
  `latest_version`) einer Ziel-Entität des Zeitplans, bündelt `AVAILABLE_DELAY` Sekunden und startet
  den Lauf; optionales Zeitfenster `window_start`/`window_end` (`in_run_window()`, über Mitternacht),
  außerhalb wird zu Fensterbeginn (`_track_window_start`) nachgeholt; läuft schon ein Lauf, wird
  der Zeitplan in `_queued` vorgemerkt. Uhrzeit/Wochentage und „Nächster Lauf“ ignorieren solche
  Zeitpläne. Kein Nachholen beim Start.
- Formular-Abschnitte (`section` aus `homeassistant.data_entry_flow`, standardmäßig
  `collapsed: False`): Die Grunddialoge von Briefkasten, Türwächter, Türklingel,
  Home Assistant Updater, Aufgabenplaner und der Trockenlauf-Dialog der Poolsteuerung haben die
  Abschnitte `general` und `notifications` (Helfer `_sections_schema()`; ein Abschnitt ohne
  Felder entfällt, z. B. „Allgemein“ des Aufgabenplaners in den Einstellungen). Das Formular
  liefert **verschachtelte** Daten, gespeichert wird aber flach (`_flatten_sections()` am
  Anfang jedes Handlers), damit bestehende Einträge und die Controller unverändert bleiben.
  Übersetzungen stehen je Abschnitt unter `...step.<schritt>.sections.<abschnitt>` (`name`,
  `description`, `data`, `data_description`); das Top-Level-`data` entfällt dann. In Tests die
  Eingaben verschachtelt übergeben (`tests/helpers.py: sectioned()`). Die Übersetzungen
  werden aus den Feldschlüsseln verteilt: Benachrichtigungsfelder gehören zu `notifications`.
- Menüs im Options-Flow sind **Formulare**, keine `async_show_menu`-Menüs: `_menu()` zeigt
  ein Formular mit dem Feld `action` (Auswahlliste, `SelectSelector` LIST, Übersetzungs-
  schlüssel `menu_action`) und „Weiter“ unten rechts; die Auswahl ist der Schritt
  (`async_step_<aktion>`), `done` heißt „Speichern & schließen“. Die Beschriftungen der
  Einträge stehen gesammelt unter `selector.menu_action.options`, in den Menüschritten nur
  `title`, `description` und `data.action`. Neuer Menüeintrag = Schritt + Beschriftung dort.
  Tests: `tests/helpers.py` (`is_menu()`, `menu_options()`), Auswahl über `{"action": ...}`.
- Push-Ziele: native **Geräteauswahl** (`DeviceSelector`, `integration: mobile_app`,
  `_mobile_selector()`), gespeichert werden **Geräte-IDs** der Geräteverwaltung.
  `notify.resolve_mobile_services()` macht beim Senden daraus `mobile_app_<slug(device_name)>`
  (Dienst der Companion-App, ohne Doppelte; ältere Einträge mit direktem Dienstnamen werden
  unverändert unterstützt). `targets_for_form()` ordnet ältere Dienstnamen für die Vorbelegung
  dem Gerät zu (nicht zuordenbare bleiben stehen). Notify-**Entitäten** kommen nicht infrage,
  weil sie keine Aktionen und keine kritische Meldung können. Alle Sende-Wege laufen über
  `Notifier._targets()`.
- `alarm_clock.py`: Wecker in `options["alarms"]` (Schlüssel `A_*`), Push-Einstellungen im
  Eintrag (`mobile_*`, `critical`, `message`). Beim Wecken werden die **ursprünglichen
  Lautstärken** der Player gemerkt (`_restore`, auch im `Store`), Lautstärke gesetzt,
  `play_media`; bei **jedem** Ende des Tons (Stoppen, Schlummern, Auto-Stopp, Pause) wird
  `media_stop` aufgerufen und die Lautstärke zurückgesetzt; nach einem Neustart mitten im
  Wecken geschieht das in `async_start`. Schlummern = Ton stoppen und neu starten (nicht
  pausieren), Phase `snoozed` mit Timer. Die Push-Meldung hat die Aktionen `HOUSEKEEPER_ALARM_
  STOP_/SNOOZE_<entry_id>` (Event `mobile_app_notification_action`) und `critical_data()`
  (iOS `push.interruption-level: critical`, Android `channel: alarm_stream`); der
  `Notifier` nimmt dafür `extra`. Der Controller hat wie die Poolsteuerung ein
  `async def async_stop`. **Werktags-/Feiertagssensoren:** globale Liste `workday_sensors` im
  Eintrag, pro Wecker `only_if_on` (mindestens einer an, ODER) und `skip_if_on` (einer an
  blockiert, ODER), UND zwischen den Feldern; `check_conditions()` ist rein, ein unbekannter
  oder nicht verfügbarer Sensor zählt bei `only_if_on` als erfüllt (fail-open), nur globale
  Sensoren zählen. Übersprungen wird in `last_skipped` (im `Store`) festgehalten. Die Felder im
  Wecker-Dialog erscheinen nur, wenn globale Sensoren existieren, sonst bleiben gespeicherte
  Werte erhalten. „Nächster Wecker“ ignoriert die Bedingungen.
- Briefkasten-Empfindlichkeit (`sensitivity_entity`, `sensitivity_value`): Feld nur in den
  Einstellungen (nicht beim Anlegen); der Wert wird im Folgeschritt `mailbox_sensitivity`
  passend zur Entität abgefragt (`number` → Zahl mit Grenzen der Entität, `select` → deren
  Stufen). Gesendet wird **ausschließlich** über den Button `send_sensitivity`
  (`async_send_sensitivity()`, Fehler nicht verschlucken); **nie automatisch** (Batteriesensoren
  müssen am Gerät aufgeweckt werden). Der Button wird per `remove_unconfigured()` entfernt, wenn
  nichts eingestellt ist.
- `issues.py`: Reparaturhinweise (Issue-Registry). `collect_references(entry)` sammelt je Funktion alle
  Entitäten/Geräte aus den Einstellungen, `async_check_entry` legt je fehlender Referenz ein Issue
  `<entry_id>_<…>` an (nicht behebbar, Warnung) und löscht veraltete; nur bei geladenem Eintrag.
  Prüfung 300 s nach dem Start, stündlich und entprellt (`EVENT_DELAY_SECONDS`) nach Entity-/Geräte-
  Registry-Ereignissen. Deaktivierte/nicht verfügbare Entitäten zählen als vorhanden. Neue Funktion
  mit Entitätsfeldern = Eintrag in `collect_references()`. Platzhalter `{entry}`, `{function}`,
  `{entity}` sind echte ASCII-Platzhalter.
- **Einzelschalter „aktiv“** (`enabled`, Standard an) bei Updater-Zeitplänen (`U_ENABLED`),
  Türklingel-Profilen (`P_ENABLED`), Türwächter-Regeln (`R_ENABLED`) und KNX-Lautsprecher-Profilen
  (`S_ENABLED`), wie bei Weckern und Aufgaben: Der Controller ignoriert ausgeschaltete Elemente
  (`UpdaterController.schedules` = nur aktive, `all_schedules` = alle; `DoorGuardController._rules()`
  nur aktive; `assign_players()` überspringt ausgeschaltete Profile; beim KNX-Connector liefert
  `_player_state()` für ein ausgeschaltetes Profil `None`, die Befehle/Rückmeldungen ruhen). Die
  Dialoge (`flows/`) arbeiten dagegen mit **allen** Elementen. Beim Briefkasten gibt es den
  Schalter `mailbox_active` (im `Store`, aus = Vibrationen werden ignoriert).
- Entity-IDs folgen den englischen Namen, z. B. `switch.<name>_doorbell_active`.
- Optionen (`entry.options`) haben Vorrang vor `entry.data`; Änderungen laden
  den Eintrag neu, **aber nicht mitten in einem Lauf**: `__init__._async_reload` merkt das
  Neuladen vor (`reload_requested`), wenn der Controller `busy` ist; das Mixin `ReloadWhenIdle`
  (`reload.py`) führt es in `async_idle()` aus, sobald etwas endet. `busy` gilt für Wecker
  (klingelnd/schlummernd), Updater (Lauf oder offener `pending`-Bericht), Aufgabenplaner
  (laufende Aufgabe) und Poolsteuerung (manueller Lauf). Ein neuer Controller mit Zuständen,
  die ein Neuladen nicht überstehen, erbt das Mixin, überschreibt `busy` und ruft `async_idle()`.
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
