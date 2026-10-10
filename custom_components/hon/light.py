"""Wine cellar light."""
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity

from .coordinator import HonEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(
        HonLight(cellar, "lightStatus", "Light")
        for cellar in entry.runtime_data
        if "lightStatus" in cellar.settings.get("parameters", {})
    )


class HonLight(HonEntity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get(self._key) == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._key, "1")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._key, "0")
