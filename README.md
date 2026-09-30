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
bis er zurückgesetzt wird. Solange Post vorhanden ist, gibt es keine erneute
Meldung.

### Einstellungen

- **Vibrationssensor** (`binary_sensor`)
- **App-Push**: ein oder mehrere `notify.mobile_app_*`-Dienste. Optional mit
  der **Aktion „Briefkasten geleert“** direkt in der Meldung (iOS und
  Android): Tippen/Halten auf die Meldung zeigt den Knopf, der den
  Briefkasten zurücksetzt und die Meldung wieder entfernt.
- **Sprachausgabe**: TTS-Dienst + Lautsprecher (`media_player`)
- **Persistente Benachrichtigung** in Home Assistant
- **Nachrichtentext**, **Entprellzeit** (Standard 60 s; weitere Vibrationen
  in dieser Zeit werden ignoriert), **Auto-Reset** nach X Stunden (0 = aus)

Alle Einstellungen lassen sich später über *Konfigurieren* ändern.

### Entitäten

- `binary_sensor` **Post vorhanden**
- `sensor` **Letzter Posteinwurf** (Zeitstempel)
- `button` **Briefkasten geleert**

Der Zustand bleibt über Neustarts erhalten.

## Entwicklung

Tests: `pip install pytest-homeassistant-custom-component && pytest`
(Python 3.13). CI: hassfest, HACS-Validierung und pytest.
