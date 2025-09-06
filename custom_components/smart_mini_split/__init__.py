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
VERSION = "1.0.0"
DEFAULT_WAIT_PERIOD_MINUTES = 3 # Minimum time between adjustments of the same mode (heat or cool). Adjustments between modes will wait 15 minutes.
DEFAULT_HEATING_THRESHOLD = 1.0 # Initiate heating when the actual temperature is this far below desired temperature
DEFAULT_HEATING_OVERSHOOT = 1.5 # Stop heating when the actual temperature exceeds the desired temperature by this much
DEFAULT_COOLING_THRESHOLD = 1.5 # Initiate cooling when the actual temperature is this far above desired temperature
DEFAULT_COOLING_OVERSHOOT = 1.0 # Stop cooling when the actual temperature exceeds the desired temperature by this much
DEFAULT_LOG_LEVEL = "info"
DEFAULT_CLIMATE_ENTITY = "climate.minisplit"
DEFAULT_ROOM_TEMP_ACTUAL = "sensor.awair_element_110243_temperature"
DEFAULT_EXTERNAL_HUMIDITY_SENSOR = "sensor.awair_element_110243_humidity"

async def async_setup(hass: HomeAssistant, config: ConfigType):
    # Read options from configuration, with defaults
    domain_config = config.get(DOMAIN, {})
    enabled = domain_config.get("enabled", True)
    if not enabled:
        _LOGGER.info("Smart Mini Split integration is disabled via configuration.")
        return True
    log_level = domain_config.get("log_level", DEFAULT_LOG_LEVEL)
    wait_period_minutes = domain_config.get("wait_period_minutes", DEFAULT_WAIT_PERIOD_MINUTES)
    heating_threshold = domain_config.get("heating_threshold", DEFAULT_HEATING_THRESHOLD)
    cooling_threshold = domain_config.get("cooling_threshold", DEFAULT_COOLING_THRESHOLD)
    heating_overshoot = domain_config.get("heating_overshoot", DEFAULT_HEATING_OVERSHOOT)
    cooling_overshoot = domain_config.get("cooling_overshoot", DEFAULT_COOLING_OVERSHOOT)
    climate_entity = domain_config.get("climate_entity", DEFAULT_CLIMATE_ENTITY)
    room_temp_actual = domain_config.get("room_temp_actual", DEFAULT_ROOM_TEMP_ACTUAL)
    external_humidity_sensor = domain_config.get("external_humidity_sensor", DEFAULT_EXTERNAL_HUMIDITY_SENSOR)

    controller = MiniSplitController(
        hass,
        log_level=log_level,
        wait_period_minutes=wait_period_minutes,
        heating_threshold=heating_threshold,
        cooling_threshold=cooling_threshold,
        heating_overshoot=heating_overshoot,
        cooling_overshoot=cooling_overshoot,
        climate_entity=climate_entity,
        room_temp_actual=room_temp_actual,
        external_humidity_sensor=external_humidity_sensor,
    )
    async def run_update(now):
        await controller.update(now)

    # Force reset of temperature
    async def handle_force_reset(call):
        await controller.force_reset_setpoint(None)

    hass.services.async_register(DOMAIN, "force_reset", handle_force_reset)
    async_track_time_interval(hass, run_update, timedelta(minutes=1))
    return True

class MiniSplitController:
    def __init__(self, hass: HomeAssistant, log_level: str = "info", wait_period_minutes: int = DEFAULT_WAIT_PERIOD_MINUTES, heating_threshold: float = DEFAULT_HEATING_THRESHOLD, cooling_threshold: float = DEFAULT_COOLING_THRESHOLD, heating_overshoot: float = DEFAULT_HEATING_OVERSHOOT, cooling_overshoot: float = DEFAULT_COOLING_OVERSHOOT, climate_entity: str = DEFAULT_CLIMATE_ENTITY, room_temp_actual: str = DEFAULT_ROOM_TEMP_ACTUAL, external_humidity_sensor: str = DEFAULT_EXTERNAL_HUMIDITY_SENSOR):
        self.hass = hass
        self.last_adjustment: datetime | None = None
        self.last_desired_temp: float | None = None
        self.log_level = log_level.lower()
        self.wait_period_minutes = wait_period_minutes
        self.heating_threshold = heating_threshold
        self.cooling_threshold = cooling_threshold
        self.heating_overshoot = heating_overshoot
        self.cooling_overshoot = cooling_overshoot
        self.climate_entity = climate_entity
        # Room temperature entity id and cached numeric value
        self.room_temp_actual_entity = room_temp_actual
        self.room_temp_actual: float | None = None
        self.external_humidity_sensor = external_humidity_sensor

        self.cooling_input_boolean = "input_boolean.cooling_enabled"
        self.cooling_desired_temp_input = "input_number.cooling_desired_temp"
        self.heating_desired_temp_input = "input_number.heating_desired_temp"
        self.heating_input_boolean = "input_boolean.heating_enabled"
        self.last_heating_event_entity = "input_datetime.last_heating_event"
        self.last_cooling_event_entity = "input_datetime.last_cooling_event"

        self.heating_active_temp = 82 # Temperature to set for heating
        self.cooling_active_temp = 60 # Temperature to set for cooling
        self.heating_idle_temp_value = 62 # Likely deprecated. Temperature to set when idle
        self.cooling_idle_temp_value = 76 # Likely deprecated. Temperature to set when idle
        self.dry_mode_humidity = 55 # Humidity level to enable dry mode. Should make this a variable.

        self.lowest_cooling_temp = 65 # Lowest temperature to set for cooling
        self.highest_heating_temp = 75 # Highest temperature to set for heating

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

    def in_wait_period(self) -> bool:
        now = datetime.now()
        # Check last_adjustment for simple check
        if self.last_adjustment and (now - self.last_adjustment) < timedelta(minutes=self.wait_period_minutes):
            return True
        # Check last heating or cooling event
        last_heat = self.get_last_event(self.last_heating_event_entity)
        last_cool = self.get_last_event(self.last_cooling_event_entity)
        if last_heat and (now - last_heat) < timedelta(minutes=self.wait_period_minutes):
            return True
        if last_cool and (now - last_cool) < timedelta(minutes=self.wait_period_minutes):
            return True
        return False

    def _update_room_temp_actual(self) -> None:
        """Update cached actual room temperature.

        Sets self.room_temp_actual or None if unavailable/invalid.
        """
        sensor_state = self.hass.states.get(self.room_temp_actual_entity)
        if sensor_state is None:
            self.room_temp_actual = None
            return
        try:
            self.room_temp_actual = float(sensor_state.state)
        except (ValueError, TypeError):
            self.log_message(f"Invalid temperature sensor value: {sensor_state.state}", "warning")
            self.room_temp_actual = None

    def external_humidity(self) -> float | None:
        sensor_state = self.hass.states.get(self.external_humidity_sensor)
        if sensor_state is None:
            self.log_message("Humidity sensor not available", "warning")
            return None
        try:
            return float(sensor_state.state)
        except (ValueError, TypeError):
            self.log_message(f"Invalid humidity sensor value: {sensor_state.state}", "warning")
            return None

    def heating_desired_temp(self) -> float | None:
        state_obj = self.hass.states.get(self.heating_desired_temp_input)
        if state_obj is None:
            self.log_message(f"Heating setpoint input '{self.heating_desired_temp_input}' not found. Heating will not be adjusted.", "warning")
            return None
        try:
            desired_temp = float(state_obj.state)
            if desired_temp < self.highest_heating_temp:
                return desired_temp
            self.log_message(f"Heating setpoint {desired_temp} is below the maximum allowed temperature {self.highest_heating_temp}.", "warning")
            return None
        except (ValueError, TypeError):
            self.log_message(f"Invalid heating setpoint value: {state_obj.state}", "warning")
            return None

    def heating_idle_temp(self) -> float | None:
        """Return the idle temperature for heating."""
        return self.heating_desired_temp()

    def needs_heating(self) -> bool:
        """Determine if heating should be activated based on cached temperature."""
        external_temp = self.room_temp_actual
        heating_allowed = self.hass.states.get(self.heating_input_boolean)
        if heating_allowed.state == "on":
            heating_desired_temp = self.heating_desired_temp()
            if external_temp is None or heating_desired_temp is None:
                return False
            last_cooling_event = self.get_last_event(self.last_cooling_event_entity)
            if external_temp < (heating_desired_temp - self.heating_threshold):
                if last_cooling_event and (datetime.now() - last_cooling_event) < timedelta(minutes=15):
                    self.log_message("Heating needed, but skipped: last cooling event was less than 15 minutes ago", "debug")
                    return False
                self.log_message(f"Heating needed. Current={external_temp}, Desired={heating_desired_temp}", "info")
                return True
            self.log_message(f"Heating is not needed needed. Current={external_temp}, Desired={heating_desired_temp}", "verbose")
        return False

    def cooling_desired_temp(self) -> float | None:
        """Get the cooling setpoint from the input_number entity, or fall back to desired temperature."""
        state_obj = self.hass.states.get(self.cooling_desired_temp_input)
        if state_obj is None:
            self.log_message(f"Cooling setpoint input '{self.cooling_desired_temp_input}' not found. Cooling will not be adjusted.", "warning")
            return None
        try:
            desired_temp = float(state_obj.state)
            if desired_temp > self.lowest_cooling_temp:
                return desired_temp
            self.log_message(f"Cooling setpoint {desired_temp} is below the minimum allowed temperature {self.lowest_cooling_temp}.", "warning")
            return self.lowest_cooling_temp
        except (ValueError, TypeError):
            self.log_message(f"Invalid cooling setpoint value: {state_obj.state}", "warning")
            return None

    def cooling_idle_temp(self) -> float | None:
        """Return the idle temperature for cooling.

        Attempts to keep setpoint near the desired cooling temperature while allowing some buffer.
        Falls back safely if any component data is unavailable.
        """
        internal_temp = self.get_minisplit_room_temp()
        room_temp_actual = self.room_temp_actual
        desired_temp = self.cooling_desired_temp()
        # Default difference to subtract when dry mode compensation not explicitly defined
        dry_mode_diff = 2

        if desired_temp is None:
            return None

        if internal_temp is not None and room_temp_actual is not None:
            temp_diff = internal_temp - room_temp_actual
            # Keep within reasonable bounds
            candidate = desired_temp + temp_diff - dry_mode_diff
            return max(min(candidate, self.cooling_active_temp), self.lowest_cooling_temp)

        # Fallback buffer above desired temp
        return min(desired_temp + 4, self.cooling_active_temp)

    def needs_cooling(self) -> bool:
        """Determine if cooling should be activated based on cached temperature."""
        external_temp = self.room_temp_actual
        cooling_allowed = self.hass.states.get(self.cooling_input_boolean)
        if not cooling_allowed.state == "on":
            return False
        # Safety check
        heating_desired_temp = self.heating_desired_temp()
        cooling_desired_temp = self.cooling_desired_temp()
        if not (heating_desired_temp + self.heating_overshoot) < cooling_desired_temp:
            self.log_message(f"Heating desired temp {heating_desired_temp} is too close to the cooling desired temp {cooling_desired_temp}. Set these more apart to avoid conflicts.", "warning")
            return False
        if external_temp is None or cooling_desired_temp is None:
            return False
        last_heating_event = self.get_last_event(self.last_heating_event_entity)
        if external_temp > (cooling_desired_temp + self.cooling_threshold):
            if last_heating_event and (datetime.now() - last_heating_event) < timedelta(minutes=15):
                self.log_message("Cooling needed but skipped: last heating event was less than 15 minutes ago", "debug")
                return False
            self.log_message(f"Cooling needed. Current={external_temp}, Desired={cooling_desired_temp}", "debug")
            return True
        self.log_message(f"Cooling is not needed. Current={external_temp}, Desired={cooling_desired_temp}", "verbose")

    def is_overcooled(self, current_mode: str | None = None) -> bool:
        """Check if the room is overcooled using cached temperature."""
        external_temp = self.room_temp_actual
        if current_mode == "heat":
            return False
        heating_desired_temp = self.heating_desired_temp()
        if external_temp is None or heating_desired_temp is None:
            return False
        if external_temp < (heating_desired_temp + self.heating_overshoot):
            self.log_message(f"Room is overcooled. Current={external_temp}, Desired={heating_desired_temp}", "info")
            return True
        return False

    def current_mode(self) -> str | None:
        """Return 'heat', 'cool', or None. Looks at the climate entity state."""
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state is None:
            self.log_message("Climate entity not available yet.", "warning")
            return None
        mode = climate_state.state
        return mode

    def get_climate_setpoint(self) -> float | None:
        """Return the current set temperature from the climate entity."""
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state is None:
            self.log_message("Climate entity not available yet.", "warning")
            return None
        set_temp = climate_state.attributes.get("temperature")
        if set_temp is not None:
            return set_temp
        self.log_message("Set temperature not available yet.", "warning")
        return None

    def get_minisplit_room_temp(self) -> float | None:
        """Return the current internal temperature from the climate entity."""
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state is None:
            self.log_message("Climate entity not available yet.", "warning")
            return None
        internal_temp = climate_state.attributes.get("current_temperature")
        if internal_temp is not None:
            return internal_temp
        self.log_message("Internal temperature not available yet.", "warning")
        return None

    def use_dry_mode(self) -> bool:
        """Determine if dry mode should be used based on humidity."""
        external_humidity = self.external_humidity()
        if external_humidity is None:
            self.log_message("External humidity sensor not available.", "warning")
            return False
        if external_humidity >= self.dry_mode_humidity:
            return True
        return False

    async def adjust_climate_setpoint(self, target_temp: float, mode: str = None, message: str = None) -> None:
        # Set mode if specified
        service_data = {
            "entity_id": self.climate_entity,
            "temperature": target_temp
        }
        if mode and mode == "cool" and self.use_dry_mode():
            mode = "dry"
        if mode:
            service_data["hvac_mode"] = mode
        log_message = f"Adjusting set temperature to {target_temp}"
        if mode:
            log_message += f" with mode {mode}"
        if message:
            log_message += f", {message}"
        self.log_message(log_message, "info")
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
        else:
            await self.set_last_event(self.last_cooling_event_entity, now_str)

    async def enforce_idle_mode(
        self,
        current_mode: str = None,
    ) -> None:
        """Enforce idle mode by resetting the set temperature."""
        # Determine last mode for reset
        if current_mode == "heat":
            idle_temperature = self.heating_idle_temp()
        else:
            idle_temperature = self.cooling_idle_temp()
        if idle_temperature is not None:
            await self.adjust_climate_setpoint(idle_temperature, mode=current_mode, message="enforcing idle mode")

    async def enforce_safe_cooling_idle_mode(self) -> None:
        """Room is overcooled, enforce a safe cooling idle mode by resetting the set temperature and turning off dry mode."""
        # Determine last mode for reset
        idle_temperature = self.cooling_idle_temp_value
        if idle_temperature is not None:
            await self.adjust_climate_setpoint(idle_temperature, mode="cool", message="enforcing safe cooling idle mode")

    def climate_is_active(
        self,
        climate_setpoint: int = None,
    ) -> bool:
        """Check if the current temperature is either heating or cooling."""
        if climate_setpoint is None:
            return False
        # Check if the set temperature is within the valid range
        if climate_setpoint == self.heating_active_temp:
            return True
        if climate_setpoint == self.cooling_active_temp:
            return True
        return False

    def temperature_reached_threshold(self, current_mode: str = None) -> bool:
        """Determine if active mode has reached its overshoot threshold using cached temp."""
        external_temp = self.room_temp_actual
        if external_temp is None:
            return False
        if current_mode == "heat":
            heating_desired_temp = self.heating_desired_temp()
            if heating_desired_temp is None:
                return False
            if external_temp >= (heating_desired_temp + self.heating_overshoot):
                self.log_message(f"Heating has reached threshold. Current={external_temp}, Desired={heating_desired_temp}", "debug")
                return True
            self.log_message(f"Temperature threshold not reached. Current={external_temp}, Heating setpoint={heating_desired_temp}", "debug")
            return False
        else:
            cooling_desired_temp = self.cooling_desired_temp()
            if cooling_desired_temp is None:
                return False
            if external_temp <= (cooling_desired_temp - self.cooling_overshoot):
                self.log_message(f"Cooling has reached threshold. Current={external_temp}, Desired={cooling_desired_temp}", "debug")
                return True
            self.log_message(f"Temperature threshold not reached. Current={external_temp}, Cooling setpoint={cooling_desired_temp}", "debug")
            return False

    async def update_desired_temp(self, setpoint: float, mode: str) -> None:
        if mode == "heat":
            entity_id = self.heating_desired_temp_input
        else:
            entity_id = self.cooling_desired_temp_input
        if entity_id:
            self.log_message(f"Updating {mode} desired temperature to {setpoint}", "info")
            await self.hass.services.async_call(
                "input_number",
                "set_value",
                {
                    "entity_id": entity_id,
                    "value": setpoint
                },
                blocking=True,
            )

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

    def numbers_are_close(self, num1: float, num2: float) -> bool:
        """Check if two numbers are close enough to be equal, able to compare float to int."""
        if num1 is None or num2 is None:
            return False
        return abs(num1 - num2) < 0.1

    async def climate_has_manually_adjusted_setpoint(
        self, 
        allow_current_setpoint: bool = False,
        current_set_point: float = None,
        current_mode: str = None,
    ) -> bool:
        return False # TODO - reenable this
        """Check if the set temperature is outside known numbers."""
        if current_mode == "heat":
            if self.numbers_are_close(current_set_point, self.heating_active_temp) or self.numbers_are_close(current_set_point, self.heating_idle_temp()):
                return False
            if allow_current_setpoint and self.numbers_are_close(current_set_point, self.heating_desired_temp()):
                return False
            return True
        else:
            if self.numbers_are_close(current_set_point, self.cooling_active_temp) or self.numbers_are_close(current_set_point, self.cooling_idle_temp() or self.numbers_are_close(current_set_point, self.cooling_idle_temp_value)):
                return False
            if allow_current_setpoint and self.numbers_are_close(current_set_point, self.cooling_desired_temp()):
                return False
            return True
    
    async def force_reset_setpoint(self, call):
        """Force reset the set temperature."""
        # If there's no manual adjustment, we don't need to reset
        if not await self.climate_has_manually_adjusted_setpoint(allow_current_setpoint=False):
            return

        # Determine last mode for reset
        current_mode = self.current_mode()
        current_set_point = self.get_climate_setpoint()
        if current_mode == "heat":
            self.log_message(f"Should force reset heating. Current={current_set_point}, Desired={self.heating_idle_temp()}", "info")
            await self.adjust_climate_setpoint(self.heating_idle_temp(), mode="heat")
        else:
            self.log_message(f"Should force reset cooling. Current={current_set_point}, Desired={self.cooling_idle_temp()}", "info")
            await self.adjust_climate_setpoint(self.cooling_idle_temp(), mode=current_mode)

        if not self.climate_is_active(climate_setpoint=current_set_point):
            self.log_message(f"Climate setpoint is still manually adjusted, resetting to an idle state", "info")
            current_mode = self.current_mode()
            await self.enforce_idle_mode(current_mode=current_mode)

    @callback
    async def update(self, now):
        try:
            if self.in_wait_period():
                return

            # Refresh cached room temp each cycle
            self._update_room_temp_actual()
            room_temp_actual = self.room_temp_actual
            current_set_point = self.get_climate_setpoint()
            current_mode = self.current_mode()

            # Skip if we don't have valid temperature readings
            if room_temp_actual is None or current_set_point is None:
                self.log_message("Skipping update: missing temperature data", "debug")
                return

            if self.climate_is_active(climate_setpoint=current_set_point):
                self.log_message("Climate is currently active.", "verbose")
                if self.temperature_reached_threshold(current_mode=current_mode):
                    self.log_message(f"Enforcing idle state on {current_mode} mode.", "debug")
                    await self.enforce_idle_mode(current_mode=current_mode)
                return

            if self.needs_heating():
                self.log_message(f"Needs heating, current temperature={room_temp_actual}", "debug")
                await self.adjust_climate_setpoint(self.heating_active_temp, mode="heat")
                return

            if self.needs_cooling():
                self.log_message(f"Needs cooling, current temperature={room_temp_actual}", "debug")
                await self.adjust_climate_setpoint(self.cooling_active_temp, mode="cool")
                return

            if self.is_overcooled(current_mode=current_mode):
                await self.enforce_safe_cooling_idle_mode(current_mode=current_mode)
                return

            # This is very noisy. Use it to confirm logs are working correctly.
            self.log_message(f"No action needed. Current temperature={room_temp_actual}", "verbose")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.log_message(f"Exception in update: {e}\nTraceback:\n{tb}", "warning")

    def log_message(self, message, level="info"):
        """Log message to Home Assistant logbook and logger, respecting configured log level."""
        # Verbose mode: log everything
        if self.log_level == "verbose":
            print(f"[{level.upper()}] {message}")
            _LOGGER.debug(message)
            try:
                log_entry(
                    self.hass,
                    "Smart Mini Split",
                    message,
                    DOMAIN,
                )
            except Exception as e:
                _LOGGER.debug(f"Failed to log to logbook: {e}")
            return

        if level == "verbose":
            return

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
