"""Wine cellar zone temperatures."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature

from .coordinator import HonEntity, to_float, zone


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(
        HonZoneTemperature(cellar, key, f"Zone {n} temperature")
        for cellar in entry.runtime_data
        for key in cellar.data
        if (n := zone(key, "temp"))
    )


class HonZoneTemperature(HonEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        return to_float(self.coordinator.data.get(self._key))
