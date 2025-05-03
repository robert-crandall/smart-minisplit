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

DOMAIN = "mini_split_controller"
COOLDOWN_MINUTES = 5
TRIGGER_THRESHOLD = 2.0  # Degrees
RESET_THRESHOLD = 1.0
VALID_TEMP_RANGE = [60, 74]

async def async_setup(hass: HomeAssistant, config: ConfigType):
    controller = MiniSplitController(hass)

    async def run_update(now):
        await controller.update(now)

    async_track_time_interval(hass, run_update, timedelta(minutes=1))
    return True

class MiniSplitController:
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self.last_adjustment: datetime | None = None
        self.last_desired_temp: float | None = None
        self.adjusted_state_active: bool = False

    def debug_entity_attributes(self, entity_id: str) -> None:
        """Debug helper to print all attributes of an entity."""
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
        return (datetime.now() - self.last_adjustment) < timedelta(minutes=COOLDOWN_MINUTES)

    def get_set_temperature(self) -> float | None:
        climate_state = self.hass.states.get("climate.minisplit")
        if climate_state is None:
            self.log_message("Climate entity not available", "warning")
            return None
        set_temp = climate_state.attributes.get("temperature")
        if set_temp is not None:
          return set_temp
          
        self.log_message("Set temperature not available", "warning")
        # Debug all available attributes to see what's available
        self.debug_entity_attributes("climate.minisplit")
        return None

    def current_temperature(self) -> float | None:
        sensor_state = self.hass.states.get("sensor.awair_element_110243_temperature")
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
        if set_temp is not None and VALID_TEMP_RANGE[0] <= set_temp <= VALID_TEMP_RANGE[1]:
            self.last_desired_temp = set_temp
            self.adjusted_state_active = False
            return set_temp
        # Use the fallback sequence: last_desired_temp -> set_temp -> default range minimum
        return self.last_desired_temp or set_temp

    def needs_heat(self, current: float, desired: float) -> bool:
        if current is None or desired is None:
            return False
        return current < (desired - TRIGGER_THRESHOLD)

    def should_reset(self, current: float, desired: float) -> bool:
        if current is None or desired is None:
            return False
        return self.adjusted_state_active and current >= (desired + RESET_THRESHOLD)

    async def adjust_set_temperature(self, target_temp: float):
        min_temp = self.hass.states.get("climate.minisplit").attributes.get("min_temp", 55)
        max_temp = self.hass.states.get("climate.minisplit").attributes.get("max_temp", 82)
        if min_temp is not None:
          target_temp = max(min_temp, target_temp)
        if max_temp is not None:
          target_temp = min(max_temp, target_temp)
        self.log_message(f"Adjusting set temperature to {target_temp}", "info")
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {
                "entity_id": "climate.minisplit",
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
                "entity_id": "climate.minisplit",
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
            self.log_message("Skipping update: missing temperature data", "warning")
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
        """Log message to Home Assistant logbook and logger."""
        # Log to logger
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
