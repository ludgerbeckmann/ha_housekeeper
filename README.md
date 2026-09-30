# Housekeeper für Home Assistant

[![Validate](https://github.com/ludgerbeckmann/ha_housekeeper/actions/workflows/validate.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_housekeeper/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Eine Custom Integration, die verschiedene Smart-Home-Anwendungsfälle
bündelt. **Jede Funktion wird als eigener Integrationseintrag angelegt** -
beim Hinzufügen wählst du zuerst den Funktionstyp aus.

## Funktionen

| Typ | Beschreibung |
| --- | --- |
| Benachrichtigung Briefkasten | Meldet einen Posteinwurf, erkannt über einen Vibrationssensor |
| Türwächter | Schließt eine Tür per Regeln automatisch auf/ab und warnt, wenn sie zu lange offen steht |
| Türklingel | Spielt beim Klingeln je nach Uhrzeit eine Ansage oder einen Klingelton auf gewählten Media Playern und sendet Push |
| Poolpumpe | Schaltet die Poolpumpe nach Zeitplan und erkennt Trockenlauf über einen Leistungssensor |
| KNX/Sonos-Connector | Steuert einen Sonos-Lautsprecher über KNX-Gruppenadressen und meldet seinen Zustand zurück an KNX |
| Updater | Meldet oder installiert Updates (Home Assistant, Add-ons, ESPHome und ESPHome-Geräte) nach Wochentag und Uhrzeit |

## Installation

**HACS:** Menü (⋮) → *Benutzerdefinierte Repositories* → diese Repository-URL,
Kategorie *Integration* → „Housekeeper“ installieren → Home Assistant neu starten.

**Manuell:** `custom_components/ha_housekeeper` nach `<config>/custom_components/`
kopieren und neu starten.

Danach: *Einstellungen → Geräte & Dienste → Integration hinzufügen → Housekeeper*
und den Funktionstyp wählen.

## Benachrichtigung Briefkasten

Bei einer Vibration (Sensor wechselt auf `on`) gilt der Briefkasten als
gefüllt. Es wird benachrichtigt, danach bleibt der Zustand „Post vorhanden“,
bis er zurückgesetzt wird. Löst der Sensor erneut aus, obwohl noch Post
vorhanden ist, gibt es einen erneuten Hinweis (eigener Text, gleiche Meldung
wird ersetzt) mit der Möglichkeit, den Briefkasten als geleert zu bestätigen.
„Letzter Posteinwurf“ wird dabei aktualisiert.

### Einstellungen

- **Vibrationssensor** (`binary_sensor`)
- **App-Push**: ein oder mehrere `notify.mobile_app_*`-Dienste; die Auswahl
  zeigt zusätzlich den Gerätenamen der Companion-App (z. B. „iPhone Ludger
  (mobile_app_iphone_ludger)“). Optional mit
  der **Aktion „Briefkasten geleert“** direkt in der Meldung (iOS und
  Android): Tippen/Halten auf die Meldung zeigt den Knopf, der den
  Briefkasten zurücksetzt und die Meldung wieder entfernt.
- **Sprachausgabe**: TTS-Dienst + Lautsprecher (`media_player`)
- **Persistente Benachrichtigung** in Home Assistant
- **Nachrichtentext** und **Text bei erneutem Auslösen**, **Entprellzeit** (Standard 60 s; weitere Vibrationen
  in dieser Zeit werden ignoriert), **Auto-Reset** nach X Stunden (0 = aus)

Alle Einstellungen lassen sich später über *Konfigurieren* ändern.

### Entitäten

- `binary_sensor` **Post vorhanden**
- `sensor` **Letzter Posteinwurf** (Zeitstempel)
- `button` **Briefkasten geleert**

Der Zustand bleibt über Neustarts erhalten.

## Türwächter

Pro Tür ein Eintrag: ein **Schloss** (`lock`) und optional ein **Türkontakt**
(`binary_sensor`, `on` = offen). Das Auf- und Abschließen steuerst du über
**Regeln**, die du unter *Konfigurieren* verwaltest (Menü: Einstellungen,
Regel hinzufügen/bearbeiten/löschen).

### Regeln

Jede Regel hat eine Aktion (**Abschließen** oder **Aufschließen**) und einen Auslöser:

- **Zustand einer Entität**: löst beim *Wechsel* in den Zielzustand aus
  (z. B. `person.ludger` → `home`, Alarmanlage → `armed_away`), optional erst
  nach X Minuten in diesem Zustand. Wechselt die Entität vorher zurück, wird
  abgebrochen.
- **Uhrzeit**: zu einer Uhrzeit an den gewählten Wochentagen.
- **Tür geschlossen seit X Sekunden**: nur zum Abschließen, braucht den Türkontakt.

### Türkontakt-Prüfungen

- **Abschließen nur bei geschlossener Tür:** Ist der Kontakt `on` (offen)
  oder nicht verfügbar, wird nicht abgeschlossen und benachrichtigt. Wählbar:
  *Nur melden* oder *Nach dem Schließen abschließen* (bis zum eingestellten
  Zeitlimit).
- **Tür zu lange offen:** Nach X Minuten Warnung, optional wiederholt.
  Setze den Wert auf 0, wenn du keinen Türkontakt hast.
- **Schloss prüfen:** Steht das Schloss nach der Aktion nicht im Zielzustand
  (z. B. klemmt), gibt es nach X Sekunden eine Meldung.

### Manuelle Bedienung

Auswahl *Bei manueller Bedienung des Schlosses*:
**Automatik weiterlaufen lassen** oder **Automatik pausieren** (für X Minuten).
Als manuell gilt jede Änderung des Schlosszustands, die nicht vom Türwächter
selbst ausging (Schlüssel, Taster, App, andere Automationen).

### Benachrichtigung

App-Push, Sprachausgabe und persistente Meldung wie beim Briefkasten
(ohne die Aktion „geleert“). Die Meldungstexte sind deutsch bzw. englisch
je nach Systemsprache.

### Entitäten

- `binary_sensor` **Tür zu lange offen**
- `switch` **Automatik** (aus = alle Regeln pausieren; Attribut `paused_until`)
- `sensor` **Letzte Aktion** (Zeitstempel; Attribute `action`, `reason`, `result`)

Der Zustand (Automatik an/aus, Pause, letzte Aktion) bleibt über Neustarts erhalten.

## Türklingel

Pro Klingel ein Eintrag. Als **Auslöser** dient ein `binary_sensor` (löst beim
Wechsel auf `on` aus) oder eine `event`-Entität (löst bei jedem Ereignis aus).
Eine **Sperrzeit** (Standard 10 s) ignoriert weiteres Klingeln.

### Audio: Zeitfenster-Profile

Unter *Konfigurieren* legst du beliebig viele **Profile** an (Menü: Einstellungen,
Profil hinzufügen/bearbeiten/löschen). Ein Profil besteht aus:

- Name, **Von/Bis** und Wochentagen. Liegt *Bis* vor *Von*, gilt das Fenster
  über Mitternacht (z. B. 22:00 bis 06:00) und gehört zum Wochentag, an dem es
  beginnt. *Von = Bis* bedeutet ganztägig.
- einem oder mehreren **Media Playern**
- der Ausgabe: entweder **Ansage (TTS)** mit TTS-Dienst und eigenem Text, oder
  **Klingelton** aus der Medienbibliothek
- optional einer Lautstärke (0 = unverändert)

Beim Klingeln werden alle Profile ausgeführt, deren Zeitfenster gerade passt.
Die Player werden gleichzeitig bedient; ein Player, der in mehreren passenden
Profilen steht, wird nur einmal bedient, und zwar vom ersten. Liegt kein Profil
im Zeitfenster, bleibt es stumm (der Push geht trotzdem raus).

### Push

Ein oder mehrere Ziele (`notify.mobile_app_*`), Push-Text und **„Push nach X
Stunden löschen“** (0 = nie). Gelöscht wird per `clear_notification` über
denselben Tag, ein erneutes Klingeln ersetzt die Meldung und startet die
Löschfrist neu. Push ist unabhängig von den Audio-Zeitfenstern.

### Entitäten

- `switch` **Klingel aktiv** (aus = komplett stumm, Audio und Push)
- `sensor` **Letztes Klingeln** (Zeitstempel)
- `button` **Test-Klingeln** (spielt aus, was jetzt im Zeitfenster passt, und
  sendet den Push; umgeht Schalter und Sperrzeit)

## Poolpumpe

Übernommen aus der Integration
[ha_pool_manager](https://github.com/ludgerbeckmann/ha_pool_manager). Pro Pumpe
ein Eintrag (Name und Pumpen-Schalter, `switch` oder `input_boolean`).

### Zeitfenster

Unter *Konfigurieren* pflegst du bis zu 8 **Zeitfenster** (Menü: Pumpe ändern,
Zeitfenster hinzufügen/bearbeiten/löschen, Trockenlauferkennung, Fertig). Ein
Fenster hat Beginn, Ende und Wochentage. Liegt das Ende vor dem Beginn, läuft es
über Mitternacht (die Wochentage beziehen sich dann auf den Tag des Beginns).

- Die Pumpe wird zu **Fensterbeginn eingeschaltet** und zu **Fensterende
  ausgeschaltet**; geprüft wird jede Minute.
- Geschaltet wird **nur bei einem Wechsel**: Schaltest du die Pumpe von Hand
  während eines Fensters aus (oder außerhalb an), bleibt das bis zum nächsten
  Fensterwechsel bestehen.
- Ohne Zeitfenster schaltet der Zeitplan die Pumpe nie.
- Nach einem **Neustart** bzw. beim Aktivieren der Automatik wird die Pumpe
  einmalig an den Soll-Zustand angeglichen.
- Ist die Pumpe `unavailable`/`unknown`, wird der Schaltvorgang **vorgemerkt**
  und nachgeholt, sobald sie wieder erreichbar ist.

### Trockenlauf-Erkennung

Unter *Trockenlauferkennung* hinterlegst du einen **Leistungssensor** (`sensor`,
Geräteklasse Leistung, W oder kW). Ohne Sensor ist die Funktion aus, die
zugehörigen Entitäten werden dann nicht angelegt bzw. entfernt.

| Einstellung | Beispiel |
|---|---|
| Untere Grenze | 75 W |
| Obere Grenze | 100 W |
| Dauer | 5 min |
| Bei Trockenlauf Pumpe ausschalten und Zeitplan pausieren (Standard: aus) | – |

Ein Trockenlauf wird erkannt, wenn die Pumpe **an** ist und die Leistung
**durchgehend** (Grenzen inklusive) für die Dauer im Bereich liegt. Verlässt die
Leistung den Bereich, geht die Pumpe aus oder ist der Sensor
`unavailable`/`unknown`, beginnt die Zeitmessung neu, ein Sensorausfall löst
also keinen Alarm aus.

Bei Erkennung geht der Binärsensor **Trockenlauf erkannt** auf `on` (gehalten,
bis über den Button **Trockenlauf quittieren** quittiert oder die Pumpe neu
gestartet wird) und es wird benachrichtigt. Mit der automatischen Abschaltung wird
zusätzlich die Pumpe ausgeschaltet und der Zeitplan pausiert; der Button
aktiviert ihn wieder. Nach einem Neustart bleibt *Zeitplan aktiv* aus, bis du es
wieder einschaltest.

**Benachrichtigung bei Trockenlauf:** persistente Meldung in Home Assistant
(Standard), optional zusätzlich App-Push und Sprachausgabe, einstellbar im
Schritt *Trockenlauferkennung*. Beim Quittieren werden die Meldungen wieder
entfernt.

### Entitäten

| Entität | Beschreibung |
|---|---|
| `switch` **Zeitplan aktiv** | Automatik an/aus, bleibt nach einem Neustart erhalten. Beim Ausschalten wird die Pumpe nicht angefasst. |
| `binary_sensor` **Pumpe soll laufen** | `on`, solange die Pumpe laut Zeitplan (oder manuellem Lauf) laufen soll |
| `sensor` **Nächster Start** | Zeitstempel des nächsten Fensterbeginns |
| `sensor` **Laufzeit heute** | bisherige Laufzeit heute in Minuten (bleibt über Neustarts erhalten) |
| `binary_sensor` **Trockenlauf erkannt**, `button` **Trockenlauf quittieren** | nur mit Leistungssensor |

### Aktion `ha_housekeeper.run_pump`

Lässt die Pumpe unabhängig vom Zeitplan für eine bestimmte Zeit laufen (auch bei
ausgeschaltetem Zeitplan). Danach gilt wieder der Zeitplan.

```yaml
action: ha_housekeeper.run_pump
data:
  duration: 30        # Minuten (1–1440)
  # entry_id: ...     # optional; ohne Angabe sind alle Poolpumpen betroffen
```

### Umstieg von ha_pool_manager

Die Einträge der alten Integration werden nicht automatisch übernommen. Lege
die Poolpumpe hier neu an (Pumpe, Zeitfenster, Trockenlauf-Einstellungen), passe
Automationen und Dashboards an die neuen Entity-IDs und die Aktion
`ha_housekeeper.run_pump` an und entferne danach die alte Integration.

## KNX/Sonos-Connector

Verbindet KNX-Gruppenadressen mit einem Sonos-Lautsprecher, in beide Richtungen.
Die Funktion setzt auf der **offiziellen KNX-Integration** von Home Assistant auf
(Dienste `knx.event_register` und `knx.send`, Ereignis `knx_event`) und baut keine
eigene Busverbindung auf. Die KNX-Integration muss eingerichtet und geladen sein,
sonst bricht das Hinzufügen ab. Pro Lautsprecher ein Eintrag.

### Einstellungen

Unter *Konfigurieren → Einstellungen*: Sonos-Lautsprecher, **Maximale Lautstärke**
(begrenzt jede per KNX gesetzte Lautstärke), **Schrittweite** für Lauter/Leiser und
Dimmen sowie die Option **Bei Pause stoppen statt pausieren** (z. B. für
Radiostreams, die sich nicht pausieren lassen).

### Befehle (KNX → Sonos)

Ein Befehl besteht aus Name, **Gruppenadresse** (3-Ebenen, 2-Ebenen oder frei),
**Datentyp** und **Aktion**. Es zählen nur eingehende **Schreibtelegramme**.

| Datentyp | Bedingung |
|---|---|
| Schalten, 1 Bit (1.001) | auslösen bei Wert 1, Wert 0 oder jedem Wert |
| Prozent, 1 Byte (5.001) | immer |
| Szene (17.001) | bei der gewählten Szenennummer (1–64) |
| Relatives Dimmen (3.007) | bei jedem Schritt außer Stopp |

Aktionen: Wiedergabe, Pause, Wiedergabe/Pause umschalten, Stopp, nächster/vorheriger
Titel, **Lautstärke setzen** (aus dem Prozentwert oder fest), **Lauter**, **Leiser**,
**Lautstärke dimmen** (Richtung aus dem Dimm-Telegramm, nur mit 3.007), Stumm, Stumm
aus, Stumm umschalten, **Stumm (Wert)** (1 = stumm, 0 = aus, nur mit 1.001) und
**Sonos-Favorit abspielen** (Auswahl aus den Favoriten des Lautsprechers; gespeichert
wird der Titel, bei einem umbenannten Favoriten muss der Befehl angepasst werden).

### Rückmeldungen (Sonos → KNX)

Eine Rückmeldung hat Name, **Quelle** und Gruppenadresse. Der Wert wird bei jeder
Änderung gesendet, und **Leseanfragen** (GroupValueRead) auf der Adresse werden mit
dem aktuellen Wert beantwortet.

| Quelle | Datentyp |
|---|---|
| Wiedergabe, Pause, Stumm | 1 Bit (1.001) |
| Lautstärke | Prozent (5.001) |
| Titel, Interpret, Album, Quelle/Favorit | Text (16.001, auf 14 Zeichen gekürzt) |

Bei Textquellen wird der **Text, wenn nichts wiedergegeben wird** (Standard leer)
gesendet, solange der Lautsprecher nicht spielt.

### Entitäten

- `switch` **Connector aktiv** (aus = keine Befehle und keine Rückmeldungen; beim
  Einschalten werden die Rückmeldungen neu gesendet)
- `sensor` **Letzter Befehl** (Zeitstempel; Attribute: Name, Adresse, Aktion, Wert)

### Hinweise

- **Eigene Telegramme** (`direction: Outgoing`) werden nie ausgewertet, damit sich die
  Rückmeldungen nicht selbst auslösen. Verwende für Befehl und Rückmeldung trotzdem
  getrennte Gruppenadressen, wie in ETS üblich.
- Die Anmeldung der Adressen bei der KNX-Integration gilt nur zur Laufzeit. Sie wird
  beim Start, nach `event_knx_reloaded` und alle 5 Minuten wiederholt (idempotent),
  damit ein Neuladen der KNX-Integration die Funktion nicht stilllegt. Nach einem
  Neuladen über die Oberfläche kann es bis zu 5 Minuten dauern, bis Befehle wieder
  ankommen.
- Relatives Dimmen löst pro Telegramm **einen Schritt** aus (kein weiches Hoch- oder
  Runterfahren über eine Zeit). Anregungen stammen u. a. aus dem Blueprint
  [KNX Media Player](https://gist.github.com/torbenledermann/e20c6d9d86406529e9941b71fca82935),
  ohne dessen Music-Assistant-, Squeezebox- und Denon-Erweiterungen.

## Updater

Meldet oder installiert Updates **zeitgesteuert**. Er arbeitet mit den
`update`-Entitäten von Home Assistant (Home Assistant OS: Core, Supervisor,
Betriebssystem, Add-ons wie ESPHome, außerdem die Firmware-Entitäten der
ESPHome-Geräte). Die Update-Entitäten der ESPHome-Geräte sind in Home Assistant
standardmäßig **deaktiviert** und müssen aktiviert sein.

Ein Eintrag enthält **mehrere Zeitpläne**; Benachrichtigungen gehen an die im Eintrag
gewählten Wege (App-Push, Sprachausgabe, persistente Meldung) und das Zeitlimit pro
Update ist dort einstellbar.

### Zeitpläne

Unter *Konfigurieren* pflegst du die Zeitpläne (hinzufügen, bearbeiten, löschen). Ein
Zeitplan hat:

- Name, **Uhrzeit** und **Wochentage**
- **Aktion**: *Nur benachrichtigen* (Standard) oder *Automatisch installieren*
- die **Updates**: eine oder mehrere `update`-Entitäten (jeder Zeitplan hat seine eigene Auswahl)
- **Sicherung vor dem Installieren** (Standard: aus; nur bei Updates, die das unterstützen)

Zur eingestellten Zeit werden nur Updates berücksichtigt, die gerade bereitstehen
(ein bewusst übersprungenes Update bleibt übersprungen).

### Ablauf beim Installieren

- Die Updates werden **nacheinander** installiert (wichtig bei ESPHome-Geräten, die je
  einige Minuten brauchen), in der gewählten Reihenfolge. **Supervisor, Core und OS**
  stehen immer am Ende.
- Schlägt ein Update fehl, laufen die übrigen Add-ons und Geräte weiter; **Supervisor,
  Core und OS werden dann ausgelassen**.
- Pro Lauf wird **höchstens ein Neustart** (Core oder OS) ausgeführt, ein weiterer
  bleibt für den nächsten Lauf übrig.
- Ein Update gilt nach dem **Zeitlimit** als fehlgeschlagen (Standard 30 Minuten); eine
  laufende Installation wird dabei nicht abgebrochen. Ein Update gilt außerdem als
  fehlgeschlagen, wenn die neue Version danach nicht übernommen wurde.
- Startet ein Core-/OS-Update Home Assistant neu, wird der **Bericht nach dem Start**
  nachgeholt (erfolgreich oder nicht).

### Benachrichtigung

- *Nur benachrichtigen*: Liste der verfügbaren Updates mit Versionen (nur wenn welche
  bereitstehen).
- *Installieren*: eine Meldung beim Start des Laufs und eine Zusammenfassung mit Ergebnis
  je Update (installiert, fehlgeschlagen, übersprungen, verschoben).

### Entitäten

- `switch` **Updater aktiv** (aus = keine Zeitpläne laufen)
- `button` **Jetzt prüfen**: meldet sofort den Stand aller gewählten Updates und
  installiert nie
- `sensor` **Letzter Update-Lauf** (Zeitstempel; Attribute: Zeitplan, Aktion, Anzahl
  installiert/fehlgeschlagen/übersprungen, Zusammenfassung)
- `sensor` **Nächster Update-Lauf**
- `sensor` **Verfügbare Updates** (Anzahl, Attribut `updates` mit den Namen)

Die Erkennung von Supervisor, Core und OS beruht auf den Standard-Entity-IDs
`update.home_assistant_supervisor_update`, `update.home_assistant_core_update` und
`update.home_assistant_operating_system_update`.

## Entwicklung

Tests: `pip install pytest-homeassistant-custom-component && pytest`
(Python 3.13). CI: hassfest, HACS-Validierung und pytest.
