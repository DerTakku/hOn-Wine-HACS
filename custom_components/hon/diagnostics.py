"""Diagnostics: the cellar's settings definition and current state, for troubleshooting."""


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    return {
        "cellars": [
            {
                "model": cellar.appliance.get("modelName"),
                "firmware": cellar.appliance.get("fwVersion"),
                "settings_command": cellar.settings,
                "state": cellar.data,
            }
            for cellar in entry.runtime_data
        ]
    }
