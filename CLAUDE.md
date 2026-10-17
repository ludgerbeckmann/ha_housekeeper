# CLAUDE.md – Projektkontext für Claude Code

Home-Assistant Custom Integration `ha_housekeeper` (Anzeigename
„Home Assistant Hausmeister“; die Domain und der Repo-Name bleiben `ha_housekeeper`, sonst gehen bestehende
Einträge verloren): **ein einziger Hub** „Funktionen“ (Config-Entry, `data` = `{"hub": True}`, `unique_id` `hub`,
Manifest `single_config_entry`, `integration_type: service`), alle Instanzen sind **Untereinträge**
(Config-Subentries, Typ = Funktionstyp, eigenes Gerät). Aktuell: `mailbox` („Benachrichtigung Briefkasten“) und
`door_guard` („Türwächter“), `doorbell` („Türklingel“), `pool_pump` („Poolsteuerung“,
portiert aus `ludgerbeckmann/ha_pool_manager`) `knx_sonos` („KNX/Sonos-Connector“, ein Eintrag je Lautsprecher) `updater` („Home Assistant Updater“) `task_planner` („Aufgabenplaner“) `alarm_clock` („Wecker“) `integration_monitor` („Integrationsmonitor“), `llm_usage` („LLM-Verbrauch“) `ir_remote` („IR-Fernbedienung“) und `consumption_guard` („Verbrauchswächter“).
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

- **Hub und Untereinträge:** `async_setup_entry` (`__init__.py`) richtet für **jeden Untereintrag** einen
  Controller ein (`CONTROLLERS[subentry.subentry_type]`, `hass.data[DOMAIN][<subentry_id>]`, flach) und leitet **alle**
  Plattformen (`ALL_PLATFORMS`) weiter. Controller, `Store`, Entitäten und Reparaturhinweise arbeiten mit
  `SubentryEntry` (`subentry.py`), einem Adapter, der einen Untereintrag wie einen Config-Entry aussehen lässt
  (`entry_id` = Untereintrags-ID, `title` = **Name der Instanz** ohne Präfix, `data` = Daten des Untereintrags,
  `options` = `{}`; `hub_entry_id`). Plattformen: `async_setup_entry` ruft je Controller `_add_entities(...)` mit
  `config_subentry_id=` auf, aber nur für Controller, deren Typ die Plattform nutzt
  (`hub_controllers(hass, hub, Platform.X)`). Änderungen an einem Untereintrag laden den **Hub** neu (`_async_reload`,
  verschoben, solange **irgendein** Controller des Hubs `busy` ist; das Flag `reload_requested` steht dann an allen
  Controllern). **Titel** der Untereinträge: „Funktion: Name“ (`instance_title()`, `instance_name()` in `const.py`; ist
  der Name gleich dem Funktionsnamen, entfällt der Präfix); `_normalize_titles()` korrigiert beim Laden. Das Namensfeld beim Anlegen ist **leer und optional** (leer = Funktionsname); `clean_instance_name()` entfernt einen vorangestellten Funktionsnamen (nur mit Trenner danach) beim Anlegen und Umbenennen, `_normalize_titles()` bereinigt bestehende Titel bewusst nicht. Ältere Einträge
  (ohne `hub`-Marker oder mit `function_type`) laden nicht, es gibt den Reparaturhinweis `legacy_entry`. `unload` stoppt
  alle Controller mit `entry.hub_entry_id`.
- **Einstellungsdialoge** liegen im Paket `flows/`: `common.py` (Hilfen wie `_notify_fields`,
  `_sections_schema`, `_mobile_selector`, Basisklasse `OptionsBase` mit `_menu`/`_save`) und
  je Funktion ein Modul (`mailbox.py`, `door_guard.py`, `doorbell.py`, `pool.py`, `knx.py`,
  `updater.py`, `planner.py`, `alarm.py`, `monitor.py`, `llm.py`, `ir.py`, `consumption.py`) mit Formularen, Prüfungen und einer Options-Klasse
  (`MailboxOptions` usw.) mit den Dialogschritten. `config_flow.py`: `HousekeeperConfigFlow` legt nur den Hub an
  (ohne Formular, `unique_id` `hub`); `HousekeeperSubentryFlow` gehört zu **allen** Funktionstypen
  (`async_get_supported_subentry_types`): Schritt `user` = Instanz hinzufügen (`NewInstanceSteps`, Anlege-Formulare
  `async_step_new_<typ>`, Titel „Funktion: Name“), `reconfigure` = das Menü des Typs (`_MENU_STEPS`), jedes Menü hat den
  Punkt `rename` (`async_step_rename`, nur der Name, der Präfix wird ergänzt); `_current`/`_save` lesen und schreiben
  die Daten des Untereintrags (`async_update_subentry`). Pumpen dürfen nur einmal vorkommen (`unique_id` des
  Untereintrags). Neue Funktion = neues Modul in `flows/` plus Einträge in `config_flow.py`.
  Übersetzungen der Einstellungsschritte stehen je Typ unter `config_subentries.<typ>` (`step`, `error`, `abort`,
  `initiate_flow.user`, `entry_type`). Die Beschriftung des Hub-Buttons („Dienst hinzufügen“) hängt am
  `integration_type` im Manifest und ist nicht frei wählbar.

- `const.py`: `FUNCTION_PLATFORMS` ist die Registry Funktionstyp → Plattformen.
  **Neue Funktion:** Typ-Konstante + Registry-Eintrag, Anlege-Schritt
  `async_step_new_<typ>`, Menü-Eintrag in `_MENU_STEPS`, Controller-Klasse, Plattformdateien, Übersetzungen
  (`config_subentries.<typ>`, `FUNCTION_TITLES`), Controller-Registry in `__init__.py`.
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
  nach einem eigenen Befehl. **Anwesenheit/Bedingungen:** `presence_entities` der Tür (`CONF_PRESENCE`);
  Auslöser `presence` (`R_PRESENCE_MODE` `all_away`/`any_home`, `R_FOR_MINUTES`, flankengesteuert über
  `_presence_was`, Timer `presence_<id>`, kein Nachholen beim Start); Bedingungen `R_PRESENCE`,
  `R_ONLY_IF_ON` (UND), `R_SKIP_IF_ON` (ODER) für alle Auslöser im Schritt `rule_conditions`.
  Reine Funktionen `entity_on()`, `presence_met()`, `evaluate_conditions()`; `_async_run_rule()` prüft sie
  und trägt Übersprungenes als `skipped` ein (keine Meldung). Unklar: Anwesenheit = nichts schalten,
  sonst Aufschließen nicht, Abschließen schon.
- Türklingel-Profile liegen als Liste in `options["profiles"]` (Schlüssel `P_*`
  in `const.py`). `in_window()`/`assign_players()` in `doorbell.py` sind reine
  Funktionen (Fenster über Mitternacht gehören zum Starttag, ein Player wird
  nur vom ersten passenden Profil bedient). Ein Profil hat Zeitfenster, **Ton** (optional,
  `players`/`mode`/TTS/Medien/`volume`) und **Push** (`mobile_enabled`, `mobile_targets`, `message`,
  `clear_after_hours`); ein Profil braucht Ton oder Push. Der Push steht **nur im Profil**, nicht
  im Eintrag: `assign_push()` liefert alle passenden Profile gleichberechtigt, jedes Ziel nur einmal
  (erstes Profil); je Profil ein eigener `Notifier` (`_notifier_for(targets)`). Löschzeitpunkte stehen
  je Profil im `Store` (`clears`, älteres `clear_at` = Schlüssel `*`). Der Profil-Dialog ist **ein** Formular mit den Abschnitten
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
  **Poolheizung** (`heater_entity`, `temperature_entity`, `heater_on_above`, `heater_off_below`, Menü
  `heater`): ab/über der Einschaltschwelle an, bei/unter der Ausschaltschwelle aus, dazwischen
  Hysterese; wie die Pumpe nur beim Wechsel des Soll-Zustands (`_heater_desired`), nicht erreichbare
  Heizung in `_heater_pending`, ungültige Temperatur = nichts tun; unabhängig von Pumpe/Zeitplan.
  `heater_auto` (Store, Schalter `heater_auto`) ist die Automatik; beim Einschalten wird neu bewertet.
  Der Heizungsdialog darf nur die Heizungsfelder leeren (nicht `_with_cleared`, das würde Trockenlauf-
  und Push-Felder löschen). Entitäten `heater_auto`/`heater_should_run` per `remove_unconfigured()`.
- `knx_sonos.py` / `knx_codec.py`: Der Connector nutzt die **offizielle KNX-Integration**
  (kein eigener Bus): Eingang über das Ereignis `knx_event` (nur `direction: Incoming`,
  `GroupValueWrite`; die Rohdaten aus `data` werden in `knx_codec.py` selbst dekodiert:
  1.001 Integer, 5.001 Byte*100/255, 17.001 Byte+1, 3.007 Bit 3 = heller/lauter,
  Schrittcode 0 = Stopp), Ausgang über `knx.send` mit `type` `1.001`/`5.001`/`16.001`
  (Text wird vorher auf 14 Zeichen gekürzt, sonst lehnt xknx ab). Adressen werden per
  `knx.event_register` angemeldet (gilt nur zur Laufzeit, daher beim Start, nach
  `event_knx_reloaded` und alle 5 Minuten neu). Lesetelegramme auf Rückmeldeadressen
  werden mit `response: true` beantwortet. Der Übersetzungsschlüssel des Schalters ist
  `connector_active` (nicht `active`, der gehört zur Türklingel). **Ein Eintrag = ein Lautsprecher.**
  Die Einstellungen sind **feste Felder auf einer Seite** (`async_step_knx_settings`, kein Menü; `_MENU_STEPS` zeigt
  direkt darauf, Speichern = `async_update_subentry` + Abbruch `reconfigure_successful`, der Name steht als Feld im
  Abschnitt `speaker`) mit den Abschnitten `speaker`, `playback`, `volume`, `scenes`, `scene_1…8` (eingeklappt),
  `status` (nach dem Blueprint „KNX Media Player“): Schlüssel `addr_*`, `scene_<n>_favorite/volume/address`,
  `status_*`, `idle_text`, `player`/`max_volume`/`volume_step`/`stop_instead_of_pause`. Gruppenadressen sind optional,
  geleerte Felder stehen als `None` in den Daten (`_CLEARABLE`). `settings_commands()`/`settings_status()` bilden
  daraus beim Start dieselben Befehls- und Rückmeldungslisten wie früher (Schlüssel `K_*`; z. B. Play/Pause = `play` bei
  1 und `pause` bei 0, Szene = Favorit plus Lautstärke auf 17.001 und auf der eigenen 1-Bit-Adresse mit „0 = Pause“),
  die Dekodierung bleibt unverändert; ältere Listen `commands`/`status` laufen daneben weiter. **Ältere Einträge:** mehrere
  Lautsprecher = Profile in `speakers` (Schlüssel `id`, `name`, `player`, `max_volume`, `volume_step`,
  `stop_instead_of_pause`, `enabled`; Befehle tragen `K_PROFILE`), `speaker_profiles()` bildet für Einträge mit nur
  `player` und Co. ein Profil „Standard“, `profile_for()` löst auf (ohne Angabe das erste). Die Seite zeigt die Werte des
  ersten Profils und setzt beim Speichern `speakers` auf `None` (weitere Profile gehen verloren, Hinweis in der
  Beschreibung); alte Listen werden nur mit dem Schalter `clear_legacy` (Abschnitt `legacy`, nur wenn welche da sind)
  gelöscht. Es gibt keine Menüeinträge `add/edit/delete_*` mehr für KNX.
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
- Menüs im Options-Flow sind **native Menüs** (`async_show_menu`): `_menu()` zeigt die Einträge direkt
  anklickbar (kein OK/„Weiter“, das X schließt, **kein** Eintrag „Speichern & schließen“); die Auswahl ist
  der Schritt (`async_step_<aktion>`). Gespeichert wird bei jedem Schritt sofort über `_save()`, deshalb
  braucht es keinen Abschluss. Die Beschriftungen stehen je Menüschritt unter `menu_options`. Neuer
  Menüeintrag = Schritt + Beschriftung dort. Tests: `tests/helpers.py` (`is_menu()`, `menu_options()`),
  Auswahl über `{"next_step_id": ...}`.
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
  `async def async_stop`. **Werktags-/Feiertagssensoren** gehören zur Zeitplanung des einzelnen Weckers (Felder
  `only_if_on`/`skip_if_on` im Wecker-Dialog neben Uhrzeit und Wochentagen, beliebige Binärsensoren, keine globale
  Liste mehr): `only_if_on` = mindestens einer an (ODER), `skip_if_on` = einer an blockiert (ODER), UND zwischen den
  Feldern; `check_conditions(alarm, get_state)` ist rein, ein unbekannter oder nicht verfügbarer Sensor zählt bei
  `only_if_on` als erfüllt (fail-open) und blockiert bei `skip_if_on` nie. Eine Umkehr-Option gibt es nicht: ein
  Sensor „arbeitsfrei“ gehört in `skip_if_on`. Übersprungen wird in `last_skipped` (im `Store`) festgehalten.
  „Nächster Wecker“ ignoriert die Bedingungen.
- Briefkasten-Empfindlichkeit (`sensitivity_entity`, `sensitivity_value`): Der Options-Flow des Briefkastens
  ist ein Menü (`mailbox_menu`: `mailbox`, `mailbox_sensitivity` nur mit Entität, `done`). Die Entität steht nur
  in den Einstellungen (nicht beim Anlegen) und wird dort **nur hinterlegt**; der Wert wird im eigenen
  Menüschritt `mailbox_sensitivity` (nicht automatisch nach dem Speichern) passend zur Entität abgefragt;
  beim Speichern der Einstellungen bleibt er bei gleicher Entität erhalten, bei anderer/leerer Entität wird er verworfen (`number` → Zahl mit Grenzen der Entität, `select` → deren
  Stufen). Gesendet wird **ausschließlich** über den Button `send_sensitivity`
  (`async_send_sensitivity()`, Fehler nicht verschlucken); **nie automatisch** (Batteriesensoren
  müssen am Gerät aufgeweckt werden). Der Button wird per `remove_unconfigured()` entfernt, wenn
  nichts eingestellt ist.
- `integration_monitor.py`: Der Monitor prüft **alle** Config-Entries außer der eigenen Domain (`entry_status()`:
  Fehlerstatus `ERROR_STATES` oder alle aktiven Entitäten der Registry `unavailable`, erst ab `min_entities`;
  deaktivierte/ladende Einträge sind „nicht beurteilbar“ = `None`). Eine Störung gilt erst nach der Wartezeit
  (`grace_minutes`, `_since` im Speicher) und wird als `faults` im `Store` bestätigt (`acted`/`notified` je
  Störung: `acted` = Aktion einmal ausgeführt, `reported` = steht in der Sammelmeldung, `result` = Ergebnis der Aktion).
  **Sammelmeldung** (`_async_flush_summary()`): eine Meldung mit fester Kennung `summary` für alle gemeldeten Störungen
  (Zeile = Integrationsname aus dem Manifest + Eintragstitel, Art, Entitätenzahl, seit, Aktion); gesendet nach
  `summary_minutes` (`summary.pending`), geändert nur bei geänderter Liste (`summary.sent`), bei leerer Liste sofort
  entfernt; TTS spricht nur die Anzahl (`Notifier.async_send(spoken=…)`). Gemeldet wird je Art nach `notify_errors`/
  `notify_unavailable` (fehlen beide: der ältere `notify_all`, Standard an), Ausnahmenliste, oder eine Regel mit
  `notify`. Beim Update von den Einzelmeldungen werden die alten Meldungen je Integration einmal entfernt.
  Regeln in `options["monitor_rules"]` (Schlüssel `M_*`) gelten nur für ausdrücklich gewählte Integrationen;
  Aktion `none`/`reload`/`disable` (Vorrang: disable). Deaktiviert wird per `async_set_disabled_by(USER)`, der
  Monitor merkt sich seine Deaktivierungen in `disabled` (Store) und aktiviert **nur diese** wieder: über die
  Anwesenheitsentität der Regel (`on`/`home`, Listener auf deren Zustand) oder den Button. Von Hand aktivierte
  oder gelöschte Einträge werden vergessen. Kein `busy`/`ReloadWhenIdle` (der Zustand liegt im `Store`).
  Menü `mon_menu` (Schritte `add/edit/delete_monitor_rule`, `monitor_rule_edit` mit den Abschnitten
  `general`, `condition`, `action`); Benachrichtigung nur im Eintrag (nicht je Regel).
- `llm_usage.py` / `llm_providers.py`: Je Instanz ein Anbieterkonto (`anthropic`, `openai`). `llm_providers.py`
  fragt per aiohttp die **Kosten je Tag (UTC)** ab (`async_fetch_costs()`, Anthropic `/v1/organizations/cost_report`
  mit `x-api-key` (Admin-Key), `amount` in **Cent** als Dezimalstring; OpenAI `/v1/organization/costs`, `amount.value`),
  mit Seitenwechsel (`next_page`, höchstens `MAX_PAGES`); 401/403 = `ProviderAuthError`. Anthropic: ohne `ending_at` endet der Zeitraum mit dem Beginn des heutigen Tages, deshalb beginnen die Abfragen (Kosten, Tokens, Key-Prüfung) höchstens **gestern** (`_request()`), sonst HTTP 400 „ending date must be after starting date“. Beide liefern **kein
  Guthaben**: `remaining_balance()` rechnet im Modus `balance` Betrag minus Kosten seit `baseline_time` (der
  Abgleichstag zählt nur über den beim ersten Abruf gemerkten `snapshot`), im Modus `budget` Betrag minus Kosten
  des Monats. Die Tageskosten liegen im `Store` (`days`, `days_from`); später werden nur die letzten
  `RECHECK_DAYS` Tage neu geladen. `average_daily()` = Durchschnitt der letzten 7 **abgeschlossenen** Tage
  (Reichweite und `forecast_month()`: Kosten bisher + Rest von heute + übrige Monatstage). Optional
  (`track_usage`) werden Tokens/Anfragen über `usage_report/messages` (Anthropic, keine Anfragenzahl) bzw.
  `usage/completions` (OpenAI) geholt (`async_fetch_usage`, nur der laufende Monat, Fehler stören die Kosten
  nicht); die Sensoren entstehen nur dann (sonst `remove_unconfigured()`), Anfragen-Sensoren nur bei OpenAI. Warnungen (`alerts` im `Store`): `low` (mit Entwarnung), `daily`/`monthly`/`forecast`
  (Datum bzw. Monat der letzten Meldung = einmal je Zeitraum; `forecast` gegen das Monatslimit bzw. das Budget, nur
  solange es noch nicht überschritten ist), `error` (nach `FAILURES_BEFORE_ALERT`, Key-Fehler
  sofort, dann zusätzlich der Reparaturhinweis `<id>_llm_auth`, den der Controller selbst anlegt und löscht). Die Sensoren sind `state_class: measurement` ohne Geräteklasse (Verlauf über die Recorder-Statistiken).
  Der Modus lässt sich nach dem Anlegen nicht ändern; Betrag im Guthaben-Modus nur über `llm_calibrate`.
  Der Key wird beim Anlegen/Ändern mit einer Abfrage geprüft (`async_check_key` liefert Fehlerschlüssel und Ursache; die Ursache steht als `{detail}` in den Fehlertexten und im Log; `_get()` meldet HTTP-Status plus `error.message` des Anbieters), Leerraum um den Key wird entfernt, `api_key` steht in
  `TO_REDACT` der Diagnose. In Tests `llm_providers.async_fetch_costs` ersetzen (`fake_costs`).
- `ir_remote.py`: Je Instanz `remotes` (mehrere `remote`-Entitäten), `ir_device` (Gerätename beim Sender, später nicht
  änderbar) und Befehle in `ir_commands` (Schlüssel `IC_*`: `id`, `name` = Anzeige, `code` = Name beim Sender aus
  `command_code()`, `type` ir/rf, `enabled`, `remotes` = Sender, an denen angelernt). Die Codes liegen im Speicher
  des Senders (Broadlink: `.storage/broadlink_remote_<unique_id>_codes`, `{gerät: {befehl: code}}`); Anlernen/Senden/
  Löschen über die Aktionen `remote.learn_command`/`send_command`/`delete_command` (Modulfunktionen `async_learn`,
  `async_send`, `async_delete`, auch vom Dialog genutzt). Codes sind **je Sender** getrennt (nicht kopierbar): Anlernen
  läuft je Sender als eigener Fortschrittsdialog (`ir_learn`, `async_show_progress` mit `progress_task`, Ergebnis in
  `self._learn`, Teilerfolge werden gespeichert), Senden geht gleichzeitig an alle Sender, die den Befehl kennen;
  ausgeschaltet/nicht verfügbar = Fehler je Sender (`outcome()` ok/partial/failed, Meldung `error`, bei Erfolg
  geräumt). „Vorhandene Befehle übernehmen“ liest die interne Broadlink-Datei (`async_stored_codes`), Handeingabe
  (`custom_value`) bleibt als Rückfall. Je aktivem Befehl ein Button (`<id>_ir_<befehl-id>`, veraltete werden wie beim
  Aufgabenplaner entfernt), optional Schalter `ir_power` (Befehle `ir_on_command`/`ir_off_command`, `assumed_state`,
  Zustand im `Store`, per `remove_unconfigured()` entfernt), Sensor `ir_last_sent`; Entity-Aktion `send_ir_command`
  (Button-Plattform, optional `num_repeats`). Löschen eines vom Schalter genutzten Befehls ist blockiert.
- `consumption_guard.py`: Je Instanz ein Sensor (`consumption_sensor`) mit Durchfluss/Leistung. Eine **Konfigurationsseite**
  (`cg_settings`, kein Menü, Name als Feld; Abschnitte `general`, `notifications`; Speichern = `async_update_subentry` +
  Abbruch `reconfigure_successful`) mit `threshold`, `duration_minutes` (Standard 15), `repeat_minutes` (0 = nie), optionalem
  Zeitfenster `window_from`/`window_to` (`in_window()`, über Mitternacht). „Läuft“ = Wert **größer** als die Schwelle
  (`is_running()`, `None` bei fehlend/unavailable/unknown/keine Zahl). `_async_evaluate()` läuft bei jeder Zustandsänderung und
  minütlich (`CHECK_INTERVAL`): außerhalb des Fensters oder bei Wert ≤ Schwelle wird alles zurückgesetzt (Warnung weg, Push
  entfernt, `since` leer); unklarer Sensor setzt nur `since` zurück, eine bestehende Warnung bleibt; sonst startet `since`
  und nach `duration` kommt **eine** Meldung (`kind="warning"`), mit Wiederholung nach `repeat`. `async_acknowledge()` (Button)
  löscht die Warnung und unterdrückt weitere Meldungen (`_acknowledged`), bis der Verbrauch einmal ≤ Schwelle war. Der Zustand
  (`since`, Warnung) liegt nur im Speicher; im `Store` steht nur `enabled` (Schalter `consumption_active`). Entitäten:
  `binary_sensor` `consumption_warning`, `sensor` `consumption_since`, `button` `consumption_acknowledge`. In Tests mit
  `freezer` arbeiten und `hass.config.async_set_time_zone(...)` setzen, wenn das Zeitfenster geprüft wird.
- `issues.py`: Reparaturhinweise (Issue-Registry; abgeglichen werden nur `<id>_entity_…`/`<id>_device_…`, andere gehören dem jeweiligen Controller). `collect_references(entry)` sammelt je Funktion alle
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
- Einstellungen stehen in den Daten des Untereintrags (`SubentryEntry.options` ist leer, ein auf `None` gesetzter
  Wert gilt als geleert); Änderungen laden den Hub neu, **aber nicht mitten in einem Lauf**: `__init__._async_reload` merkt das
  Neuladen vor (`reload_requested`), wenn ein Controller des Hubs `busy` ist; das Mixin `ReloadWhenIdle`
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
- Nach Änderungen `pyflakes` + `pytest` (Python 3.14,
  `pytest-homeassistant-custom-component`) laufen lassen; `py_compile`
  erkennt fehlende Imports nicht.
- Entity-IDs entstehen aus den englischen Namen (`strings.json`).
- Beim Umbenennen/Ersetzen von Config-Feldern Migration in
  `async_setup_entry` ergänzen (bestehende Einträge werden nicht neu gespeichert).
