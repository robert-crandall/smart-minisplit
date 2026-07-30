"""Fixtures for the Range Thermostat tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    setup_test_component_platform,
)

from custom_components.range_thermostat.const import (
    CONF_CLIMATE_ENTITY,
    CONF_SENSOR_ENTITY,
    DOMAIN,
)

CLIMATE_ENTITY = "climate.minisplit"
SENSOR_ENTITY = "sensor.bedroom_temperature"
THERMOSTAT = "climate.bedroom_range"


@dataclass
class Command:
    """One command the thermostat sent to the minisplit."""

    hvac_mode: HVACMode | None
    temperature: float | None

    def __repr__(self) -> str:  # pragma: no cover - test output only
        return f"<{self.hvac_mode} @ {self.temperature}>"


class MockMinisplit(ClimateEntity):
    """A single-setpoint climate entity that records what it is told to do.

    Defaults to the common case: a platform that ignores ``hvac_mode`` passed
    into ``set_temperature``. Home Assistant forwards that kwarg without
    dispatching ``async_set_hvac_mode``, and most platforms drop it on the
    floor, so a thermostat that relies on it would never change mode here.
    """

    _attr_name = "Minisplit"
    _attr_unique_id = "minisplit"
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 60
    _attr_max_temp = 86
    _attr_target_temperature_step = 1

    #: Whether ``async_set_temperature`` acts on a ``hvac_mode`` kwarg.
    honours_hvac_mode = False

    def __init__(self) -> None:
        """Start powered off."""
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 72
        self.commands: list[Command] = []
        self._available = True

    @property
    def available(self) -> bool:
        """Return whether the unit is reachable."""
        return self._available

    @property
    def settled(self) -> Command | None:
        """The state the unit was driven to, or None if nothing was sent.

        A mode change is normally two service calls, so the individual entries
        in ``commands`` include a transient. This is the net result.
        """
        if not self.commands:
            return None
        return Command(self._attr_hvac_mode, self._attr_target_temperature)

    def set_available(self, available: bool) -> None:
        """Flip availability and push the new state."""
        self._available = available
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Record a setpoint, and a mode only if this platform honours one."""
        hvac_mode = kwargs.get("hvac_mode")
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if hvac_mode is not None and self.honours_hvac_mode:
            self._attr_hvac_mode = HVACMode(hvac_mode)
        if temperature is not None:
            self._attr_target_temperature = temperature
        self.commands.append(Command(self._attr_hvac_mode, temperature))
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Record a mode change."""
        self._attr_hvac_mode = hvac_mode
        self.commands.append(Command(hvac_mode, None))
        self.async_write_ha_state()


class ESPHomeStyleMinisplit(MockMinisplit):
    """An IR bridge that folds ``hvac_mode`` into one command, as ESPHome does."""

    honours_hvac_mode = True


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ during tests."""
    return enable_custom_integrations


@pytest.fixture
def minisplit(request) -> MockMinisplit:
    """Return the fake underlying unit.

    Parametrize indirectly to swap in a different platform flavour, e.g.
    ``@pytest.mark.parametrize("minisplit", [ESPHomeStyleMinisplit], indirect=True)``.
    """
    cls = getattr(request, "param", MockMinisplit)
    return cls()


@pytest.fixture
def set_sensor(hass: HomeAssistant) -> Callable[[float | str], None]:
    """Return a helper that writes a new value to the external sensor."""

    def _set(value: float | str) -> None:
        attributes = {"device_class": "temperature"}
        if value != STATE_UNAVAILABLE:
            attributes[ATTR_UNIT_OF_MEASUREMENT] = UnitOfTemperature.FAHRENHEIT
        hass.states.async_set(SENSOR_ENTITY, str(value), attributes, force_update=True)

    return _set


@pytest.fixture
def make_entry() -> Callable[..., MockConfigEntry]:
    """Return a factory for Range Thermostat config entries."""

    def _make(**options: Any) -> MockConfigEntry:
        return MockConfigEntry(
            domain=DOMAIN,
            title="Bedroom Range",
            data={
                CONF_NAME: "Bedroom Range",
                CONF_CLIMATE_ENTITY: CLIMATE_ENTITY,
                CONF_SENSOR_ENTITY: SENSOR_ENTITY,
            },
            options=options,
            unique_id=CLIMATE_ENTITY,
        )

    return _make


@pytest.fixture
def setup_thermostat(
    hass: HomeAssistant,
    minisplit: MockMinisplit,
    set_sensor,
    make_entry,
) -> Callable[..., Any]:
    """Return a coroutine factory that brings up the whole stack."""

    async def _setup(
        temperature: float | str = 70.0, **options: Any
    ) -> MockConfigEntry:
        hass.config.units = US_CUSTOMARY_SYSTEM
        setup_test_component_platform(hass, "climate", [minisplit])
        assert await async_setup_component(
            hass, "climate", {"climate": {"platform": "test"}}
        )
        set_sensor(temperature)
        await hass.async_block_till_done()

        entry = make_entry(**options)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
