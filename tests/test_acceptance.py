"""The ten acceptance criteria from the requirements document.

Band 70-72, deadband 1.0, overshoot 0.0, min_cycle_duration 15 unless stated.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.range_thermostat.const import (
    ATTR_COMMANDED_SETPOINT,
    ATTR_SENSOR_STALE,
    ATTR_TIME_UNTIL_NEXT_ALLOWED_CHANGE,
    CONF_SENSOR_TIMEOUT,
)

from .conftest import THERMOSTAT, Command

# Long enough that time travel for the cooldown does not also age out the sensor.
NO_SENSOR_TIMEOUT = {CONF_SENSOR_TIMEOUT: 600}


async def set_band(hass: HomeAssistant, low: float, high: float) -> None:
    """Set the virtual thermostat's band the way an automation would."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: THERMOSTAT,
            "target_temp_low": low,
            "target_temp_high": high,
        },
        blocking=True,
    )
    await hass.async_block_till_done()


async def advance(
    hass: HomeAssistant, freezer, minutes: float, set_sensor, temp
) -> None:
    """Move the clock forward and let the sensor report again."""
    freezer.tick(timedelta(minutes=minutes))
    set_sensor(temp)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_1_below_band_commands_heat(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Room at 68.5 -> heat @ 70, and hvac_action reports heating."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    assert minisplit.commands == []

    set_sensor(68.5)
    await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)
    state = hass.states.get(THERMOSTAT)
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    assert state.attributes[ATTR_COMMANDED_SETPOINT] == 70.0


async def test_2_inside_band_issues_nothing(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Room rises to 72 -> no command, unit stays in heat @ 70."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    minisplit.commands.clear()

    for temperature in (69.0, 70.0, 71.0, 72.0):
        set_sensor(temperature)
        await hass.async_block_till_done()

    assert minisplit.commands == []
    assert minisplit.hvac_mode == HVACMode.HEAT
    assert minisplit.target_temperature == 70.0
    assert (
        hass.states.get(THERMOSTAT).attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    )


async def test_3_above_band_commands_cool(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """Room rises to 74 -> cool @ 72 once the cooldown has expired."""
    await setup_thermostat(70.0, **NO_SENSOR_TIMEOUT)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    minisplit.commands.clear()

    await advance(hass, freezer, 16, set_sensor, 74.0)

    assert minisplit.settled == Command(HVACMode.COOL, 72.0)
    assert (
        hass.states.get(THERMOSTAT).attributes[ATTR_HVAC_ACTION] == HVACAction.COOLING
    )


async def test_4_cooldown_blocks_mode_change(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """A flip back within 15 minutes is blocked and reported as such."""
    await setup_thermostat(70.0, **NO_SENSOR_TIMEOUT)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    await advance(hass, freezer, 16, set_sensor, 74.0)
    minisplit.commands.clear()

    await advance(hass, freezer, 5, set_sensor, 68.5)

    assert minisplit.commands == []
    state = hass.states.get(THERMOSTAT)
    assert state.attributes[ATTR_TIME_UNTIL_NEXT_ALLOWED_CHANGE] > 0
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.COOLING


async def test_5_mode_change_after_cooldown(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """The same flip goes through once the cooldown expires."""
    await setup_thermostat(70.0, **NO_SENSOR_TIMEOUT)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    await advance(hass, freezer, 16, set_sensor, 74.0)
    await advance(hass, freezer, 5, set_sensor, 68.5)
    minisplit.commands.clear()

    await advance(hass, freezer, 11, set_sensor, 68.5)

    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)
    # The flip restarts the cooldown.
    assert (
        hass.states.get(THERMOSTAT).attributes[ATTR_TIME_UNTIL_NEXT_ALLOWED_CHANGE] > 0
    )


async def test_6_same_mode_setpoint_change_ignores_cooldown(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """Moving the band while cooling adjusts the setpoint immediately."""
    await setup_thermostat(70.0, **NO_SENSOR_TIMEOUT)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    await advance(hass, freezer, 16, set_sensor, 74.0)
    minisplit.commands.clear()

    # Still well inside the cooldown.
    await set_band(hass, 66, 68)

    assert minisplit.settled == Command(HVACMode.COOL, 68.0)
    assert (
        hass.states.get(THERMOSTAT).attributes[ATTR_TIME_UNTIL_NEXT_ALLOWED_CHANGE] > 0
    )


async def test_6b_band_change_that_needs_a_flip_still_waits(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """...unless the new band requires a mode flip, in which case cooldown applies."""
    await setup_thermostat(70.0, **NO_SENSOR_TIMEOUT)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    await advance(hass, freezer, 16, set_sensor, 74.0)
    minisplit.commands.clear()

    await set_band(hass, 78, 80)

    assert minisplit.commands == []


async def test_7_stale_sensor_stops_commanding(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """20 minutes of silence -> sensor_stale, no commands, unit untouched."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    minisplit.commands.clear()

    freezer.tick(timedelta(minutes=20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(THERMOSTAT)
    assert state.attributes[ATTR_SENSOR_STALE] is True
    assert minisplit.commands == []
    assert minisplit.hvac_mode == HVACMode.HEAT
    assert minisplit.target_temperature == 70.0


async def test_7b_unavailable_sensor_stops_commanding(
    hass, setup_thermostat, minisplit, set_sensor
):
    """An unavailable sensor is stale immediately."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    minisplit.commands.clear()

    set_sensor(STATE_UNAVAILABLE)
    await hass.async_block_till_done()

    assert hass.states.get(THERMOSTAT).attributes[ATTR_SENSOR_STALE] is True
    assert minisplit.commands == []


async def test_8_restart_restores_band_and_mode(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Band and hvac_mode survive a restart; cooldown does not."""
    mock_restore_cache(
        hass,
        (
            State(
                THERMOSTAT,
                HVACMode.HEAT_COOL,
                {
                    ATTR_TARGET_TEMP_LOW: 66.0,
                    ATTR_TARGET_TEMP_HIGH: 68.0,
                },
            ),
        ),
    )
    await setup_thermostat(60.0)

    state = hass.states.get(THERMOSTAT)
    assert state.state == HVACMode.HEAT_COOL
    assert state.attributes[ATTR_TARGET_TEMP_LOW] == 66.0
    assert state.attributes[ATTR_TARGET_TEMP_HIGH] == 68.0
    # Cooldown is treated as expired, so the first evaluation may command straight away.
    assert minisplit.settled == Command(HVACMode.HEAT, 66.0)


async def test_9_narrow_band_is_widened(hass, setup_thermostat, caplog):
    """70-70.5 with deadband 1.0 is widened to the minimum controllable width."""
    await setup_thermostat(70.0)

    await set_band(hass, 70, 70.5)

    state = hass.states.get(THERMOSTAT)
    # Displayed at the entity's precision (whole degrees F); the band is 69.25-71.25.
    assert (
        state.attributes[ATTR_TARGET_TEMP_HIGH] - state.attributes[ATTR_TARGET_TEMP_LOW]
        >= 2.0
    )
    assert "narrower than 2 x deadband" in caplog.text


async def test_10_identical_evaluations_issue_one_command(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Repeated evaluations under identical conditions are deduplicated."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    minisplit.commands.clear()

    set_sensor(68.5)
    await hass.async_block_till_done()
    set_sensor(68.5)
    await hass.async_block_till_done()
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)


async def test_off_is_only_commanded_by_the_user(
    hass, setup_thermostat, minisplit, set_sensor
):
    """OFF is never used to regulate, only when the virtual thermostat is turned off."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    minisplit.commands.clear()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: THERMOSTAT, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert minisplit.commands == [Command(HVACMode.OFF, None)]
    state = hass.states.get(THERMOSTAT)
    assert state.state == HVACMode.OFF
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.OFF
