# Example Automations

This document provides ready-to-use automation examples that work with the Smart Thermostat Controller to create a more intelligent and responsive climate control system.

## Daily Schedule Automations

### Basic Day/Night Schedule

```yaml
# Morning temperature adjustment
- id: smart_thermostat_morning
  alias: "Smart Thermostat: Morning Schedule"
  trigger:
    - platform: time
      at: "06:30:00"
  condition:
    - condition: state
      entity_id: climate.smart_thermostat_bedroom
      state: "auto"
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 72
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 0.5  # More precise control during day

# Evening temperature adjustment
- id: smart_thermostat_evening
  alias: "Smart Thermostat: Evening Schedule"
  trigger:
    - platform: time
      at: "22:00:00"
  condition:
    - condition: state
      entity_id: climate.smart_thermostat_bedroom
      state: "auto"
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 68
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 1.5  # Less precise at night for stability
```

### Workday vs Weekend Schedule

```yaml
# Workday schedule - energy saving when away
- id: smart_thermostat_workday
  alias: "Smart Thermostat: Workday Schedule"
  trigger:
    - platform: time
      at: "08:00:00"
  condition:
    - condition: state
      entity_id: binary_sensor.workday_sensor
      state: "on"
    - condition: state
      entity_id: device_tracker.phone
      state: "not_home"
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 76  # Energy saving temperature
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 2.0
        cooldown_period: 600  # Longer cooldown for efficiency

# Return home - restore comfort
- id: smart_thermostat_return_home
  alias: "Smart Thermostat: Return Home"
  trigger:
    - platform: state
      entity_id: device_tracker.phone
      to: "home"
  condition:
    - condition: state
      entity_id: binary_sensor.workday_sensor
      state: "on"
    - condition: time
      after: "15:00:00"
      before: "19:00:00"
  action:
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
        cooldown_period: 300
```

## Occupancy-Based Automations

### Room Occupancy Control

```yaml
# Occupied room - comfort mode
- id: smart_thermostat_room_occupied
  alias: "Smart Thermostat: Room Occupied"
  trigger:
    - platform: state
      entity_id: binary_sensor.bedroom_occupancy
      to: "on"
  action:
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
        humidity_max_threshold: 55

# Unoccupied room - energy saving
- id: smart_thermostat_room_unoccupied
  alias: "Smart Thermostat: Room Unoccupied"
  trigger:
    - platform: state
      entity_id: binary_sensor.bedroom_occupancy
      to: "off"
      for: "00:30:00"  # Wait 30 minutes before adjusting
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 75
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 2.0
        humidity_max_threshold: 65
```

### Sleep Mode Automation

```yaml
# Sleep mode - cooler and quieter
- id: smart_thermostat_sleep_mode
  alias: "Smart Thermostat: Sleep Mode"
  trigger:
    - platform: state
      entity_id: input_boolean.sleep_mode
      to: "on"
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 68
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 1.0
        cooldown_period: 600  # Longer cooldown for quieter operation

# Wake up - return to normal
- id: smart_thermostat_wake_up
  alias: "Smart Thermostat: Wake Up"
  trigger:
    - platform: state
      entity_id: input_boolean.sleep_mode
      to: "off"
  action:
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
        cooldown_period: 300
```

## Weather-Based Automations

### Outdoor Temperature Response

```yaml
# Hot day - aggressive cooling
- id: smart_thermostat_hot_day
  alias: "Smart Thermostat: Hot Day Response"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature
      above: 90
      for: "01:00:00"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 0.3
        humidity_max_threshold: 50
        default_cooling_offset: 7.0
        cooldown_period: 180

# Mild day - energy efficient
- id: smart_thermostat_mild_day
  alias: "Smart Thermostat: Mild Day Response"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature
      below: 80
      above: 65
      for: "02:00:00"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 1.5
        humidity_max_threshold: 60
        cooldown_period: 450
```

### Humidity Response

```yaml
# High outdoor humidity - prioritize dehumidification
- id: smart_thermostat_high_humidity_day
  alias: "Smart Thermostat: High Humidity Day"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_humidity
      above: 80
      for: "02:00:00"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 45
        temperature_deadband: 1.0  # Allow slightly wider temp range for humidity control

# Low humidity - relax dehumidification
- id: smart_thermostat_low_humidity_day
  alias: "Smart Thermostat: Low Humidity Day"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_humidity
      below: 40
      for: "04:00:00"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 70
        humidity_min_threshold: 30
```

## Seasonal Automations

### Summer Configuration

```yaml
# Summer settings - focus on cooling and dehumidification
- id: smart_thermostat_summer_config
  alias: "Smart Thermostat: Summer Configuration"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature_7day_avg
      above: 75
  condition:
    - condition: template
      value_template: "{{ now().month in [6, 7, 8, 9] }}"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 50
        temperature_deadband: 0.5
        default_cooling_offset: 6.0
        cooldown_period: 240
        learning_period_days: 5  # Faster learning in consistent season
```

### Winter Configuration

```yaml
# Winter settings - focus on heating efficiency
- id: smart_thermostat_winter_config
  alias: "Smart Thermostat: Winter Configuration"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature_7day_avg
      below: 50
  condition:
    - condition: template
      value_template: "{{ now().month in [12, 1, 2, 3] }}"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 65
        temperature_deadband: 1.0
        default_heating_offset: 3.0
        cooldown_period: 360
        learning_period_days: 10  # Slower learning due to variable conditions
```

## Energy Optimization Automations

### Peak Hours Energy Saving

```yaml
# Peak electricity hours - reduce cooling
- id: smart_thermostat_peak_hours
  alias: "Smart Thermostat: Peak Hours Energy Saving"
  trigger:
    - platform: time
      at: "14:00:00"  # Peak hours start
  condition:
    - condition: numeric_state
      entity_id: sensor.outdoor_temperature
      below: 95  # Only if not extremely hot
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 75  # Slightly higher target
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 2.0
        cooldown_period: 600

# Off-peak hours - restore comfort
- id: smart_thermostat_off_peak
  alias: "Smart Thermostat: Off-Peak Hours"
  trigger:
    - platform: time
      at: "19:00:00"  # Peak hours end
  action:
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
        cooldown_period: 300
```

### Solar Panel Integration

```yaml
# Excess solar power - pre-cool the house
- id: smart_thermostat_solar_excess
  alias: "Smart Thermostat: Solar Excess Cooling"
  trigger:
    - platform: numeric_state
      entity_id: sensor.solar_power_excess
      above: 2000  # 2kW excess
      for: "00:15:00"
  condition:
    - condition: numeric_state
      entity_id: sensor.bedroom_temperature
      above: 70
    - condition: time
      after: "10:00:00"
      before: "16:00:00"
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 69  # Pre-cool while solar is abundant
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 0.3
        cooldown_period: 120  # More aggressive cooling
```

## Health and Comfort Automations

### Air Quality Response

```yaml
# Poor air quality - increase ventilation via temperature cycling
- id: smart_thermostat_air_quality
  alias: "Smart Thermostat: Air Quality Response"
  trigger:
    - platform: numeric_state
      entity_id: sensor.bedroom_air_quality_index
      above: 100
      for: "00:30:00"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 0.8
        cooldown_period: 180  # More frequent cycling for air movement
    - service: notify.mobile_app
      data:
        message: "Poor air quality detected. Adjusting thermostat for better ventilation."
```

### Allergy Season Adjustments

```yaml
# High pollen count - keep windows closed, rely on AC
- id: smart_thermostat_high_pollen
  alias: "Smart Thermostat: High Pollen Response"
  trigger:
    - platform: numeric_state
      entity_id: sensor.pollen_count
      above: 7  # High pollen level
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 45  # Lower humidity to reduce allergens
        temperature_deadband: 0.5   # Maintain consistent temperature
```

## Maintenance and Monitoring Automations

### Learning Performance Monitoring

```yaml
# Low learning confidence - notify for maintenance
- id: smart_thermostat_low_confidence
  alias: "Smart Thermostat: Low Learning Confidence"
  trigger:
    - platform: numeric_state
      entity_id: sensor.smart_thermostat_offset_confidence
      below: 0.5
      for: "48:00:00"
  action:
    - service: notify.mobile_app
      data:
        message: "Smart thermostat learning confidence is low. Check sensor placement and calibration."
        data:
          actions:
            - action: "reset_learning"
              title: "Reset Learning"
            - action: "ignore_24h"
              title: "Ignore for 24h"

# Handle notification responses
- id: smart_thermostat_maintenance_response
  alias: "Smart Thermostat: Handle Maintenance Response"
  trigger:
    - platform: event
      event_type: mobile_app_notification_action
  condition:
    - condition: template
      value_template: "{{ trigger.event.data.action in ['reset_learning', 'ignore_24h'] }}"
  action:
    - choose:
        - conditions:
            - condition: template
              value_template: "{{ trigger.event.data.action == 'reset_learning' }}"
          sequence:
            - service: smart_thermostat_controller.reset_learning
              target:
                entity_id: climate.smart_thermostat_bedroom
        - conditions:
            - condition: template
              value_template: "{{ trigger.event.data.action == 'ignore_24h' }}"
          sequence:
            - service: automation.turn_off
              target:
                entity_id: automation.smart_thermostat_low_learning_confidence
            - delay: "24:00:00"
            - service: automation.turn_on
              target:
                entity_id: automation.smart_thermostat_low_learning_confidence
```

### Sensor Health Monitoring

```yaml
# Temperature sensor offline
- id: smart_thermostat_temp_sensor_offline
  alias: "Smart Thermostat: Temperature Sensor Offline"
  trigger:
    - platform: state
      entity_id: sensor.bedroom_temperature
      to: "unavailable"
      for: "00:05:00"
  action:
    - service: smart_thermostat_controller.set_manual_override
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        override_enabled: true
        reason: "Temperature sensor offline"
    - service: notify.mobile_app
      data:
        message: "Bedroom temperature sensor is offline. Smart thermostat switched to manual mode."
        data:
          tag: "sensor_offline"

# Temperature sensor back online
- id: smart_thermostat_temp_sensor_online
  alias: "Smart Thermostat: Temperature Sensor Online"
  trigger:
    - platform: state
      entity_id: sensor.bedroom_temperature
      from: "unavailable"
  condition:
    - condition: state
      entity_id: sensor.smart_thermostat_manual_override
      state: "on"
  action:
    - service: smart_thermostat_controller.set_manual_override
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        override_enabled: false
        reason: "Temperature sensor restored"
    - service: notify.mobile_app
      data:
        message: "Bedroom temperature sensor is back online. Smart thermostat resumed automatic control."
        data:
          tag: "sensor_offline"
```

## Emergency Automations

### Extreme Temperature Protection

```yaml
# Emergency cooling for extreme heat
- id: smart_thermostat_emergency_heat
  alias: "Smart Thermostat: Emergency Heat Protection"
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
        reason: "Emergency high temperature protection"
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 70
    - service: notify.mobile_app
      data:
        message: "EMERGENCY: Bedroom temperature exceeded 85°F. Forced cooling activated."
        data:
          priority: "high"

# Emergency heating for extreme cold
- id: smart_thermostat_emergency_cold
  alias: "Smart Thermostat: Emergency Cold Protection"
  trigger:
    - platform: numeric_state
      entity_id: sensor.bedroom_temperature
      below: 50
  action:
    - service: smart_thermostat_controller.force_mode_change
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        hvac_mode: "heat"
        reason: "Emergency low temperature protection"
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 68
    - service: notify.mobile_app
      data:
        message: "EMERGENCY: Bedroom temperature dropped below 50°F. Forced heating activated."
        data:
          priority: "high"
```

## Guest Mode Automations

### Guest Preferences

```yaml
# Guest mode - different comfort settings
- id: smart_thermostat_guest_mode
  alias: "Smart Thermostat: Guest Mode"
  trigger:
    - platform: state
      entity_id: input_boolean.guest_mode
      to: "on"
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 74  # Slightly warmer for guests
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 0.5
        humidity_max_threshold: 55
        cooldown_period: 240
    - service: smart_thermostat_controller.set_manual_override
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        override_enabled: true
        reason: "Guest preferences active"

# Return to normal after guest mode
- id: smart_thermostat_guest_mode_off
  alias: "Smart Thermostat: Guest Mode Off"
  trigger:
    - platform: state
      entity_id: input_boolean.guest_mode
      to: "off"
  action:
    - service: smart_thermostat_controller.set_manual_override
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        override_enabled: false
        reason: "Guest mode ended"
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 72
```

## Integration with Other Systems

### Smart Home Security Integration

```yaml
# Away mode - energy saving when security system armed
- id: smart_thermostat_security_away
  alias: "Smart Thermostat: Security Away Mode"
  trigger:
    - platform: state
      entity_id: alarm_control_panel.home_security
      to: "armed_away"
  action:
    - service: climate.set_temperature
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature: 78  # Energy saving
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        temperature_deadband: 3.0
        cooldown_period: 900  # Very long cooldown for efficiency

# Home mode - restore comfort when disarmed
- id: smart_thermostat_security_home
  alias: "Smart Thermostat: Security Home Mode"
  trigger:
    - platform: state
      entity_id: alarm_control_panel.home_security
      to: "disarmed"
  condition:
    - condition: state
      entity_id: alarm_control_panel.home_security
      state: "disarmed"
      for: "00:02:00"  # Wait to confirm not false alarm
  action:
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
        cooldown_period: 300
```

These automations provide a comprehensive foundation for intelligent climate control that adapts to your lifestyle, weather conditions, energy costs, and comfort preferences. Customize the temperature values, timing, and conditions to match your specific needs and preferences.