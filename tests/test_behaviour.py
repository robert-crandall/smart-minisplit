"""Behaviour beyond the acceptance criteria: options, robustness, config flow."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    SERVICE_SET_HVAC_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.range_thermostat.const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEADBAND,
    CONF_MIN_CYCLE_DURATION,
    CONF_OVERSHOOT,
    CONF_RESEND_INTERVAL,
    CONF_SENSOR_ENTITY,
    CONF_SENSOR_TIMEOUT,
    CONF_SINGLE_COMMAND,
    DOMAIN,
)

from .conftest import (
    CLIMATE_ENTITY,
    SENSOR_ENTITY,
    THERMOSTAT,
    Command,
    ESPHomeStyleMinisplit,
)
from .test_acceptance import NO_SENSOR_TIMEOUT, advance, set_band


async def test_overshoot_pulls_the_setpoint_inward(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Heating aims above the bottom of the band by the overshoot."""
    await setup_thermostat(70.0, **{CONF_OVERSHOOT: 0.5})
    await set_band(hass, 70, 72)

    set_sensor(68.5)
    await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.HEAT, 70.5)


async def test_overshoot_is_clamped_at_the_midpoint(
    hass, setup_thermostat, minisplit, set_sensor
):
    """An absurd overshoot can never push a setpoint past the middle of the band."""
    await setup_thermostat(70.0, **{CONF_OVERSHOOT: 10.0})
    await set_band(hass, 70, 72)

    set_sensor(74.0)
    await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.COOL, 71.0)


async def test_resend_reasserts_the_same_command(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """resend_interval re-issues an unchanged command to survive dropped IR."""
    await setup_thermostat(70.0, **{CONF_RESEND_INTERVAL: 5})
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)

    await advance(hass, freezer, 5, set_sensor, 68.5)

    # The resend re-asserts the mode too, so a dropped IR frame that left the
    # unit in the wrong mode gets corrected, not just the setpoint.
    assert minisplit.commands[-2:] == [
        Command(HVACMode.HEAT, 70.0),
        Command(HVACMode.HEAT, None),
    ]
    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)


async def test_resend_disabled_by_default(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """With resend_interval 0 nothing is re-sent."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    minisplit.commands.clear()

    for _ in range(3):
        await advance(hass, freezer, 5, set_sensor, 68.5)

    assert minisplit.commands == []


async def test_unavailable_minisplit_is_retried(
    hass, setup_thermostat, minisplit, set_sensor
):
    """A command against an unavailable unit is skipped, not raised, and retried."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    minisplit.set_available(False)
    await hass.async_block_till_done()

    set_sensor(68.5)
    await hass.async_block_till_done()
    assert minisplit.commands == []

    minisplit.set_available(True)
    await hass.async_block_till_done()
    set_sensor(68.4)
    await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)


async def test_options_apply_without_a_restart(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Changing the deadband takes effect on the live entity."""
    entry = await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(69.2)
    await hass.async_block_till_done()
    assert minisplit.commands == []

    hass.config_entries.async_update_entry(entry, options={CONF_DEADBAND: 0.1})
    await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)


async def test_options_update_keeps_the_cooldown(
    hass, setup_thermostat, minisplit, set_sensor
):
    """An options edit must not reset the mode-change cooldown."""
    entry = await setup_thermostat(70.0, **NO_SENSOR_TIMEOUT)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry, options={**NO_SENSOR_TIMEOUT, CONF_OVERSHOOT: 0.0}
    )
    await hass.async_block_till_done()

    remaining = hass.states.get(THERMOSTAT).attributes["time_until_next_allowed_change"]
    assert 0 < remaining <= 15 * 60


async def test_turning_back_on_can_act_immediately(
    hass, setup_thermostat, minisplit, set_sensor
):
    """A user off/on is not treated as a compressor cycle."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()

    for mode in (HVACMode.OFF, HVACMode.HEAT_COOL):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: THERMOSTAT, "hvac_mode": mode},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)
    assert (
        hass.states.get(THERMOSTAT).attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    )


async def test_off_is_not_resent_every_cycle(
    hass, setup_thermostat, minisplit, set_sensor, freezer
):
    """Turning off issues exactly one command, not one per evaluation."""
    await setup_thermostat(70.0)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: THERMOSTAT, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()

    for _ in range(3):
        await advance(hass, freezer, 5, set_sensor, 60.0)

    assert minisplit.commands == [Command(HVACMode.OFF, None)]


async def test_celsius_sensor_is_converted(
    hass, setup_thermostat, minisplit, set_sensor
):
    """A sensor reporting Celsius still governs a Fahrenheit thermostat."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)

    hass.states.async_set(
        SENSOR_ENTITY,
        "20",  # 68.0 F
        {
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
            "device_class": "temperature",
        },
        force_update=True,
    )
    await hass.async_block_till_done()

    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)
    assert hass.states.get(THERMOSTAT).attributes["current_temperature"] == 68


async def test_band_is_clamped_to_the_units_limits(hass, setup_thermostat):
    """The band can never ask for something the minisplit would reject."""
    await setup_thermostat(70.0)

    with pytest.raises(ServiceValidationError):
        # The underlying reports min_temp 60, so HA rejects this outright.
        await set_band(hass, 40, 50)

    state = hass.states.get(THERMOSTAT)
    assert state.attributes["min_temp"] == 60
    assert state.attributes["max_temp"] == 86
    assert state.attributes["target_temp_step"] == 1


async def test_only_heat_cool_and_off_are_offered(hass, setup_thermostat):
    """No heat-only or cool-only passthrough."""
    await setup_thermostat(70.0)
    assert hass.states.get(THERMOSTAT).attributes["hvac_modes"] == [
        HVACMode.HEAT_COOL,
        HVACMode.OFF,
    ]


async def test_unload_entry(hass, setup_thermostat):
    """The entity goes away cleanly."""
    entry = await setup_thermostat(70.0)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(THERMOSTAT).state == STATE_UNAVAILABLE


async def test_config_flow_creates_an_entry(hass, setup_thermostat, minisplit):
    """The UI flow produces a usable entry."""
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import (
        setup_test_component_platform,
    )

    setup_test_component_platform(hass, "climate", [minisplit])
    assert await async_setup_component(
        hass, "climate", {"climate": {"platform": "test"}}
    )
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Bedroom Range",
            CONF_CLIMATE_ENTITY: CLIMATE_ENTITY,
            CONF_SENSOR_ENTITY: SENSOR_ENTITY,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom Range"
    assert result["data"][CONF_CLIMATE_ENTITY] == CLIMATE_ENTITY


async def test_config_flow_rejects_a_second_thermostat(hass, setup_thermostat):
    """One range thermostat per minisplit."""
    await setup_thermostat(70.0)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Duplicate",
            CONF_CLIMATE_ENTITY: CLIMATE_ENTITY,
            CONF_SENSOR_ENTITY: SENSOR_ENTITY,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass, setup_thermostat):
    """Every tunable is editable from the options flow."""
    entry = await setup_thermostat(70.0)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEADBAND: 2.0,
            CONF_MIN_CYCLE_DURATION: 30,
            CONF_OVERSHOOT: 1.5,
            CONF_SENSOR_TIMEOUT: 20,
            CONF_RESEND_INTERVAL: 10,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DEADBAND] == 2.0
    assert entry.options[CONF_MIN_CYCLE_DURATION] == 30


async def test_repeated_identical_readings_are_not_stale(
    hass, setup_thermostat, minisplit, freezer
):
    """A sensor re-reporting the same value keeps the thermostat alive.

    Home Assistant does not bump ``last_updated`` when a state is written with an
    identical value; it only bumps ``last_reported``. Reading the wrong one would
    make a perfectly healthy sensor look stale after ``sensor_timeout``.
    """
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)

    for _ in range(4):
        freezer.tick(timedelta(minutes=6))
        hass.states.async_set(
            SENSOR_ENTITY,
            "70",
            {
                ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.FAHRENHEIT,
                "device_class": "temperature",
            },
        )
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert hass.states.get(THERMOSTAT).attributes["sensor_stale"] is False


# ----------------------------------------------------------------------
# How a mode change is put on the wire
# ----------------------------------------------------------------------


async def test_mode_change_is_two_calls_by_default(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Setpoint then mode, so it works on platforms that ignore hvac_mode.

    Home Assistant forwards ``hvac_mode`` into ``async_set_temperature``
    without dispatching ``async_set_hvac_mode``, and most climate platforms
    ignore the kwarg. The default mock is one of those, so a single combined
    call would leave the unit off.
    """
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()

    # Setpoint lands first, while the unit is still off; then the mode.
    assert minisplit.commands == [
        Command(HVACMode.OFF, 70.0),
        Command(HVACMode.HEAT, None),
    ]
    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)


async def test_setpoint_change_within_a_mode_is_one_call(
    hass, setup_thermostat, minisplit, set_sensor
):
    """No mode flip means no set_hvac_mode call."""
    await setup_thermostat(70.0)
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()
    minisplit.commands.clear()

    await set_band(hass, 66, 72)
    await hass.async_block_till_done()

    assert minisplit.commands == [Command(HVACMode.HEAT, 66.0)]


@pytest.mark.parametrize("minisplit", [ESPHomeStyleMinisplit], indirect=True)
async def test_single_command_option_sends_one_call(
    hass, setup_thermostat, minisplit, set_sensor
):
    """ESPHome honours hvac_mode inside set_temperature -- one call, one IR frame."""
    await setup_thermostat(70.0, **{CONF_SINGLE_COMMAND: True})
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()

    assert minisplit.commands == [Command(HVACMode.HEAT, 70.0)]
    assert minisplit.settled == Command(HVACMode.HEAT, 70.0)


async def test_single_command_would_strand_a_platform_that_ignores_hvac_mode(
    hass, setup_thermostat, minisplit, set_sensor
):
    """Why two calls is the default.

    Turning the option on against a platform that drops ``hvac_mode`` gets the
    setpoint applied and the mode silently ignored, so the unit never starts
    heating. This is the failure mode the default avoids.
    """
    await setup_thermostat(70.0, **{CONF_SINGLE_COMMAND: True})
    await set_band(hass, 70, 72)
    set_sensor(68.5)
    await hass.async_block_till_done()

    assert minisplit.target_temperature == 70.0
    assert minisplit.hvac_mode == HVACMode.OFF
