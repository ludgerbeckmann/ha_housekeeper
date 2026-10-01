# Home Assistant Hausmeister

[![Validate](https://github.com/ludgerbeckmann/ha_housekeeper/actions/workflows/validate.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_housekeeper/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Eine Custom Integration, die verschiedene Smart-Home-Anwendungsfälle
bündelt. **Jede Funktion ist ein Hub** (Integrationseintrag, benannt wie die Funktion, z. B.
„Türklingel“); die einzelnen **Instanzen** (eine Klingel, ein Pool, ein Wecker-Eintrag …) sind
**Untereinträge** des Hubs mit eigenem Gerät.

## Funktionen

| Typ | Beschreibung |
| --- | --- |
| Benachrichtigung Briefkasten | Meldet einen Posteinwurf, erkannt über einen Vibrationssensor |
| Türwächter | Schließt eine Tür per Regeln automatisch auf/ab und warnt, wenn sie zu lange offen steht |
| Türklingel | Spielt beim Klingeln je nach Uhrzeit eine Ansage oder einen Klingelton auf gewählten Media Playern und sendet Push |
| Poolsteuerung | Schaltet die Poolpumpe nach Zeitplan und erkennt Trockenlauf über einen Leistungssensor |
| KNX/Sonos-Connector | Steuert einen Sonos-Lautsprecher über KNX-Gruppenadressen und meldet seinen Zustand zurück an KNX |
| Home Assistant Updater | Meldet oder installiert Updates (Home Assistant, Add-ons, ESPHome und ESPHome-Geräte) nach Wochentag und Uhrzeit oder sobald ein Update verfügbar wird |
| Aufgabenplaner | Führt frei definierte Aktionen aus, wenn Auslöser eintreten (Zeitpunkte, Monatstage, Zustände, Grenzwerte) |
| Wecker | Spielt zur Weckzeit eine Audiodatei auf Media Playern ab, mit kritischer Push-Meldung (Stoppen/Schlummern) |

## Bedienung der Einstellungen

Das **Zahnrad** einer Instanz (*Neu konfigurieren*) öffnet ein **Menü**: Die Einträge (Einstellungen, hinzufügen,
bearbeiten, löschen …) sind direkt anklickbar, es gibt keinen OK-Button. Nach einem Dialog
geht es zurück ins Menü, das **X** oben links schließt es. Änderungen werden bei jedem Schritt
sofort gespeichert, das Schließen verliert also nichts.

Nach dem Speichern wird der Eintrag neu geladen. Läuft gerade etwas, das ein Neuladen nicht
überstünde, **wartet das Neuladen** bis zum Ende und wird dann einmal ausgeführt (mehrere
Änderungen ergeben nur ein Neuladen): ein klingelnder oder schlummernder **Wecker**, ein
laufender **Update-Lauf** (auch ein noch offener Bericht nach einem Neustart), eine laufende
**Aufgabe** und ein **manueller Poolpumpen-Lauf**. Die Einstellungen gelten dann nach dem Ende
dieses Vorgangs.

## Einzelne Elemente ein- und ausschalten

Wecker, Aufgaben, Updater-Zeitpläne, Türklingel-Profile, Türwächter-Regeln und
KNX/Sonos-Lautsprecher-Profile haben im Dialog ein Feld **Aktiv**. Ein ausgeschaltetes Element
wird ignoriert (Standard: an, bestehende Elemente bleiben aktiv) und in den Listen mit „aus“
markiert. Bei einem ausgeschalteten Updater-Zeitplan zählen auch seine Updates und
Benachrichtigungswege nicht für „Verfügbare Updates“ und „Jetzt prüfen“; ein ausgeschaltetes
KNX/Sonos-Profil sendet keine Rückmeldungen und führt keine Befehle aus.

## Installation

**HACS:** Menü (⋮) → *Benutzerdefinierte Repositories* → diese Repository-URL,
Kategorie *Integration* → „Home Assistant Hausmeister“ installieren → Home Assistant neu starten.

**Manuell:** `custom_components/ha_housekeeper` nach `<config>/custom_components/`
kopieren und neu starten.

Danach: *Einstellungen → Geräte & Dienste → Integration hinzufügen → Home Assistant Hausmeister*,
den Funktionstyp wählen und die erste Instanz einrichten. Dabei entsteht der **Hub** der
Funktion (je Funktionstyp einer). **Weitere Instanzen** (z. B. eine zweite Klingel oder ein
zweiter Pool) fügst du im Hub über die Schaltfläche **„… hinzufügen“** hinzu; jede Instanz hat ihr
Zahnrad (*Neu konfigurieren*) und ihr eigenes Gerät. Voraussetzung ist Home Assistant 2025.3 oder
neuer.

**Update von einer älteren Version:** Bisher war jede Instanz ein eigener Eintrag. Diese
Einträge werden nicht mehr geladen; es erscheint ein Reparaturhinweis. Lösche den alten Eintrag
und lege die Funktion neu an.

## Benachrichtigung Briefkasten

Bei einer Vibration (Sensor wechselt auf `on`) gilt der Briefkasten als
gefüllt. Es wird benachrichtigt, danach bleibt der Zustand „Post vorhanden“,
bis er zurückgesetzt wird. Löst der Sensor erneut aus, obwohl noch Post
vorhanden ist, gibt es einen erneuten Hinweis (eigener Text, gleiche Meldung
wird ersetzt) mit der Möglichkeit, den Briefkasten als geleert zu bestätigen.
„Letzter Posteinwurf“ wird dabei aktualisiert.

### Einstellungen

Der Dialog ist in zwei ausgeklappte Abschnitte gegliedert.

**Allgemein**

- **Vibrationssensor** (`binary_sensor`)
- **Entprellzeit** (Standard 60 s; weitere Vibrationen in dieser Zeit werden ignoriert)
- **Auto-Reset** nach X Stunden (0 = aus)
- **Empfindlichkeits-Entität** (optional, nur unter *Konfigurieren*): die `number`- oder
  `select`-Entität des Sensors für seine Empfindlichkeit, z. B. bei Zigbee2MQTT
  `number.vibrationssensor_sensitivity`. Die Entität wird nur **hinterlegt**; den **Wert**
  stellst du danach im Konfigurationsmenü über den eigenen Punkt **Empfindlichkeit einstellen**
  ein (Zahlenfeld mit den Grenzen der Entität bzw. die Stufen der `select`-Entität; der Punkt
  erscheint erst, wenn eine Entität hinterlegt ist). Der Wert bleibt beim Speichern der
  Einstellungen erhalten, solange die Entität dieselbe ist. Der Wert wird **nie automatisch** gesendet, weil Batteriesensoren ihn
  meist nur übernehmen, wenn sie am Gerät aufgeweckt wurden: Sensor aufwecken, dann den
  Button **Empfindlichkeit senden** drücken. Schlägt das Senden fehl, wird die Fehlermeldung
  angezeigt. Leeren der Entität entfernt Wert und Button.

**Benachrichtigungen**

- **App-Push**: ein oder mehrere **Companion-App-Geräte** (die native Geräteauswahl von
  Home Assistant mit Name und Bereich). Intern wird daraus der Dienst
  `notify.mobile_app_<gerät>`. Optional mit
  der **Aktion „Briefkasten geleert“** direkt in der Meldung (iOS und
  Android): Tippen/Halten auf die Meldung zeigt den Knopf, der den
  Briefkasten zurücksetzt und die Meldung wieder entfernt.
- **Sprachausgabe**: TTS-Dienst + Lautsprecher (`media_player`)
- **Persistente Benachrichtigung** in Home Assistant
- **Nachrichtentext** und **Text bei erneutem Auslösen**

Alle Einstellungen lassen sich später über *Konfigurieren* ändern.

Die Grunddialoge der anderen Funktionen (Türwächter, Türklingel, Home Assistant Updater,
Aufgabenplaner und die Trockenlauf-Erkennung der Poolsteuerung) haben dieselbe Gliederung
in **Allgemein** und **Benachrichtigungen**. Die Push-Ziele wählst du überall über die native
Geräteauswahl der **Companion-App-Geräte**; gesendet wird über deren Dienst
`notify.mobile_app_…`, nur darüber funktionieren die Aktionen (Briefkasten geleert, Stoppen,
Schlummern) und kritische Meldungen. Notify-Entitäten (`notify.send_message`) unterstützen das
nicht. Bereits gespeicherte Ziele (frühere Dienstnamen) laufen unverändert weiter und werden
im Dialog dem passenden Gerät zugeordnet.

### Entitäten

- `switch` **Briefkasten-Benachrichtigung aktiv** (aus = Vibrationen werden ignoriert; „Briefkasten
  geleert“ funktioniert weiter)
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

### Zeitfenster-Profile (Ton und Push)

Unter *Konfigurieren* legst du beliebig viele **Profile** an (Menü: Einstellungen,
Profil hinzufügen/bearbeiten/löschen). Ein Profil hat **ein** Formular mit drei Abschnitten:

**Zeitfenster**

- Name, aktiv, **Von/Bis** und Wochentage. Liegt *Bis* vor *Von*, gilt das Fenster
  über Mitternacht (z. B. 22:00 bis 06:00) und gehört zum Wochentag, an dem es
  beginnt. *Von = Bis* bedeutet ganztägig.

**Ton** (optional)

- ein oder mehrere **Media Player**; ohne Player gibt das Profil keinen Ton aus
- die Ausgabe: **Ansage (TTS)** mit TTS-Dienst und eigenem Text, oder **Klingelton**
  aus der Medienbibliothek
- optional eine Lautstärke (0 = unverändert)

**Benachrichtigung** (optional)

- **App-Push** an ein oder mehrere Companion-App-Geräte, Push-Text und **„Push nach X
  Stunden löschen“** (0 = nie). Gelöscht wird per `clear_notification` über denselben
  Tag, ein erneutes Klingeln ersetzt die Meldung und startet die Löschfrist neu.

Ein Profil braucht mindestens Ton **oder** Push; ein Profil nur mit Push (z. B. nachts
„nur aufs Handy, kein Ton“) ist möglich. Beim Klingeln werden **alle** Profile
ausgeführt, deren Zeitfenster gerade passt – gleichberechtigt. Ein Player oder ein
Push-Ziel, das in mehreren passenden Profilen steht, wird nur einmal bedient, und zwar
vom ersten. Liegt kein Profil im Zeitfenster, bleibt es stumm.

Der Push steht **nur noch in den Profilen**. Ältere Einträge mit Push im Eintrag werden
beim Start automatisch übernommen: als ganztägiges Profil „Benachrichtigung“ ohne Ton
(gleiches Verhalten wie vorher).

### Entitäten

- `switch` **Klingel aktiv** (aus = komplett stumm, Audio und Push)
- `sensor` **Letztes Klingeln** (Zeitstempel)
- `button` **Test-Klingeln** (spielt aus und sendet, was jetzt im Zeitfenster passt;
  umgeht Schalter und Sperrzeit)

## Poolsteuerung

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

### Poolheizung

Optional lässt sich eine **Heizung** (Schalter) nach der Temperatur steuern (Menü *Poolheizung*):

- **Heizung (Schalter)** und **Temperatursensor** (`sensor` oder `input_number`)
- **Einschalten ab** (°C): Erreicht oder überschreitet die Temperatur diese Schwelle, wird die
  Heizung eingeschaltet.
- **Ausschalten bei** (°C): Erreicht oder unterschreitet sie diese Schwelle, wird die Heizung
  ausgeschaltet. Sie muss **unter** der Einschaltschwelle liegen; dazwischen bleibt die Heizung,
  wie sie ist (Hysterese gegen ständiges Schalten).

Geschaltet wird nur beim **Wechsel** des Soll-Zustands; ein manueller Eingriff bleibt bis zum
nächsten Überschreiten einer Schwelle bestehen. Ist die Heizung nicht erreichbar, wird es nachgeholt;
bei ungültiger Temperatur (nicht verfügbar, keine Zahl) geschieht nichts. Die Heizung ist
unabhängig von Pumpe und Zeitplan. Wird das Feld Heizung geleert, ist die Funktion aus.

### Entitäten

| Entität | Beschreibung |
|---|---|
| `switch` **Heizung automatisch**, `binary_sensor` **Heizung soll laufen** | nur mit Heizung; die Automatik lässt sich ein-/ausschalten (aus = die Heizung wird nie geschaltet), der Sensor zeigt den Soll-Zustand samt Temperatur und Schwellen |
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

Verbindet KNX-Gruppenadressen mit einem oder mehreren Sonos-Lautsprechern, in beide Richtungen.
Die Funktion setzt auf der **offiziellen KNX-Integration** von Home Assistant auf
(Dienste `knx.event_register` und `knx.send`, Ereignis `knx_event`) und baut keine
eigene Busverbindung auf. Die KNX-Integration muss eingerichtet und geladen sein,
sonst bricht das Hinzufügen ab. Mehrere Lautsprecher werden als **Profile** in einem Eintrag
verwaltet.

### Lautsprecher-Profile

Unter *Konfigurieren* legst du die Profile an (hinzufügen, bearbeiten, löschen). Ein Profil hat:

- **Name** und **Sonos-Lautsprecher**
- **Maximale Lautstärke** (begrenzt jede per KNX gesetzte Lautstärke)
- **Schrittweite** für Lauter/Leiser und Dimmen
- die Option **Bei Pause stoppen statt pausieren** (z. B. für Radiostreams, die sich nicht
  pausieren lassen)

Jeder **Befehl** und jede **Rückmeldung** gehört zu einem Profil (Auswahl im Dialog, sobald es
mehrere Profile gibt) und hat **eigene Gruppenadressen**. Der Lautsprecher, den du beim
Hinzufügen wählst, wird das erste Profil „Standard“; bestehende Einträge laufen unverändert
weiter, alle bisherigen Befehle und Rückmeldungen gehören dann zu diesem Profil. Ohne
Profilangabe gilt immer das erste Profil. Ein Profil lässt sich nur löschen, wenn kein Befehl
und keine Rückmeldung es mehr nutzt, und das letzte Profil bleibt erhalten. Eine Gruppierung
der Lautsprecher über Sonos gehört nicht dazu.

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
- `sensor` **Letzter Befehl** (Zeitstempel; Attribute: Profil, Name, Adresse, Aktion, Wert)

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

## Home Assistant Updater

Meldet oder installiert Updates **zeitgesteuert**. Er arbeitet mit den
`update`-Entitäten von Home Assistant (Home Assistant OS: Core, Supervisor,
Betriebssystem, Add-ons wie ESPHome, außerdem die Firmware-Entitäten der
ESPHome-Geräte). Die Update-Entitäten der ESPHome-Geräte sind in Home Assistant
standardmäßig **deaktiviert** und müssen aktiviert sein.

Ein Eintrag enthält **mehrere Zeitpläne**. Im Eintrag selbst (*Einstellungen*) steht nur das
**Zeitlimit pro Update**; die **Benachrichtigung stellst du je Zeitplan ein**.

### Zeitpläne

Unter *Konfigurieren* pflegst du die Zeitpläne (hinzufügen, bearbeiten, löschen). Der
Dialog hat drei ausgeklappte Abschnitte. Ein Zeitplan hat:

**Zeitpunkt**

- Name, **Auslöser** und – je nach Auslöser – die Zeitangaben:
  - *Zu einer Uhrzeit* (Standard): **Uhrzeit** und **Wochentage**
  - *Sobald ein Update verfügbar wird*: Der Zeitplan läuft etwa eine Minute nach einer neuen
    Update-Meldung eines seiner Ziele (mehrere gleichzeitige Meldungen ergeben einen Lauf);
    Uhrzeit und Wochentage entfallen. Welche Updates ihn auslösen, bestimmen die gewählten
    **Komponenten** und **einzelnen Updates** – für unterschiedliches Verhalten je Komponente
    legst du einfach mehrere Zeitpläne an (z. B. Add-ons sofort, Core nur sonntags nachts).
    Optional ein **Zeitfenster** (von/bis, auch über Mitternacht): Außerhalb wartet der Zeitplan
    und holt zu Beginn des Fensters nach. Beim Start oder Neuladen werden bereits vorhandene
    Updates nicht ausgelöst („Jetzt prüfen“ meldet sie).

**Aktionen**

- **Aktion**: *Nur benachrichtigen* (Standard) oder *Automatisch installieren*
- die **Komponenten**, die aktualisiert werden sollen (Mehrfachauswahl):
  *Home Assistant Core*, *Supervisor*, *Betriebssystem (OS)*, *Add-ons* (inklusive
  ESPHome), *ESPHome-Geräte (Firmware)* sowie *Integrationen und Sonstiges* (z. B. HACS).
  Die Komponenten werden **bei jedem Lauf neu ermittelt**, ein später installiertes Add-on
  ist also automatisch dabei. Deaktivierte Entitäten zählen nicht.
- optional zusätzlich **einzelne Updates**: eine oder mehrere `update`-Entitäten.
  Verwendet wird die Vereinigung aus Komponenten und einzelnen Updates; mindestens eines
  von beiden muss gewählt sein. Jeder Zeitplan hat seine eigene Auswahl.
- **Sicherung vor dem Installieren** (Standard: aus; nur bei Updates, die das unterstützen)

**Benachrichtigungen**

- **App-Push** (ein oder mehrere Ziele), **Sprachausgabe** (TTS-Dienst und Lautsprecher),
  **persistente Meldung**; mindestens ein Weg muss gewählt sein. Neue Zeitpläne sind mit den
  bisherigen Einstellungen des Eintrags vorbelegt (sonst: nur persistente Meldung).
- Zeitpläne aus älteren Versionen haben noch keine eigenen Einstellungen und nutzen weiter
  die des Eintrags, bis du sie einmal bearbeitest und speicherst.
- Der Bericht nach einem Neustart (Core/OS-Update) geht über die Wege des Zeitplans, der den
  Lauf gestartet hat. Der Button **Jetzt prüfen** meldet über die **Vereinigung aller
  Zeitpläne** (alle Push-Ziele, Sprachausgabe vom ersten Zeitplan, der sie nutzt, persistente
  Meldung, wenn ein Zeitplan sie nutzt).

Zur eingestellten Zeit werden nur Updates berücksichtigt, die gerade bereitstehen
(ein bewusst übersprungenes Update bleibt übersprungen). Zugeordnet wird über die
Plattform der Entität: Core, Supervisor und OS über ihre Standard-Entity-IDs, Add-ons über
`hassio`, ESPHome-Geräte über `esphome`, alles andere zählt zu *Integrationen und
Sonstiges*. Bestehende Zeitpläne mit einzelnen Updates laufen unverändert weiter.

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

## Aufgabenplaner

Führt **Aktionen** aus, sobald ein **Auslöser** eintritt. Ein Eintrag enthält **mehrere
Aufgaben**; Benachrichtigungen gehen an die im Eintrag gewählten Wege (App-Push,
Sprachausgabe, persistente Meldung).

### Aufgaben

Unter *Konfigurieren* pflegst du die Aufgaben (hinzufügen, bearbeiten, löschen). Eine
Aufgabe hat:

- **Name** und einen Schalter *Aufgabe aktiv*
- **Aktionen**: der Aktionseditor von Home Assistant (Dienstaufrufe, Verzögerungen,
  Bedingungen, Benachrichtigungen …). In den Aktionen stehen die Variablen `trigger`
  (`type`, bei Entitäten außerdem `entity_id`, `from_state`, `to_state`) und `task`
  zur Verfügung.
- **Auslöser** (einer oder mehrere, jeder löst die Aufgabe aus)
- **Benachrichtigung** bei Start, Erfolg und Fehler, einzeln schaltbar
  (Standard: nur bei Fehler)

### Auslöser

| Art | Beschreibung |
| --- | --- |
| Wochentag und Uhrzeit | Uhrzeit an den gewählten Wochentagen |
| Monat | Uhrzeit am **ersten**, **letzten** oder einem **bestimmten Tag** des Monats (hat der Monat weniger Tage, gilt der letzte Tag) |
| Einmaliger Zeitpunkt | Datum und Uhrzeit, liegt in der Zukunft |
| Intervall | alle N Minuten, gezählt ab dem Start (Home-Assistant-Start oder Neuladen) |
| Zustand einer Entität | Wechsel in einen Zielzustand (leer = jede Änderung), optional erst nach N Minuten |
| Grenzwert eines Sensors | Wert steigt über / fällt unter einen Wert (oder Bereich), optional erst nach N Minuten |

Zustands- und Grenzwertauslöser lösen nur bei der **Flanke** aus (beim Übergang in die
Bedingung), nicht bei jeder weiteren Änderung. Hält die Bedingung die Mindestdauer nicht
ein, wird nichts ausgelöst. Auslöser einer Aufgabe lassen sich hinzufügen und entfernen;
zum Ändern entfernst du einen Auslöser und legst ihn neu an.

### Hinweise

- Eine Aufgabe läuft nie doppelt gleichzeitig; ein neuer Auslöser während des Laufs wird
  ignoriert.
- Ein Fehler in den Aktionen (z. B. unbekannter Dienst) gilt als fehlgeschlagen und wird
  gemeldet.
- Zeitpunkte, die während eines Neustarts von Home Assistant verstreichen, werden nicht
  nachgeholt.

### Entitäten

- `switch` **Aufgabenplaner aktiv** (aus = Auslöser starten nichts)
- `button` je Aufgabe (Name der Aufgabe): führt sie sofort aus, auch bei Pause
- `sensor` **Letzte Aufgabe** (Zeitstempel; Attribute: Aufgabe, Auslöser, Ergebnis, Fehler)
- `sensor` **Nächste Aufgabe** (nächster Zeitpunkt aller zeitgesteuerten Aufgaben)

## Wecker

Spielt zur Weckzeit eine **Audiodatei** auf einem oder mehreren **Media Playern** ab und
sendet eine **kritische Push-Meldung** mit den Aktionen **Stoppen** und **Schlummern**. Ein
Eintrag enthält **mehrere Wecker**; die Push-Ziele gelten für den ganzen Eintrag.

### Wecker

Unter *Konfigurieren* pflegst du die Wecker (hinzufügen, bearbeiten, löschen). Ein Wecker hat:

- **Name**, Schalter *Wecker aktiv*, **Uhrzeit** und **Wochentage**
- einen oder mehrere **Media Player**
- die **Audiodatei** aus der Medienauswahl von Home Assistant (lokale Medien, Medienbrowser, Streams)
- die **Lautstärke** in Prozent (Standard 30)
- die **Schlummerzeit** (Standard 9 Minuten)
- **Automatisch stoppen nach** X Minuten (Standard 30, 0 = nie), jeweils pro Klingeln
- optional **Werktags-/Feiertagsbedingungen** (nur, wenn in den Einstellungen Sensoren hinterlegt
  sind, siehe unten)

### Ablauf

1. Zur Weckzeit wird die **ursprüngliche Lautstärke** jedes Players gemerkt, die
   eingestellte Lautstärke gesetzt und die Datei abgespielt.
2. Die Push-Meldung kommt gleichzeitig. **Stoppen** beendet die Wiedergabe und entfernt die
   Meldung. **Schlummern** stoppt den Ton und startet ihn nach der Schlummerzeit erneut
   (mit neuer Meldung); das geht beliebig oft.
3. Bei jedem Ende des Tons (Stoppen, Schlummern, automatisches Stoppen, Wecker
   ausschalten) wird die **ursprüngliche Lautstärke** der Player **wiederhergestellt**. Das
   passiert auch nach einem Neustart von Home Assistant mitten im Wecken. Meldet ein Player
   keine Lautstärke, wird sie nicht zurückgesetzt.
4. Löst ein Wecker aus, während ein anderer klingelt, wird der laufende beendet.

### Werktags- und Feiertagssensoren

In den Einstellungen (*Konfigurieren → Einstellungen*, Abschnitt *Allgemein*) hinterlegst du
einen oder mehrere **Binärsensoren**, z. B. den Sensor der Werktags-Integration von Home
Assistant. Bei jedem Wecker kannst du dann aus diesen Sensoren zwei optionale Bedingungen wählen:

- **Nur klingeln, wenn an:** mindestens **einer** der gewählten Sensoren muss an sein (ODER),
  z. B. Werktagssensor.
- **Nicht klingeln, wenn an:** sobald **einer** der gewählten Sensoren an ist (ODER), klingelt der
  Wecker nicht, z. B. Feiertagssensor.

Mit **Sensorwerte umkehren** (Einstellungen, Abschnitt *Allgemein*, Standard aus) gilt bei allen
Sensoren *aus* als *an* und umgekehrt, z. B. wenn ein Sensor „arbeitsfrei“ statt „Werktag“ meldet.
Ein nicht verfügbarer oder unbekannter Sensor bleibt dabei unverändert.

Beide Felder sind UND-verknüpft und gelten zusätzlich zu den Wochentagen. Die Bedingungen
werden **zur Weckzeit** geprüft. Ein **nicht verfügbarer oder unbekannter** Sensor zählt bei
„Nur klingeln, wenn an“ als erfüllt, der Wecker klingelt dann eher einmal zu viel als gar nicht.
Ein übersprungener Wecker steht mit Grund und Sensoren im Attribut `skipped` des Sensors
**Letzter Wecker**. Sensoren, die aus den Einstellungen entfernt wurden, werden bei den Weckern
ignoriert. Der Sensor **Nächster Wecker** kennt die Bedingungen nicht (er kann künftige
Werktage nicht vorhersagen) und zeigt den nächsten Termin nach Wochentag und Uhrzeit.

### Kritische Meldung

Standardmäßig wird die Push-Meldung als **kritische Meldung** gesendet:

- **iOS:** `interruption-level: critical` mit kritischem Ton, durchbricht „Nicht stören“ und
  die Stummschaltung.
- **Android:** Alarm-Kanal (`alarm_stream`) mit hoher Priorität.

In der Companion-App müssen **kritische Hinweise erlaubt** sein. Die Option *Als kritische
Meldung senden* lässt sich in den Einstellungen abschalten (dann normale Meldung mit den
beiden Aktionen).

### Entitäten

- `switch` **Wecker aktiv** (aus = alle Wecker pausiert; ein klingelnder Wecker wird gestoppt)
- `binary_sensor` **Wecker klingelt** (beim Schlummern aus, Attribute `snoozed`, `snooze_until`)
- `sensor` **Nächster Wecker** und **Letzter Wecker** (Zeitstempel, Attribut `alarm`; beim
  letzten Wecker außerdem `skipped` mit dem zuletzt übersprungenen Wecker)
- `button` **Wecker stoppen** und **Schlummern**

## Reparaturhinweise

Der Hausmeister prüft, ob die in den Einstellungen gewählten Entitäten und Companion-App-Geräte noch existieren. Fehlt eine, erscheint unter **Einstellungen → System → Reparaturen** ein Hinweis (je fehlender Referenz einer, mit Name des Eintrags und der Entität).

- Geprüft werden Sensoren, Schlösser, Player, Schalter, Updates, Sprachausgabe und Push-Geräte aller Funktionen.
- Zeitpunkt: 5 Minuten nach dem Start, danach stündlich sowie kurz nach dem Löschen oder Umbenennen einer Entität bzw. dem Entfernen eines Geräts.
- Nicht verfügbare oder deaktivierte Entitäten gelten als vorhanden.
- Die Hinweise sind nicht automatisch behebbar; sie verschwinden von selbst, sobald die Referenz wieder stimmt (Einstellungen angepasst) oder der Eintrag gelöscht wird.

## Entwicklung

Tests: `pip install pytest-homeassistant-custom-component && pytest`
(Python 3.13). CI: hassfest, HACS-Validierung und pytest.
