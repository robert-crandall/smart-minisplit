import pytest
from datetime import datetime, timedelta

from custom_components.smart_mini_split.__init__ import (
    MiniSplitController,
    DEFAULT_WAIT_PERIOD_MINUTES,
    DEFAULT_HEATING_THRESHOLD,
    DEFAULT_COOLING_THRESHOLD,
    DEFAULT_HEATING_OVERSHOOT,
    DEFAULT_COOLING_OVERSHOOT,
)

@pytest.fixture
def controller(fake_hass):
    c = MiniSplitController(
        fake_hass,
        log_level="debug",
        wait_period_minutes=DEFAULT_WAIT_PERIOD_MINUTES,
        heating_threshold=DEFAULT_HEATING_THRESHOLD,
        cooling_threshold=DEFAULT_COOLING_THRESHOLD,
        heating_overshoot=DEFAULT_HEATING_OVERSHOOT,
        cooling_overshoot=DEFAULT_COOLING_OVERSHOOT,
        climate_entity="climate.test_minisplit",
        room_temp_sensor="sensor.room_temp",
        external_humidity_sensor="sensor.room_humidity",
    )
    # Default entity states
    fake_hass.states.set("input_boolean.heating_enabled", "on")
    fake_hass.states.set("input_boolean.cooling_enabled", "on")
    fake_hass.states.set("input_number.heating_desired_temp", "68")
    fake_hass.states.set("input_number.cooling_desired_temp", "74")
    fake_hass.states.set("sensor.room_temp", "70")
    fake_hass.states.set("sensor.room_humidity", "40")
    fake_hass.states.set("climate.test_minisplit", "cool", temperature=74, current_temperature=75)
    return c

# ---------- Helper tests ----------

def test_numbers_are_close(controller):
    assert controller.numbers_are_close(1.0, 1.05)
    assert not controller.numbers_are_close(1.0, 1.2)
    assert not controller.numbers_are_close(None, 1.0)

# ---------- Temperature & humidity acquisition ----------

def test_room_temp(controller, fake_hass):
    # Manually refresh cached value
    controller._update_room_temp()
    assert controller.room_temp == 70.0
    fake_hass.states.set("sensor.room_temp", "bad")
    controller._update_room_temp()
    assert controller.room_temp is None


def test_external_humidity(controller, fake_hass):
    assert controller.external_humidity() == 40.0
    fake_hass.states.set("sensor.room_humidity", "bad")
    assert controller.external_humidity() is None

# ---------- Desired temperature logic ----------

def test_heating_desired_temp(controller, fake_hass):
    # Valid case
    assert controller.heating_desired_temp() == 68.0
    # Above max allowed (>= highest_heating_temp)
    fake_hass.states.set("input_number.heating_desired_temp", str(controller.highest_heating_temp + 1))
    assert controller.heating_desired_temp() is None


def test_cooling_desired_temp(controller, fake_hass):
    assert controller.cooling_desired_temp() == 74.0
    # Below minimum: returns enforced minimum (lowest_cooling_temp)
    fake_hass.states.set("input_number.cooling_desired_temp", str(controller.lowest_cooling_temp - 5))
    assert controller.cooling_desired_temp() == controller.lowest_cooling_temp

# ---------- Need heating / cooling logic ----------

def test_needs_heating(controller, fake_hass):
    # Set cached temp below threshold
    fake_hass.states.set("sensor.room_temp", "66.5")
    controller._update_room_temp()
    assert controller.needs_heating()  # threshold 1.0 below 68
    # Above threshold
    fake_hass.states.set("sensor.room_temp", "67.2")
    controller._update_room_temp()
    assert not controller.needs_heating()
    # Disable heating
    fake_hass.states.set("input_boolean.heating_enabled", "off")
    assert not controller.needs_heating()


def test_needs_cooling(controller, fake_hass):
    # Above threshold (74 + 1.5 = 75.5)
    fake_hass.states.set("sensor.room_temp", "76.0")
    controller._update_room_temp()
    assert controller.needs_cooling()
    # Below threshold
    fake_hass.states.set("sensor.room_temp", "75.0")
    controller._update_room_temp()
    assert not controller.needs_cooling()
    # Disable cooling
    fake_hass.states.set("input_boolean.cooling_enabled", "off")
    assert not controller.needs_cooling()

# ---------- Overcool and thresholds ----------

def test_is_overcooled(controller, fake_hass):
    fake_hass.states.set("input_number.heating_desired_temp", "66")
    fake_hass.states.set("sensor.room_temp", "66.5")
    controller._update_room_temp()
    controller._update_climate_mode()
    assert controller.is_overcooled()  # overshoot 1.5 -> 66 + 1.5 = 67.5
    fake_hass.states.set("sensor.room_temp", "69")
    controller._update_room_temp()
    assert not controller.is_overcooled()
    fake_hass.states.set("sensor.room_temp", "60")
    controller._update_room_temp()
    # Switch climate to heat to validate heat path
    fake_hass.states.set("climate.test_minisplit", "heat", temperature=controller.heating_active_temp, current_temperature=60)
    controller._update_climate_mode()
    assert not controller.is_overcooled()


def test_temperature_reached_threshold_heating(controller, fake_hass):
    fake_hass.states.set("input_number.heating_desired_temp", "66")
    fake_hass.states.set("sensor.room_temp", "67.6")
    controller._update_room_temp()
    fake_hass.states.set("climate.test_minisplit", "heat", temperature=controller.heating_active_temp, current_temperature=67.6)
    controller._update_climate_mode()
    assert controller.temperature_reached_threshold()
    fake_hass.states.set("sensor.room_temp", "66.5")
    controller._update_room_temp()
    assert not controller.temperature_reached_threshold()


def test_temperature_reached_threshold_cooling(controller, fake_hass):
    fake_hass.states.set("input_number.cooling_desired_temp", "74")
    fake_hass.states.set("sensor.room_temp", "73.0")
    controller._update_room_temp()
    # Ensure climate mode is cool
    fake_hass.states.set("climate.test_minisplit", "cool", temperature=controller.cooling_active_temp, current_temperature=73.0)
    controller._update_climate_mode()
    assert controller.temperature_reached_threshold()
    fake_hass.states.set("sensor.room_temp", "73.5")
    controller._update_room_temp()
    assert not controller.temperature_reached_threshold()

# ---------- Climate active ----------

def test_climate_is_active(controller, fake_hass):
    # Initial setpoint (74) is neither active heating (82) nor active cooling (60)
    controller._update_climate_setpoint()
    assert controller.climate_setpoint == 74
    assert not controller.climate_is_active()

    # Simulate active heating
    fake_hass.states.set("climate.test_minisplit", "heat", temperature=controller.heating_active_temp, current_temperature=70)
    controller._update_climate_setpoint()
    assert controller.climate_setpoint == controller.heating_active_temp
    assert controller.climate_is_active()

    # Simulate active cooling
    fake_hass.states.set("climate.test_minisplit", "cool", temperature=controller.cooling_active_temp, current_temperature=75)
    controller._update_climate_setpoint()
    assert controller.climate_setpoint == controller.cooling_active_temp
    assert controller.climate_is_active()

    # Back to an idle midpoint value
    fake_hass.states.set("climate.test_minisplit", "cool", temperature=70, current_temperature=72)
    controller._update_climate_setpoint()
    assert controller.climate_setpoint == 70
    assert not controller.climate_is_active()

# ---------- Wait period ----------

def test_in_wait_period_recent_adjustment(controller):
    controller.last_adjustment = datetime.now() - timedelta(minutes=controller.wait_period_minutes - 1)
    assert controller.in_wait_period()


def test_in_wait_period_last_events(controller, fake_hass):
    # No recent events
    assert not controller.in_wait_period()
    # Set recent heating event
    fake_hass.states.set("input_datetime.last_heating_event", (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"))
    assert controller.in_wait_period()

# Additional test for numbers_are_close on edge threshold

def test_numbers_are_close_edge(controller):
    assert controller.numbers_are_close(10.0, 10.05)
    assert not controller.numbers_are_close(10.0, 10.11)
