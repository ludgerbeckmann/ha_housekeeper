# Home Assistant Hausmeister

[![Validate](https://github.com/ludgerbeckmann/ha_housekeeper/actions/workflows/validate.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_housekeeper/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Eine Custom Integration, die verschiedene Smart-Home-Anwendungsfälle
bündelt. Es gibt **einen Hub „Funktionen“**; jede **Instanz** (eine Klingel, ein Pool, ein
Wecker …) ist ein **Untereintrag** dieses Hubs mit eigenem Gerät.

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
| LLM-Verbrauch | Überwacht Kosten und Restguthaben eines LLM-API-Kontos (Anthropic, OpenAI) mit Verlauf und Warnungen bei niedrigem Guthaben oder hohem Verbrauch |
| Verbrauchswächter | Meldet, wenn ein Durchfluss oder eine Leistung (z. B. Wasser, Strom) länger als eine eingestellte Zeit am Stück über einer Schwelle liegt |
| IR-Fernbedienung | Lernt Infrarot-/Funkbefehle an Sendern (z. B. Broadlink RM4 mini) an, übernimmt vorhandene Befehle und stellt sie als Tasten und optional als Schalter bereit |
| Integrationsmonitor | Überwacht alle Integrationen auf Fehler oder lauter nicht verfügbare Entitäten, meldet Störungen und lädt ausgewählte Integrationen neu oder deaktiviert/aktiviert sie |

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

Wecker, Aufgaben, Updater-Zeitpläne, Türklingel-Profile, Türwächter-Regeln (und ältere
KNX/Sonos-Lautsprecher-Profile) haben im Dialog ein Feld **Aktiv**. Ein ausgeschaltetes Element
wird ignoriert (Standard: an, bestehende Elemente bleiben aktiv) und in den Listen mit „aus“
markiert. Bei einem ausgeschalteten Updater-Zeitplan zählen auch seine Updates und
Benachrichtigungswege nicht für „Verfügbare Updates“ und „Jetzt prüfen“; ein ausgeschaltetes
älteres KNX/Sonos-Profil sendet keine Rückmeldungen und führt keine Befehle aus (beim KNX/Sonos-Connector
schaltet man sonst den Eintrag mit „Connector aktiv“ aus).

## Installation

**HACS:** Menü (⋮) → *Benutzerdefinierte Repositories* → diese Repository-URL,
Kategorie *Integration* → „Home Assistant Hausmeister“ installieren → Home Assistant neu starten.

**Manuell:** `custom_components/ha_housekeeper` nach `<config>/custom_components/`
kopieren und neu starten.

Danach: *Einstellungen → Geräte & Dienste → Integration hinzufügen → Home Assistant Hausmeister*.
Das legt den **Hub „Funktionen“** an (ohne weitere Abfrage; es gibt nur einen). **Instanzen** fügst du
über die Schaltflächen am Hub hinzu: **„Briefkasten hinzufügen“, „Türwächter hinzufügen“,
„Klingel hinzufügen“, „Pool hinzufügen“, „KNX/Sonos-Connector hinzufügen“, „Updater hinzufügen“,
„Aufgabenplaner hinzufügen“, „Wecker hinzufügen“, „Integrationsmonitor hinzufügen“, „LLM-Verbrauch hinzufügen“, „IR-Fernbedienung hinzufügen“, „Verbrauchswächter hinzufügen“**. Jede Instanz hat ihr Zahnrad
(*Neu konfigurieren*) und ihr eigenes Gerät. Voraussetzung ist Home Assistant 2025.3 oder neuer.

**Namen:** Beim Anlegen gibst du nur den Namen der Instanz ein (leer und optional; leer = Funktionsname,
z. B. „Türwächter“). Die Feldbeschriftung zeigt den Präfix („Name (erscheint als „Türwächter: Name“)“); ein
vorangestellter Funktionsname wird automatisch entfernt („Türwächter Garagentür“ wird zu „Türwächter:
Garagentür“).
In der Liste erscheint die Instanz als **„Funktion: Name“** (z. B. „Wecker: Zimmer Hannah“; so stehen
gleiche Funktionen beieinander), das **Gerät** heißt nur „Name“. Im Menü hinter dem Zahnrad gibt es
den Punkt **Umbenennen**; der Präfix bleibt dabei automatisch erhalten, auch eine Umbenennung über
Home Assistant selbst wird beim nächsten Neuladen korrigiert.

**Update von einer älteren Version:** Bisher war jede Instanz (oder später jede Funktion) ein
eigener Eintrag. Diese Einträge werden nicht mehr geladen; es erscheint ein Reparaturhinweis. Lösche
den alten Eintrag, lege den Hub „Funktionen“ an und füge die Instanzen neu hinzu.

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
- **Anwesenheit**: braucht die *Personen für die Anwesenheit* in den Einstellungen der Tür
  (Personen oder Gerätetracker, z. B. die Eltern; Kinder nicht eintragen). *Alle sind weg*
  löst nach einer Wartezeit aus (Standard 3 Minuten; kommt jemand zurück, wird abgebrochen),
  *Jemand kommt nach Hause* sobald eine Person ankommt. Beim Start wird nichts nachgeholt.

### Bedingungen (optional, für alle Auslöser)

- **Anwesenheit**: *Egal* (Standard), *Nur wenn jemand zu Hause ist* oder *Nur wenn alle weg sind*.
  Ist ein Standort unklar, wird nichts geschaltet.
- **Nur wenn an**: alle gewählten Entitäten müssen an sein (z. B. Arbeitstagssensor).
- **Nicht wenn an**: ist eine der Entitäten an, wird die Regel übersprungen (z. B. Ferien).

Erlaubt sind Binärsensor, Hilfsschalter, Kalender, Zeitplan, Person, Gerätetracker und Zone
(Personen/Tracker zählen zu Hause als an, Zonen mit mindestens einer Person darin). Bei
unklarem Zustand gilt die sichere Seite: Aufschließen entfällt, Abschließen läuft. Übersprungene
Regeln senden keine Meldung, stehen aber mit Grund in „Letzte Aktion“ (Ergebnis `skipped`).

**Empfehlung (Batterie schont):** morgens und abends je eine Zeitregel mit Bedingungen,
dazu „Abschließen bei Anwesenheit: alle weg“; Regeln wie „Tür geschlossen seit X Sekunden“
vermeiden, sie lösen oft aus.

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

Verbindet KNX-Gruppenadressen mit einem Sonos-Lautsprecher, in beide Richtungen.
Die Funktion setzt auf der **offiziellen KNX-Integration** von Home Assistant auf
(Dienste `knx.event_register` und `knx.send`, Ereignis `knx_event`) und baut keine
eigene Busverbindung auf. Die KNX-Integration muss eingerichtet und geladen sein,
sonst bricht das Hinzufügen ab. **Jeder Lautsprecher ist ein eigener Eintrag** („KNX/Sonos-Connector
hinzufügen“), mit eigenem Gerät, Schalter und Sensor.

### Konfigurationsseite

Alle Einstellungen stehen auf **einer Seite** (Anlegen und Zahnrad), in Abschnitten; nur „Lautsprecher“ ist aufgeklappt, die übrigen sind eingeklappt. Jede
Gruppenadresse ist optional, ein leeres Feld bedeutet „nicht verwendet“. Es zählen nur eingehende
**Schreibtelegramme**. Das Layout orientiert sich am Blueprint
[KNX Media Player](https://gist.github.com/torbenledermann/e20c6d9d86406529e9941b71fca82935).

| Abschnitt | Felder |
|---|---|
| **Lautsprecher** | Name, Sonos-Lautsprecher, **Lautstärkegrenze** (begrenzt jede per KNX gesetzte Lautstärke), **Lautstärkeschritt**, **Stoppen statt Pause** (z. B. für Radiostreams) |
| **Wiedergabe** | Play/Pause (1 Bit: 1 = Wiedergabe, 0 = Pause), Nächster/Vorheriger Titel (1 = nächster, 0 = vorheriger), Stopp (1), Play/Pause umschalten (1) |
| **Lautstärke** | absolut (5.001), Lauter/Leiser (1 Bit, ein Schritt), relatives Dimmen (3.007, ein Schritt je Telegramm, Schrittcode 0 = Stopp), Stumm (1 Bit, folgt dem Wert) |
| **Szenen** | Szenenadresse (17.001, Szenennummer 1–5); je **Szene 1–5**: Favorit (Auswahl aus den Quellen des Lautsprechers oder Name eintippen), optional Lautstärke und optional eine eigene 1-Bit-Adresse (1 = starten, 0 = Pause) |
| **Rückmeldungen** (drei Abschnitte) | *Wiedergabe:* Spielt, Pausiert (1 Bit). *Lautstärke:* Lautstärke (5.001), Stumm (1 Bit). *Text:* Titel, Interpret, Album, Quelle (auf 14 Zeichen gekürzt) und der **Text, wenn nichts läuft** |

**Gruppenadressen aus dem ETS-Projekt:** Hast du in der KNX-Integration ein **ETS-Projekt importiert**
(KNX → Konfigurieren → ETS-Projekt importieren), bieten alle Adressfelder die Adressen des Projekts als Dropdown an
(„1/2/3 – Name (Datentyp)“, durchsuchbar). Jedes Feld zeigt nur Adressen mit passendem Datentyp (1 Bit, 5.xxx,
3.xxx, 17.xxx, 16.xxx), Adressen ohne hinterlegten Datentyp erscheinen überall. Die Felder bleiben frei beschreibbar,
gespeichert wird nur die Adresse. Ohne importiertes Projekt sind es Textfelder. Die Liste wird beim Öffnen der Seite aus
der Speicherdatei der KNX-Integration gelesen (eine interne Datei: ändert sich ihr Format, entfällt nur die Auswahl).

Der Wert einer Rückmeldung wird bei jeder Änderung gesendet; **Leseanfragen** (GroupValueRead) auf der
Adresse werden mit dem aktuellen Wert beantwortet. Beim Speichern wird geprüft, ob die Adressen gültig sind
(3-Ebenen, 2-Ebenen oder frei) und ob jede Szene mit Favorit oder Lautstärke einen Auslöser hat. Der Favorit
wird als Name gespeichert; bei einem umbenannten Favoriten muss er angepasst werden.

**Frühere Szenen 6–8** werden nicht mehr ausgewertet und beim Speichern der Seite gelöscht.

### Ältere Einträge

Bestehende Einträge laufen unverändert weiter, auch mit mehreren Lautsprecher-Profilen und den früheren
Listen für Befehle und Rückmeldungen. Die neue Seite zeigt dann die Werte des ersten Profils; **beim
Speichern werden weitere Profile verworfen** (ein Hinweis steht auf der Seite), lege sie als eigene Einträge
an. Die älteren Befehle und Rückmeldungen bleiben aktiv, bis du im eingeklappten Abschnitt „Ältere Einträge“
das Löschen wählst (er erscheint nur, wenn es welche gibt).

### Entitäten

- `switch` **Connector aktiv** (aus = keine Befehle und keine Rückmeldungen; beim
  Einschalten werden die Rückmeldungen neu gesendet)
- `sensor` **Letzter Befehl** (Zeitstempel; Attribute: Name des Felds, Adresse, Aktion, Wert)

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
  Runterfahren über eine Zeit). Aus dem Blueprint nicht übernommen: Ein/Aus des Players sowie die
  Erweiterungen für Music Assistant, Squeezebox und Denon.

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
  - *Zu einer Uhrzeit* (Standard): **Uhrzeit** und **Wochentage** (beide ohne Vorgabe, du wählst sie selbst)
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
- optional **Werktags-/Feiertagsbedingungen** mit Binärsensoren (siehe unten)

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

Zur Zeitplanung jedes Weckers (im Wecker-Dialog direkt bei Uhrzeit und Wochentagen) gehören zwei
optionale Bedingungen mit beliebigen **Binärsensoren**, z. B. dem Sensor der Werktags-Integration
von Home Assistant:

- **Nur klingeln, wenn an:** mindestens **einer** der gewählten Sensoren muss an sein (ODER),
  z. B. ein Werktagssensor.
- **Nicht klingeln, wenn an:** sobald **einer** der gewählten Sensoren an ist (ODER), klingelt der
  Wecker nicht, z. B. ein Feiertagssensor oder ein Sensor „arbeitsfrei“.

Beide Felder sind UND-verknüpft und gelten zusätzlich zu den Wochentagen. Die Bedingungen
werden **zur Weckzeit** geprüft. Ein **nicht verfügbarer oder unbekannter** Sensor zählt bei
„Nur klingeln, wenn an“ als erfüllt und blockiert bei „Nicht klingeln, wenn an“ nie; der Wecker
klingelt dann eher einmal zu viel als gar nicht. Ein übersprungener Wecker steht mit Grund und
Sensoren im Attribut `skipped` des Sensors **Letzter Wecker**. Der Sensor **Nächster Wecker** kennt
die Bedingungen nicht (er kann künftige Werktage nicht vorhersagen) und zeigt den nächsten Termin
nach Wochentag und Uhrzeit.

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

## Integrationsmonitor

Überwacht **alle** Integrationen (außer dieser) und kann für **ausgewählte** Integrationen handeln.
Eine Integration gilt als **gestört**, wenn

- ihr Eintrag einen **Fehlerstatus** hat (Setup-Fehler, Wiederholungsversuch, Migrationsfehler,
  Fehler beim Entladen) oder
- **alle** ihre aktiven Entitäten **nicht verfügbar** sind (erst ab einer einstellbaren
  Mindestanzahl Entitäten, damit Integrationen mit nur einer Entität keinen Fehlalarm auslösen).

Eine Störung zählt erst, wenn sie die **Wartezeit** (Standard 5 Minuten) ununterbrochen besteht; kurze
Aussetzer lösen nichts aus. Geprüft wird beim Start (nach zwei Minuten) und dann im **Prüfintervall**
(Standard 1 Minute). Von dir selbst deaktivierte Integrationen werden nie beurteilt oder angefasst.

### Einstellungen

- **Wartezeit**, **Mindestanzahl Entitäten**, **Prüfintervall**
- **Fehlerstatus melden** (Standard an) und **„Alle Entitäten nicht verfügbar“ melden** (Standard aus für neue
  Instanzen), dazu eine Liste **ausgenommener** Integrationen
- **Meldungen bündeln** (Standard 10 Minuten, 0 = sofort)
- die **Benachrichtigungswege** (App-Push, Sprachausgabe, persistente Meldung)

**Sammelmeldung:** Alle Störungen stehen in **einer** Meldung, je Zeile die **Integration**, der Eintrag, die
Art der Störung (bei „nicht verfügbar“ mit Anzahl der Entitäten), seit wann und eine ausgeführte Aktion, z. B.
„• Shelly: shellypmminig3-… – alle 8 Entitäten nicht verfügbar (seit 12:30)“. Sie wird nach der Bündelungszeit
gesendet bzw. aktualisiert (der Push ersetzt den vorigen, es stapeln sich keine) und verschwindet, wenn keine
Störung mehr besteht. Die Sprachausgabe nennt nur die Anzahl. Einzelne „läuft wieder“-Meldungen gibt es nicht.

**Empfehlung:** „Alle Entitäten nicht verfügbar“ ist bei **Einzelgeräten** (Lampen, Steckdosen, Shelly, IKEA,
Batteriegeräte, Drucker, Klimaanlage) oft normal, z. B. bei ausgeschaltetem Wandschalter. Lass die globale
Meldung dafür aus und lege stattdessen eine **Regel mit „Melden“** für Brücken und Dienste an, bei denen ein
Ausfall zählt (MQTT, Zigbee2MQTT, ZHA, KNX, Hue-Bridge, Router und Netzwerkgeräte, Sonos, Wetter u. ä.).

### Regeln

Eine Regel gilt für **eine oder mehrere ausdrücklich gewählte Integrationen** und hat:

- Name und Schalter *Aktiv*
- **Auslöser**: bei Fehlerstatus und/oder wenn alle Entitäten nicht verfügbar sind
- **Aktion**: *Nur melden*, *Neu laden* oder *Deaktivieren* (einmal je Störung), dazu der Schalter
  *Melden* (nimmt die Störung auch dann in die Sammelmeldung auf, wenn die globalen Schalter aus sind)
- optional eine **Anwesenheitsentität** und *Automatisch wieder aktivieren*: Eine vom Monitor
  deaktivierte Integration wird wieder aktiviert, sobald die Anwesenheitsentität „an“ oder „home“
  meldet. Das passt zu Geräten, die zeitweise fehlen (Klimaanlage, Drucker): Die Entität sollte
  unabhängig von der Integration zeigen, ob das Gerät da ist (z. B. ein Ping-Sensor, ein
  Router-Tracker oder eine Steckdose).

Der Monitor aktiviert **nur Integrationen wieder, die er selbst deaktiviert hat**. Schaltest du eine
solche Integration von Hand wieder ein, vergisst er sie.

### Entitäten

- `switch` **Monitor aktiv** (aus = keine Prüfung, keine Meldungen, keine Aktionen)
- `binary_sensor` **Integrationsstörung** (an = mindestens eine Störung; Attribut: Integrationen)
- `sensor` **Integrationen mit Störung** und **Vom Monitor deaktiviert** (Anzahl, Namen als Attribut)
- `button` **Jetzt prüfen** und **Deaktivierte aktivieren** (aktiviert alle vom Monitor
  deaktivierten Integrationen wieder)

## LLM-Verbrauch

Überwacht die **Kosten** eines LLM-API-Kontos (**Anthropic**, **OpenAI**), berechnet daraus ein
**Restguthaben** bzw. **Restbudget** und warnt bei niedrigem Guthaben oder hohem Verbrauch. Je Konto
eine Instanz. Google Gemini ist nicht dabei: Für einen normalen API-Key gibt es keine Kostenabfrage.

**Voraussetzung:** ein **Admin-Key** der Organisation (Anthropic: `sk-ant-admin01-…`, OpenAI: Admin-Key).
Ein normaler API-Key funktioniert nicht. So kommst du an den Key:

- **Anthropic:** Claude Console (`platform.claude.com`) → *Settings → Admin keys* → *Create key*. Das dürfen
  nur Organisations-**Admins**. Ein privater Zugang ohne Organisation hat den Menüpunkt nicht; richte dann
  zuerst unter *Settings → Organization* eine Organisation ein. Ein Abo bei claude.ai (Pro/Max/Team) ist
  etwas anderes. Laut Anthropic-Dokumentation akzeptiert die Kosten-Abfrage auch einen persönlichen oder
  Service-Account-Key, der nicht an einen Workspace gebunden ist; das ist hier nicht getestet (beim Anlegen
  wird der Key mit einer Abfrage geprüft).
- **OpenAI:** `platform.openai.com` → Organisations-Einstellungen → *Admin keys* → *Create new admin key*. Das
  dürfen nur Organisations-**Owner**. Beim Anlegen das Recht für **Nutzung und Kosten** auswählen
  (Admin-Keys gelten nur für die Verwaltungs-Schnittstellen).

Der Admin-Key kann auch Mitglieder und Schlüssel verwalten; bewahre ihn sorgfältig auf. Er liegt wie alle Zugangsdaten **unverschlüsselt** im
Speicher von Home Assistant (die Diagnose schwärzt ihn). Beim Anlegen und beim Ändern wird der Key mit
einer Abfrage geprüft. Schlägt sie fehl, nennt die Meldung die Ursache (HTTP-Status und Meldung des Anbieters oder den
Verbindungsfehler), sie steht auch im Protokoll. Leerzeichen und Zeilenumbrüche am Anfang und Ende des Keys
werden entfernt.

**Wie das Guthaben entsteht:** Die Anbieter liefern nur die **Kosten je Tag** (UTC, mit einigen Stunden
Verzögerung), kein Guthaben. Zwei Modi:

- **Guthaben (mit Abgleich):** Du trägst das aktuelle Guthaben aus der Konsole des Anbieters ein, im Menü
  *Guthaben abgleichen* auch nach jedem Aufladen. Restguthaben = Betrag − Kosten seit dem Abgleich.
- **Monatsbudget:** Restbudget = Betrag − Kosten im laufenden Monat (UTC), am Monatsersten beginnt es neu.

Das Restguthaben ist ein Schätzwert (Steuern, Gratis-Guthaben und Rundungen können abweichen); mit dem
Abgleich holst du es auf den echten Stand zurück. **Bei automatischem Aufladen** stimmt der Modus
„Guthaben“ nicht (die Aufladungen sind in den Kosten nicht sichtbar): dann *Monatsbudget* wählen und mit
Tages-/Monatslimit arbeiten.

### Einstellungen

- **Anbieter**, **Admin-Key**, **Modus** und **Betrag** (nur beim Anlegen wählbar; später Betrag über
  *Guthaben abgleichen* bzw. das Monatsbudget in den Einstellungen)
- **Abfrageintervall** (Standard 60 Minuten)
- **Warnungen** (jeweils leer = aus): **Guthaben unter** einem Betrag, **Tageslimit** und **Monatslimit**
  für die Kosten; dazu **Warnen, wenn die Prognose das Limit übersteigt** (Standard an)
- **Tokens und Anfragen abfragen** (Standard aus; eine weitere Abfrage je Intervall)
- die **Benachrichtigungswege** (App-Push, Sprachausgabe, persistente Meldung)

Jede Warnung kommt **einmal je Überschreitung** (Tageslimit einmal pro Tag, Monatslimit einmal pro
Monat); die Guthabenwarnung meldet eine Entwarnung, sobald das Guthaben wieder über der Grenze liegt.
Die **Prognose** warnt einmal pro Monat, wenn die erwarteten Monatskosten das Monatslimit (im Modus
Monatsbudget das Budget) übersteigen, bevor es tatsächlich überschritten ist.
Schlägt die Abfrage dreimal in Folge fehl, kommt eine Meldung. Wird der Key abgelehnt, kommt sie sofort und
zusätzlich erscheint ein **Reparaturhinweis** (verschwindet, sobald die Abfrage wieder funktioniert).

### Entitäten

- `sensor` **Restguthaben**, **Kosten heute**, **Kosten im Monat**, **Prognose Monatsende** (in der Währung
  des Anbieters, derzeit USD) und **Reichweite** (Tage). Prognose und Reichweite rechnen mit den
  Durchschnittskosten der letzten 7 abgeschlossenen Tage. Den **Verlauf** liefern die Langzeitstatistiken
  des Recorders (Verlaufs- und Statistikdiagramm).
- `sensor` **Tokens heute/im Monat** (Eingabe + Ausgabe; Eingabe, Ausgabe und Cache als Attribute) und, nur bei
  OpenAI, **Anfragen heute/im Monat** – nur mit der Einstellung *Tokens und Anfragen abfragen*
- `binary_sensor` **LLM-Warnung** (an = Warnung aktiv; Attribute: Warnungen, Fehler)
- `switch` **LLM-Abfrage aktiv** und `button` **Jetzt abfragen**

## Reparaturhinweise

Der Hausmeister prüft, ob die in den Einstellungen gewählten Entitäten und Companion-App-Geräte noch existieren. Fehlt eine, erscheint unter **Einstellungen → System → Reparaturen** ein Hinweis (je fehlender Referenz einer, mit Name des Eintrags und der Entität).

- Geprüft werden Sensoren, Schlösser, Player, Schalter, Updates, Sprachausgabe und Push-Geräte aller Funktionen.
- Zeitpunkt: 5 Minuten nach dem Start, danach stündlich sowie kurz nach dem Löschen oder Umbenennen einer Entität bzw. dem Entfernen eines Geräts.
- Nicht verfügbare oder deaktivierte Entitäten gelten als vorhanden.
- Die Hinweise sind nicht automatisch behebbar; sie verschwinden von selbst, sobald die Referenz wieder stimmt (Einstellungen angepasst) oder der Eintrag gelöscht wird.

## IR-Fernbedienung

Sendet Infrarot- (oder Funk-)Befehle über einen oder mehrere **Sender** (`remote`-Entitäten, z. B. Broadlink
RM4 mini) und ersetzt damit Lern- und Sende-Skripte. Die Codes bleiben im Speicher des Senders (bei Broadlink
unter dem **Gerätenamen**, z. B. `candle`); die Funktion lernt sie an, übernimmt vorhandene und sendet sie.

### Einrichtung

Beim Anlegen: Name, **Sender** (mehrere möglich, gesendet wird an alle gleichzeitig), **Gerätename beim
Sender** (bei vorhandenen Skripten der Wert von `device`, lässt sich später nicht ändern), Wiederholungen und
Pause sowie die Benachrichtigung bei Sendefehlern.

### Befehle (Menü)

- **Befehl anlernen:** Name (z. B. „Timer 2h“, „Light +“; daraus wird `timer_2h`, `light_plus`), Art (Infrarot/Funk)
  und die Sender. Je Sender erscheint ein Fortschrittsdialog: Taste der Original-Fernbedienung auf den Sender
  richten und drücken (Zeitlimit etwa 30 Sekunden). Schlägt es an einem Sender fehl, bleiben die erfolgreichen
  gespeichert und die Ursache wird angezeigt.
- **Vorhandene Befehle übernehmen:** Liest bei Broadlink-Sendern die dort schon gespeicherten Befehle des Geräts und
  bietet sie zum Ankreuzen an; weitere Namen kannst du eintippen (dann gilt der Befehl an allen Sendern als
  angelernt). Danach können die alten Lern- und Sende-Skripte gelöscht werden. Die Funktion liest dafür eine
  interne Datei der Broadlink-Integration; bei anderen Sendern oder geändertem Format entfällt die Liste, die
  Handeingabe bleibt.
- **Befehl an Sendern (neu) anlernen** (auch zum Nachlernen an einem weiteren Sender; Codes werden je Sender
  gespeichert und lassen sich nicht kopieren), **Befehl testen**, **bearbeiten** (Anzeigename, aktiv) und
  **löschen** (auf Wunsch auch der Code beim Sender).
- **Schalter (An/Aus):** Optional zwei Befehle (z. B. Power On und Power Off) als Schalter, praktisch für
  Sprachassistenten (Alexa, Google, Siri, Assist). Der Zustand ist nur **angenommen**, die Geräte melden nichts zurück.

### Entitäten und Aktion

- `button` je aktivem Befehl (Name = Befehlsname); gesendet wird nur an Sender, an denen der Befehl angelernt ist.
- `switch` **Schalter** (nur mit gesetzten An-/Aus-Befehlen), `sensor` **Zuletzt gesendet** (Attribute: Befehl, Ergebnis
  `ok`/`partial`/`failed`, Fehler je Sender).
- Aktion `ha_housekeeper.send_ir_command` mit einer Befehlstaste als Ziel und optional abweichenden Wiederholungen.
- Ein ausgeschalteter oder nicht verfügbarer Sender zählt als Fehler und wird gemeldet (die Meldung verschwindet,
  sobald wieder alles gesendet wird). Gelöschte `remote`-Entitäten erzeugen einen Reparaturhinweis.

## Verbrauchswächter

Meldet, wenn ein **Durchfluss** oder eine **Leistung** zu lange am Stück anliegt, zum Beispiel Wasser, das länger
als 15 Minuten läuft (hängende Toilettenspülung, offener Hahn). Eine Instanz überwacht einen Sensor; eine zweite
Regel (z. B. nachts schon nach 2 Minuten) legst du als weitere Instanz an. Es wird nichts geschaltet, nur gemeldet.

### Konfigurationsseite

Alles steht auf **einer Seite** (Anlegen und Zahnrad, der Name ist ein Feld):

- **Sensor** mit Zahlenwert (Durchfluss in l/min, Leistung in W). Zählerstände (Summen) sind nicht geeignet.
- **Schwelle** in der Einheit des Sensors; „läuft“ heißt Wert **größer** als die Schwelle.
- **Dauer** in Minuten (Standard 15): so lange muss der Wert am Stück über der Schwelle liegen.
- **Meldung wiederholen alle … Minuten** (0 = nie).
- **Zeitfenster** (optional, von/bis, auch über Mitternacht): nur dann wird überwacht.
- **Benachrichtigungen:** App-Push, Sprachausgabe, persistente Meldung (mindestens ein Weg).

### Verhalten

- Fällt der Wert vor Ablauf der Dauer auf die Schwelle oder darunter, beginnt die Dauer neu.
- Nach der Dauer gibt es **eine** Meldung (mit Sensor, Schwelle und aktuellem Wert). Fällt der Wert danach wieder
  unter die Schwelle, endet die Warnung von selbst und die Push-Meldung wird entfernt.
- Ist der Sensor nicht verfügbar oder unbekannt, wird die Dauer zurückgesetzt (keine Fehlalarme); eine
  bestehende Warnung bleibt bestehen.
- Außerhalb des Zeitfensters zählt nichts; läuft der Verbrauch beim Fensterbeginn noch, beginnt die Dauer neu,
  am Fensterende endet eine Warnung. Beim Neustart von Home Assistant beginnt die Dauer von vorn.
- Die Prüfung läuft bei jeder Wertänderung und einmal pro Minute; gemeldet wird also bis zu eine Minute nach Ablauf.

### Entitäten

- `binary_sensor` **Verbrauchswarnung** (an = Warnung aktiv; Attribute: Sensor, Schwelle, seit)
- `sensor` **Läuft seit** (Zeitstempel, leer wenn nichts über der Schwelle liegt)
- `button` **Warnung quittieren** (schaltet die Warnung ab und unterdrückt die Wiederholung, bis der Verbrauch einmal
  unter die Schwelle gefallen ist)
- `switch` **Wächter aktiv** (aus = keine Überwachung; beim Einschalten beginnt die Dauer neu)

## Entwicklung

Tests: `pip install pytest-homeassistant-custom-component && pytest`
(Python 3.14). CI: hassfest, HACS-Validierung und pytest.
