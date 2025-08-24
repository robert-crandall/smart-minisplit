# API Documentation

This document provides detailed information about the Smart Thermostat Controller's services, configuration options, and automation examples.

## Services

### smart_thermostat_controller.update_config

Updates configuration parameters for a Smart Thermostat Controller instance.

**Service Data**:
```yaml
service: smart_thermostat_controller.update_config
target:
  entity_id: climate.smart_thermostat_bedroom
data:
  target_temperature: 72.0
  humidity_max_threshold: 60
  humidity_min_threshold: 40
  temperature_deadband: 1.0
  cooldown_period: 300
  learning_enabled: true
  learning_period_days: 7
  default_cooling_offset: 5.0
  default_heating_offset: 2.0
```

**Parameters**:
- `target_temperature` (float): Default target temperature in °F or °C
- `humidity_max_threshold` (int): Maximum humidity percentage before dry mode
- `humidity_min_threshold` (int): Minimum humidity percentage threshold
- `temperature_deadband` (float): Temperature tolerance before mode switching
- `cooldown_period` (int): Minimum seconds between mode changes
- `learning_enabled` (bool): Enable/disable automatic offset learning
- `learning_period_days` (int): Days of data for offset calculation
- `default_cooling_offset` (float): Initial cooling mode temperature offset
- `default_heating_offset` (float): Initial heating mode temperature offset

### smart_thermostat_controller.reset_learning

Resets the learning algorithm data and starts fresh learning.

**Service Data**:
```yaml
service: smart_thermostat_controller.reset_learning
target:
  entity_id: climate.smart_thermostat_bedroom
```

### smart_thermostat_controller.set_manual_override

Enables or disables manual override mode.

**Service Data**:
```yaml
service: smart_thermostat_controller.set_manual_override
target:
  entity_id: climate.smart_thermostat_bedroom
data:
  override_enabled: true
  reason: "Guest preferences"
```

**Parameters**:
- `override_enabled` (bool): Enable or disable manual override
- `reason` (string, optional): Reason for override (logged for audit)

### smart_thermostat_controller.force_mode_change

Forces an immediate mode change, bypassing cooldown protection.

**Service Data**:
```yaml
service: smart_thermostat_controller.force_mode_change
target:
  entity_id: climate.smart_thermostat_bedroom
data:
  hvac_mode: "cool"
  reason: "Emergency override"
```

**Parameters**:
- `hvac_mode` (string): Target HVAC mode (heat, cool, dry, off, auto)
- `reason` (string): Reason for emergency override (required for audit)

**⚠️ Warning**: Use sparingly as this can potentially damage equipment if used excessively.

### smart_thermostat_controller.get_diagnostics

Retrieves diagnostic information for troubleshooting.

**Service Data**:
```yaml
service: smart_thermostat_controller.get_diagnostics
target:
  entity_id: climate.smart_thermostat_bedroom
```

**Returns**: JSON object with system status, recent decisions, and performance metrics.

## Advanced Configuration Options

### Configuration File Structure

The integration stores configuration in Home Assistant's storage system, but advanced users can access additional options through the configuration flow or services.

### Learning Algorithm Parameters

```yaml
# Advanced learning configuration (via service call)
learning_config:
  min_data_points: 50          # Minimum data points before learning
  max_data_age_days: 30        # Maximum age of data points to consider
  outlier_threshold: 3.0       # Standard deviations for outlier removal
  confidence_threshold: 0.7    # Minimum confidence for offset application
  update_frequency_hours: 6    # How often to recalculate offset
```

### Control Algorithm Parameters

```yaml
# Advanced control configuration
control_config:
  temperature_hysteresis: 0.2  # Additional hysteresis for stability
  humidity_priority_weight: 1.5 # Weight for humidity vs temperature priority
  mode_change_delay: 30        # Additional delay before executing mode change
  sensor_timeout_seconds: 300  # Timeout for sensor readings
  max_offset_change_per_day: 1.0 # Maximum daily offset adjustment
```

### Cooldown Configuration

```yaml
# Advanced cooldown settings
cooldown_config:
  heat_to_cool: 300           # Seconds between heat and cool
  cool_to_heat: 300           # Seconds between cool and heat
  any_to_dry: 180             # Seconds before switching to dry
  dry_to_any: 240             # Seconds after dry mode
  startup_delay: 600          # Initial delay after system start
```

## Entity Attributes

### Climate Entity Attributes

The main climate entity exposes these attributes:

```yaml
# climate.smart_thermostat_bedroom attributes
current_temperature: 72.1      # From external sensor
current_humidity: 55           # From external sensor
target_temperature: 72.0      # User-set target
hvac_mode: "cool"             # Current mode
hvac_action: "cooling"        # Current action
hvac_modes: ["heat", "cool", "dry", "off", "auto"]
preset_mode: null
preset_modes: []
min_temp: 50                  # Configurable minimum
max_temp: 90                  # Configurable maximum
target_temp_step: 0.5         # Temperature step size
learned_offset: 5.2           # Current learned offset
offset_confidence: 0.85       # Confidence in learned offset
manual_override: false        # Manual override status
cooldown_remaining: 0         # Seconds until next change allowed
last_mode_change: "2024-01-15T10:30:00Z"
control_reason: "Temperature above target + deadband"
```

### Sensor Entity States

```yaml
# Status sensors
sensor.smart_thermostat_current_mode:
  state: "cool"
  attributes:
    friendly_name: "Smart Thermostat Current Mode"
    icon: "mdi:thermostat"

sensor.smart_thermostat_learned_offset:
  state: 5.2
  attributes:
    unit_of_measurement: "°F"
    friendly_name: "Smart Thermostat Learned Offset"
    icon: "mdi:thermometer-plus"

sensor.smart_thermostat_offset_confidence:
  state: 0.85
  attributes:
    unit_of_measurement: "%"
    friendly_name: "Smart Thermostat Offset Confidence"
    icon: "mdi:chart-line"

sensor.smart_thermostat_cooldown_remaining:
  state: 0
  attributes:
    unit_of_measurement: "s"
    friendly_name: "Smart Thermostat Cooldown Remaining"
    icon: "mdi:timer"

sensor.smart_thermostat_manual_override:
  state: "off"
  attributes:
    friendly_name: "Smart Thermostat Manual Override"
    icon: "mdi:hand-back-right"
```

## Automation Examples

### Basic Temperature Control

```yaml
# Automation to adjust target temperature based on time of day
- id: smart_thermostat_schedule
  alias: "Smart Thermostat: Daily Schedule"
  trigger:
    - platform: time
      at: "07:00:00"  # Morning
    - platform: time
      at: "22:00:00"  # Night
  action:
    - choose:
        - conditions:
            - condition: time
              after: "07:00:00"
              before: "22:00:00"
          sequence:
            - service: climate.set_temperature
              target:
                entity_id: climate.smart_thermostat_bedroom
              data:
                temperature: 72
        - conditions:
            - condition: time
              after: "22:00:00"
          sequence:
            - service: climate.set_temperature
              target:
                entity_id: climate.smart_thermostat_bedroom
              data:
                temperature: 68
```

### Humidity-Based Control

```yaml
# Automation for high humidity conditions
- id: smart_thermostat_high_humidity
  alias: "Smart Thermostat: High Humidity Response"
  trigger:
    - platform: numeric_state
      entity_id: sensor.bedroom_humidity
      above: 70
      for: "00:10:00"
  condition:
    - condition: state
      entity_id: climate.smart_thermostat_bedroom
      state: "auto"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 65
    - service: notify.mobile_app
      data:
        message: "High humidity detected, adjusting thermostat settings"
```

### Seasonal Adjustments

```yaml
# Automation for seasonal configuration changes
- id: smart_thermostat_seasonal_summer
  alias: "Smart Thermostat: Summer Configuration"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature_avg_7d
      above: 80
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 50
        temperature_deadband: 0.5
        default_cooling_offset: 6.0
        cooldown_period: 240

- id: smart_thermostat_seasonal_winter
  alias: "Smart Thermostat: Winter Configuration"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature_avg_7d
      below: 40
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 65
        temperature_deadband: 1.0
        default_heating_offset: 3.0
        cooldown_period: 300
```

### Occupancy-Based Control

```yaml
# Automation based on room occupancy
- id: smart_thermostat_occupancy
  alias: "Smart Thermostat: Occupancy Control"
  trigger:
    - platform: state
      entity_id: binary_sensor.bedroom_occupancy
  action:
    - choose:
        - conditions:
            - condition: state
              entity_id: binary_sensor.bedroom_occupancy
              state: "on"
          sequence:
            - service: climate.set_temperature
              target:
                entity_id: climate.smart_thermostat_bedroom
              data:
                temperature: 72
            - service: smart_thermostat_controller.update_config
              target:
                entity_id: climate.smart_thermostat_bedroom
              data:
                temperature_deadband: 0.5
        - conditions:
            - condition: state
              entity_id: binary_sensor.bedroom_occupancy
              state: "off"
              for: "01:00:00"
          sequence:
            - service: climate.set_temperature
              target:
                entity_id: climate.smart_thermostat_bedroom
              data:
                temperature: 75  # Energy saving
            - service: smart_thermostat_controller.update_config
              target:
                entity_id: climate.smart_thermostat_bedroom
              data:
                temperature_deadband: 2.0
```

### Learning Management

```yaml
# Automation to reset learning when offset seems wrong
- id: smart_thermostat_reset_learning
  alias: "Smart Thermostat: Reset Learning if Inaccurate"
  trigger:
    - platform: numeric_state
      entity_id: sensor.smart_thermostat_learned_offset
      above: 10  # Offset seems too high
      for: "24:00:00"
    - platform: numeric_state
      entity_id: sensor.smart_thermostat_learned_offset
      below: -2  # Offset seems too low
      for: "24:00:00"
  condition:
    - condition: numeric_state
      entity_id: sensor.smart_thermostat_offset_confidence
      above: 0.8  # Only if we're confident in the bad reading
  action:
    - service: smart_thermostat_controller.reset_learning
      target:
        entity_id: climate.smart_thermostat_bedroom
    - service: notify.mobile_app
      data:
        message: "Smart thermostat learning reset due to unusual offset values"
```

### Emergency Override

```yaml
# Automation for emergency situations
- id: smart_thermostat_emergency_cool
  alias: "Smart Thermostat: Emergency Cooling"
  trigger:
    - platform: numeric_state
      entity_id: sensor.bedroom_temperature
      above: 85
  action:
    - service: smart_thermostat_controller.force_mode_change
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        hvac_mode: "cool"
        reason: "Emergency high temperature"
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 70
```

### Maintenance Notifications

```yaml
# Automation for maintenance reminders
- id: smart_thermostat_maintenance
  alias: "Smart Thermostat: Maintenance Notifications"
  trigger:
    - platform: numeric_state
      entity_id: sensor.smart_thermostat_offset_confidence
      below: 0.5
      for: "72:00:00"
  action:
    - service: notify.mobile_app
      data:
        message: "Smart thermostat learning confidence is low. Check sensor placement and calibration."
        data:
          actions:
            - action: "reset_learning"
              title: "Reset Learning"
            - action: "check_sensors"
              title: "Check Sensors"

# Handle notification actions
- id: smart_thermostat_maintenance_actions
  alias: "Smart Thermostat: Handle Maintenance Actions"
  trigger:
    - platform: event
      event_type: mobile_app_notification_action
      event_data:
        action: "reset_learning"
  action:
    - service: smart_thermostat_controller.reset_learning
      target:
        entity_id: climate.smart_thermostat_bedroom
```

## Integration with Other Systems

### Node-RED Integration

```javascript
// Node-RED flow for advanced logic
[
    {
        "id": "smart_thermostat_node",
        "type": "api-call-service",
        "name": "Update Smart Thermostat",
        "server": "home_assistant",
        "version": 3,
        "service_domain": "smart_thermostat_controller",
        "service": "update_config",
        "entityId": "climate.smart_thermostat_bedroom",
        "data": "{\"temperature_deadband\": payload.deadband}",
        "dataType": "jsonata"
    }
]
```

### AppDaemon Integration

```python
# AppDaemon app for advanced control
import appdaemon.plugins.hass.hassapi as hass

class SmartThermostatController(hass.Hass):
    def initialize(self):
        self.listen_state(self.on_temperature_change, "sensor.bedroom_temperature")
        self.listen_state(self.on_humidity_change, "sensor.bedroom_humidity")
    
    def on_temperature_change(self, entity, attribute, old, new, kwargs):
        # Custom logic for temperature changes
        if float(new) > 80:
            self.call_service("smart_thermostat_controller/update_config",
                            entity_id="climate.smart_thermostat_bedroom",
                            temperature_deadband=0.3)
    
    def on_humidity_change(self, entity, attribute, old, new, kwargs):
        # Custom logic for humidity changes
        if float(new) > 70:
            self.call_service("smart_thermostat_controller/update_config",
                            entity_id="climate.smart_thermostat_bedroom",
                            humidity_max_threshold=65)
```

## Performance Optimization

### Reducing Update Frequency

```yaml
# Optimize sensor update intervals
sensor_update_intervals:
  temperature: 30  # seconds
  humidity: 60     # seconds
  control_loop: 30 # seconds
```

### Memory Management

```yaml
# Configure data retention
data_retention:
  learning_data_days: 30      # Keep learning data for 30 days
  log_retention_days: 7       # Keep detailed logs for 7 days
  cleanup_interval_hours: 24  # Run cleanup daily
```

## Security Considerations

### Access Control

The integration respects Home Assistant's built-in access control:
- Users need appropriate permissions to modify climate entities
- Service calls require proper authentication
- Configuration changes are logged for audit purposes

### Data Privacy

- All data is stored locally within Home Assistant
- No external data transmission required
- Historical data can be purged on demand
- Diagnostic information excludes sensitive details

## Migration and Backup

### Configuration Backup

```yaml
# Include in Home Assistant backup
backup_include:
  - .storage/smart_thermostat_controller_*
  - custom_components/smart_thermostat_controller/
```

### Migration Between Versions

The integration includes automatic migration for configuration changes between versions. Manual migration may be required for major version updates.

### Export/Import Configuration

```yaml
# Export configuration (via service call)
service: smart_thermostat_controller.export_config
target:
  entity_id: climate.smart_thermostat_bedroom

# Import configuration
service: smart_thermostat_controller.import_config
target:
  entity_id: climate.smart_thermostat_bedroom
data:
  config_data: !include smart_thermostat_config.yaml
```