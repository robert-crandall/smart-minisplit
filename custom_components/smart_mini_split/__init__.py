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
    heating_threshold = domain_config.get("heating_threshold", DEFAULT_HEATING_THRESHOLD)
    cooling_threshold = domain_config.get("cooling_threshold", DEFAULT_COOLING_THRESHOLD)
    heating_reset_threshold = domain_config.get("heating_reset_threshold", DEFAULT_HEATING_RESET_THRESHOLD)
    cooling_reset_threshold = domain_config.get("cooling_reset_threshold", DEFAULT_COOLING_RESET_THRESHOLD)
    climate_entity = domain_config.get("climate_entity", DEFAULT_CLIMATE_ENTITY)
    external_temp_sensor = domain_config.get("external_temp_sensor", DEFAULT_EXTERNAL_TEMP_SENSOR)

    controller = MiniSplitController(
        hass,
        log_level=log_level,
        cooldown_minutes=cooldown_minutes,
        heating_threshold=heating_threshold,
        cooling_threshold=cooling_threshold,
        heating_reset_threshold=heating_reset_threshold,
        cooling_reset_threshold=cooling_reset_threshold,
        climate_entity=climate_entity,
        external_temp_sensor=external_temp_sensor,
    )
    async def run_update(now):
        await controller.update(now)

    # Force reset of temperature
    async def handle_force_reset(call):
        await controller.force_reset(None)

    hass.services.async_register(DOMAIN, "force_reset", handle_force_reset)
    async_track_time_interval(hass, run_update, timedelta(minutes=1))
    return True

class MiniSplitController:
    def __init__(self, hass: HomeAssistant, log_level: str = "info", cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES, heating_threshold: float = DEFAULT_HEATING_THRESHOLD, cooling_threshold: float = DEFAULT_COOLING_THRESHOLD, heating_reset_threshold: float = DEFAULT_HEATING_RESET_THRESHOLD, cooling_reset_threshold: float = DEFAULT_COOLING_RESET_THRESHOLD, climate_entity: str = DEFAULT_CLIMATE_ENTITY, external_temp_sensor: str = DEFAULT_EXTERNAL_TEMP_SENSOR):
        self.hass = hass
        self.last_adjustment: datetime | None = None
        self.last_desired_temp: float | None = None
        self.log_level = log_level.lower()
        self.cooldown_minutes = cooldown_minutes
        self.heating_threshold = heating_threshold
        self.cooling_threshold = cooling_threshold
        self.heating_reset_threshold = heating_reset_threshold
        self.cooling_reset_threshold = cooling_reset_threshold
        self.climate_entity = climate_entity
        self.external_temp_sensor = external_temp_sensor

        self.cooling_input_boolean = "input_boolean.cooling_enabled"
        self.cooling_desired_temp_input = "input_number.cooling_desired_temp"
        self.heating_desired_temp_input = "input_number.heating_desired_temp"
        self.heating_input_boolean = "input_boolean.heating_enabled"
        self.last_heating_event_entity = "input_datetime.last_heating_event"
        self.last_cooling_event_entity = "input_datetime.last_cooling_event"

        self.heating_temperature = 82 # Temperature to set for heating
        self.cooling_temperature = 60 # Temperature to set for cooling
        self.heating_reset_point = 62 # Temperature to reset heating
        self.cooling_reset_point = 76 # Temperature to reset cooling

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
        now = datetime.now()
        # Check last_adjustment for simple check
        if self.last_adjustment and (now - self.last_adjustment) < timedelta(minutes=self.cooldown_minutes):
            return True
        # Check last heating or cooling event
        last_heat = self.get_last_event(self.last_heating_event_entity)
        last_cool = self.get_last_event(self.last_cooling_event_entity)
        if last_heat and (now - last_heat) < timedelta(minutes=self.cooldown_minutes):
            return True
        if last_cool and (now - last_cool) < timedelta(minutes=self.cooldown_minutes):
            return True
        return False

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

    def _get_heating_desired_temp(self) -> float | None:
        state_obj = self.hass.states.get(self.heating_desired_temp_input)
        if state_obj is None:
            self.log_message(f"Heating setpoint input '{self.heating_desired_temp_input}' not found. Heating will not be adjusted.", "warning")
            return None
        try:
            return float(state_obj.state)
        except (ValueError, TypeError):
            self.log_message(f"Invalid heating setpoint value: {state_obj.state}", "warning")
            return None

    def needs_heating(self, current: float) -> bool:
        heating_allowed = self.hass.states.get(self.heating_input_boolean)
        if heating_allowed.state == "on":
            heating_desired_temp = self._get_heating_desired_temp()
            if current is None or heating_desired_temp is None:
                return False
            last_cooling_event = self.get_last_event(self.last_cooling_event_entity)
            if last_cooling_event and (datetime.now() - last_cooling_event) < timedelta(minutes=15):
                self.log_message("Skipping heating: last cooling event was less than 15 minutes ago", "debug")
                return False
            if current < (heating_desired_temp - self.heating_threshold):
                self.log_message(f"Heating needed. Current={current}, Desired={heating_desired_temp}", "debug")
                return True
            # self.log_message(f"Heating is not needed needed. Current={current}, Desired={heating_desired_temp}", "debug")
        return False

    def _get_cooling_desired_temp(self) -> float | None:
        """Get the cooling setpoint from the input_number entity, or fall back to desired temperature."""
        state_obj = self.hass.states.get(self.cooling_desired_temp_input)
        if state_obj is None:
            self.log_message(f"Cooling setpoint input '{self.cooling_desired_temp_input}' not found. Cooling will not be adjusted.", "warning")
            return None
        try:
            return float(state_obj.state)
        except (ValueError, TypeError):
            self.log_message(f"Invalid cooling setpoint value: {state_obj.state}", "warning")
            return None

    def needs_cooling(self, current: float) -> bool:
        cooling_allowed = self.hass.states.get(self.cooling_input_boolean)
        if cooling_allowed.state == "on":
            cooling_desired_temp = self._get_cooling_desired_temp()
            if current is None or cooling_desired_temp is None:
                return False
            last_heating_event = self.get_last_event(self.last_heating_event_entity)
            if last_heating_event and (datetime.now() - last_heating_event) < timedelta(minutes=15):
                self.log_message("Skipping cooling: last heating event was less than 15 minutes ago", "debug")
                return False
            if current > (cooling_desired_temp + self.cooling_threshold):
                self.log_message(f"Cooling needed. Current={current}, Desired={cooling_desired_temp}", "debug")
                return True
            # self.log_message(f"Cooling is not needed. Current={current}, Desired={cooling_desired_temp}", "debug")
        return False

    def last_mode(self) -> str | None:
        """Return 'heat', 'cool', or None depending on which event was most recent."""
        last_heating_event = self.get_last_event(self.last_heating_event_entity)
        last_cooling_event = self.get_last_event(self.last_cooling_event_entity)
        if last_heating_event and (not last_cooling_event or last_heating_event > last_cooling_event):
            return "heat"
        if last_cooling_event and (not last_heating_event or last_cooling_event > last_heating_event):
            return "cool"
        return None

    def current_mode(self) -> str | None:
        """Return the current mode of the climate entity."""
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state is None:
            self.log_message("Climate entity not available yet.", "warning")
            return None
        mode = climate_state.state
        if mode == "heat" or mode == "cool":
            return mode
        self.log_message("Current mode not available yet. Returning last mode instead.", "warning")
        # Debug all available attributes to see what's available
        return self.last_mode()

    def _get_set_temperature(self) -> float | None:
        """Return the current set temperature from the climate entity."""
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state is None:
            self.log_message("Climate entity not available yet.", "warning")
            return None
        set_temp = climate_state.attributes.get("temperature")
        if set_temp is not None:
            return set_temp
        self.log_message("Set temperature not available yet.", "warning")
        # Debug all available attributes to see what's available
        # self.debug_entity_attributes(self.climate_entity)
        return None

    def adjusted_state_active(self) -> bool:
        """Check if the current temperature is either heating or cooling."""
        set_temperature = self._get_set_temperature()
        if set_temperature is None:
            return False
        # Check if the set temperature is within the valid range
        if set_temperature == self.heating_temperature:
            return True
        if set_temperature == self.cooling_temperature:
            return True
        return False

    def should_reset(self, current: float) -> bool:
        # Support both heating and cooling reset thresholds
        heating_desired_temp = self._get_heating_desired_temp()
        cooling_desired_temp = self._get_cooling_desired_temp()
        in_adjusted_state = self.adjusted_state_active()
        current_mode = self.current_mode()
        if in_adjusted_state:
            if current_mode == "heat":
                if current >= (heating_desired_temp + self.heating_reset_threshold):
                    self.log_message(f"Should reset heating. Current={current}, Desired={heating_desired_temp}", "debug")
                    return True
            if current_mode == "cool":
                cooling_desired_temp = self._get_cooling_desired_temp()
                if current <= (cooling_desired_temp - self.cooling_reset_threshold):
                    self.log_message(f"Should reset cooling. Current={current}, Desired={cooling_desired_temp}", "debug")
                    return True
        self.log_message(f"Resetting not needed. Adjusted state={in_adjusted_state}, Current={current}, Heating setpoint={heating_desired_temp}, Cooling setpoint={cooling_desired_temp}, current_mode={current_mode}", "debug")
        return False

    async def _update_desired_temp(self, setpoint: float, mode: str) -> None:
        if mode == "heat":
            entity_id = self.heating_desired_temp_input
        elif mode == "cool":
            entity_id = self.cooling_desired_temp_input
        if entity_id:
            self.log_message(f"Updating {mode} setpoint to {setpoint}", "info")
            await self.hass.services.async_call(
                "input_number",
                "set_value",
                {
                    "entity_id": entity_id,
                    "value": setpoint  # your new value here
                },
                blocking=True,
            )

    async def adjust_set_temperature(self, target_temp: float, mode: str = None):
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
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        if mode == "heat":
            await self.set_last_event(self.last_heating_event_entity, now_str)
        elif mode == "cool":
            await self.set_last_event(self.last_cooling_event_entity, now_str)

    def get_last_event(self, entity_id: str) -> datetime | None:
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None or not state_obj.state or state_obj.state in ("unknown", "unavailable"):
            return None
        try:
            # Home Assistant input_datetime state is in 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS' format
            dt_str = state_obj.state.replace("T", " ")
            return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    async def set_last_event(self, entity_id: str, dt_str: str):
        # dt_str should be 'YYYY-MM-DDTHH:MM:SS'
        await self.hass.services.async_call(
            "input_datetime",
            "set_datetime",
            {
                "entity_id": entity_id,
                "datetime": dt_str,
            },
            blocking=True,
        )

    async def reset_set_temperature(self):
        # Determine last mode for reset
        mode = self.current_mode()
        if mode == "heat":
            desired_temperature = self.heating_reset_point
        elif mode == "cool":
            desired_temperature = self.cooling_reset_point
        else:
            self.log_message(f"No valid mode found for reset. Mode is {mode}. Assuming in heating.", "warning")
            desired_temperature = self.heating_reset_point
        self.log_message(f"Resetting temperature to {desired_temperature}{' with mode ' + mode if mode else ''}", "info")
        service_data = {
            "entity_id": self.climate_entity,
            "temperature": desired_temperature
        }
        if mode:
            service_data["hvac_mode"] = mode
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            service_data,
            blocking=True,
        )

    async def has_manually_adjusted_temperature(self, allow_current_setpoint: bool = False) -> bool:
        """Check if the set temperature is outside known numbers."""
        current_mode = self.current_mode()
        current_set_point = self._get_set_temperature()
        if current_mode == "heat":
            if current_set_point is self.heating_temperature or current_set_point is self.heating_reset_point:
                return False
            if allow_current_setpoint and current_set_point == int(self._get_heating_desired_temp()):
                return False
            return True
        if current_mode == "cool":
            if current_set_point is self.cooling_temperature or current_set_point is self.cooling_reset_point:
                return False
            if allow_current_setpoint and current_set_point == int(self._get_cooling_desired_temp()):
                return False
            return True
    
    async def force_reset(self, call):
        """Force reset the set temperature."""
        if not await self.has_manually_adjusted_temperature(allow_current_setpoint=False):
            return
        # Determine last mode for reset
        current_mode = self.current_mode()
        current_set_point = self._get_set_temperature()
        if current_mode == "heat":
            self.log_message(f"Should force reset heating. Current={current_set_point}, Desired={self.heating_reset_point}", "info")
            await self.adjust_set_temperature(self.heating_reset_point, mode="heat")
        if current_mode == "cool":
            self.log_message(f"Should force reset cooling. Current={current_set_point}, Desired={self.cooling_reset_point}", "info")
            await self.adjust_set_temperature(self.cooling_reset_point, mode="cool")

    @callback
    async def update(self, now):
        if self.in_cooldown():
            return

        current = self.current_temperature()

        # Skip if we don't have valid temperature readings
        if current is None:
            self.log_message("Skipping update: missing temperature data", "debug")
            return

        # Check if there is a manually adjusted temperature
        if await self.has_manually_adjusted_temperature(allow_current_setpoint=True):
            current_set_point = self._get_set_temperature()
            if current_set_point is not None:
                self.log_message(f"Manually adjusted temperature of {current_set_point} detected. Updating setpoint.", "debug")
                await self._update_desired_temp(current_set_point, self.current_mode())
            return

        if self.adjusted_state_active():
            if self.should_reset(current):
                await self.reset_set_temperature()
            return

        if self.needs_heating(current):
            await self.adjust_set_temperature(self.heating_temperature, mode="heat")
            return
        
        if self.needs_cooling(current):
            await self.adjust_set_temperature(self.cooling_temperature, mode="cool")
            return

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
