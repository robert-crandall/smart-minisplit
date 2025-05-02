"""Smart Mini Split Controller integration for Home Assistant."""
import asyncio
import logging
from datetime import datetime, timedelta
import voluptuous as vol
import json
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.storage import Store
# Import from our compatibility layer to handle different Home Assistant versions
from .compat import (
    CONF_ENTITY_ID,
    ATTR_ENTITY_ID,
    CONF_NAME,
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    CLIMATE_DOMAIN,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components.logbook import log_entry
import homeassistant.helpers.entity_registry as er

_LOGGER = logging.getLogger(__name__)

DOMAIN = "smart_mini_split"

# Storage constants
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.state"
STORAGE_REAL_SETPOINT_KEY = "real_setpoint"
STORAGE_LAST_ADJUSTMENT_KEY = "last_adjustment"

CONF_EXTERNAL_SENSOR = "external_sensor"
CONF_VALID_RANGE = "valid_range"
CONF_ADJUSTMENT_STEP = "adjustment_step"
CONF_TRIGGER_THRESHOLD = "trigger_threshold"
CONF_RESET_THRESHOLD = "reset_threshold"
CONF_COOLDOWN_MINUTES = "cooldown_minutes"
CONF_LOG_LEVEL = "log_level"

DEFAULT_VALID_RANGE = [63, 72]
DEFAULT_ADJUSTMENT_STEP = 10
DEFAULT_TRIGGER_THRESHOLD = 2
DEFAULT_RESET_THRESHOLD = 1
DEFAULT_COOLDOWN_MINUTES = 5
DEFAULT_LOG_LEVEL = "info"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): cv.entity_id,
                vol.Required(CONF_EXTERNAL_SENSOR): cv.entity_id,
                vol.Optional(CONF_VALID_RANGE, default=DEFAULT_VALID_RANGE): vol.All(
                    vol.Length(min=2, max=2), [vol.Coerce(float)]
                ),
                vol.Optional(
                    CONF_ADJUSTMENT_STEP, default=DEFAULT_ADJUSTMENT_STEP
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_TRIGGER_THRESHOLD, default=DEFAULT_TRIGGER_THRESHOLD
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_RESET_THRESHOLD, default=DEFAULT_RESET_THRESHOLD
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_COOLDOWN_MINUTES, default=DEFAULT_COOLDOWN_MINUTES
                ): vol.Coerce(int),
                vol.Optional(CONF_LOG_LEVEL, default=DEFAULT_LOG_LEVEL): vol.In(
                    ["info", "debug"]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_FORCE_ADJUSTMENT = "force_adjustment"
SERVICE_TOGGLE_AUTOMATION = "toggle_automation"
SERVICE_CLEAR_OVERRIDE = "clear_override"

SERVICE_FORCE_ADJUSTMENT_SCHEMA = vol.Schema({})
SERVICE_TOGGLE_AUTOMATION_SCHEMA = vol.Schema(
    {vol.Required("enabled"): cv.boolean}
)
SERVICE_CLEAR_OVERRIDE_SCHEMA = vol.Schema({})

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Smart Mini Split integration."""
    if DOMAIN not in config:
        return True

    controller = SmartMiniSplitController(hass, config[DOMAIN])
    hass.data[DOMAIN] = controller

    await controller.async_initialize()

    # Register services
    async def handle_force_adjustment(call: ServiceCall):
        """Handle the force adjustment service call."""
        await controller.async_force_adjustment()

    async def handle_toggle_automation(call: ServiceCall):
        """Handle the toggle automation service call."""
        enabled = call.data["enabled"]
        await controller.async_toggle_automation(enabled)

    async def handle_clear_override(call: ServiceCall):
        """Handle the clear override service call."""
        await controller.async_clear_override()

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_ADJUSTMENT,
        handle_force_adjustment,
        schema=SERVICE_FORCE_ADJUSTMENT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_TOGGLE_AUTOMATION,
        handle_toggle_automation,
        schema=SERVICE_TOGGLE_AUTOMATION_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_OVERRIDE,
        handle_clear_override,
        schema=SERVICE_CLEAR_OVERRIDE_SCHEMA,
    )

    return True


class SmartMiniSplitController:
    """Class to control a mini split based on external temperature sensor."""

    def __init__(self, hass: HomeAssistant, config: dict):
        """Initialize the controller."""
        self.hass = hass
        self.entity_id = config[CONF_ENTITY_ID]
        self.external_sensor = config[CONF_EXTERNAL_SENSOR]
        self.valid_range = config[CONF_VALID_RANGE]
        self.adjustment_step = config[CONF_ADJUSTMENT_STEP]
        self.trigger_threshold = config[CONF_TRIGGER_THRESHOLD]
        self.reset_threshold = config[CONF_RESET_THRESHOLD]
        self.cooldown_minutes = config[CONF_COOLDOWN_MINUTES]
        self.log_level = config[CONF_LOG_LEVEL]
        self.temperature_unit = UnitOfTemperature.FAHRENHEIT  # Default to Fahrenheit
        
        # Create storage for persistent data
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        
        self.last_adjustment_time = None
        self.override_detected = False
        self.automation_enabled = True
        self.real_setpoint = None
        self.max_setpoint = None
        self._unsubscribe_timer = None

    async def async_initialize(self):
        """Initialize the controller by setting up timer."""
        # Load saved state from storage first
        await self._load_state()

        # Get reference to mini split max temperature
        climate_state = self.hass.states.get(self.entity_id)
        if climate_state is not None:
            self.max_setpoint = climate_state.attributes.get("max_temp")
            
        # Get the desired temperature, which will either use current settings or restore from storage
        desired_temp = await self.desired_temperature()
        
        if desired_temp is not None:
            self.log_message(f"Initial desired setpoint is {desired_temp}°{self.temperature_unit}", "info")
        else:
            self.log_message("No valid desired temperature available during initialization", "info")

        # Set up the timer to check temperatures every minute
        interval = timedelta(minutes=1)
        self._unsubscribe_timer = async_track_time_interval(
            self.hass, self.async_check_temperatures, interval
        )
        
        self.log_message("Smart Mini Split Controller initialized", "info")

    async def async_check_temperatures(self, now=None):
        """Compare external temperature with the set temperature and adjust if needed."""
        if not self.automation_enabled:
            self.log_message("Automation disabled, skipping check", "debug")
            return
        
        # Check if we're in cooldown period
        in_cooldown = False
        if self.last_adjustment_time is not None:
            time_since_last = datetime.now() - self.last_adjustment_time
            if time_since_last < timedelta(minutes=self.cooldown_minutes):
                remaining = self.cooldown_minutes - (time_since_last.seconds // 60)
                self.log_message(f"In cooldown period, {remaining} minutes remaining", "debug")
                in_cooldown = True
        
        # Get current states
        climate_state = self.hass.states.get(self.entity_id)
        sensor_state = self.hass.states.get(self.external_sensor)
        
        if climate_state is None or sensor_state is None:
            self.log_message(f"Missing state data: Climate: {climate_state}, Sensor: {sensor_state}", "info")
            return
        
        # Get temperature values
        current_setpoint = climate_state.attributes.get(ATTR_TEMPERATURE)
        external_temp = float(sensor_state.state)
        
        if current_setpoint is None:
            self.log_message("Current setpoint is None, skipping check", "info")
            return
            
        # Get the desired temperature using our new function
        desired_temp = await self.desired_temperature()
        
        # If we don't have a desired temperature yet, we can't make adjustments
        if desired_temp is None:
            self.log_message("No valid desired temperature determined, skipping check", "info")
            return
            
        # Check for manual override (if current setpoint changed to be within valid range)
        if self.valid_range[0] <= current_setpoint <= self.valid_range[1] and self.real_setpoint != current_setpoint:
            self.override_detected = True
            self.log_message(f"Manual override detected. New setpoint: {current_setpoint}°{self.temperature_unit}", "info")
            return  # Skip this check to honor the manual change
            
        # Calculate the temperature difference
        temp_diff = external_temp - desired_temp
        
        self.log_message(
            f"Check: External temp: {external_temp}°{self.temperature_unit}, Desired setpoint: {desired_temp}°{self.temperature_unit}, "
            f"Current setpoint: {current_setpoint}°{self.temperature_unit}, Delta: {temp_diff}°{self.temperature_unit}, "
            f"Cooldown: {in_cooldown}, Override: {self.override_detected}",
            "debug" if self.log_level == "debug" else "info"
        )
        
        # Skip if in cooldown or manual override
        if in_cooldown or self.override_detected:
            if self.override_detected:
                self.log_message("Manual override active, skipping adjustment", "debug")
                # Clear override after one check
                self.override_detected = False
            return
            
        # Determine if adjustment is needed
        if abs(temp_diff) > self.trigger_threshold:
            if not in_cooldown:
                await self._adjust_temperature(temp_diff)
        elif abs(temp_diff) <= self.reset_threshold and current_setpoint != desired_temp:
            # Reset to desired setpoint when temperature stabilizes
            await self._reset_to_desired_setpoint()

    async def _adjust_temperature(self, temp_diff):
        """Adjust the temperature setting based on temperature difference."""
        # Get the current desired temperature
        desired_temp = await self.desired_temperature()
        if desired_temp is None:
            self.log_message("Cannot adjust temperature: no valid desired temperature", "info")
            return
            
        # Determine direction of adjustment
        if temp_diff > 0:  # External temperature is higher than setpoint
            new_setpoint = desired_temp + self.adjustment_step
            reason = f"External temperature {temp_diff}°{self.temperature_unit} higher than setpoint"
        else:  # External temperature is lower than setpoint
            new_setpoint = desired_temp - self.adjustment_step
            reason = f"External temperature {abs(temp_diff)}°{self.temperature_unit} lower than setpoint"

        if self.max_setpoint is not None and new_setpoint > self.max_setpoint:
            new_setpoint = self.max_setpoint
            reason += f", capped at max setpoint {self.max_setpoint}°{self.temperature_unit}"
        
        # Call service to set new temperature
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: self.entity_id, ATTR_TEMPERATURE: new_setpoint},
            blocking=True,
        )
        
        # Update last adjustment time
        self.last_adjustment_time = datetime.now()
        
        # Save state to storage
        await self._save_state()
        
        # Log the adjustment
        self.log_message(
            f"Adjusted setpoint from {desired_temp}°{self.temperature_unit} to {new_setpoint}°{self.temperature_unit}: {reason}",
            "info"
        )

    async def _reset_to_desired_setpoint(self):
        """Reset the temperature to the desired setpoint."""
        climate_state = self.hass.states.get(self.entity_id)
        current_setpoint = climate_state.attributes.get(ATTR_TEMPERATURE)
        
        # Get the desired temperature
        desired_temp = await self.desired_temperature()
        if desired_temp is None:
            self.log_message("Cannot reset temperature: no valid desired temperature", "info")
            return
            
        if current_setpoint == desired_temp:
            return  # No need to adjust if already at desired setpoint
            
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: self.entity_id, ATTR_TEMPERATURE: desired_temp},
            blocking=True,
        )
        
        self.last_adjustment_time = datetime.now()
        
        # Save state to storage
        await self._save_state()
        
        self.log_message(
            f"Reset from {current_setpoint}°{self.temperature_unit} to desired setpoint {desired_temp}°{self.temperature_unit}: "
            f"External temperature within tolerance",
            "info"
        )

    async def _load_state(self):
        """Load state from storage."""
        data = await self._store.async_load()
        if data:
            _LOGGER.debug("Loaded stored state: %s", data)
            if STORAGE_REAL_SETPOINT_KEY in data:
                self.real_setpoint = data[STORAGE_REAL_SETPOINT_KEY]
                _LOGGER.debug("Loaded real setpoint: %s", self.real_setpoint)
            
            if STORAGE_LAST_ADJUSTMENT_KEY in data:
                try:
                    self.last_adjustment_time = datetime.fromisoformat(data[STORAGE_LAST_ADJUSTMENT_KEY])
                    _LOGGER.debug("Loaded last adjustment time: %s", self.last_adjustment_time)
                except (ValueError, TypeError):
                    self.last_adjustment_time = None

    async def _save_state(self):
        """Save state to storage."""
        data = {
            STORAGE_REAL_SETPOINT_KEY: self.real_setpoint
        }
        
        if self.last_adjustment_time:
            data[STORAGE_LAST_ADJUSTMENT_KEY] = self.last_adjustment_time.isoformat()
        
        _LOGGER.debug("Saving state: %s", data)
        await self._store.async_save(data)

    async def async_force_adjustment(self):
        """Force an immediate temperature check and adjustment."""
        self.log_message("Forced adjustment requested", "info")
        self.last_adjustment_time = None  # Clear cooldown timer
        await self.async_check_temperatures()

    async def async_toggle_automation(self, enabled):
        """Toggle the automation on or off."""
        self.automation_enabled = enabled
        state = "enabled" if enabled else "disabled"
        self.log_message(f"Automation {state}", "info")

    async def async_clear_override(self):
        """Clear any manual override flags."""
        self.override_detected = False
        self.log_message("Manual override cleared", "info")

    async def desired_temperature(self):
        """Get the desired temperature setpoint.
        
        Checks set point of climate entity. If it's within valid range, it uses that, 
        then updates storage if it differs from stored value.
        If set_temperature of climate entity is not within range, it gets the value from storage.
        
        Returns:
            float: The desired temperature setpoint or None if no valid temperature is available.
        """
        # Get current state from climate entity
        climate_state = self.hass.states.get(self.entity_id)
        if climate_state is None:
            self.log_message("Climate entity not available, using stored setpoint", "debug")
            return self.real_setpoint
            
        current_setpoint = climate_state.attributes.get(ATTR_TEMPERATURE)
        
        # Case 1: Current setpoint is within valid range - use it as the desired temperature
        if current_setpoint is not None and self.valid_range[0] <= current_setpoint <= self.valid_range[1]:
            if self.real_setpoint != current_setpoint:
                # Update stored value if different
                self.log_message(f"Updating stored setpoint from {self.real_setpoint}°{self.temperature_unit} to {current_setpoint}°{self.temperature_unit}", "debug")
                self.real_setpoint = current_setpoint
                await self._save_state()
            return current_setpoint
            
        # Case 2: Current setpoint is outside valid range - use stored value
        if self.real_setpoint is not None:
            self.log_message(f"Using stored setpoint: {self.real_setpoint}°{self.temperature_unit}", "debug")
            return self.real_setpoint
            
        # Case 3: No valid temperature available
        self.log_message("No valid temperature setpoint available", "info")
        return None

    def log_message(self, message, level="info"):
        """Log message to Home Assistant logbook and logger."""
        if level == "debug" and self.log_level != "debug":
            # Only log debug messages if debug logging is enabled
            return
            
        # Log to HA logbook
        log_entry(
            self.hass,
            "Smart Mini Split",
            message,
            DOMAIN,
        )
        
        # Log to logger
        if level == "debug":
            _LOGGER.debug(message)
        else:
            _LOGGER.info(message)
