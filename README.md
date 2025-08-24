# Smart Thermostat Controller

A Home Assistant custom integration that provides intelligent climate control for minisplit units with unreliable internal thermostats. The system uses external sensors for accurate temperature and humidity readings, implements learning algorithms to compensate for thermostat offset, and provides intelligent mode switching with cooldown protection.

## Features

- **External Sensor Integration**: Uses external temperature and humidity sensors instead of unreliable minisplit thermostats
- **Intelligent Mode Switching**: Automatically switches between heating, cooling, and dehumidifying based on conditions
- **Learning Algorithm**: Learns and compensates for thermostat offset over time for improved accuracy
- **Equipment Protection**: Implements cooldown periods to prevent rapid mode switching that could damage equipment
- **Manual Override**: Allows manual control when needed while maintaining monitoring and learning
- **Comprehensive Monitoring**: Provides detailed status sensors and logging for troubleshooting

## Installation

### HACS Installation (Recommended)

1. Open HACS in your Home Assistant instance
2. Go to "Integrations"
3. Click the three dots in the top right corner and select "Custom repositories"
4. Add this repository URL and select "Integration" as the category
5. Click "Install" on the Smart Thermostat Controller integration
6. Restart Home Assistant

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/your-repo/smart-thermostat-controller/releases)
2. Extract the contents to your `custom_components` directory:
   ```
   custom_components/
   └── smart_thermostat_controller/
       ├── __init__.py
       ├── climate.py
       ├── config_flow.py
       ├── const.py
       ├── control_manager.py
       ├── cooldown_manager.py
       ├── coordinator.py
       ├── error_handling.py
       ├── learning_manager.py
       ├── logging_utils.py
       ├── manifest.json
       ├── models.py
       ├── sensor.py
       └── strings.json
   ```
3. Restart Home Assistant

## Setup

### Prerequisites

Before setting up the Smart Thermostat Controller, ensure you have:

1. **External Temperature Sensor**: A reliable temperature sensor entity in Home Assistant
2. **External Humidity Sensor**: A humidity sensor entity (optional but recommended)
3. **Minisplit Climate Entity**: Your minisplit unit integrated into Home Assistant
4. **Stable Network**: Reliable communication between sensors and Home Assistant

### Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Smart Thermostat Controller" and select it
3. Follow the configuration wizard:

#### Step 1: Entity Selection
- **Temperature Sensor**: Select your external temperature sensor
- **Humidity Sensor**: Select your external humidity sensor (optional)
- **Minisplit Entity**: Select your minisplit climate entity

#### Step 2: Temperature Settings
- **Target Temperature**: Set your desired temperature (default: 72°F)
- **Temperature Deadband**: Temperature tolerance before switching modes (default: 1.0°F)
- **Default Cooling Offset**: Initial offset for cooling mode (default: 5.0°F)

#### Step 3: Humidity Settings
- **Maximum Humidity**: Humidity level that triggers dry mode (default: 60%)
- **Minimum Humidity**: Lower humidity threshold (default: 40%)

#### Step 4: Advanced Settings
- **Cooldown Period**: Minimum time between mode changes (default: 300 seconds)
- **Learning Enabled**: Enable automatic offset learning (default: true)
- **Learning Period**: Days of data for offset calculation (default: 7 days)

## Usage

### Basic Operation

Once configured, the Smart Thermostat Controller will:

1. **Monitor Conditions**: Continuously read external temperature and humidity sensors
2. **Make Decisions**: Determine the optimal HVAC mode based on current conditions
3. **Control Minisplit**: Send commands to your minisplit unit with appropriate timing
4. **Learn and Adapt**: Collect data to improve temperature control accuracy over time

### Climate Entity

The integration creates a climate entity named `climate.smart_thermostat_[device_name]` with these features:

- **Temperature Control**: Set target temperature through the Home Assistant UI
- **Mode Selection**: Choose between Auto, Heat, Cool, Dry, and Off modes
- **Current Readings**: View current temperature and humidity from external sensors
- **Status Information**: See current HVAC action and system status

### Status Sensors

The integration provides several sensors for monitoring:

- `sensor.smart_thermostat_current_mode`: Current operating mode
- `sensor.smart_thermostat_learned_offset`: Current learned temperature offset
- `sensor.smart_thermostat_offset_confidence`: Confidence level in learned offset
- `sensor.smart_thermostat_cooldown_remaining`: Time until next mode change allowed
- `sensor.smart_thermostat_manual_override`: Manual override status

### Manual Override

To temporarily take manual control:

1. Use the climate entity to set your desired mode
2. The system will respect your choice and enter manual override mode
3. Automatic control resumes after you return to "Auto" mode
4. Learning continues even during manual override

## Configuration Examples

See [CONFIGURATION_EXAMPLES.md](docs/CONFIGURATION_EXAMPLES.md) for detailed examples of common setups.

## Troubleshooting

See [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for solutions to common issues.

## API Documentation

See [API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) for advanced configuration options and automation examples.

## Support

- **Issues**: Report bugs and feature requests on [GitHub Issues](https://github.com/your-repo/smart-thermostat-controller/issues)
- **Discussions**: Join the community discussion on [GitHub Discussions](https://github.com/your-repo/smart-thermostat-controller/discussions)
- **Home Assistant Community**: Visit the [Home Assistant Community Forum](https://community.home-assistant.io/)

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and contribute to the project.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a detailed history of changes and updates.