"""Haier hOn, wine cellar only."""
import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HonApi, HonError
from .const import WINE_CELLAR
from .coordinator import HonWineCellar

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.NUMBER, Platform.SENSOR]

type HonConfigEntry = ConfigEntry[list[HonWineCellar]]


async def async_setup_entry(hass: HomeAssistant, entry: HonConfigEntry) -> bool:
    api = HonApi(async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        await api.login()
        appliances = await api.get_appliances()
        cellars = [
            HonWineCellar(hass, entry, api, appliance, await api.get_commands(appliance))
            for appliance in appliances
            if appliance["applianceTypeName"] == WINE_CELLAR
        ]
    except (aiohttp.ClientError, HonError) as err:
        raise ConfigEntryNotReady(f"hOn connection failed: {err}") from err

    if not cellars:
        _LOGGER.warning(
            "No wine cellar on this hOn account (appliance types found: %s)",
            [appliance["applianceTypeName"] for appliance in appliances],
        )
    for cellar in cellars:
        await cellar.async_config_entry_first_refresh()

    entry.runtime_data = cellars
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HonConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
