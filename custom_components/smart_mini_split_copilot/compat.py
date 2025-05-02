"""Smart Mini Split Controller compatibility module."""
from enum import Enum

# Import compatibility layer for Home Assistant constants that move between versions
try:
    # Try the most recent locations first (Home Assistant 2023+)
    from homeassistant.const import (
        CONF_ENTITY_ID,
        ATTR_ENTITY_ID,
        CONF_NAME,
        ATTR_TEMPERATURE,
        UnitOfTemperature,
    )
except ImportError:
    # Fall back for older Home Assistant versions
    from homeassistant.const import (
        CONF_ENTITY_ID,
        ATTR_ENTITY_ID,
        CONF_NAME,
    )
    
    # Handle temperature attribute
    try:
        from homeassistant.const import ATTR_TEMPERATURE
    except ImportError:
        try:
            from homeassistant.components.climate.const import ATTR_TEMPERATURE
        except ImportError:
            ATTR_TEMPERATURE = "temperature"  # Final fallback
    
    # Handle temperature units
    try:
        from homeassistant.const import UnitOfTemperature
    except ImportError:
        try:
            from homeassistant.components.climate.const import UnitOfTemperature
        except ImportError:
            from enum import Enum
            # Create our own version if all else fails
            class UnitOfTemperature(str, Enum):
                """Temperature units."""
                CELSIUS = "°C"
                FAHRENHEIT = "°F"

# Climate domain constants
try:
    from homeassistant.components.climate.const import (
        DOMAIN as CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
    )
except ImportError:
    # Fall back to hardcoded values if needed
    CLIMATE_DOMAIN = "climate"
    try:
        from homeassistant.const import SERVICE_SET_TEMPERATURE
    except ImportError:
        SERVICE_SET_TEMPERATURE = "set_temperature"
