"""Wine cellar coordinator and base entity."""
import asyncio
import logging
import re
import time
from datetime import timedelta

import aiohttp
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import HonApi, HonError, build_settings_params
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# How long a value we sent wins over cloud state that has not caught up yet.
# ponytail: a change made in the hOn app within this window can be masked; shorten if that bites.
PENDING_TTL = 120  # seconds


def zone(key: str, base: str) -> str | None:
    """'tempZ2' -> '2', bare 'temp' -> '1', anything else -> None."""
    if match := re.fullmatch(rf"{base}(?:Z(\d))?", key):
        return match[1] or "1"
    return None


def to_float(value: str | None) -> float | None:
    return None if value in (None, "") else float(str(value).replace(",", "."))


class HonWineCellar(DataUpdateCoordinator[dict[str, str]]):
    """Polls one cellar and changes settings without touching anything else."""

    def __init__(self, hass, entry, api: HonApi, appliance: dict, commands: dict) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"hOn {appliance.get('modelName', 'wine cellar')}",
            update_interval=timedelta(seconds=60),
        )
        self.api = api
        self.appliance = appliance
        self.connected = True
        settings = commands.get("settings", {})
        # Some models nest the definition one level down
        self.settings = settings if "parameters" in settings else settings.get("setParameters", {})
        if not self.settings.get("parameters"):
            _LOGGER.warning("No settings command for %s; light and zone targets can't be controlled", appliance.get("modelName"))
        self._options = commands.get("applianceModel", {}).get("options", {})
        self._ancillary = {
            key: spec.get("fixedValue", spec.get("defaultValue"))
            for key, spec in self.settings.get("ancillaryParameters", {}).items()
            if key != "programRules"
        }
        self._lock = asyncio.Lock()
        self._pending: dict[str, tuple[str, float]] = {}
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance["macAddress"])},
            name=appliance.get("nickName") or "Wine Cellar",
            manufacturer=str(appliance.get("brand", "Haier")).title(),
            model=appliance.get("modelName"),
            serial_number=appliance.get("serialNumber"),
            sw_version=appliance.get("fwVersion"),
        )

    def _state(self, context: dict) -> dict[str, str]:
        """Flatten the cloud context; values we just sent win until the cloud reflects them."""
        self.connected = context.get("lastConnEvent", {}).get("category") != "DISCONNECTED"
        state = {
            key: value.get("parNewVal")
            for key, value in context.get("shadow", {}).get("parameters", {}).items()
        }
        now = time.monotonic()
        for key, (value, sent_at) in list(self._pending.items()):
            if state.get(key) == value or now - sent_at > PENDING_TTL:
                del self._pending[key]
            else:
                state[key] = value
        return state

    async def _async_update_data(self) -> dict[str, str]:
        try:
            return self._state(await self.api.get_context(self.appliance))
        except (aiohttp.ClientError, HonError) as err:
            raise UpdateFailed(str(err)) from err

    async def async_set(self, key: str, value: str) -> None:
        """Change one setting; every other parameter is re-sent exactly as the cellar has it now."""
        # One write at a time, so a scene changing several values can't race itself
        async with self._lock:
            try:
                # Fresh read: never send back a value the hOn app changed since the last poll
                state = self._state(await self.api.get_context(self.appliance))
                params = build_settings_params(self.settings, state, {key: value})
                await self.api.send_command(self.appliance, self._options, "settings", params, self._ancillary)
            except (aiohttp.ClientError, HonError) as err:
                raise HomeAssistantError(f"Wine cellar {key}: {err}") from err
            self._pending[key] = (value, time.monotonic())
            state[key] = value
            self.async_set_updated_data(state)


class HonEntity(CoordinatorEntity[HonWineCellar]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HonWineCellar, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.appliance['macAddress']}_{key}"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.connected
