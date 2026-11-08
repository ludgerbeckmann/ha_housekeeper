"""Logik der Funktion "IR-Fernbedienung": Befehle anlernen und über `remote`-Entitäten senden."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from datetime import datetime, timedelta

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_sunset,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_IR_AUTO,
    CONF_IR_COMMANDS,
    CONF_IR_DELAY,
    CONF_IR_DEVICE,
    CONF_IR_OFF,
    CONF_IR_ON,
    CONF_IR_REPEATS,
    CONF_REMOTES,
    DEFAULT_IA_OFF_DELAY,
    DEFAULT_IR_DELAY,
    DEFAULT_IR_REPEATS,
    DOMAIN,
    IA_LATEST_OFF,
    IA_LIGHTS,
    IA_OFF_DELAY,
    IA_OFFSET,
    IC_CODE,
    IC_B64,
    IC_ENABLED,
    IC_ID,
    IC_LEARNED,
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
    b64: str | None = None,
    native: list[str] | None = None,
) -> dict[str, str | None]:
    """Befehl gleichzeitig an alle Sender schicken; je Sender `None` oder der Fehler.

    Sender, bei denen der Code nicht unter seinem Namen gespeichert ist (nicht in `native`),
    bekommen ihn als `b64:`-Code (nur wenn `b64` bekannt ist)."""

    async def _one(remote: str) -> str | None:
        if problem := _remote_problem(hass, remote):
            return problem
        command = code
        if b64 and native is not None and remote not in native:
            command = f"b64:{b64}"
        try:
            await hass.services.async_call(
                "remote",
                "send_command",
                {
                    "entity_id": remote,
                    "device": device,
                    "command": [command],
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


async def _stored(hass: HomeAssistant, remote: str, device: str) -> dict[str, Any]:
    """Codes eines Geräts aus dem Speicher der Broadlink-Integration (leer bei anderen Sendern)."""
    entity = er.async_get(hass).async_get(remote)
    if entity is None or entity.platform != BROADLINK:
        return {}
    data = await Store(hass, 1, f"broadlink_remote_{entity.unique_id}_codes").async_load()
    codes = data.get(device) if isinstance(data, dict) else None
    return codes if isinstance(codes, dict) else {}


async def async_stored_codes(hass: HomeAssistant, remote: str, device: str) -> set[str]:
    """Bereits angelernte Befehle eines Geräts aus dem Speicher der Broadlink-Integration.

    Liest deren interne Datei (`broadlink_remote_<id>_codes`); bei anderen Sendern oder einem
    geänderten Format ist das Ergebnis leer (dann werden die Namen von Hand eingegeben)."""
    return set(await _stored(hass, remote, device))


async def async_stored_code(
    hass: HomeAssistant, remotes: list[str], device: str, code: str
) -> str | None:
    """Base64-Code eines Befehls vom ersten Sender, der ihn gespeichert hat (sonst `None`)."""
    for remote in remotes:
        value = (await _stored(hass, remote, device)).get(code)
        if isinstance(value, str) and value:
            return value
    return None


# --- Controller --------------------------------------------------------------------------------


class IrRemoteController:
    """Sendet die angelernten Befehle an alle Sender der Instanz."""

    model = "IR-Fernbedienung"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.last_sent: dict[str, Any] | None = None
        self.assumed_on: bool | None = None
        self.assumed_remote: dict[str, bool] = {}
        self.auto_off: set[str] = set()                   # Sender, deren Automatik ausgeschaltet ist
        self._lights_on: dict[str, bool] = {}
        self._off_timers: dict[str, Any] = {}
        self._unsubs: list = []
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
        """Sender der Instanz, denen der Befehl zugeordnet ist."""
        known = command.get(IC_REMOTES) or []
        return [r for r in self.remotes if r in known]

    def native_remotes(self, command: dict[str, Any]) -> list[str]:
        """Sender, bei denen der Code unter seinem Namen gespeichert ist (ältere Befehle: alle zugeordneten)."""
        learned = command.get(IC_LEARNED)
        return list(command.get(IC_REMOTES) or []) if learned is None else list(learned)

    def remote_name(self, remote: str) -> str:
        state = self.hass.states.get(remote)
        return state.name if state else remote

    @property
    def power_configured(self) -> bool:
        return bool(
            self.command(self._get(CONF_IR_ON)) and self.command(self._get(CONF_IR_OFF))
        )

    def _notify_dispatch(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "last_sent": self.last_sent,
                "assumed_on": self.assumed_on,
                "assumed_remote": self.assumed_remote,
                "auto_off": sorted(self.auto_off),
            }
        )

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.last_sent = stored.get("last_sent")
        self.assumed_on = stored.get("assumed_on")
        self.assumed_remote = dict(stored.get("assumed_remote") or {})
        self.auto_off = set(stored.get("auto_off") or [])
        self._start_auto()

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._off_timers.values():
            unsub()
        self._off_timers.clear()

    # --- Automatik: Kerzen nach Licht und Sonnenuntergang ---------------------------

    def auto_rules(self) -> dict[str, dict[str, Any]]:
        """Automatik je Sender (nur mit Lichtern und gesetzten An-/Aus-Befehlen)."""
        if not self.power_configured:
            return {}
        rules = self._get(CONF_IR_AUTO, {}) or {}
        return {
            remote: rule
            for remote, rule in rules.items()
            if remote in self.remotes and rule.get(IA_LIGHTS)
        }

    def auto_enabled(self, remote: str) -> bool:
        return remote not in self.auto_off

    async def async_set_auto(self, remote: str, enabled: bool) -> None:
        if enabled:
            self.auto_off.discard(remote)
        else:
            self.auto_off.add(remote)
        await self._async_save()
        self._notify_dispatch()

    def _lights_state(self, remote: str) -> bool | None:
        """`True` = mindestens ein Licht an, `False` = alle eindeutig aus, `None` = unklar."""
        states = [self.hass.states.get(e) for e in self.auto_rules()[remote][IA_LIGHTS]]
        if any(s is not None and s.state == "on" for s in states):
            return True
        if all(s is not None and s.state == "off" for s in states):
            return False
        return None

    def _is_dark(self, rule: dict[str, Any]) -> bool:
        """Nach Sonnenuntergang (plus Versatz) oder vor Sonnenaufgang."""
        now = dt_util.now()
        sunset = get_astral_event_date(self.hass, "sunset", now.date())
        sunrise = get_astral_event_date(self.hass, "sunrise", now.date())
        if sunset is None or sunrise is None:
            sun = self.hass.states.get("sun.sun")
            return sun is not None and sun.state == "below_horizon"
        offset = timedelta(minutes=float(rule.get(IA_OFFSET) or 0))
        return now >= sunset + offset or now < sunrise

    def _start_auto(self) -> None:
        rules = self.auto_rules()
        if not rules:
            return
        lights = sorted({e for rule in rules.values() for e in rule[IA_LIGHTS]})
        for remote in rules:
            self._lights_on[remote] = bool(self._lights_state(remote))     # beim Start: so wie die Lichter stehen
        self._unsubs.append(async_track_state_change_event(self.hass, lights, self._on_light_change))
        for remote, rule in rules.items():
            async def _sunset(remote=remote) -> None:
                if self.auto_enabled(remote) and self._lights_state(remote):
                    self._lights_on[remote] = True
                    await self.async_set_power(True, remote)

            @callback
            def _on_sunset(remote=remote, _sunset=_sunset) -> None:
                self.hass.async_create_task(_sunset(remote))

            self._unsubs.append(
                async_track_sunset(
                    self.hass, _on_sunset, timedelta(minutes=float(rule.get(IA_OFFSET) or 0))
                )
            )
            if latest := dt_util.parse_time(str(rule.get(IA_LATEST_OFF) or "")):
                async def _latest(_now: datetime, remote=remote) -> None:
                    if self.auto_enabled(remote):
                        self._cancel_off(remote)
                        self._lights_on[remote] = False
                        await self.async_set_power(False, remote)

                self._unsubs.append(
                    async_track_time_change(
                        self.hass, _latest, hour=latest.hour, minute=latest.minute, second=0
                    )
                )

    def _cancel_off(self, remote: str) -> None:
        if unsub := self._off_timers.pop(remote, None):
            unsub()

    async def _on_light_change(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        for remote, rule in self.auto_rules().items():
            if entity_id not in rule[IA_LIGHTS] or not self.auto_enabled(remote):
                continue
            state = self._lights_state(remote)
            if state is None:
                continue                                  # unklar: nichts ändern
            on_now = self._lights_on.get(remote, False)     # die Automatik hat die Kerzen eingeschaltet
            if state:
                self._cancel_off(remote)
                if not on_now and self._is_dark(rule):
                    self._lights_on[remote] = True
                    await self.async_set_power(True, remote)
            elif on_now and remote not in self._off_timers:
                delay = float(rule.get(IA_OFF_DELAY, DEFAULT_IA_OFF_DELAY) or 0)
                if delay <= 0:
                    self._lights_on[remote] = False
                    await self.async_set_power(False, remote)
                else:
                    self._off_timers[remote] = async_call_later(
                        self.hass, delay * 60, self._make_off(remote)
                    )

    def _make_off(self, remote: str):
        async def _off(_now: datetime) -> None:
            self._off_timers.pop(remote, None)
            if self.auto_enabled(remote) and self._lights_state(remote) is False:
                self._lights_on[remote] = False
                await self.async_set_power(False, remote)

        return _off

    # --- Senden --------------------------------------------------------------

    def _reason(self, error: str) -> str:
        return _TEXT[self._lang].get(error, error)

    async def async_send(
        self, command_id: str, repeats: int | None = None, remote: str | None = None
    ) -> str:
        """Befehl senden (an alle zugeordneten Sender oder nur an `remote`); Ergebnis `ok`, `partial` oder `failed`."""
        command = self.command(command_id)
        if command is None:
            return "failed"
        remotes = self.remotes_for(command)
        if remote is not None:
            remotes = [r for r in remotes if r == remote]
        if remotes:
            errors = await async_send(
                self.hass,
                remotes,
                self.device,
                command[IC_CODE],
                int(repeats or self._get(CONF_IR_REPEATS, DEFAULT_IR_REPEATS)),
                float(self._get(CONF_IR_DELAY, DEFAULT_IR_DELAY)),
                command.get(IC_B64),
                self.native_remotes(command),
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

    async def async_set_power(self, on: bool, remote: str | None = None) -> None:
        """Schalter: den Befehl „an“ bzw. „aus“ senden (an alle oder nur an `remote`) und den angenommenen Zustand merken."""
        command_id = self._get(CONF_IR_ON if on else CONF_IR_OFF)
        if await self.async_send(command_id, remote=remote) != "failed":
            if remote is None:
                self.assumed_on = on
                self.assumed_remote = {r: on for r in self.remotes}
            else:
                self.assumed_remote[remote] = on
            await self._async_save()
            self._notify_dispatch()
