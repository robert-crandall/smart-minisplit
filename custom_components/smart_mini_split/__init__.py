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
DEFAULT_WAIT_PERIOD_MINUTES = 5 # Minimum time between adjustments of the same mode (heat or cool). Adjustments between modes will wait 15 minutes.
DEFAULT_HEATING_THRESHOLD = 1.0 # Initiate heating when the actual temperature is this far below desired temperature
DEFAULT_HEATING_OVERSHOOT = 1.5 # Stop heating when the actual temperature exceeds the desired temperature by this much
DEFAULT_COOLING_THRESHOLD = 1.5 # Initiate cooling when the actual temperature is this far above desired temperature
DEFAULT_COOLING_OVERSHOOT = 1.0 # Stop cooling when the actual temperature exceeds the desired temperature by this much
DEFAULT_HUMIDITY_THRESHOLD = 60.0 # Start dehumidifying above this % RH
DEFAULT_HUMIDITY_TEMP_WINDOW = 2.0 # Only run dehumidify if within ±this of target temp
DEFAULT_HUMIDITY_PRIORITY = False # If true, dehumidify even if slightly outside temp range
DEFAULT_LOG_LEVEL = "info"
DEFAULT_CLIMATE_ENTITY = "climate.minisplit"
DEFAULT_EXTERNAL_TEMP_SENSOR = "sensor.awair_element_110243_temperature"
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
    humidity_threshold = domain_config.get("humidity_threshold", DEFAULT_HUMIDITY_THRESHOLD)
    humidity_temp_window = domain_config.get("humidity_temp_window", DEFAULT_HUMIDITY_TEMP_WINDOW)
    humidity_priority = domain_config.get("humidity_priority", DEFAULT_HUMIDITY_PRIORITY)
    climate_entity = domain_config.get("climate_entity", DEFAULT_CLIMATE_ENTITY)
    external_temp_sensor = domain_config.get("external_temp_sensor", DEFAULT_EXTERNAL_TEMP_SENSOR)
    external_humidity_sensor = domain_config.get("external_humidity_sensor", DEFAULT_EXTERNAL_HUMIDITY_SENSOR)

    controller = MiniSplitController(
        hass,
        log_level=log_level,
        wait_period_minutes=wait_period_minutes,
        heating_threshold=heating_threshold,
        cooling_threshold=cooling_threshold,
        heating_overshoot=heating_overshoot,
        cooling_overshoot=cooling_overshoot,
        humidity_threshold=humidity_threshold,
        humidity_temp_window=humidity_temp_window,
        humidity_priority=humidity_priority,
        climate_entity=climate_entity,
        external_temp_sensor=external_temp_sensor,
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
    def __init__(self, hass: HomeAssistant, log_level: str = "info", wait_period_minutes: int = DEFAULT_WAIT_PERIOD_MINUTES, heating_threshold: float = DEFAULT_HEATING_THRESHOLD, cooling_threshold: float = DEFAULT_COOLING_THRESHOLD, heating_overshoot: float = DEFAULT_HEATING_OVERSHOOT, cooling_overshoot: float = DEFAULT_COOLING_OVERSHOOT, humidity_threshold: float = DEFAULT_HUMIDITY_THRESHOLD, humidity_temp_window: float = DEFAULT_HUMIDITY_TEMP_WINDOW, humidity_priority: int = DEFAULT_HUMIDITY_PRIORITY, climate_entity: str = DEFAULT_CLIMATE_ENTITY, external_temp_sensor: str = DEFAULT_EXTERNAL_TEMP_SENSOR, external_humidity_sensor: str = DEFAULT_EXTERNAL_HUMIDITY_SENSOR):
        self.hass = hass
        self.last_adjustment: datetime | None = None
        self.last_desired_temp: float | None = None
        self.log_level = log_level.lower()
        self.wait_period_minutes = wait_period_minutes
        self.heating_threshold = heating_threshold
        self.cooling_threshold = cooling_threshold
        self.heating_overshoot = heating_overshoot
        self.cooling_overshoot = cooling_overshoot
        self.humidity_threshold = humidity_threshold
        self.humidity_temp_window = humidity_temp_window
        self.humidity_priority = humidity_priority
        self.climate_entity = climate_entity
        self.external_temp_sensor = external_temp_sensor
        self.external_humidity_sensor = external_humidity_sensor

        self.cooling_input_boolean = "input_boolean.cooling_enabled"
        self.cooling_desired_temp_input = "input_number.cooling_desired_temp"
        self.heating_desired_temp_input = "input_number.heating_desired_temp"
        self.heating_input_boolean = "input_boolean.heating_enabled"
        self.last_heating_event_entity = "input_datetime.last_heating_event"
        self.last_cooling_event_entity = "input_datetime.last_cooling_event"

        self.heating_active_temp = 82 # Temperature to set for heating
        self.cooling_active_temp = 60 # Temperature to set for cooling
        self.heating_idle_temp = 62 # Temperature to reset heating
        self.cooling_idle_temp = 76 # Temperature to reset cooling

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

    def external_temperature(self) -> float | None:
        sensor_state = self.hass.states.get(self.external_temp_sensor)
        if sensor_state is None:
            self.log_message("Temperature sensor not available", "warning")
            return None
        try:
            return float(sensor_state.state)
        except (ValueError, TypeError):
            self.log_message(f"Invalid temperature sensor value: {sensor_state.state}", "warning")
            return None

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

    def needs_heating(self, external_temp: float) -> bool:
        heating_allowed = self.hass.states.get(self.heating_input_boolean)
        if heating_allowed.state == "on":
            heating_desired_temp = self.heating_desired_temp()
            if external_temp is None or heating_desired_temp is None:
                return False
            last_cooling_event = self.get_last_event(self.last_cooling_event_entity)
            if last_cooling_event and (datetime.now() - last_cooling_event) < timedelta(minutes=15):
                self.log_message("Skipping heating: last cooling event was less than 15 minutes ago", "debug")
                return False
            if external_temp < (heating_desired_temp - self.heating_threshold):
                self.log_message(f"Heating needed. Current={external_temp}, Desired={heating_desired_temp}", "debug")
                return True
            # self.log_message(f"Heating is not needed needed. Current={current}, Desired={heating_desired_temp}", "debug")
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
            self.log_message(f"Cooling setpoint {desired_temp} is above the minimum allowed temperature {self.lowest_cooling_temp}.", "warning")
            return None
        except (ValueError, TypeError):
            self.log_message(f"Invalid cooling setpoint value: {state_obj.state}", "warning")
            return None

    def needs_cooling(self, external_temp: float) -> bool:
        cooling_allowed = self.hass.states.get(self.cooling_input_boolean)
        if not cooling_allowed.state == "on":
            return False
        # Safety check
        heating_desired_temp = self.heating_desired_temp()
        cooling_desired_temp = self.cooling_desired_temp()
        if not heating_desired_temp < (cooling_desired_temp - 2):
            self.log_message(f"Heating desired temp {heating_desired_temp} is too close to the cooling desired temp {cooling_desired_temp}. Set these more apart to avoid conflicts.", "warning")
            return False
            
        if external_temp is None or cooling_desired_temp is None:
            return False
        last_heating_event = self.get_last_event(self.last_heating_event_entity)
        if last_heating_event and (datetime.now() - last_heating_event) < timedelta(minutes=15):
            self.log_message("Skipping cooling: last heating event was less than 15 minutes ago", "debug")
            return False
        if external_temp > (cooling_desired_temp + self.cooling_threshold):
            self.log_message(f"Cooling needed. Current={external_temp}, Desired={cooling_desired_temp}", "debug")
            return True
        # self.log_message(f"Cooling is not needed. Current={current}, Desired={cooling_desired_temp}", "debug")

    def needs_drying(self, external_temp: float, external_humidity: float) -> bool:
        drying_allowed = self.hass.states.get(self.drying_input_boolean)
        if drying_allowed.state == "on":
            if external_temp is None or external_humidity is None:
                return False
                
            # Wait period after heating or cooling events
            last_heating_event = self.get_last_event(self.last_heating_event_entity)
            last_cooling_event = self.get_last_event(self.last_cooling_event_entity)
            
            if last_heating_event and (datetime.now() - last_heating_event) < timedelta(minutes=15):
                self.log_message("Skipping drying: last heating event was less than 15 minutes ago", "debug")
                return False
                
            if last_cooling_event and (datetime.now() - last_cooling_event) < timedelta(minutes=15):
                self.log_message("Skipping drying: last cooling event was less than 15 minutes ago", "debug")
                return False
            
            # Check if humidity is above threshold
            if external_humidity > self.humidity_threshold:
                # Optional: Only dry if temperature is within comfortable range
                heating_desired_temp = self.heating_desired_temp()
                cooling_desired_temp = self.cooling_desired_temp()
                
                if heating_desired_temp is not None and cooling_desired_temp is not None:
                    temp_range_min = heating_desired_temp - self.humidity_temp_window
                    temp_range_max = cooling_desired_temp + self.humidity_temp_window
                    
                    if temp_range_min <= external_temp <= temp_range_max:
                        self.log_message(f"Drying needed. Humidity={external_humidity}%, Temp={external_temp}°F in acceptable range", "debug")
                        return True
                    else:
                        self.log_message(f"Drying skipped: temp {external_temp}°F outside comfortable range ({temp_range_min}-{temp_range_max})", "debug")
                else:
                    # Fallback if desired temps not available
                    self.log_message(f"Drying needed. Humidity={external_humidity}%", "debug")
                    return True
        self.log_message(f"Drying not needed. Humidity={external_humidity}%", "debug")
        return False

    def current_mode(self) -> str | None:
        """Return 'heat', 'cool', 'dry', or None. Looks at the climate entity state."""
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state is None:
            self.log_message("Climate entity not available yet.", "warning")
            return None
        mode = climate_state.state
        if mode == "heat" or mode == "cool" or mode == "dry":
            return mode
        self.log_message("Current mode not available yet. Returning Heat as default.", "warning")
        # Debug all available attributes to see what's available
        return "heat"

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
        # Debug all available attributes to see what's available
        # self.debug_entity_attributes(self.climate_entity)
        return None

    async def adjust_climate_setpoint(self, target_temp: float, mode: str = None, message: str = None) -> None:
        # Set mode if specified
        service_data = {
            "entity_id": self.climate_entity,
            "temperature": target_temp
        }
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
        elif mode == "cool":
            await self.set_last_event(self.last_cooling_event_entity, now_str)

    async def adjust_climate_dry(self, current_mode: str = None, message: str = None) -> None:        
        # Determine target temperature based on what mode we should be in for comfort
        heating_desired_temp = self.heating_desired_temp()
        cooling_desired_temp = self.cooling_desired_temp()
        
        if current_mode == "heat" and heating_desired_temp is not None:
            target_temp = heating_desired_temp
        elif current_mode == "cool" and cooling_desired_temp is not None:
            target_temp = cooling_desired_temp
        elif cooling_desired_temp is not None:
            # Default to midpoint or bias toward cooling (dry mode typically works better when slightly cool)
            target_temp = cooling_desired_temp
        else:
            # Fallback - use current temperature as target
            current_state = self.hass.states.get(self.climate_entity)
            target_temp = current_state.attributes.get("current_temperature", 72)  # 72°F fallback
        
        service_data = {
            "entity_id": self.climate_entity,
            "hvac_mode": "dry",
            "temperature": target_temp
        }
        
        log_message = f"Adjusting to dry mode with temperature {target_temp}°F"
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
        await self.set_last_event(self.last_drying_event_entity, now_str)

    async def enforce_idle_mode(
            self,
            current_mode: str = None,
        ) -> None:
        """Enforce idle mode by resetting the set temperature."""
        # Determine last mode for reset

        idle_temperature = self.heating_idle_temp
        if current_mode == "cool":
            idle_temperature = self.cooling_idle_temp
        await self.adjust_climate_setpoint(idle_temperature, mode=current_mode, message="enforcing idle mode")

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

    def temperature_reached_threshold(self, 
            external_temp: float = None,
            current_mode: str = None,
        ) -> bool:
        
        if current_mode == "heat":
            heating_desired_temp = self.heating_desired_temp()
            if external_temp >= (heating_desired_temp + self.heating_overshoot):
                self.log_message(f"Heating has reached threshold. Current={external_temp}, Desired={heating_desired_temp}", "debug")
                return True

        if current_mode == "cool":
            cooling_desired_temp = self.cooling_desired_temp()
            if external_temp <= (cooling_desired_temp - self.cooling_overshoot):
                self.log_message(f"Cooling has reached threshold. Current={external_temp}, Desired={cooling_desired_temp}", "debug")
                return True

        if current_mode == "dry":
            # Exit dry mode if temperature moves outside acceptable range
            heating_desired_temp = self.heating_desired_temp()
            cooling_desired_temp = self.cooling_desired_temp()
            if heating_desired_temp is not None and cooling_desired_temp is not None:
                temp_range_min = heating_desired_temp - self.humidity_temp_window
                temp_range_max = cooling_desired_temp + self.humidity_temp_window
                if external_temp < temp_range_min or external_temp > temp_range_max:
                    self.log_message(f"Exiting dry mode: temperature outside range. Current={external_temp}, Range=({temp_range_min}, {temp_range_max})", "debug")
                    return True  # Exit dry mode
                else:
                    self.log_message(f"Dry mode temperature within range. Current={external_temp}, Range=({temp_range_min}, {temp_range_max})", "debug")
                    return False  # Stay in dry mode

        self.log_message(f"Temperature threshold not reached. Current={external_temp}, Heating setpoint={heating_desired_temp}, Cooling setpoint={cooling_desired_temp}, current_mode={current_mode}", "debug")
        return False

    def humidity_threshold_reached(self, external_humidity: float) -> bool:
        """Returns True if humidity is below the threshold (dry enough to stop drying)"""
        if external_humidity is None:
            self.log_message("Humidity data not available", "debug")
            return False
        
        # Add some hysteresis to prevent rapid cycling
        # Stop drying when humidity drops below threshold minus some buffer
        humidity_stop_threshold = self.humidity_threshold - 3 # TODO - can make this a variable, humidity overshoot
        
        if external_humidity <= humidity_stop_threshold:
            self.log_message(f"Humidity threshold reached. Current={external_humidity}%, Stop threshold={humidity_stop_threshold}%", "debug")
            return True
        else:
            self.log_message(f"Humidity still above threshold. Current={external_humidity}%, Stop threshold={humidity_stop_threshold}%", "debug")
            return False
    
    async def update_desired_temp(self, setpoint: float, mode: str) -> None:
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

    async def climate_has_manually_adjusted_setpoint(
            self, 
            allow_current_setpoint: bool = False,
            current_set_point: float = None,
            current_mode: str = None,
        ) -> bool:
        """Check if the set temperature is outside known numbers."""
        if current_mode == "heat":
            if current_set_point is self.heating_active_temp or current_set_point is self.heating_idle_temp:
                return False
            if allow_current_setpoint and current_set_point == int(self.heating_desired_temp()):
                return False
            return True
        if current_mode == "cool":
            if current_set_point is self.cooling_active_temp or current_set_point is self.cooling_idle_temp:
                return False
            if allow_current_setpoint and current_set_point == int(self.cooling_desired_temp()):
                return False
            return True
    
    async def force_reset_setpoint(self, call):
        """Force reset the set temperature."""
        if not await self.climate_has_manually_adjusted_setpoint(allow_current_setpoint=False):
            return
        # Determine last mode for reset
        current_mode = self.current_mode()
        current_set_point = self.get_climate_setpoint()
        if current_mode == "heat":
            self.log_message(f"Should force reset heating. Current={current_set_point}, Desired={self.heating_idle_temp}", "info")
            await self.adjust_climate_setpoint(self.heating_idle_temp, mode="heat")
        if current_mode == "cool":
            self.log_message(f"Should force reset cooling. Current={current_set_point}, Desired={self.cooling_idle_temp}", "info")
            await self.adjust_climate_setpoint(self.cooling_idle_temp, mode="cool")
        if not self.climate_is_active(climate_setpoint=current_set_point):
            self.log_message(f"Climate setpoint is still manually adjusted, resetting to an idle state", "info")
            current_mode = self.current_mode()
            await self.enforce_idle_mode(current_mode=current_mode)

    @callback
    async def update(self, now):
        if self.in_wait_period():
            return

        external_temperature = self.external_temperature()
        external_humidity = self.external_humidity()
        current_set_point = self.get_climate_setpoint()
        current_mode = self.current_mode()

        # Skip if we don't have valid temperature readings
        if external_temperature is None or current_set_point is None or current_mode is None:
            self.log_message("Skipping update: missing temperature data", "debug")
            return

        # Check if there is a manually adjusted temperature
        if await self.climate_has_manually_adjusted_setpoint(
            allow_current_setpoint=True,
            current_set_point=current_set_point,
            current_mode=current_mode
        ):
            if current_set_point is not None:
                self.log_message(f"Manually adjusted temperature of {current_set_point} detected. Updating setpoint.", "debug")
                await self.update_desired_temp(current_set_point, current_mode)
            return

        if self.climate_is_active(climate_setpoint=current_set_point):
            if self.temperature_reached_threshold(
                external_temp=external_temperature,
                current_mode=current_mode
            ):
                await self.enforce_idle_mode(current_mode=current_mode)
            return

        if self.needs_heating(external_temperature):
            await self.adjust_climate_setpoint(self.heating_active_temp, mode="heat")
            return

        if self.needs_cooling(external_temperature):
            await self.adjust_climate_setpoint(self.cooling_active_temp, mode="cool")
            return

        if self.needs_drying(external_temperature, external_humidity):
            # If drying is needed, set the mode to dry
            if current_mode != "dry":
                await self.adjust_climate_dry(current_mode=current_mode)
            return

        if current_mode == "dry":
            # If we are in dry mode, check if things have gotten too hot or cold
            if self.temperature_reached_threshold(
                external_temp=external_temperature,
                current_mode=current_mode
            ):
                await self.enforce_idle_mode(current_mode="cool") # Likely in cooling mode after dry
                return
            if self.humidity_threshold_reached(external_humidity):
                await self.enforce_idle_mode(current_mode="cool") # Likely in cooling mode after dry
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
