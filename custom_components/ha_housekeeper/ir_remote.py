"""Logik der Funktion "IR-Fernbedienung": Befehle anlernen und über `remote`-Entitäten senden."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_IR_COMMANDS,
    CONF_IR_DELAY,
    CONF_IR_DEVICE,
    CONF_IR_OFF,
    CONF_IR_ON,
    CONF_IR_REPEATS,
    CONF_REMOTES,
    DEFAULT_IR_DELAY,
    DEFAULT_IR_REPEATS,
    DOMAIN,
    IC_CODE,
    IC_ENABLED,
    IC_ID,
    IC_NAME,
    IC_REMOTES,
    signal_update,
)
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
BROADLINK = "broadlink"

_TEXT = {
    "de": {
        "failed": "„{title}“: „{command}“ konnte nicht gesendet werden ({details}).",
        "partial": "„{title}“: „{command}“ wurde nicht an alle Sender gesendet ({details}).",
        "no_remote": "kein Sender mit diesem Befehl",
        STATE_UNAVAILABLE: "nicht verfügbar",
        STATE_OFF: "ausgeschaltet",
    },
    "en": {
        "failed": "\"{title}\": \"{command}\" could not be sent ({details}).",
        "partial": "\"{title}\": \"{command}\" was not sent to all remotes ({details}).",
        "no_remote": "no remote knows this command",
        STATE_UNAVAILABLE: "unavailable",
        STATE_OFF: "turned off",
    },
}


# --- reine Funktionen ------------------------------------------------------------------------


def command_code(name: str) -> str:
    """Befehlsname beim Sender aus dem Anzeigenamen: „Timer 2h“ wird `timer_2h`, „Light +“ `light_plus`."""
    return slugify(name.replace("+", " plus ").replace("-", " minus "))


def command_label(code: str) -> str:
    """Anzeigename zu einem vorhandenen Befehlsnamen: `power_on` wird „Power On“."""
    return " ".join(word.capitalize() for word in code.split("_") if word)


def outcome(errors: dict[str, str | None]) -> str:
    """`ok`, `partial` oder `failed` aus den Fehlern je Sender."""
    failed = [r for r, err in errors.items() if err]
    if not errors or len(failed) == len(errors):
        return "failed"
    return "partial" if failed else "ok"


# --- Zugriff auf die `remote`-Entitäten --------------------------------------------------------


def _remote_problem(hass: HomeAssistant, remote: str) -> str | None:
    """Zustand der Sender-Entität: `unavailable`/`off`, sonst `None` (sendebereit)."""
    state = hass.states.get(remote)
    if state is None or state.state == STATE_UNAVAILABLE:
        return STATE_UNAVAILABLE
    if state.state == STATE_OFF:
        return STATE_OFF
    return None


async def async_send(
    hass: HomeAssistant,
    remotes: list[str],
    device: str,
    code: str,
    repeats: int = DEFAULT_IR_REPEATS,
    delay: float = DEFAULT_IR_DELAY,
) -> dict[str, str | None]:
    """Befehl gleichzeitig an alle Sender schicken; je Sender `None` oder der Fehler."""

    async def _one(remote: str) -> str | None:
        if problem := _remote_problem(hass, remote):
            return problem
        try:
            await hass.services.async_call(
                "remote",
                "send_command",
                {
                    "entity_id": remote,
                    "device": device,
                    "command": [code],
                    "num_repeats": repeats,
                    "delay_secs": delay,
                },
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: Senden von %s/%s fehlgeschlagen: %s", remote, device, code, err)
            return str(err) or type(err).__name__
        return None

    results = await asyncio.gather(*(_one(remote) for remote in remotes))
    return dict(zip(remotes, results, strict=True))


async def async_learn(
    hass: HomeAssistant, remote: str, device: str, code: str, command_type: str
) -> None:
    """Befehl am Sender anlernen (wartet, bis die Taste gedrückt wurde oder das Zeitlimit abläuft)."""
    await hass.services.async_call(
        "remote",
        "learn_command",
        {
            "entity_id": remote,
            "device": device,
            "command": [code],
            "command_type": command_type,
        },
        blocking=True,
    )


async def async_delete(hass: HomeAssistant, remote: str, device: str, code: str) -> None:
    """Gespeicherten Code beim Sender löschen; Fehler werden nur protokolliert."""
    try:
        await hass.services.async_call(
            "remote",
            "delete_command",
            {"entity_id": remote, "device": device, "command": [code]},
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("%s: Löschen von %s/%s fehlgeschlagen: %s", remote, device, code, err)


async def async_stored_codes(hass: HomeAssistant, remote: str, device: str) -> set[str]:
    """Bereits angelernte Befehle eines Geräts aus dem Speicher der Broadlink-Integration.

    Liest deren interne Datei (`broadlink_remote_<id>_codes`); bei anderen Sendern oder einem
    geänderten Format ist das Ergebnis leer (dann werden die Namen von Hand eingegeben)."""
    entity = er.async_get(hass).async_get(remote)
    if entity is None or entity.platform != BROADLINK:
        return set()
    data = await Store(hass, 1, f"broadlink_remote_{entity.unique_id}_codes").async_load()
    codes = data.get(device) if isinstance(data, dict) else None
    return set(codes) if isinstance(codes, dict) else set()


# --- Controller --------------------------------------------------------------------------------


class IrRemoteController:
    """Sendet die angelernten Befehle an alle Sender der Instanz."""

    model = "IR-Fernbedienung"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.last_sent: dict[str, Any] | None = None
        self.assumed_on: bool | None = None
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", lambda: entry.title
        )

    # --- Hilfen ------------------------------------------------------------

    @property
    def _lang(self) -> str:
        return "de" if (self.hass.config.language or "").startswith("de") else "en"

    @property
    def remotes(self) -> list[str]:
        return list(self._get(CONF_REMOTES, []) or [])

    @property
    def device(self) -> str:
        return self._get(CONF_IR_DEVICE, "") or ""

    @property
    def commands(self) -> list[dict[str, Any]]:
        return list(self._get(CONF_IR_COMMANDS, []) or [])

    @property
    def active_commands(self) -> list[dict[str, Any]]:
        return [c for c in self.commands if c.get(IC_ENABLED, True)]

    def command(self, command_id: str | None) -> dict[str, Any] | None:
        return next((c for c in self.commands if c[IC_ID] == command_id), None)

    def remotes_for(self, command: dict[str, Any]) -> list[str]:
        """Sender der Instanz, an denen der Befehl angelernt ist."""
        known = command.get(IC_REMOTES) or []
        return [r for r in self.remotes if r in known]

    @property
    def power_configured(self) -> bool:
        return bool(
            self.command(self._get(CONF_IR_ON)) and self.command(self._get(CONF_IR_OFF))
        )

    def _notify_dispatch(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"last_sent": self.last_sent, "assumed_on": self.assumed_on}
        )

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.last_sent = stored.get("last_sent")
        self.assumed_on = stored.get("assumed_on")

    def async_stop(self) -> None:
        """Nichts zu beenden (kein Zustand im Speicher)."""

    # --- Senden --------------------------------------------------------------

    def _reason(self, error: str) -> str:
        return _TEXT[self._lang].get(error, error)

    async def async_send(self, command_id: str, repeats: int | None = None) -> str:
        """Befehl senden; Ergebnis `ok`, `partial` oder `failed`."""
        command = self.command(command_id)
        if command is None:
            return "failed"
        remotes = self.remotes_for(command)
        if remotes:
            errors = await async_send(
                self.hass,
                remotes,
                self.device,
                command[IC_CODE],
                int(repeats or self._get(CONF_IR_REPEATS, DEFAULT_IR_REPEATS)),
                float(self._get(CONF_IR_DELAY, DEFAULT_IR_DELAY)),
            )
        else:
            errors = {"": "no_remote"}
        result = outcome(errors)
        self.last_sent = {
            "time": dt_util.utcnow().isoformat(),
            "command": command[IC_NAME],
            "result": result,
            "errors": {r: e for r, e in errors.items() if e},
        }
        await self._async_save()
        self._notify_dispatch()
        if result == "ok":
            await self._notifier.async_clear("error")
        else:
            details = ", ".join(
                f"{remote}: {self._reason(error)}" if remote else self._reason(error)
                for remote, error in errors.items()
                if error
            )
            await self._notifier.async_send(
                _TEXT[self._lang][result].format(
                    title=self.entry.title, command=command[IC_NAME], details=details
                ),
                kind="error",
            )
        return result

    async def async_set_power(self, on: bool) -> None:
        """Schalter: den Befehl „an“ bzw. „aus“ senden und den angenommenen Zustand merken."""
        command_id = self._get(CONF_IR_ON if on else CONF_IR_OFF)
        if await self.async_send(command_id) != "failed":
            self.assumed_on = on
            await self._async_save()
            self._notify_dispatch()
