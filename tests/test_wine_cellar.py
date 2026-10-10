"""Runs the integration in a real Home Assistant against a fake hOn cloud.

The fake cloud never applies sent commands to its state, like the real cloud for
the first seconds after a write, so the tests also cover stale reads.
"""
import asyncio
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hon.api import HonApi
from custom_components.hon.diagnostics import async_get_config_entry_diagnostics

RANGE_0_1 = {"typology": "range", "minimumValue": "0", "maximumValue": "1", "incrementValue": "1"}
RANGE_5_20 = {"typology": "range", "minimumValue": "5", "maximumValue": "20", "incrementValue": "1"}
CELLAR = {
    "macAddress": "aa-bb-cc", "applianceTypeName": "WC", "applianceTypeId": 6, "code": "1",
    "applianceModelId": 1, "eepromId": 1, "fwVersion": "5.12.0", "modelName": "HWS77GDAU1",
    "brand": "haier", "nickName": "Wine Cellar",
}
COMMANDS = {
    "resultCode": "0",
    "applianceModel": {"options": {}},
    "settings": {"parameters": {
        "lightStatus": RANGE_0_1, "tempSelZ1": RANGE_5_20, "tempSelZ2": RANGE_5_20,
        "tempUnit": RANGE_0_1, "machMode": {"typology": "fixed", "fixedValue": "1"},
    }},
}

LIGHT = "light.wine_cellar_light"
ZONE1_TARGET = "number.wine_cellar_zone_1_target_temperature"
ZONE2_TARGET = "number.wine_cellar_zone_2_target_temperature"


@pytest.fixture
def cloud(enable_custom_integrations):
    state = {"lightStatus": "0", "tempSelZ1": "17", "tempSelZ2": "9", "tempZ1": "16.5", "tempZ2": "9", "tempUnit": "0"}
    sent = []

    async def get_context(self, appliance):
        await asyncio.sleep(0)  # yield like real network I/O, so concurrent writes overlap
        return {
            "shadow": {"parameters": {k: {"parNewVal": v} for k, v in state.items()}},
            "lastConnEvent": {"category": "CONNECTED"},
        }

    async def send_command(self, appliance, options, command, parameters, ancillary):
        await asyncio.sleep(0)
        sent.append((command, parameters))

    async def noop(self, *args):
        pass

    async def appliances(self):
        return [CELLAR, {"macAddress": "dd", "applianceTypeName": "WM"}]

    async def commands(self, appliance):
        return COMMANDS

    with patch.multiple(
        HonApi, login=noop, get_appliances=appliances, get_commands=commands,
        get_context=get_context, send_command=send_command,
    ):
        yield state, sent


async def test_wine_cellar(hass, cloud):
    state, sent = cloud
    entry = MockConfigEntry(domain="hon", unique_id="me@example.com", data={"email": "me@example.com", "password": "x"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Only the cellar's entities, with the zones read from the cloud
    assert sorted(hass.states.async_entity_ids()) == [
        LIGHT, ZONE1_TARGET, ZONE2_TARGET,
        "sensor.wine_cellar_zone_1_temperature", "sensor.wine_cellar_zone_2_temperature",
    ]
    assert hass.states.get(LIGHT).state == "off"
    assert hass.states.get(ZONE1_TARGET).state == "17.0"
    assert hass.states.get("sensor.wine_cellar_zone_1_temperature").state == "16.5"

    async def call(domain, service, entity_id, **data):
        await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)

    # Light on: both zones re-sent exactly as they are
    await call("light", "turn_on", LIGHT)
    assert sent[-1] == ("settings", {"lightStatus": "1", "tempSelZ1": "17", "tempSelZ2": "9", "tempUnit": "0", "machMode": "1"})
    assert hass.states.get(LIGHT).state == "on"

    # Zone 2 change while the cloud still says the light is off: the light stays on
    await call("number", "set_value", ZONE2_TARGET, value=10)
    assert sent[-1][1] == {"lightStatus": "1", "tempSelZ1": "17", "tempSelZ2": "10", "tempUnit": "0", "machMode": "1"}

    # Zone 1 changed in the hOn app since the last poll: the light command keeps the app's value
    state["tempSelZ1"] = "15"
    await call("light", "turn_off", LIGHT)
    assert sent[-1][1]["tempSelZ1"] == "15"

    # A scene changing light and a zone at once: the later write carries both
    await asyncio.gather(
        call("light", "turn_on", LIGHT),
        call("number", "set_value", ZONE1_TARGET, value=14),
    )
    assert {"lightStatus": "1", "tempSelZ1": "14"}.items() <= sent[-1][1].items()

    # A current value is unknown: nothing is sent instead of a default
    del state["tempUnit"]
    count = len(sent)
    with pytest.raises(HomeAssistantError, match="tempUnit"):
        await call("light", "turn_off", LIGHT)
    assert len(sent) == count

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["cellars"][0]["model"] == "HWS77GDAU1"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow(hass, cloud):
    result = await hass.config_entries.flow.async_init("hon", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "me@example.com", "password": "x"}
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {"email": "me@example.com", "password": "x"}
