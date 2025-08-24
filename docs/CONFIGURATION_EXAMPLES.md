# Configuration Examples

This document provides configuration examples for common minisplit and sensor combinations with the Smart Thermostat Controller.

## Basic Configuration Examples

### Example 1: Bedroom Setup with Zigbee Sensors

**Scenario**: Bedroom minisplit with Zigbee temperature/humidity sensor

**Hardware**:
- Minisplit: Mitsubishi Electric (integrated via IR blaster)
- Sensor: Aqara Temperature and Humidity Sensor

**Configuration**:
```yaml
# Configuration via UI results in these settings:
external_temperature_sensor: sensor.bedroom_temperature
external_humidity_sensor: sensor.bedroom_humidity
minisplit_climate_entity: climate.bedroom_ac
target_temperature: 72
humidity_max_threshold: 60
humidity_min_threshold: 40
temperature_deadband: 1.0
cooldown_period: 300
learning_enabled: true
learning_period_days: 7
default_cooling_offset: 5.0
```

**Expected Behavior**:
- Maintains 72°F ± 1°F using external sensor readings
- Activates dry mode when humidity exceeds 60%
- Learns offset over 7 days to compensate for minisplit thermostat inaccuracy

### Example 2: Living Room with Z-Wave Sensors

**Scenario**: Large living room with multiple sensors for better accuracy

**Hardware**:
- Minisplit: Daikin (integrated via WiFi)
- Sensors: Z-Wave multisensor (temperature/humidity/motion)

**Configuration**:
```yaml
external_temperature_sensor: sensor.living_room_temperature
external_humidity_sensor: sensor.living_room_humidity
minisplit_climate_entity: climate.living_room_daikin
target_temperature: 74
humidity_max_threshold: 55
humidity_min_threshold: 35
temperature_deadband: 0.5
cooldown_period: 240
learning_enabled: true
learning_period_days: 10
default_cooling_offset: 3.0
```

**Notes**:
- Tighter temperature deadband (0.5°F) for more precise control
- Lower humidity thresholds for drier climate preference
- Shorter cooldown period for more responsive control
- Longer learning period for more stable offset calculation

### Example 3: Home Office with ESPHome Sensor

**Scenario**: Home office with custom ESPHome temperature/humidity sensor

**Hardware**:
- Minisplit: Generic IR-controlled unit
- Sensor: ESP32 with DHT22 sensor (ESPHome)

**Configuration**:
```yaml
external_temperature_sensor: sensor.office_esp_temperature
external_humidity_sensor: sensor.office_esp_humidity
minisplit_climate_entity: climate.office_ac
target_temperature: 70
humidity_max_threshold: 65
humidity_min_threshold: 45
temperature_deadband: 1.5
cooldown_period: 360
learning_enabled: true
learning_period_days: 14
default_cooling_offset: 4.0
```

**Notes**:
- Cooler target temperature for office work comfort
- Higher humidity tolerance
- Wider temperature deadband to reduce frequent switching
- Longer cooldown and learning periods for stability

## Advanced Configuration Examples

### Example 4: Multi-Zone Setup with Template Sensors

**Scenario**: Large room with multiple sensors averaged for better accuracy

**Template Sensor Configuration**:
```yaml
# configuration.yaml
template:
  - sensor:
      - name: "Master Bedroom Average Temperature"
        unit_of_measurement: "°F"
        state: >
          {% set sensors = [
            states('sensor.bedroom_sensor1_temperature') | float,
            states('sensor.bedroom_sensor2_temperature') | float,
            states('sensor.bedroom_sensor3_temperature') | float
          ] %}
          {{ (sensors | sum / sensors | length) | round(1) }}
        availability: >
          {{ states('sensor.bedroom_sensor1_temperature') not in ['unknown', 'unavailable'] and
             states('sensor.bedroom_sensor2_temperature') not in ['unknown', 'unavailable'] and
             states('sensor.bedroom_sensor3_temperature') not in ['unknown', 'unavailable'] }}

      - name: "Master Bedroom Average Humidity"
        unit_of_measurement: "%"
        state: >
          {% set sensors = [
            states('sensor.bedroom_sensor1_humidity') | float,
            states('sensor.bedroom_sensor2_humidity') | float,
            states('sensor.bedroom_sensor3_humidity') | float
          ] %}
          {{ (sensors | sum / sensors | length) | round(1) }}
        availability: >
          {{ states('sensor.bedroom_sensor1_humidity') not in ['unknown', 'unavailable'] and
             states('sensor.bedroom_sensor2_humidity') not in ['unknown', 'unavailable'] and
             states('sensor.bedroom_sensor3_humidity') not in ['unknown', 'unavailable'] }}
```

**Smart Thermostat Configuration**:
```yaml
external_temperature_sensor: sensor.master_bedroom_average_temperature
external_humidity_sensor: sensor.master_bedroom_average_humidity
minisplit_climate_entity: climate.master_bedroom_ac
target_temperature: 73
humidity_max_threshold: 58
humidity_min_threshold: 42
temperature_deadband: 0.8
cooldown_period: 300
learning_enabled: true
learning_period_days: 7
default_cooling_offset: 5.5
```

### Example 5: Seasonal Configuration with Automations

**Scenario**: Different settings for summer and winter seasons

**Automation for Seasonal Adjustments**:
```yaml
# automations.yaml
- id: smart_thermostat_summer_settings
  alias: "Smart Thermostat: Summer Settings"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature
      above: 75
      for: "24:00:00"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 55
        temperature_deadband: 0.5
        default_cooling_offset: 6.0

- id: smart_thermostat_winter_settings
  alias: "Smart Thermostat: Winter Settings"
  trigger:
    - platform: numeric_state
      entity_id: sensor.outdoor_temperature
      below: 50
      for: "24:00:00"
  action:
    - service: smart_thermostat_controller.update_config
      target:
        entity_id: climate.smart_thermostat_bedroom
      data:
        humidity_max_threshold: 65
        temperature_deadband: 1.0
        default_cooling_offset: 3.0
```

## Sensor-Specific Configurations

### Zigbee Sensors (Aqara, Xiaomi, etc.)

**Recommended Settings**:
- Update frequency: 30-60 seconds
- Temperature deadband: 0.5-1.0°F (these sensors are quite accurate)
- Cooldown period: 240-300 seconds

**Common Issues**:
- Battery-powered sensors may have delayed updates
- Consider using mains-powered Zigbee repeaters nearby

### Z-Wave Sensors

**Recommended Settings**:
- Update frequency: 15-30 seconds
- Temperature deadband: 0.5-1.5°F
- Cooldown period: 180-300 seconds

**Optimization Tips**:
- Configure reporting intervals in Z-Wave settings
- Use association groups for faster updates

### ESPHome Sensors

**Recommended Settings**:
- Update frequency: 10-30 seconds
- Temperature deadband: 0.3-1.0°F (highly configurable accuracy)
- Cooldown period: 180-240 seconds

**ESPHome Configuration Example**:
```yaml
# esphome configuration
sensor:
  - platform: dht
    pin: GPIO4
    temperature:
      name: "Room Temperature"
      filters:
        - sliding_window_moving_average:
            window_size: 5
            send_every: 3
    humidity:
      name: "Room Humidity"
      filters:
        - sliding_window_moving_average:
            window_size: 5
            send_every: 3
    update_interval: 30s
```

### WiFi Smart Sensors

**Recommended Settings**:
- Update frequency: 30-60 seconds
- Temperature deadband: 1.0-1.5°F
- Cooldown period: 300-360 seconds

**Considerations**:
- May have higher latency than Zigbee/Z-Wave
- Check WiFi signal strength in sensor location

## Minisplit-Specific Configurations

### Mitsubishi Electric

**Typical Characteristics**:
- Cooling offset: 4-6°F
- Heating offset: 1-3°F
- Recommended cooldown: 300 seconds

**Configuration Notes**:
- Usually well-integrated via IR or WiFi
- Dry mode typically very effective

### Daikin

**Typical Characteristics**:
- Cooling offset: 3-5°F
- Heating offset: 2-4°F
- Recommended cooldown: 240-300 seconds

**Configuration Notes**:
- Often have built-in WiFi integration
- May require specific IR codes for dry mode

### LG

**Typical Characteristics**:
- Cooling offset: 5-7°F
- Heating offset: 2-5°F
- Recommended cooldown: 300-360 seconds

**Configuration Notes**:
- Variable offset depending on model
- Some models have aggressive auto-mode switching

### Generic/IR-Controlled Units

**Typical Characteristics**:
- Cooling offset: 3-8°F (highly variable)
- Heating offset: 1-6°F (highly variable)
- Recommended cooldown: 300-600 seconds

**Configuration Notes**:
- Start with longer learning periods (14+ days)
- May need manual offset adjustment initially
- Test all modes thoroughly during setup

## Climate-Specific Configurations

### Hot and Humid Climates

```yaml
humidity_max_threshold: 50
humidity_min_threshold: 35
temperature_deadband: 0.5
cooldown_period: 240
default_cooling_offset: 6.0
learning_period_days: 10
```

### Dry Climates

```yaml
humidity_max_threshold: 70
humidity_min_threshold: 30
temperature_deadband: 1.0
cooldown_period: 300
default_cooling_offset: 4.0
learning_period_days: 7
```

### Moderate Climates

```yaml
humidity_max_threshold: 60
humidity_min_threshold: 40
temperature_deadband: 1.0
cooldown_period: 300
default_cooling_offset: 5.0
learning_period_days: 7
```

## Troubleshooting Configuration Issues

### Frequent Mode Switching

**Symptoms**: Minisplit changes modes too often
**Solutions**:
- Increase temperature deadband (try 1.5-2.0°F)
- Increase cooldown period (try 360-600 seconds)
- Check sensor placement for temperature stability

### Slow Response

**Symptoms**: Takes too long to reach target temperature
**Solutions**:
- Decrease temperature deadband (try 0.5°F)
- Decrease cooldown period (try 180-240 seconds)
- Verify sensor update frequency

### Inaccurate Temperature Control

**Symptoms**: Room temperature doesn't match target
**Solutions**:
- Adjust default cooling/heating offset manually
- Increase learning period for more data
- Verify sensor calibration and placement

### Humidity Control Issues

**Symptoms**: Dry mode not activating or too aggressive
**Solutions**:
- Adjust humidity thresholds based on local climate
- Verify humidity sensor accuracy
- Consider seasonal automation adjustments