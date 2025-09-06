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
        external_temp_sensor="sensor.room_temp",
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

def test_room_actual_temp(controller, fake_hass):
    assert controller.room_actual_temp() == 70.0
    fake_hass.states.set("sensor.room_temp", "bad")
    assert controller.room_actual_temp() is None


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
    # External temp below threshold triggers heating
    assert controller.needs_heating(external_temp=66.5)  # threshold 1.0 below 68
    # External temp above threshold doesn't trigger
    assert not controller.needs_heating(external_temp=67.2)
    # Disable heating
    fake_hass.states.set("input_boolean.heating_enabled", "off")
    assert not controller.needs_heating(external_temp=60)


def test_needs_cooling(controller, fake_hass):
    # External temp above threshold triggers cooling (74 + 1.5 = 75.5)
    assert controller.needs_cooling(external_temp=76.0)
    # External temp below threshold does not
    assert not controller.needs_cooling(external_temp=75.0)
    # Disable cooling
    fake_hass.states.set("input_boolean.cooling_enabled", "off")
    assert not controller.needs_cooling(external_temp=80.0)

# ---------- Overcool and thresholds ----------

def test_is_overcooled(controller, fake_hass):
    # Setup heating desired lower for test
    fake_hass.states.set("input_number.heating_desired_temp", "66")
    # external temp less than desired + overshoot triggers overcooled
    assert controller.is_overcooled(current_mode="cool", external_temp=66.5)  # overshoot 1.5 -> 66 + 1.5 = 67.5
    # Not overcooled at higher temp
    assert not controller.is_overcooled(current_mode="cool", external_temp=69)
    # If in heat mode, always False
    assert not controller.is_overcooled(current_mode="heat", external_temp=60)


def test_temperature_reached_threshold_heating(controller, fake_hass):
    fake_hass.states.set("input_number.heating_desired_temp", "66")
    # At desired + overshoot triggers threshold reached
    assert controller.temperature_reached_threshold(external_temp=67.6, current_mode="heat")
    # Below threshold -> not reached
    assert not controller.temperature_reached_threshold(external_temp=66.5, current_mode="heat")


def test_temperature_reached_threshold_cooling(controller, fake_hass):
    fake_hass.states.set("input_number.cooling_desired_temp", "74")
    # At desired - overshoot triggers threshold (74 - 1.0 = 73.0)
    assert controller.temperature_reached_threshold(external_temp=73.0, current_mode="cool")
    # Above threshold -> not reached
    assert not controller.temperature_reached_threshold(external_temp=73.5, current_mode="cool")

# ---------- Climate active ----------

def test_climate_is_active(controller):
    assert controller.climate_is_active(climate_setpoint=controller.heating_active_temp)
    assert controller.climate_is_active(climate_setpoint=controller.cooling_active_temp)
    assert not controller.climate_is_active(climate_setpoint=70)

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
