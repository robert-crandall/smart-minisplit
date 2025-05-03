# Smart Mini Split Controller for Home Assistant

A custom Home Assistant integration that intelligently manages a mini split heat/cool unit by comparing its internal set temperature against readings from an external thermometer.

## Features

- **External Temperature-Based Control:** Adjusts the mini split's set temperature up/down based on the difference between the external temperature reading and the target setpoint.
- **Cooldown Timer:** Prevents frequent adjustments with a configurable cooldown period.
- **Custom Heat Conditions:** Can start heating at a given difference, and heat until a threshold has been hit.
- **Logbook Logging:** Logs all activities and decisions to the Home Assistant logbook.

## Installation

1. Copy the `custom_components/smart_mini_split` folder to your Home Assistant `custom_components` directory.
2. Add the configuration to your `configuration.yaml` file (see below).
3. Restart Home Assistant.

## Configuration

Add the following to your `configuration.yaml` file:

```yaml
smart_mini_split:
  entity_id: climate.minisplit  # Your mini split climate entity
  external_sensor: sensor.awair_element_110243_temperature  # Your external temperature sensor
  valid_temp_range: [60, 74]  # Range of temperatures considered to be manually set. Ranges outside this are considered set by automation.
  trigger_threshold: 1.5  # Temperature difference that triggers an adjustment (degrees F)
  reset_threshold: 1.5  # Temperature difference to return to normal setpoint (degrees F)
  cooldown_minutes: 5  # Minimum time between adjustments
  log_level: info  # 'info' or 'debug'
```

## How It Works

1. The integration compares the external temperature sensor reading with the mini split's set temperature.
2. If the difference exceeds the trigger threshold, it adjusts the mini split's temperature up to start the heat.
3. When the external temperature reached the set temperature + reset threshold, it returns the minisplit's set temperature back to the starting point.
4. If a user manually changes the temperature to a value within the valid range, the integration uses this as the new set temperature.
5. All actions are logged to the Home Assistant logbook for transparency.

## Notes

- The integration assumes your mini split can be controlled via Home Assistant.
- Temperature values are in Fahrenheit.
- The integration runs checks every minute.
- Debug logging can be enabled for more detailed information.
