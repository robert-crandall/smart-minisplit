"""Tests for the Smart Thermostat Controller sensor platform."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature, UnitOfTime, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.const import DOMAIN
from custom_components.smart_thermostat_controller.coordinator import SmartThermostatCoordinator
from custom_components.smart_thermostat_controller.models import (
    ControllerState,
    SmartThermostatConfig,
    TemperatureDataPoint,
)
from custom_components.smart_thermostat_controller.sensor import (
    SmartThermostatSensor,
    SENSOR_DESCRIPTIONS,
    async_setup_entry,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock(spec=SmartThermostatCoordinator)
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.entry_id = "test_entry"
    coordinator.config = SmartThermostatConfig(
        external_temp_sensor="sensor.temp",
        external_humidity_sensor="sensor.humidity",
        minisplit_entity="climate.minisplit",
        target_temperature=72.0,
        humidity_max_threshold=60.0,
        humidity_min_threshold=40.0,
        temperature_deadband=1.0,
        cooldown_period=300,
        learning_enabled=True,
        learning_period_days=7,
        default_cooling_offset=5.0,
    )
    coordinator.last_update_success = True
    coordinator.historical_data = []
    return coordinator


@pytest.fixture
def mock_controller_state():
    """Create a mock controller state."""
    return ControllerState(
        current_mode="cool",
        target_temperature=72.0,
        current_temperature=75.0,
        current_humidity=55.0,
        last_mode_change=dt_util.utcnow() - timedelta(minutes=2),
        learned_offset=4.5,
        offset_confidence=0.8,
        manual_override=False,
        cooldown_remaining=120,
        is_available=True,
    )


class TestSensorDescriptions:
    """Test sensor descriptions."""

    def test_sensor_descriptions_count(self):
        """Test that all required sensors are defined."""
        assert len(SENSOR_DESCRIPTIONS) == 8
        
        expected_keys = {
            "current_mode",
            "learned_offset", 
            "offset_confidence",
            "cooldown_remaining",
            "manual_override",
            "sensor_status",
            "learning_data_points",
            "last_mode_change",
        }
        
        actual_keys = {desc.key for desc in SENSOR_DESCRIPTIONS}
        assert actual_keys == expected_keys

    def test_sensor_descriptions_properties(self):
        """Test sensor description properties."""
        descriptions_by_key = {desc.key: desc for desc in SENSOR_DESCRIPTIONS}
        
        # Test current_mode sensor
        current_mode = descriptions_by_key["current_mode"]
        assert current_mode.name == "Current Mode"
        assert current_mode.icon == "mdi:thermostat"
        assert current_mode.entity_category is None  # Main status sensor
        
        # Test learned_offset sensor
        learned_offset = descriptions_by_key["learned_offset"]
        assert learned_offset.name == "Learned Offset"
        assert learned_offset.device_class == SensorDeviceClass.TEMPERATURE
        assert learned_offset.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
        assert learned_offset.entity_category == EntityCategory.DIAGNOSTIC
        
        # Test offset_confidence sensor
        offset_confidence = descriptions_by_key["offset_confidence"]
        assert offset_confidence.name == "Offset Confidence"
        assert offset_confidence.native_unit_of_measurement == PERCENTAGE
        assert offset_confidence.entity_category == EntityCategory.DIAGNOSTIC
        
        # Test cooldown_remaining sensor
        cooldown_remaining = descriptions_by_key["cooldown_remaining"]
        assert cooldown_remaining.name == "Cooldown Remaining"
        assert cooldown_remaining.device_class == SensorDeviceClass.DURATION
        assert cooldown_remaining.native_unit_of_measurement == UnitOfTime.SECONDS
        
        # Test manual_override sensor
        manual_override = descriptions_by_key["manual_override"]
        assert manual_override.name == "Manual Override"
        assert manual_override.icon == "mdi:hand-back-right"
        assert manual_override.entity_category == EntityCategory.DIAGNOSTIC


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_async_setup_entry(self, mock_coordinator):
        """Test setting up sensor entities."""
        # Mock hass
        hass = MagicMock()
        hass.data = {DOMAIN: {"test_entry": mock_coordinator}}
        
        # Mock config entry
        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        
        # Mock async_add_entities
        async_add_entities = MagicMock()
        
        # Call setup
        await async_setup_entry(hass, config_entry, async_add_entities)
        
        # Verify entities were added
        async_add_entities.assert_called_once()
        entities = async_add_entities.call_args[0][0]
        
        assert len(entities) == 8
        assert all(isinstance(entity, SmartThermostatSensor) for entity in entities)
        
        # Verify entity keys
        entity_keys = {entity.entity_description.key for entity in entities}
        expected_keys = {desc.key for desc in SENSOR_DESCRIPTIONS}
        assert entity_keys == expected_keys


class TestSmartThermostatSensor:
    """Test SmartThermostatSensor class."""

    def test_sensor_initialization(self, mock_coordinator):
        """Test sensor initialization."""
        description = SENSOR_DESCRIPTIONS[0]  # current_mode
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.entity_description == description
        assert sensor._attr_unique_id == "test_entry_current_mode"
        assert sensor._attr_device_info["name"] == "Smart Thermostat Controller"
        assert sensor._attr_device_info["identifiers"] == {(DOMAIN, "test_entry")}

    def test_current_mode_sensor(self, mock_coordinator, mock_controller_state):
        """Test current mode sensor."""
        mock_coordinator.data = mock_controller_state
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "current_mode")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == "cool"
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["target_temperature"] == 72.0
        assert attrs["current_temperature"] == 75.0
        assert attrs["current_humidity"] == 55.0

    def test_learned_offset_sensor(self, mock_coordinator, mock_controller_state):
        """Test learned offset sensor."""
        mock_coordinator.data = mock_controller_state
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "learned_offset")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == 4.5
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["confidence"] == 0.8
        assert attrs["learning_enabled"] is True

    def test_offset_confidence_sensor(self, mock_coordinator, mock_controller_state):
        """Test offset confidence sensor."""
        mock_coordinator.data = mock_controller_state
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "offset_confidence")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == 80.0  # 0.8 * 100
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["learned_offset"] == 4.5
        assert attrs["threshold"] == 0.7

    def test_cooldown_remaining_sensor(self, mock_coordinator, mock_controller_state):
        """Test cooldown remaining sensor."""
        mock_coordinator.data = mock_controller_state
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "cooldown_remaining")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == 120
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["cooldown_period"] == 300
        assert attrs["can_change_mode"] is False

    def test_manual_override_sensor(self, mock_coordinator, mock_controller_state):
        """Test manual override sensor."""
        mock_coordinator.data = mock_controller_state
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "manual_override")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == "Off"
        
        # Test with override enabled
        mock_controller_state.manual_override = True
        assert sensor.native_value == "On"
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["automatic_control"] is False

    def test_sensor_status_sensor(self, mock_coordinator, mock_controller_state):
        """Test sensor status sensor."""
        mock_coordinator.data = mock_controller_state
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "sensor_status")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == "OK"
        
        # Test with temperature sensor unavailable
        mock_controller_state.current_temperature = None
        assert sensor.native_value == "Temperature sensor unavailable"
        
        # Test with both sensors unavailable
        mock_controller_state.current_humidity = None
        assert sensor.native_value == "2 issues"
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["temperature_sensor"] == "sensor.temp"
        assert attrs["humidity_sensor"] == "sensor.humidity"
        assert attrs["temperature_available"] is False
        assert attrs["humidity_available"] is False

    def test_learning_data_points_sensor(self, mock_coordinator, mock_controller_state):
        """Test learning data points sensor."""
        mock_coordinator.data = mock_controller_state
        mock_coordinator.historical_data = [
            TemperatureDataPoint(
                timestamp=dt_util.utcnow(),
                external_temperature=75.0,
                internal_temperature=80.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        ] * 15  # 15 data points
        
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "learning_data_points")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == 15
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["learning_period_days"] == 7
        assert attrs["learning_active"] is True

    def test_last_mode_change_sensor(self, mock_coordinator, mock_controller_state):
        """Test last mode change sensor."""
        mock_coordinator.data = mock_controller_state
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "last_mode_change")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value == mock_controller_state.last_mode_change
        
        # Test attributes
        attrs = sensor.extra_state_attributes
        assert attrs["cooldown_remaining"] == 120

    def test_sensor_availability(self, mock_coordinator, mock_controller_state):
        """Test sensor availability."""
        mock_coordinator.data = mock_controller_state
        mock_coordinator.last_update_success = True
        
        description = SENSOR_DESCRIPTIONS[0]
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.available is True
        
        # Test unavailable
        mock_coordinator.last_update_success = False
        assert sensor.available is False

    def test_sensor_no_data(self, mock_coordinator):
        """Test sensor behavior when no data is available."""
        mock_coordinator.data = None
        
        description = SENSOR_DESCRIPTIONS[0]
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        assert sensor.native_value is None
        assert sensor.extra_state_attributes is None

    def test_dynamic_icons(self, mock_coordinator, mock_controller_state):
        """Test dynamic icon changes based on state."""
        mock_coordinator.data = mock_controller_state
        
        # Test current_mode icons
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "current_mode")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        mock_controller_state.current_mode = "heat"
        assert sensor.icon == "mdi:fire"
        
        mock_controller_state.current_mode = "cool"
        assert sensor.icon == "mdi:snowflake"
        
        mock_controller_state.current_mode = "dry"
        assert sensor.icon == "mdi:water-percent"
        
        mock_controller_state.current_mode = "off"
        assert sensor.icon == "mdi:power-off"
        
        # Test manual_override icons
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "manual_override")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        mock_controller_state.manual_override = True
        assert sensor.icon == "mdi:hand-back-right"
        
        mock_controller_state.manual_override = False
        assert sensor.icon == "mdi:auto-mode"
        
        # Test sensor_status icons
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "sensor_status")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        # OK status
        assert sensor.icon == "mdi:check-circle"
        
        # Error status
        mock_controller_state.current_temperature = None
        assert sensor.icon == "mdi:alert-circle"
        
        # Test cooldown_remaining icons
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "cooldown_remaining")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        mock_controller_state.cooldown_remaining = 120
        assert sensor.icon == "mdi:timer-sand"
        
        mock_controller_state.cooldown_remaining = 0
        assert sensor.icon == "mdi:timer-sand-empty"


class TestSensorStateUpdates:
    """Test sensor state updates and data accuracy."""

    def test_sensor_state_updates_with_coordinator_data(self, mock_coordinator):
        """Test that sensors update when coordinator data changes."""
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "current_mode")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        # Initial state
        mock_coordinator.data = ControllerState(
            current_mode="off",
            target_temperature=70.0,
            current_temperature=70.0,
            current_humidity=50.0,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.0,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        assert sensor.native_value == "off"
        
        # Update state
        mock_coordinator.data.current_mode = "heat"
        assert sensor.native_value == "heat"

    def test_sensor_data_accuracy(self, mock_coordinator):
        """Test sensor data accuracy with various values."""
        # Test learned offset rounding
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "learned_offset")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        mock_coordinator.data = ControllerState(
            current_mode="cool",
            target_temperature=72.0,
            current_temperature=75.0,
            current_humidity=55.0,
            last_mode_change=dt_util.utcnow(),
            learned_offset=4.567,  # Should be rounded to 2 decimal places
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        assert sensor.native_value == 4.57
        
        # Test confidence percentage conversion
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "offset_confidence")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        mock_coordinator.data.offset_confidence = 0.856  # Should be 85.6%
        assert sensor.native_value == 85.6

    def test_sensor_error_handling(self, mock_coordinator):
        """Test sensor error handling with invalid data."""
        description = next(desc for desc in SENSOR_DESCRIPTIONS if desc.key == "current_mode")
        sensor = SmartThermostatSensor(mock_coordinator, description)
        
        # Test with None data
        mock_coordinator.data = None
        assert sensor.native_value is None
        
        # Test with missing attributes (should not raise exceptions)
        mock_coordinator.data = MagicMock()
        mock_coordinator.data.current_mode = "cool"
        
        # Should handle missing attributes gracefully
        try:
            value = sensor.native_value
            assert value == "cool"
        except AttributeError:
            pytest.fail("Sensor should handle missing attributes gracefully")