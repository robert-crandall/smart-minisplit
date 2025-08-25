# Smart Mini Split Controller

**Intelligently control your mini split heat pump with external temperature sensors**

This integration allows you to use an external temperature sensor to control your mini split unit more accurately than relying solely on the unit's internal temperature sensor. Perfect for situations where your mini split's internal sensor doesn't accurately represent the room temperature.

## Key Features

🌡️ **External Temperature Control** - Uses your own temperature sensor for more accurate climate control  
⏱️ **Smart Cooldown** - Prevents frequent adjustments with configurable wait periods  
🔥 **Intelligent Heating** - Custom heating thresholds and overshoot protection  
❄️ **Smart Cooling** - Automatic cooling with humidity-based dry mode  
📝 **Comprehensive Logging** - All actions logged to Home Assistant logbook  
⚙️ **Flexible Configuration** - Highly configurable thresholds and timing

## Perfect For

- Mini splits with inaccurate internal temperature sensors
- Rooms where the mini split location doesn't represent the actual room temperature
- Advanced climate control with multiple temperature zones
- Users who want detailed logging and control over their HVAC system

## Requirements

- A Home Assistant-compatible mini split (climate entity)
- External temperature sensor (any Home Assistant sensor)
- Optional: External humidity sensor for enhanced dry mode functionality

## Quick Setup

1. Install via HACS
2. Add configuration to `configuration.yaml`
3. Create required input helpers (booleans, numbers, datetime)
4. Restart Home Assistant
5. Enjoy intelligent climate control!

The integration runs automatically every minute, making smart decisions about when to heat, cool, or maintain your desired temperature.
