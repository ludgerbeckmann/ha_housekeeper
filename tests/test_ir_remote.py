"""Tests für die Funktion IR-Fernbedienung."""

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from .helpers import is_menu, make_entry, menu_options, new_instance, reconfigure, sectioned
from custom_components.ha_housekeeper import ir_remote
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.issues import collect_references

R1 = "remote.universal_remote"
R2 = "remote.remote_kuche"


def cmd(cid, name, code, remotes=(R1, R2), **over):
    return {"id": cid, "name": name, "code": code, "type": "ir", "enabled": True,
            "remotes": list(remotes), **over}


BASE = {
    "function_type": "ir_remote", "name": "Kerze", "remotes": [R1, R2], "ir_device": "candle",
    "num_repeats": 1, "delay_secs": 0.5,
    "ir_commands": [cmd("c1", "Power On", "power_on"), cmd("c2", "Power Off", "power_off"),
                    cmd("c3", "Timer 2h", "timer_2h", remotes=[R1])],
    "mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
    "tts_enabled": False, "persistent_enabled": False,
}


async def _setup(hass: HomeAssistant, **over):
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    sent = async_mock_service(hass, "remote", "send_command")
    hass.states.async_set(R1, "on")
    hass.states.async_set(R2, "on")
    entry = make_entry(domain=DOMAIN, title="Kerze", data={**BASE, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id], sent, push


def _entity(hass, platform, unique_suffix, entry):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{unique_suffix}")


def test_pure_helpers() -> None:
    assert ir_remote.command_code("Timer 2h") == "timer_2h"
    assert ir_remote.command_code("Light +") == "light_plus"
    assert ir_remote.command_code("Light -") == "light_minus"
    assert ir_remote.command_label("power_on") == "Power On"
    assert ir_remote.command_label("timer_2h") == "Timer 2h"
    assert ir_remote.outcome({"a": None, "b": None}) == "ok"
    assert ir_remote.outcome({"a": None, "b": "x"}) == "partial"
    assert ir_remote.outcome({"a": "x"}) == "failed"
    assert ir_remote.outcome({}) == "failed"


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "ir_remote")
    assert result["step_id"] == "new_ir_remote"
    data = {"remotes": [R1, R2], "ir_device": "candle", "num_repeats": 1, "delay_secs": 0.5,
            "mobile_enabled": False, "tts_enabled": False, "persistent_enabled": True}
    flow = hass.config_entries.subentries
    bad = await flow.async_configure(result["flow_id"], sectioned({**data, "remotes": []}))
    assert bad["errors"] == {"base": "no_remotes"}
    bad = await flow.async_configure(result["flow_id"], sectioned({**data, "ir_device": " "}))
    assert bad["errors"] == {"base": "no_device"}
    ok = await flow.async_configure(result["flow_id"], sectioned({**data, "name": "Kerze"}))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["ir_commands"] == [] and ok["data"]["ir_device"] == "candle"
    assert "name" not in ok["data"]


async def test_button_sends_to_all_known_remotes(hass: HomeAssistant) -> None:
    entry, controller, sent, push = await _setup(hass)
    button = _entity(hass, "button", "ir_c1", entry)
    assert button
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert {c.data["entity_id"] for c in sent} == {R1, R2}
    assert all(c.data["device"] == "candle" and c.data["command"] == ["power_on"] for c in sent)
    last = hass.states.get(_entity(hass, "sensor", "ir_last_sent", entry))
    assert last.attributes["command"] == "Power On" and last.attributes["result"] == "ok"
    # Befehl nur an einem Sender angelernt: nur dort gesendet
    sent.clear()
    only_one = _entity(hass, "button", "ir_c3", entry)
    await hass.services.async_call("button", "press", {"entity_id": only_one}, blocking=True)
    assert [c.data["entity_id"] for c in sent] == [R1]


async def test_partial_failure_notifies(hass: HomeAssistant) -> None:
    entry, controller, sent, push = await _setup(hass)
    hass.states.async_set(R2, "unavailable")
    assert await controller.async_send("c1") == "partial"
    assert [c.data["entity_id"] for c in sent] == [R1]
    assert len(push) == 1 and R2 in push[0].data["message"]
    hass.states.async_set(R1, "off")
    hass.states.async_set(R2, "off")
    assert await controller.async_send("c1") == "failed"
    hass.states.async_set(R1, "on")
    hass.states.async_set(R2, "on")
    push.clear()
    assert await controller.async_send("c1") == "ok"
    assert [c.data["message"] for c in push] == ["clear_notification"]


async def test_send_service_with_repeats(hass: HomeAssistant) -> None:
    entry, controller, sent, push = await _setup(hass)
    button = _entity(hass, "button", "ir_c1", entry)
    await hass.services.async_call(
        DOMAIN, "send_ir_command", {"entity_id": button, "num_repeats": 3}, blocking=True
    )
    assert sent and all(c.data["num_repeats"] == 3 for c in sent)


async def test_power_switch(hass: HomeAssistant) -> None:
    entry, controller, sent, push = await _setup(hass)
    assert _entity(hass, "switch", "ir_power", entry) is None       # ohne Befehle kein Schalter
    entry2, controller2, sent2, _ = await _setup_with_switch(hass)
    switch = _entity(hass, "switch", "ir_power", entry2)
    assert switch
    assert hass.states.get(switch).state == "unknown"
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert sent2[-1].data["command"] == ["power_on"]
    assert hass.states.get(switch).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert sent2[-1].data["command"] == ["power_off"]
    assert hass.states.get(switch).state == "off"
    # Fehlschlag ändert den angenommenen Zustand nicht
    hass.states.async_set(R1, "unavailable")
    hass.states.async_set(R2, "unavailable")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert hass.states.get(switch).state == "off"


async def _setup_with_switch(hass):
    # zweite Instanz in einem eigenen Hub-Test geht nicht; deshalb Einstellungen ändern
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)))
    sub = next(iter(entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        entry, sub, data={**sub.data, "ir_on_command": "c1", "ir_off_command": "c2"}
    )
    await hass.async_block_till_done()
    sent = async_mock_service(hass, "remote", "send_command")
    return type("E", (), {"entry_id": sub.subentry_id})(), hass.data[DOMAIN][sub.subentry_id], sent, None


def test_references() -> None:
    entry = make_entry(domain=DOMAIN, title="Kerze", data=BASE)
    entities, _ = collect_references(entry.sub)
    assert R1 in entities and R2 in entities


async def _flow_menu(hass, entry):
    result = await reconfigure(hass, entry)
    assert is_menu(result)
    return result


async def test_learn_flow_per_remote(hass: HomeAssistant) -> None:
    entry, controller, sent, push = await _setup(hass, ir_commands=[])
    learned = []

    async def _learn(call):
        learned.append(call)
        await asyncio.sleep(0)          # nicht sofort fertig: der Fortschrittsdialog erscheint

    hass.services.async_register("remote", "learn_command", _learn)
    flow = hass.config_entries.subentries
    result = await _flow_menu(hass, entry)
    assert "learn_ir_command" not in menu_options(result)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_ir_command"})
    result = await flow.async_configure(
        result["flow_id"], {"name": "Light +", "type": "ir", "learn_on": [R1, R2]}
    )
    for remote in (R1, R2):                                 # je Sender ein Fortschrittsdialog
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        assert result["progress_action"] == "learn"
        assert result["description_placeholders"]["command"] == "Light +"
        await hass.async_block_till_done()
        result = await flow.async_configure(result["flow_id"])
    assert is_menu(result)
    assert [c.data["entity_id"] for c in learned] == [R1, R2]
    assert learned[0].data["command"] == ["light_plus"] and learned[0].data["device"] == "candle"
    (saved,) = entry.options["ir_commands"]
    assert saved["name"] == "Light +" and saved["code"] == "light_plus"
    assert saved["remotes"] == [R1, R2]
    assert "learn_ir_command" in menu_options(result)


async def test_learn_failure_keeps_successful_remote(hass: HomeAssistant) -> None:
    entry, controller, sent, push = await _setup(hass, ir_commands=[])

    async def _learn(call):
        await asyncio.sleep(0)
        if call.data["entity_id"] == R2:
            raise HomeAssistantError("Timeout")

    hass.services.async_register("remote", "learn_command", _learn)
    flow = hass.config_entries.subentries
    result = await _flow_menu(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_ir_command"})
    result = await flow.async_configure(
        result["flow_id"], {"name": "Mode", "type": "ir", "learn_on": [R1, R2]}
    )
    for _ in range(2):
        await hass.async_block_till_done()
        result = await flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "ir_learn_done"
    assert result["errors"] == {"base": "learn_failed"}
    assert "Timeout" in result["description_placeholders"]["detail"]
    (saved,) = entry.options["ir_commands"]
    assert saved["remotes"] == [R1]
    assert is_menu(await flow.async_configure(result["flow_id"], {}))


async def test_add_command_duplicate(hass: HomeAssistant) -> None:
    entry, *_ = await _setup(hass)
    flow = hass.config_entries.subentries
    result = await _flow_menu(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_ir_command"})
    result = await flow.async_configure(
        result["flow_id"], {"name": "power on", "type": "ir", "learn_on": [R1]}
    )
    assert result["errors"] == {"base": "command_exists"}


async def test_import_from_broadlink_storage(hass: HomeAssistant, hass_storage) -> None:
    er.async_get(hass).async_get_or_create("remote", "broadlink", "aabbcc", suggested_object_id="universal_remote")
    hass_storage["broadlink_remote_aabbcc_codes"] = {
        "version": 1, "minor_version": 1, "key": "broadlink_remote_aabbcc_codes",
        "data": {"candle": {"power_on": "x", "timer_2h": "y", "light_minus": "z"}, "other": {"a": "b"}},
    }
    entry, *_ = await _setup(hass, ir_commands=[cmd("c1", "Power On", "power_on", remotes=[R1])])
    assert await ir_remote.async_stored_codes(hass, R1, "candle") == {"power_on", "timer_2h", "light_minus"}
    assert await ir_remote.async_stored_codes(hass, R2, "candle") == set()
    flow = hass.config_entries.subentries
    result = await _flow_menu(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "import_ir_commands"})
    assert result["step_id"] == "import_ir_commands"
    assert result["description_placeholders"]["found"] == "2"   # power_on ist schon vorhanden
    result = await flow.async_configure(result["flow_id"], {"codes": ["timer_2h", "light_minus", "Mode Candle"]})
    assert is_menu(result)
    by_code = {c["code"]: c for c in entry.options["ir_commands"]}
    assert by_code["timer_2h"]["name"] == "Timer 2h" and by_code["timer_2h"]["remotes"] == [R1]
    assert by_code["light_minus"]["name"] == "Light Minus"
    assert by_code["mode_candle"]["remotes"] == [R1, R2]        # von Hand: an allen Sendern angenommen


def _page(**over):
    """Eingaben der Einstellungsseite, verteilt auf die Abschnitte."""
    commands = {"active_commands": ["c1", "c2", "c3"], "delete_commands": [], "delete_codes": True}
    switch = {}
    general = {"name": "Kerze", "remotes": [R1, R2], "num_repeats": 1, "delay_secs": 0.5}
    for key, value in over.items():
        if key in commands:
            commands[key] = value
        elif key in ("ir_on_command", "ir_off_command"):
            switch[key] = value
        else:
            general[key] = value
    return {"general": general, "commands": commands, "switch": switch,
            "notifications": {"mobile_enabled": False, "tts_enabled": False, "persistent_enabled": False}}


async def _open_page(hass, entry):
    result = await _flow_menu(hass, entry)
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "ir_settings"}
    )


async def test_settings_page_switch_and_delete(hass: HomeAssistant) -> None:
    entry, *_ = await _setup(hass)
    deleted = async_mock_service(hass, "remote", "delete_command")
    flow = hass.config_entries.subentries
    result = await _open_page(hass, entry)
    assert result["step_id"] == "ir_settings"
    assert list(result["data_schema"].schema) == ["general", "commands", "switch", "notifications"]
    bad = await flow.async_configure(result["flow_id"], _page(ir_on_command="c1"))
    assert bad["errors"] == {"base": "switch_incomplete"}
    result = await _open_page(hass, entry)
    bad = await flow.async_configure(result["flow_id"], _page(ir_on_command="c1", ir_off_command="c1"))
    assert bad["errors"] == {"base": "switch_same"}
    result = await _open_page(hass, entry)
    bad = await flow.async_configure(
        result["flow_id"],
        _page(ir_on_command="c1", ir_off_command="c2", delete_commands=["c1"]),
    )
    assert bad["errors"] == {"base": "command_in_use"}
    result = await _open_page(hass, entry)
    done = await flow.async_configure(
        result["flow_id"],
        _page(ir_on_command="c1", ir_off_command="c2", delete_commands=["c3"], active_commands=["c1", "c2"]),
    )
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "reconfigure_successful"
    assert entry.options["ir_on_command"] == "c1"
    assert [c["id"] for c in entry.options["ir_commands"]] == ["c1", "c2"]
    assert [(c.data["entity_id"], c.data["command"]) for c in deleted] == [(R1, ["timer_2h"])]


async def test_settings_page_deactivates_command_and_removes_button(hass: HomeAssistant) -> None:
    entry, *_ = await _setup(hass)
    assert _entity(hass, "button", "ir_c3", entry)
    result = await _open_page(hass, entry)
    done = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _page(active_commands=["c1", "c2"], num_repeats=3)
    )
    assert done["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    saved = {c["id"]: c for c in entry.options["ir_commands"]}
    assert saved["c3"]["enabled"] is False and saved["c1"]["enabled"] is True
    assert entry.options["num_repeats"] == 3
    assert _entity(hass, "button", "ir_c3", entry) is None


async def test_b64_for_remotes_without_stored_code(hass: HomeAssistant) -> None:
    cmds = [cmd("c1", "Power On", "power_on", remotes=[R1, R2], learned=[R1], b64="AAAA")]
    entry, controller, sent, push = await _setup(hass, ir_commands=cmds)
    assert await controller.async_send("c1") == "ok"
    by_remote = {c.data["entity_id"]: c.data["command"] for c in sent}
    assert by_remote == {R1: ["power_on"], R2: ["b64:AAAA"]}


async def test_per_remote_buttons_and_switches(hass: HomeAssistant) -> None:
    cmds = [cmd("c1", "Power On", "power_on"), cmd("c2", "Power Off", "power_off"),
            cmd("c3", "Timer 2h", "timer_2h", remotes=[R1])]
    entry, controller, sent, push = await _setup(
        hass, ir_commands=cmds, ir_on_command="c1", ir_off_command="c2"
    )
    reg = er.async_get(hass)
    uid = lambda c, r: f"{entry.entry_id}_ir_{c}_{r.replace('.', '_')}"        # noqa: E731
    r1_button = reg.async_get_entity_id("button", DOMAIN, uid("c1", R1))
    assert r1_button and reg.async_get_entity_id("button", DOMAIN, uid("c1", R2))
    assert reg.async_get_entity_id("button", DOMAIN, uid("c3", R1))
    assert reg.async_get_entity_id("button", DOMAIN, uid("c3", R2)) is None     # R2 hat den Befehl nicht
    await hass.services.async_call("button", "press", {"entity_id": r1_button}, blocking=True)
    assert [c.data["entity_id"] for c in sent] == [R1]                          # nur dieser Sender
    sent.clear()
    await hass.services.async_call("button", "press", {"entity_id": _entity(hass, "button", "ir_c1", entry)}, blocking=True)
    assert {c.data["entity_id"] for c in sent} == {R1, R2}                      # Taste für alle
    sent.clear()
    sw2 = reg.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_ir_power_{R2.replace('.', '_')}")
    assert sw2
    await hass.services.async_call("switch", "turn_on", {"entity_id": sw2}, blocking=True)
    assert [c.data["entity_id"] for c in sent] == [R2]
    assert hass.states.get(sw2).state == "on"
    sw1 = reg.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_ir_power_{R1.replace('.', '_')}")
    assert hass.states.get(sw1).state == "unknown"                              # Sender getrennt


async def _assign(hass, entry, remote, **form):
    flow = hass.config_entries.subentries
    result = await _flow_menu(hass, entry)
    assert "ir_assign" in menu_options(result)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "ir_assign"})
    result = await flow.async_configure(result["flow_id"], {"remote": remote})
    assert result["step_id"] == "ir_assign_edit"
    return await flow.async_configure(result["flow_id"], form)


async def test_assign_takes_code_from_broadlink_storage(hass: HomeAssistant, hass_storage) -> None:
    er.async_get(hass).async_get_or_create("remote", "broadlink", "aabbcc", suggested_object_id="universal_remote")
    hass_storage["broadlink_remote_aabbcc_codes"] = {
        "version": 1, "minor_version": 1, "key": "broadlink_remote_aabbcc_codes",
        "data": {"candle": {"timer_2h": "QkJC"}},
    }
    entry, controller, sent, push = await _setup(hass)
    # c3 ist nur an R1 angelernt: R2 zuordnen, der Code wird aus dem Speicher von R1 gelesen
    done = await _assign(hass, entry, R2, commands=["c1", "c2", "c3"])
    assert is_menu(done)
    await hass.async_block_till_done()
    saved = {c["id"]: c for c in entry.options["ir_commands"]}
    assert saved["c3"]["remotes"] == [R1, R2] and saved["c3"]["b64"] == "QkJC"
    sent.clear()
    controller = next(iter(hass.data[DOMAIN].values()))
    assert await controller.async_send("c3") == "ok"
    assert {c.data["entity_id"]: c.data["command"] for c in sent} == {R1: ["timer_2h"], R2: ["b64:QkJC"]}


async def test_assign_without_readable_code_and_unassign(hass: HomeAssistant) -> None:
    entry, *_ = await _setup(hass)
    bad = await _assign(hass, entry, R2, commands=["c1", "c2", "c3"])           # kein Code lesbar
    assert bad["errors"] == {"base": "code_unavailable"}
    assert bad["description_placeholders"]["commands"] == "Timer 2h"
    # Befehl dem Sender entziehen
    done = await _assign(hass, entry, R2, commands=["c1"])
    assert is_menu(done)
    saved = {c["id"]: c for c in entry.options["ir_commands"]}
    assert saved["c1"]["remotes"] == [R1, R2] and saved["c2"]["remotes"] == [R1]


async def test_assign_all_commands_and_clear_old_groups(hass: HomeAssistant) -> None:
    entry, *_ = await _setup(hass, ir_groups=[{"id": "g", "name": "Kerze", "commands": ["c1"]}], ir_commands=[
        cmd("c1", "Power On", "power_on", remotes=[R1], b64="AA"),
        cmd("c2", "Power Off", "power_off", remotes=[R1], b64="BB"),
        cmd("c3", "Timer 2h", "timer_2h", remotes=[R1], b64="CC"),
    ])
    result = await _flow_menu(hass, entry)
    assert "ir_groups" not in menu_options(result)
    done = await _assign(hass, entry, R2, commands=[], all_commands=True)
    assert is_menu(done)
    saved = {c["id"]: c for c in entry.options["ir_commands"]}
    assert all(c["remotes"] == [R1, R2] for c in saved.values())
    assert entry.options["ir_groups"] is None                    # frühere Gruppen werden entfernt
