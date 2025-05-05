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
DEFAULT_HEATING_THRESHOLD = 1.0
DEFAULT_HEATING_RESET_THRESHOLD = 1.0
DEFAULT_COOLING_THRESHOLD = 1.0
DEFAULT_COOLING_RESET_THRESHOLD = 1.0
DEFAULT_VALID_TEMP_RANGE = [60, 74]
DEFAULT_LOG_LEVEL = "info"
DEFAULT_CLIMATE_ENTITY = "climate.minisplit"
DEFAULT_EXTERNAL_TEMP_SENSOR = "sensor.awair_element_110243_temperature"
DEFAULT_COOLING_INPUT_BOOLEAN = "input_boolean.cooling_enabled"

async def async_setup(hass: HomeAssistant, config: ConfigType):
    # Read options from configuration, with defaults
    domain_config = config.get(DOMAIN, {})
    enabled = domain_config.get("enabled", True)
    if not enabled:
        _LOGGER.info("Smart Mini Split integration is disabled via configuration.")
        return True
    log_level = domain_config.get("log_level", DEFAULT_LOG_LEVEL)
    cooldown_minutes = domain_config.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
    heating_threshold = domain_config.get("heating_threshold", DEFAULT_HEATING_THRESHOLD)
    cooling_threshold = domain_config.get("cooling_threshold", DEFAULT_COOLING_THRESHOLD)
    heating_reset_threshold = domain_config.get("heating_reset_threshold", DEFAULT_HEATING_RESET_THRESHOLD)
    cooling_reset_threshold = domain_config.get("cooling_reset_threshold", DEFAULT_COOLING_RESET_THRESHOLD)
    valid_temp_range = domain_config.get("valid_temp_range", DEFAULT_VALID_TEMP_RANGE)
    climate_entity = domain_config.get("climate_entity", DEFAULT_CLIMATE_ENTITY)
    external_temp_sensor = domain_config.get("external_temp_sensor", DEFAULT_EXTERNAL_TEMP_SENSOR)
    cooling_input_boolean = domain_config.get("cooling_input_boolean", DEFAULT_COOLING_INPUT_BOOLEAN)
    controller = MiniSplitController(
        hass,
        log_level=log_level,
        cooldown_minutes=cooldown_minutes,
        heating_threshold=heating_threshold,
        cooling_threshold=cooling_threshold,
        heating_reset_threshold=heating_reset_threshold,
        cooling_reset_threshold=cooling_reset_threshold,
        valid_temp_range=valid_temp_range,
        climate_entity=climate_entity,
        external_temp_sensor=external_temp_sensor,
        cooling_input_boolean=cooling_input_boolean,
    )
    async def run_update(now):
        await controller.update(now)
    async_track_time_interval(hass, run_update, timedelta(minutes=1))
    return True

class MiniSplitController:
    def __init__(self, hass: HomeAssistant, log_level: str = "info", cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES, heating_threshold: float = DEFAULT_HEATING_THRESHOLD, cooling_threshold: float = DEFAULT_COOLING_THRESHOLD, heating_reset_threshold: float = DEFAULT_HEATING_RESET_THRESHOLD, cooling_reset_threshold: float = DEFAULT_COOLING_RESET_THRESHOLD, valid_temp_range = DEFAULT_VALID_TEMP_RANGE, climate_entity: str = DEFAULT_CLIMATE_ENTITY, external_temp_sensor: str = DEFAULT_EXTERNAL_TEMP_SENSOR, cooling_input_boolean: str = DEFAULT_COOLING_INPUT_BOOLEAN):
        self.hass = hass
        self.last_adjustment: datetime | None = None
        self.last_desired_temp: float | None = None
        self.adjusted_state_active: bool = False
        self.log_level = log_level.lower()
        self.cooldown_minutes = cooldown_minutes
        self.heating_threshold = heating_threshold
        self.cooling_threshold = cooling_threshold
        self.heating_reset_threshold = heating_reset_threshold
        self.cooling_reset_threshold = cooling_reset_threshold
        self.valid_temp_range = valid_temp_range
        self.climate_entity = climate_entity
        self.external_temp_sensor = external_temp_sensor
        self.cooling_input_boolean = cooling_input_boolean
        self.last_heating_event: datetime | None = None
        self.last_cooling_event: datetime | None = None

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
        # Do not use if last cooling event was less than 15 minutes ago
        if self.last_cooling_event and (datetime.now() - self.last_cooling_event) < timedelta(minutes=15):
            self.log_message("Skipping heating: last cooling event was less than 15 minutes ago", "debug")
            return False
        return current < (desired - self.heating_threshold)

    def needs_cooling(self, current: float, desired: float) -> bool:
        if current is None or desired is None:
            return False
        # Do not use if last heating event was less than 15 minutes ago
        if self.last_heating_event and (datetime.now() - self.last_heating_event) < timedelta(minutes=15):
            self.log_message("Skipping cooling: last heating event was less than 15 minutes ago", "debug")
            return False
        return current > (desired + self.cooling_threshold)

    def cooling_allowed_now(self) -> bool:
        """Check if cooling is allowed by reading the state of an input_boolean entity."""
        state_obj = self.hass.states.get(self.cooling_input_boolean)
        if state_obj is None:
            self.log_message(f"Cooling allowed input_boolean '{self.cooling_input_boolean}' not found, assuming disabled.", "debug")
            return False
        if state_obj.state == "on":
            self.log_message(f"Cooling is allowed: {self.cooling_input_boolean} is on.", "debug")
            return True
        self.log_message(f"Cooling not allowed: {self.cooling_input_boolean} is not on.", "debug")
        return False

    def last_mode(self) -> str | None:
        """Return 'heat', 'cool', or None depending on which event was most recent."""
        if self.last_heating_event and (not self.last_cooling_event or self.last_heating_event > self.last_cooling_event):
            return "heat"
        if self.last_cooling_event and (not self.last_heating_event or self.last_cooling_event > self.last_heating_event):
            return "cool"
        return None

    def should_reset(self, current: float, desired: float) -> bool:
        if current is None or desired is None:
            return False
        # Support both heating and cooling reset thresholds
        if self.adjusted_state_active:
            mode = self.last_mode()
            if mode == "heat":
                return current >= (desired + self.heating_reset_threshold)
            if mode == "cool":
                return current <= (desired - self.cooling_reset_threshold)
        return False

    async def adjust_set_temperature(self, target_temp: float, mode: str = None):
        climate_state = self.hass.states.get(self.climate_entity)
        min_temp = climate_state.attributes.get("min_temp", 55) if climate_state else 55
        max_temp = climate_state.attributes.get("max_temp", 82) if climate_state else 82
        if min_temp is not None:
            target_temp = max(min_temp, target_temp)
        if max_temp is not None:
            target_temp = min(max_temp, target_temp)
        # Set mode if specified
        service_data = {
            "entity_id": self.climate_entity,
            "temperature": target_temp
        }
        if mode:
            service_data["hvac_mode"] = mode
        self.log_message(f"Adjusting set temperature to {target_temp}{' with mode ' + mode if mode else ''}", "info")
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            service_data,
            blocking=True,
        )
        self.last_adjustment = datetime.now()
        if mode == "heat":
            self.last_heating_event = datetime.now()
        elif mode == "cool":
            self.last_cooling_event = datetime.now()
        self.adjusted_state_active = True

    async def reset_set_temperature(self):
        # Determine last mode for reset
        mode = self.last_mode()
        self.log_message(f"Resetting temperature to {self.last_desired_temp}{' with mode ' + mode if mode else ''}", "info")
        service_data = {
            "entity_id": self.climate_entity,
            "temperature": self.last_desired_temp
        }
        if mode:
            service_data["hvac_mode"] = mode
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            service_data,
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
            await self.adjust_set_temperature(82, mode="heat")
        elif self.cooling_allowed_now() and self.needs_cooling(current, desired):
            self.log_message(f"Needs cooling. Current={current}, Desired={desired}", "debug")
            await self.adjust_set_temperature(desired, mode="cool")
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
