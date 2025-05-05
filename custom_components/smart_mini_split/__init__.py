from datetime import timedelta, datetime
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
try:
    from homeassistant.components.logbook import log_entry
except ImportError:
    # Create a fallback if logbook is not available
    def log_entry(hass, name, message, domain):
        pass

_LOGGER = logging.getLogger(__name__)

DOMAIN = "smart_mini_split"
DEFAULT_COOLDOWN_MINUTES = 5
DEFAULT_TRIGGER_THRESHOLD = 2.0  # Degrees
DEFAULT_RESET_THRESHOLD = 1.0
DEFAULT_VALID_TEMP_RANGE = [60, 74]
DEFAULT_LOG_LEVEL = "info"
DEFAULT_CLIMATE_ENTITY = "climate.minisplit"
DEFAULT_EXTERNAL_TEMP_SENSOR = "sensor.awair_element_110243_temperature"

async def async_setup(hass: HomeAssistant, config: ConfigType):
    # Read options from configuration, with defaults
    domain_config = config.get(DOMAIN, {})
    enabled = domain_config.get("enabled", True)
    if not enabled:
        _LOGGER.info("Smart Mini Split integration is disabled via configuration.")
        return True
    log_level = domain_config.get("log_level", DEFAULT_LOG_LEVEL)
    cooldown_minutes = domain_config.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
    trigger_threshold = domain_config.get("trigger_threshold", DEFAULT_TRIGGER_THRESHOLD)
    reset_threshold = domain_config.get("reset_threshold", DEFAULT_RESET_THRESHOLD)
    valid_temp_range = domain_config.get("valid_temp_range", DEFAULT_VALID_TEMP_RANGE)
    climate_entity = domain_config.get("climate_entity", DEFAULT_CLIMATE_ENTITY)
    external_temp_sensor = domain_config.get("external_temp_sensor", DEFAULT_EXTERNAL_TEMP_SENSOR)
    controller = MiniSplitController(
        hass,
        log_level=log_level,
        cooldown_minutes=cooldown_minutes,
        trigger_threshold=trigger_threshold,
        reset_threshold=reset_threshold,
        valid_temp_range=valid_temp_range,
        climate_entity=climate_entity,
        external_temp_sensor=external_temp_sensor,
    )
    async def run_update(now):
        await controller.update(now)
    async_track_time_interval(hass, run_update, timedelta(minutes=1))
    return True

class MiniSplitController:
    def __init__(self, hass: HomeAssistant, log_level: str = "info", cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES, trigger_threshold: float = DEFAULT_TRIGGER_THRESHOLD, reset_threshold: float = DEFAULT_RESET_THRESHOLD, valid_temp_range = DEFAULT_VALID_TEMP_RANGE, climate_entity: str = DEFAULT_CLIMATE_ENTITY, external_temp_sensor: str = DEFAULT_EXTERNAL_TEMP_SENSOR):
        self.hass = hass
        self.last_adjustment: datetime | None = None
        self.last_desired_temp: float | None = None
        self.adjusted_state_active: bool = False
        self.log_level = log_level.lower()
        self.cooldown_minutes = cooldown_minutes
        self.trigger_threshold = trigger_threshold
        self.reset_threshold = reset_threshold
        self.valid_temp_range = valid_temp_range
        self.climate_entity = climate_entity
        self.external_temp_sensor = external_temp_sensor

    def debug_entity_attributes(self, entity_id: str = None) -> None:
        """Debug helper to print all attributes of an entity."""
        if entity_id is None:
            entity_id = self.climate_entity
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None:
            self.log_message(f"Entity {entity_id} not found", "warning")
            return
        self.log_message(f"Entity {entity_id} state: {state_obj.state}", "debug")
        self.log_message(f"Entity {entity_id} attributes:", "debug")
        for attr, value in state_obj.attributes.items():
            self.log_message(f"  - {attr}: {value}", "debug")

    def in_cooldown(self) -> bool:
        if not self.last_adjustment:
            return False
        return (datetime.now() - self.last_adjustment) < timedelta(minutes=self.cooldown_minutes)

    def get_set_temperature(self) -> float | None:
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state is None:
            self.log_message("Climate entity not available yet.", "warning")
            return None
        set_temp = climate_state.attributes.get("temperature")
        if set_temp is not None:
            return set_temp
        self.log_message("Set temperature not available yet.", "warning")
        # Debug all available attributes to see what's available
        self.debug_entity_attributes(self.climate_entity)
        return None

    def current_temperature(self) -> float | None:
        sensor_state = self.hass.states.get(self.external_temp_sensor)
        if sensor_state is None:
            self.log_message("Temperature sensor not available", "warning")
            return None
        try:
            return float(sensor_state.state)
        except (ValueError, TypeError):
            self.log_message(f"Invalid temperature sensor value: {sensor_state.state}", "warning")
            return None

    def desired_temperature(self) -> float | None:
        set_temp = self.get_set_temperature()
        if set_temp is not None and self.valid_temp_range[0] <= set_temp <= self.valid_temp_range[1]:
            if self.last_desired_temp is None:
                self.log_message(f"Set temperature successfully read. Desired temperature set to {set_temp}", "info")
            self.last_desired_temp = set_temp
            self.adjusted_state_active = False
            return set_temp
        if self.last_desired_temp is not None:
            self.log_message(f"Set temperature could not read a valid temperature. Using last desired temperature: {self.last_desired_temp}", "debug")
            return self.last_desired_temp
        if set_temp is not None:
            # Set temperature is out of range, but no last desired temperature is available.
            # This is likely due to overheating or cooling, and hass was reset.
            default_temp = int((self.valid_temp_range[0] + self.valid_temp_range[1]) / 2)
            self.log_message(f"Set temperature is out of normal range. Defaulting to {default_temp}", "info")
            return default_temp
        self.log_message(f"Desired temperature could not be read. Likely due to system starting up.", "debug")
        return None

    def needs_heat(self, current: float, desired: float) -> bool:
        if current is None or desired is None:
            return False
        return current < (desired - self.trigger_threshold)

    def needs_cooling(self, current: float, desired: float) -> bool:
        if current is None or desired is None:
            return False
        offset = getattr(self, "cooling_trigger_offset", 2.0)
        return current > (desired + offset)

    def cooling_allowed_now(self) -> bool:
        if not getattr(self, "day_cooling_enabled", False):
            return False
        current_hour = datetime.now().hour
        return current_hour < getattr(self, "cooling_cutoff_hour", 17)

    def should_reset(self, current: float, desired: float) -> bool:
        if current is None or desired is None:
            return False
        return self.adjusted_state_active and current >= (desired + self.reset_threshold)

    async def adjust_set_temperature(self, target_temp: float):
        climate_state = self.hass.states.get(self.climate_entity)
        min_temp = climate_state.attributes.get("min_temp", 55) if climate_state else 55
        max_temp = climate_state.attributes.get("max_temp", 82) if climate_state else 82
        if min_temp is not None:
            target_temp = max(min_temp, target_temp)
        if max_temp is not None:
            target_temp = min(max_temp, target_temp)
        self.log_message(f"Adjusting set temperature to {target_temp}", "info")
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {
                "entity_id": self.climate_entity,
                "temperature": target_temp
            },
            blocking=True,
        )
        self.last_adjustment = datetime.now()
        self.adjusted_state_active = True

    async def reset_set_temperature(self):
        self.log_message(f"Resetting temperature to {self.last_desired_temp}", "info")
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {
                "entity_id": self.climate_entity,
                "temperature": self.last_desired_temp
            },
            blocking=True,
        )
        self.last_adjustment = datetime.now()
        self.adjusted_state_active = False

    @callback
    async def update(self, now):
        if self.in_cooldown():
            return

        current = self.current_temperature()
        desired = self.desired_temperature()

        # Skip if we don't have valid temperature readings
        if current is None or desired is None:
            self.log_message("Skipping update: missing temperature data", "debug")
            return

        if self.needs_heat(current, desired):
            self.log_message(f"Needs heat. Current={current}, Desired={desired}, Adjusted={self.adjusted_state_active}", "debug")
            await self.adjust_set_temperature(82)
        elif self.should_reset(current, desired):
            self.log_message(f"Needs to reset set temperature. Current={current}, Desired={desired}, Adjusted={self.adjusted_state_active}", "debug")
            await self.reset_set_temperature()
        else:
            if self.adjusted_state_active:
                self.log_message(f"No adjustment needed, but adjusted state is active. Current={current}, Desired={desired}, Adjusted={self.adjusted_state_active}", "debug")
            else:
                self.log_message(f"No adjustment needed and not adjusted state. Current={current}, Desired={desired}, Adjusted={self.adjusted_state_active}", "debug")

    def log_message(self, message, level="info"):
        """Log message to Home Assistant logbook and logger, respecting configured log level."""
        # Only log debug messages if log_level is 'debug'
        if level == "debug" and self.log_level != "debug":
            return
        if level == "debug":
            _LOGGER.debug(message)
        elif level == "warning":
            _LOGGER.warning(message)
        else:
            _LOGGER.info(message)
        # Log to HA logbook
        try:
            log_entry(
                self.hass,
                "Smart Mini Split",
                message,
                DOMAIN,
            )
        except Exception as e:
            _LOGGER.debug(f"Failed to log to logbook: {e}")
            pass
