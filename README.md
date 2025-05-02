# Smart Mini Split Controller for Home Assistant

A custom Home Assistant integration that intelligently manages a mini split heat/cool unit by comparing its internal set temperature against readings from an external thermometer.

## Features

- **External Temperature-Based Control:** Adjusts the mini split's set temperature up/down based on the difference between the external temperature reading and the target setpoint.
- **Smart Override Detection:** Recognizes manual user overrides and temporarily suspends automatic adjustments.
- **Cooldown Timer:** Prevents frequent adjustments with a configurable cooldown period.
- **Logbook Logging:** Logs all activities and decisions to the Home Assistant logbook.
- **Custom Services:** Service calls to force adjustments, toggle the automation, and clear overrides.

## Installation

1. Copy the `custom_components/smart_mini_split` folder to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the configuration to your `configuration.yaml` file (see below).

## Configuration

Add the following to your `configuration.yaml` file:

```yaml
smart_mini_split:
  entity_id: climate.minisplit  # Your mini split climate entity
  external_sensor: sensor.awair_element_110243_temperature  # Your external temperature sensor
  valid_range: [63, 72]  # Range of temperatures considered to be manually set. Keep this range in range of adjustment_step.
  adjustment_step: 15  # How much to adjust temperature when needed (degrees F)
  trigger_threshold: 2  # Temperature difference that triggers an adjustment (degrees F)
  reset_threshold: 1  # Temperature difference to return to normal setpoint (degrees F)
  cooldown_minutes: 5  # Minimum time between adjustments
  log_level: info  # 'info' or 'debug'
```

## Services

### `smart_mini_split.force_adjustment`

Force an immediate temperature check and adjustment, bypassing the cooldown timer.

### `smart_mini_split.toggle_automation`

Enable or disable the automation.

Parameters:
- `enabled`: Boolean, whether to enable or disable the automation.

### `smart_mini_split.clear_override`

Clear any manual override flags, allowing the automation to resume normal operation.

## How It Works

1. The integration compares the external temperature sensor reading with the mini split's set temperature.
2. If the difference exceeds the trigger threshold, it adjusts the mini split's temperature up or down by the adjustment step.
3. When the external temperature returns to within the reset threshold of the real setpoint, it returns the mini split to the original setting.
4. If a user manually changes the temperature to a value within the valid range, the integration temporarily suspends automation.
5. All actions are logged to the Home Assistant logbook for transparency.

## Notes

- The integration assumes your mini split can be controlled via Home Assistant.
- Temperature values are in Fahrenheit.
- The integration runs checks every minute.
- Debug logging can be enabled for more detailed information.

## Version Compatibility

This integration is compatible with Home Assistant Core versions that meet these requirements:

| Home Assistant Version | Status |
|------------------------|--------|
| 2023.x and newer       | Compatible with latest code |
| Older versions         | May require import path adjustments |

If you encounter import errors when installing this integration, please check the notes.md file for guidance on adjusting import paths for your specific Home Assistant version.

## Development & Testing

### Virtual Environment

This project uses a Python virtual environment to isolate dependencies:

1. **Create and activate the virtual environment**:
   ```bash
   # Option 1: Use the helper script
   ./activate_venv.sh
   
   # Option 2: Manual activation
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Deactivate the virtual environment when done**:
   ```bash
   deactivate
   ```

### Unit Tests

The integration includes a comprehensive test suite to ensure functionality and prevent regressions:

1. **Install test dependencies**:
   ```bash
   ./run_tests.sh --install
   ```

2. **Run the tests**:
   ```bash
   ./run_tests.sh
   ```

The test suite covers:
- Core controller functionality
- Temperature adjustment logic
- Manual override detection
- Compatibility layer for different Home Assistant versions
- Service calls and integration points

### Test Coverage

Tests are organized into:
- Unit tests for individual components
- Integration tests for complete functionality
- Compatibility tests for version support
