# hOn Wine Cellar

A Home Assistant integration for Haier wine cellars connected to the hOn app. It is a
stripped-down fork of [gvigroux/hon](https://github.com/gvigroux/hon) that only
supports wine cellars (hOn appliance type `WC`). Other hOn appliances on the account
are ignored.

Tested against Home Assistant 2026.7.2.

## Why this fork

The upstream `hon.turn_light_on` / `hon.turn_light_off` services send a `startProgram`
command that contains only `lightStatus`. The cellar resets every parameter it does
not receive, so each light toggle also reset the zone temperatures (see
gvigroux/hon#166, Andre0512/hon#238).

This fork changes settings with the `settings` command the hOn app uses. It sends
every parameter the cellar has:

- Before each change it reads the cellar's current state fresh from the cloud. A
  temperature you just changed in the hOn app is kept, not reverted.
- It changes only the value you asked for and re-sends everything else exactly as
  the cellar reports it.
- If any current value is unknown, it sends nothing and shows an error. It never
  falls back to a default.
- Writes go out one at a time, so a scene that sets the light and a zone together
  can't overwrite itself.

## Entities

| Entity | What it does |
| --- | --- |
| `light.<cellar>_light` | Turns the cellar light on and off |
| `number.<cellar>_zone_N_target_temperature` | Shows and sets a zone's target temperature |
| `sensor.<cellar>_zone_N_temperature` | A zone's measured temperature |

`<cellar>` is the cellar's name in the hOn app. Zones come from the cellar's own
parameter list (`tempSel`/`tempSelZ1` → zone 1, `tempSelZ2` → zone 2).

## Install (replacing gvigroux/hon)

1. In HA: **Settings → Devices & services → hOn → ⋮ → Delete**. This removes the old
   entities, which this fork doesn't provide.
2. If you installed upstream through HACS, remove it in HACS too (**HACS → hOn → ⋮ →
   Remove**). Both use the folder `custom_components/hon`.
3. **HACS → ⋮ → Custom repositories**: add `https://github.com/DerTakku/hOn-Wine-HACS`,
   type **Integration**. Then open **hOn Wine Cellar** in HACS and **Download** it.
4. Restart Home Assistant.
5. **Settings → Devices & services → Add integration → hOn Wine Cellar**, then log in
   with your hOn app email and password.
6. Update automations and scenes. The `hon.*` actions no longer exist. Use
   `light.turn_on` / `light.turn_off` on the light entity, or put the light entity
   in your scenes.

## Troubleshooting

If a change is refused with *"current value of … is unknown"*, the cellar's state
didn't include a value the settings command needs. Nothing was sent, so nothing
changed. Open the device page and use **⋮ → Download diagnostics**. The file contains
the settings definition and the current state (no credentials), which shows what is
missing.

Debug logging shows every command that was sent:

```yaml
logger:
  logs:
    custom_components.hon: debug
```

## Tests

```bash
pip install pytest-homeassistant-custom-component==0.13.346  # pins HA 2026.7.2, needs Python 3.14
pytest
```
