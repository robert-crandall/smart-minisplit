# Range Thermostat

A Home Assistant custom integration that gives you a real "keep it between 70 and 72"
thermostat on top of a minisplit that only understands one setpoint at a time.

It creates a virtual `climate` entity that wraps an existing minisplit `climate` entity plus
an external temperature sensor, watches the sensor, and flips the minisplit between heat and
cool to hold the room inside the band.

Works with any single-setpoint `climate` entity - a wifi integration like `gree`, or a
minisplit driven over IR by ESPHome (`heatpumpir`/`greeyac`). The control logic never trusts
the minisplit's reported state or its internal sensor, so an optimistic fire-and-forget IR
entity is fine.

## What you get

- A `climate` entity in `heat_cool` mode with a low and a high setpoint.
- Works with the built-in thermostat card, which renders both handles for you.
- Works with `climate.set_temperature`, scenes, and voice assistants with no adaptation.
- `hvac_action` tells you whether it thinks the unit is heating, cooling, or idle.
- `min_temp`, `max_temp` and `target_temperature_step` are inherited from the minisplit, so
  the virtual entity can't accept a setpoint the real one would reject.

## Install

Via HACS as a custom repository:

1. HACS -> three-dot menu -> Custom repositories.
2. Add `https://github.com/robert-crandall/smart-minisplit`, category **Integration**.
3. Install "Range Thermostat" and restart Home Assistant.
4. Settings -> Devices & services -> Add integration -> Range Thermostat.

Or copy `custom_components/range_thermostat/` into your `config/custom_components/` and restart.

## Setup

| Field | What it is |
|---|---|
| Name | Friendly name for the virtual entity |
| Minisplit | The `climate` entity this thermostat commands |
| Temperature sensor | The external `sensor` that governs the room |

One range thermostat per minisplit. Two would fight each other, so a second setup on the same
climate entity is rejected.

## Options

All of these are editable from the integration's options and take effect immediately - no
restart, and the mode-change cooldown keeps running across an edit.

| Option | Default | What it does |
|---|---|---|
| `deadband` | 1.0 | How far outside the band the room has to drift before a mode change fires. Symmetric. |
| `min_cycle_duration` | 15 min | Minimum time between mode changes. |
| `overshoot` | 0.0 | Pulls the commanded setpoint toward the middle of the band to buy coast time. |
| `sensor_timeout` | 15 min | How long the sensor may go quiet before the thermostat stops commanding. |
| `resend_interval` | 0 | Re-send the current command this often, to recover from dropped IR frames. 0 disables it. |
| `single_command` | off | Send a mode change as one `set_temperature` call carrying `hvac_mode`. Only for ESPHome. See below. |

## How it decides

With a band of `low`-`high`:

- `T < low - deadband` -> command the minisplit to **heat** at `low + overshoot`
- `T > high + deadband` -> command the minisplit to **cool** at `high - overshoot`
- anything in between -> keep the current mode

A mode change is blocked until `min_cycle_duration` has passed since the last one. A setpoint
change within the same mode is never blocked.

Three things that are deliberate:

**It never turns the minisplit off to regulate.** A unit sitting in heat at 70 in a 74 degree
room is already above its own setpoint and just idles. Powering it off would only add
compressor cycles. `off` is sent only when you set the *virtual* thermostat to off.

**There is no emergency override on the cooldown.** Bypassing the timer when the room is far
outside the band reintroduces exactly the oscillation the timer exists to prevent.

**It never falls back to the minisplit's internal sensor.** If the external sensor goes
unavailable or stops updating for longer than `sensor_timeout`, the thermostat holds the
current state, sets `sensor_stale: true`, logs once, and stops commanding. Silently changing
which sensor governs the room is worse than doing nothing.

The band is widened if it is ever narrower than `2 x deadband`, because a narrower band flips
modes continuously. A warning is logged when that happens.

`overshoot` is clamped so a commanded setpoint can never cross the middle of the band.

### One command per change

The thermostat tracks what it last sent and only calls a service when the mode or the setpoint
actually changes.

A mode change goes out as two service calls: `climate.set_temperature` for the setpoint, then
`climate.set_hvac_mode`. Setpoint-only changes are a single call.

Two calls rather than one is deliberate. Home Assistant lets you pass `hvac_mode` to
`climate.set_temperature`, but core does **not** dispatch `async_set_hvac_mode` for you - it
forwards the kwarg and leaves each platform to handle it, and most don't. Only 29 of the 108
climate platforms in core even reference it. On the other 79 a combined call would set the
temperature and silently ignore the mode, so the unit would never start heating or cooling.

The setpoint is sent first on purpose. A unit briefly left in the old mode at the new setpoint
just idles, whereas the old setpoint under the new mode would run the wrong direction until
the second call lands.

Set `single_command` to fold a mode change back into one call. ESPHome does honour `hvac_mode`
inside `set_temperature` and turns it into a single IR frame, so if that's your setup this
halves the IR traffic and the beeping. Leave it off for anything else.

## Attributes

| Attribute | Description |
|---|---|
| `controlled_entity` | The minisplit being commanded |
| `sensor_entity` | The external sensor |
| `last_mode_change` | ISO timestamp of the last heat/cool flip |
| `time_until_next_allowed_change` | Seconds left on the cooldown, 0 if none |
| `commanded_setpoint` | What was last sent to the minisplit |
| `sensor_stale` | Whether the sensor is currently unusable |

## Example automation

```yaml
automation:
  - alias: "Night comfort band"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedroom_range
        data:
          target_temp_low: 66
          target_temp_high: 68
```

## Notes and known edges

- After a restart the band and on/off state are restored, but the cooldown is treated as
  expired, so the first evaluation can act immediately.
- Turning the virtual thermostat off and back on while the room is inside the band leaves the
  minisplit off until the room actually drifts past a band edge. That's intended: there is
  nothing to do while the room is comfortable.
- The commanded setpoint is sent as calculated. If your unit only accepts whole degrees, it
  rounds on its side.

## Not included

Presets, scheduling, window/presence detection, fan or swing passthrough, multi-sensor
averaging, heat-only or cool-only modes, and any custom Lovelace card. Use automations and the
built-in thermostat card.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

The test suite covers each of the design's acceptance criteria against a mock minisplit that
ignores `hvac_mode` inside `set_temperature`, like most real integrations. A second mock
models the ESPHome behaviour and covers the `single_command` path.
