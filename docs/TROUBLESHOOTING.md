# Troubleshooting Guide

This guide helps you diagnose and resolve common issues with the Smart Thermostat Controller.

## Quick Diagnostics

### Check System Status

1. **View Status Sensors**: Check the status sensors in Home Assistant:
   - `sensor.smart_thermostat_current_mode`
   - `sensor.smart_thermostat_learned_offset`
   - `sensor.smart_thermostat_cooldown_remaining`
   - `sensor.smart_thermostat_manual_override`

2. **Check Logs**: Look at Home Assistant logs for Smart Thermostat Controller entries:
   ```
   Settings → System → Logs
   Filter by: smart_thermostat_controller
   ```

3. **Verify Entity States**: Ensure all configured entities are available and updating:
   - External temperature sensor
   - External humidity sensor
   - Minisplit climate entity

## Common Issues and Solutions

### 1. Integration Not Loading

**Symptoms**:
- Smart Thermostat Controller doesn't appear in integrations
- Error messages during Home Assistant startup

**Diagnostic Steps**:
1. Check Home Assistant logs for error messages
2. Verify file permissions in `custom_components/smart_thermostat_controller/`
3. Confirm all required files are present

**Solutions**:
```bash
# Check file permissions (if using Docker)
docker exec homeassistant ls -la /config/custom_components/smart_thermostat_controller/

# Verify manifest.json is valid
cat /config/custom_components/smart_thermostat_controller/manifest.json
```

**Common Fixes**:
- Restart Home Assistant after installation
- Clear browser cache and refresh
- Check for Python syntax errors in log files
- Ensure manifest.json has correct format and dependencies

### 2. Configuration Flow Errors

**Symptoms**:
- Cannot complete setup wizard
- Entity selection shows no options
- Configuration validation errors

**Diagnostic Steps**:
1. Verify target entities exist and are available
2. Check entity IDs are correct (case-sensitive)
3. Ensure entities have recent state updates

**Solutions**:

**No Temperature Sensors Available**:
```yaml
# Verify sensor exists and has temperature data
Developer Tools → States → Search for your sensor
# Should show state like "72.5" with unit_of_measurement: "°F" or "°C"
```

**No Climate Entities Available**:
```yaml
# Check climate entity is properly integrated
Developer Tools → States → Search for climate entities
# Should show state like "cool", "heat", "off" etc.
```

**Configuration Validation Errors**:
- Temperature values must be numeric (not strings)
- Humidity thresholds must be between 0-100
- Cooldown period must be positive integer
- Entity IDs must exist and be accessible

### 3. Sensor Communication Issues

**Symptoms**:
- "Sensor unavailable" errors in logs
- Temperature/humidity readings show as "unknown" or "unavailable"
- Inconsistent sensor updates

**Diagnostic Steps**:
1. Check sensor battery levels (if battery-powered)
2. Verify network connectivity (Zigbee/Z-Wave/WiFi)
3. Check sensor placement and environmental factors

**Solutions**:

**Zigbee Sensor Issues**:
```yaml
# Check Zigbee network health
Settings → Devices & Services → Zigbee Home Automation
# Look for offline devices or poor signal strength
```

**Z-Wave Sensor Issues**:
```yaml
# Check Z-Wave network health
Settings → Devices & Services → Z-Wave JS
# Verify node status and communication
```

**WiFi Sensor Issues**:
- Check WiFi signal strength at sensor location
- Verify sensor is connected to correct network
- Check for IP address conflicts

**ESPHome Sensor Issues**:
```yaml
# Check ESPHome device logs
Settings → Devices & Services → ESPHome
# Click on device → Logs
```

### 4. Minisplit Control Problems

**Symptoms**:
- Commands sent but minisplit doesn't respond
- Incorrect mode changes
- Minisplit shows different state than Home Assistant

**Diagnostic Steps**:
1. Test manual control through Home Assistant UI
2. Check IR blaster positioning and battery (if using IR)
3. Verify climate entity integration is working

**Solutions**:

**IR Control Issues**:
- Check IR blaster battery and positioning
- Verify IR codes are correct for your minisplit model
- Test line-of-sight between blaster and minisplit
- Check for IR interference from other devices

**WiFi Integration Issues**:
- Verify minisplit WiFi connection
- Check for firmware updates on minisplit
- Restart minisplit WiFi module if available

**State Synchronization Issues**:
```yaml
# Force state update
Developer Tools → Services
Service: homeassistant.update_entity
Entity: climate.your_minisplit_entity
```

### 5. Temperature Control Accuracy

**Symptoms**:
- Room temperature doesn't reach target
- Overshooting target temperature
- Frequent mode switching

**Diagnostic Steps**:
1. Check learned offset value and confidence
2. Verify sensor placement and calibration
3. Monitor temperature trends over time

**Solutions**:

**Inaccurate Temperature Control**:
```yaml
# Check current learned offset
sensor.smart_thermostat_learned_offset
# Should show value like "5.2" after learning period

# Check offset confidence
sensor.smart_thermostat_offset_confidence
# Should be above 0.7 for reliable offset
```

**Manual Offset Adjustment**:
If learning isn't working well, manually adjust the offset:
1. Go to integration configuration
2. Adjust "Default Cooling Offset" based on observed behavior
3. Monitor for 24-48 hours and adjust as needed

**Sensor Placement Issues**:
- Ensure sensor is at same height as occupants
- Avoid direct sunlight, heat sources, or drafts
- Place sensor away from minisplit air flow
- Consider averaging multiple sensors for large rooms

### 6. Humidity Control Issues

**Symptoms**:
- Dry mode not activating when humid
- Excessive dehumidification
- Humidity readings seem incorrect

**Diagnostic Steps**:
1. Verify humidity sensor accuracy with reference device
2. Check humidity thresholds are appropriate for climate
3. Monitor humidity trends and minisplit dry mode effectiveness

**Solutions**:

**Humidity Sensor Calibration**:
```yaml
# Check humidity sensor state
Developer Tools → States → sensor.your_humidity_sensor
# Compare with weather station or reference hygrometer
```

**Threshold Adjustment**:
- Hot, humid climates: Lower max threshold (45-55%)
- Dry climates: Raise max threshold (65-75%)
- Consider seasonal adjustments

**Dry Mode Not Working**:
- Verify minisplit supports dry/dehumidify mode
- Check IR codes include dry mode commands
- Some units may not have effective dry mode

### 7. Learning Algorithm Issues

**Symptoms**:
- Learned offset not changing over time
- Low confidence in learned offset
- Erratic offset values

**Diagnostic Steps**:
1. Check data collection is working (logs should show data points)
2. Verify minisplit is actually cooling during data collection
3. Ensure sufficient runtime for learning (at least 7 days)

**Solutions**:

**Insufficient Data**:
```yaml
# Check learning status in logs
# Should see entries like:
# "Collected temperature data point: external=72.1, internal=77.3"
```

**Poor Learning Conditions**:
- Ensure minisplit runs in cooling mode regularly
- Avoid manual overrides during initial learning period
- Consider longer learning period (14+ days) for variable conditions

**Reset Learning Data**:
If learning data seems corrupted:
1. Go to integration options
2. Disable learning temporarily
3. Re-enable learning to start fresh

### 8. Cooldown and Timing Issues

**Symptoms**:
- Mode changes delayed too long
- Rapid mode switching despite cooldown
- Cooldown timer not working correctly

**Diagnostic Steps**:
1. Check cooldown remaining sensor
2. Verify cooldown period configuration
3. Monitor mode change timestamps in logs

**Solutions**:

**Cooldown Too Long**:
- Reduce cooldown period in configuration
- Consider different cooldowns for different transitions
- Balance equipment protection vs. responsiveness

**Cooldown Not Working**:
```yaml
# Check cooldown status
sensor.smart_thermostat_cooldown_remaining
# Should show seconds remaining after mode change
```

**Emergency Override**:
For urgent situations, you can force immediate mode changes:
1. Enable manual override
2. Set desired mode directly on minisplit
3. Return to auto mode when ready

## Advanced Troubleshooting

### Debug Logging

Enable debug logging for detailed troubleshooting:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.smart_thermostat_controller: debug
```

This will provide detailed logs including:
- Sensor reading timestamps and values
- Control decision reasoning
- Learning algorithm calculations
- Error details and stack traces

### Performance Issues

**Symptoms**:
- Home Assistant becomes slow
- High CPU usage
- Memory usage increasing over time

**Solutions**:
- Reduce sensor update frequency
- Increase data cleanup intervals
- Check for memory leaks in logs
- Consider reducing learning data retention period

### Integration Conflicts

**Symptoms**:
- Other climate integrations interfering
- Sensor readings inconsistent
- Unexpected automation triggers

**Solutions**:
- Disable conflicting climate automations
- Use unique entity names
- Check for duplicate sensor usage
- Review automation triggers and conditions

## Getting Help

### Information to Collect

When reporting issues, please provide:

1. **Home Assistant Version**: `Settings → About`
2. **Integration Version**: Check HACS or manual installation
3. **Configuration**: Sanitized configuration (remove sensitive data)
4. **Logs**: Relevant log entries with timestamps
5. **Hardware Details**: Sensor and minisplit models
6. **Environment**: Room size, climate, typical usage patterns

### Log Collection

```bash
# Collect relevant logs
grep -i "smart_thermostat" /config/home-assistant.log > smart_thermostat_logs.txt

# Or use Home Assistant log viewer
Settings → System → Logs → Download full log
```

### Diagnostic Information

```yaml
# Run diagnostic service (if available)
Developer Tools → Services
Service: smart_thermostat_controller.get_diagnostics
Entity: climate.smart_thermostat_your_device
```

### Support Channels

1. **GitHub Issues**: For bugs and feature requests
2. **Home Assistant Community**: For general questions and discussion
3. **Discord/Reddit**: For real-time community support

## Preventive Maintenance

### Regular Checks

1. **Monthly**:
   - Verify sensor battery levels
   - Check learned offset stability
   - Review error logs

2. **Seasonally**:
   - Adjust humidity thresholds for climate changes
   - Update temperature preferences
   - Clean sensors and minisplit filters

3. **Annually**:
   - Update integration to latest version
   - Review and optimize configuration
   - Check sensor calibration accuracy

### Best Practices

- Keep sensors clean and unobstructed
- Maintain stable network connectivity
- Regular Home Assistant backups
- Document configuration changes
- Monitor system performance metrics