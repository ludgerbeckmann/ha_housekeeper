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

## Entwicklung

Tests: `pip install pytest-homeassistant-custom-component && pytest`
(Python 3.13). CI: hassfest, HACS-Validierung und pytest.
