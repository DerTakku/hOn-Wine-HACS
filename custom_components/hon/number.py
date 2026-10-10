"""Wine cellar zone target temperatures."""
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature

from .coordinator import HonEntity, to_float, zone


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(
        HonZoneTarget(cellar, key, spec, n)
        for cellar in entry.runtime_data
        for key, spec in cellar.settings.get("parameters", {}).items()
        if spec.get("typology") == "range" and (n := zone(key, "tempSel"))
    )


class HonZoneTarget(HonEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, cellar, key: str, spec: dict, n: str) -> None:
        super().__init__(cellar, key, f"Zone {n} target temperature")
        self._attr_native_min_value = to_float(spec["minimumValue"])
        self._attr_native_max_value = to_float(spec["maximumValue"])
        self._attr_native_step = to_float(spec["incrementValue"])

    @property
    def native_value(self) -> float | None:
        return to_float(self.coordinator.data.get(self._key))

    async def async_set_native_value(self, value: float) -> None:
        # Same format the cellar reports: "17", not "17.0", for whole-degree steps
        text = str(int(value)) if self._attr_native_step.is_integer() else str(value)
        await self.coordinator.async_set(self._key, text)
