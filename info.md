# Smart Thermostat Controller

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

A Home Assistant custom integration that provides intelligent climate control for minisplit units with unreliable internal thermostats.

## Features

- **External Sensor Integration**: Uses external temperature and humidity sensors instead of unreliable minisplit thermostats
- **Intelligent Mode Switching**: Automatically switches between heating, cooling, and dehumidifying based on conditions  
- **Learning Algorithm**: Learns and compensates for thermostat offset over time for improved accuracy
- **Equipment Protection**: Implements cooldown periods to prevent rapid mode switching that could damage equipment
- **Manual Override**: Allows manual control when needed while maintaining monitoring and learning
- **Comprehensive Monitoring**: Provides detailed status sensors and logging for troubleshooting

## Installation

1. Install via HACS (recommended) or manually download the integration
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "Smart Thermostat Controller"
5. Follow the configuration wizard to set up your sensors and preferences

## Configuration

The integration requires:
- External temperature sensor entity
- Minisplit climate entity
- Optional: External humidity sensor entity

Configure temperature thresholds, humidity limits, cooldown periods, and learning parameters through the UI.

## Support

- [Documentation](https://github.com/your-repo/smart-thermostat-controller)
- [Issue Tracker](https://github.com/your-repo/smart-thermostat-controller/issues)
- [Community Forum](https://community.home-assistant.io/)

[commits-shield]: https://img.shields.io/github/commit-activity/y/your-repo/smart-thermostat-controller.svg?style=for-the-badge
[commits]: https://github.com/your-repo/smart-thermostat-controller/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/your-repo/smart-thermostat-controller.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/your-repo/smart-thermostat-controller.svg?style=for-the-badge
[releases]: https://github.com/your-repo/smart-thermostat-controller/releases