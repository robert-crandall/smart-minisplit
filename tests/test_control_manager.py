"""Tests for the ControlManager class."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock

from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.control_manager import ControlManager
from custom_components.smart_thermostat_controller.const import (
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
)
from custom_components.smart_thermostat_controller.models import (
    ControllerState,
    SensorReadings,
    SmartThermostatConfig,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return Mock()


@pytest.fixture
def default_config():
    """Create a default configuration for testing."""
    return SmartThermostatConfig(
        external_temp_sensor="sensor.temp",
        external_humidity_sensor="sensor.humidity",
        minisplit_entity="climate.minisplit",
        target_temperature=72.0,
        humidity_max_threshold=60.0,
        humidity_min_threshold=40.0,
        temperature_deadband=1.0,
        cooldown_period=300,  # 5 minutes
        learning_enabled=True,
        learning_period_days=7,
        default_cooling_offset=5.0,
    )


@pytest.fixture
def control_manager(mock_hass, default_config):
    """Create a ControlManager instance for testing."""
    return ControlManager(mock_hass, default_config)


@pytest.fixture
def default_controller_state():
    """Create a default controller state for testing."""
    return ControllerState(
        current_mode=HVAC_MODE_OFF,
        target_temperature=72.0,
        current_temperature=72.0,
        current_humidity=50.0,
        last_mode_change=None,
        learned_offset=5.0,
        offset_confidence=0.8,
        manual_override=False,
        cooldown_remaining=0,
    )


@pytest.fixture
def valid_sensor_readings():
    """Create valid sensor readings for testing."""
    return SensorReadings(
        temperature=72.0,
        humidity=50.0,
        timestamp=dt_util.utcnow(),
        temperature_available=True,
        humidity_available=True,
    )


class TestControlManager:
    """Test the ControlManager class."""

    def test_init(self, mock_hass, default_config):
        """Test ControlManager initialization."""
        manager = ControlManager(mock_hass, default_config)
        
        assert manager._hass is mock_hass
        assert manager._config is default_config
        assert manager._last_mode_change is None
        assert manager._current_mode == HVAC_MODE_OFF

    def test_calculate_required_action_invalid_readings(
        self, control_manager, default_controller_state
    ):
        """Test calculation with invalid sensor readings."""
        # Create invalid readings (old timestamp)
        old_timestamp = dt_util.utcnow() - timedelta(minutes=10)
        invalid_readings = SensorReadings(
            temperature=72.0,
            humidity=50.0,
            timestamp=old_timestamp,
            temperature_available=True,
            humidity_available=True,
        )
        
        action = control_manager.calculate_required_action(
            invalid_readings, default_controller_state
        )
        
        assert action.action_type == HVAC_MODE_OFF
        assert action.can_execute is False
        assert "Invalid or stale sensor readings" in action.reason

    def test_calculate_required_action_humidity_priority(
        self, control_manager, default_controller_state, valid_sensor_readings
    ):
        """Test that humidity control takes priority over temperature."""
        # Set humidity above threshold
        high_humidity_readings = SensorReadings(
            temperature=70.0,  # Below target, would normally heat
            humidity=65.0,     # Above threshold, should trigger dry mode
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        action = control_manager.calculate_required_action(
            high_humidity_readings, default_controller_state
        )
        
        assert action.action_type == HVAC_MODE_DRY
        assert action.target_temperature == default_controller_state.target_temperature
        assert "Humidity 65.0% > 60.0%" in action.reason

    def test_calculate_required_action_cooling_needed(
        self, control_manager, default_controller_state, valid_sensor_readings
    ):
        """Test cooling activation when temperature exceeds target + deadband."""
        # Set temperature above target + deadband
        hot_readings = SensorReadings(
            temperature=74.0,  # 72 + 1 + 1 = above threshold
            humidity=50.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        action = control_manager.calculate_required_action(
            hot_readings, default_controller_state
        )
        
        assert action.action_type == HVAC_MODE_COOL
        # Should apply learned offset: 72 - 5 = 67
        assert action.target_temperature == 67.0
        assert "Temperature 74.0°F > target 72.0°F + deadband 1.0°F" in action.reason

    def test_calculate_required_action_heating_needed(
        self, control_manager, default_controller_state, valid_sensor_readings
    ):
        """Test heating activation when temperature below target - deadband."""
        # Set temperature below target - deadband
        cold_readings = SensorReadings(
            temperature=70.0,  # 72 - 1 - 1 = below threshold
            humidity=50.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        action = control_manager.calculate_required_action(
            cold_readings, default_controller_state
        )
        
        assert action.action_type == HVAC_MODE_HEAT
        # No offset applied for heating
        assert action.target_temperature == 72.0
        assert "Temperature 70.0°F < target 72.0°F - deadband 1.0°F" in action.reason

    def test_calculate_required_action_within_deadband(
        self, control_manager, default_controller_state, valid_sensor_readings
    ):
        """Test that system turns off when temperature is within deadband."""
        # Temperature within deadband (72 ± 1)
        comfortable_readings = SensorReadings(
            temperature=72.5,  # Within deadband
            humidity=50.0,     # Within acceptable range
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        action = control_manager.calculate_required_action(
            comfortable_readings, default_controller_state
        )
        
        assert action.action_type == HVAC_MODE_OFF
        assert action.target_temperature is None
        assert "within acceptable ranges" in action.reason

    def test_apply_learned_offset_cooling(self, control_manager):
        """Test learned offset application for cooling mode."""
        adjusted = control_manager._apply_learned_offset(72.0, 5.0, HVAC_MODE_COOL)
        assert adjusted == 67.0  # 72 - 5

    def test_apply_learned_offset_heating(self, control_manager):
        """Test learned offset application for heating mode (no offset)."""
        adjusted = control_manager._apply_learned_offset(72.0, 5.0, HVAC_MODE_HEAT)
        assert adjusted == 72.0  # No offset for heating

    def test_can_change_mode_same_mode(self, control_manager):
        """Test that same mode change is always allowed."""
        control_manager._current_mode = HVAC_MODE_COOL
        assert control_manager.can_change_mode(HVAC_MODE_COOL) is True

    def test_can_change_mode_no_previous_change(self, control_manager):
        """Test mode change when no previous change recorded."""
        assert control_manager.can_change_mode(HVAC_MODE_COOL) is True

    def test_can_change_mode_within_cooldown(self, control_manager):
        """Test mode change blocked during cooldown period."""
        # Record a recent mode change
        control_manager._last_mode_change = dt_util.utcnow() - timedelta(seconds=60)
        control_manager._current_mode = HVAC_MODE_COOL
        
        assert control_manager.can_change_mode(HVAC_MODE_HEAT) is False

    def test_can_change_mode_after_cooldown(self, control_manager):
        """Test mode change allowed after cooldown period."""
        # Record an old mode change
        control_manager._last_mode_change = dt_util.utcnow() - timedelta(seconds=400)
        control_manager._current_mode = HVAC_MODE_COOL
        
        assert control_manager.can_change_mode(HVAC_MODE_HEAT) is True

    def test_record_mode_change(self, control_manager):
        """Test recording a mode change."""
        initial_time = control_manager._last_mode_change
        
        control_manager.record_mode_change(HVAC_MODE_COOL)
        
        assert control_manager._current_mode == HVAC_MODE_COOL
        assert control_manager._last_mode_change is not None
        assert control_manager._last_mode_change != initial_time

    def test_record_mode_change_same_mode(self, control_manager):
        """Test recording same mode doesn't update timestamp."""
        control_manager._current_mode = HVAC_MODE_COOL
        control_manager._last_mode_change = dt_util.utcnow() - timedelta(seconds=60)
        initial_time = control_manager._last_mode_change
        
        control_manager.record_mode_change(HVAC_MODE_COOL)
        
        assert control_manager._last_mode_change == initial_time

    def test_get_remaining_cooldown_no_previous_change(self, control_manager):
        """Test cooldown calculation with no previous change."""
        assert control_manager.get_remaining_cooldown() == 0

    def test_get_remaining_cooldown_within_period(self, control_manager):
        """Test cooldown calculation within cooldown period."""
        control_manager._last_mode_change = dt_util.utcnow() - timedelta(seconds=60)
        remaining = control_manager.get_remaining_cooldown()
        
        assert 230 <= remaining <= 240  # Should be around 240 seconds remaining

    def test_get_remaining_cooldown_after_period(self, control_manager):
        """Test cooldown calculation after cooldown period."""
        control_manager._last_mode_change = dt_util.utcnow() - timedelta(seconds=400)
        assert control_manager.get_remaining_cooldown() == 0

    def test_validate_sensor_readings_valid(self, control_manager, valid_sensor_readings):
        """Test validation of valid sensor readings."""
        assert control_manager.validate_sensor_readings(valid_sensor_readings) is True

    def test_validate_sensor_readings_invalid_temperature(self, control_manager):
        """Test validation with invalid temperature reading."""
        invalid_readings = SensorReadings(
            temperature=150.0,  # Out of range
            humidity=50.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        assert control_manager.validate_sensor_readings(invalid_readings) is False

    def test_validate_sensor_readings_invalid_humidity(self, control_manager):
        """Test validation with invalid humidity reading."""
        invalid_readings = SensorReadings(
            temperature=72.0,
            humidity=150.0,  # Out of range
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        assert control_manager.validate_sensor_readings(invalid_readings) is False

    def test_validate_sensor_readings_stale(self, control_manager):
        """Test validation with stale sensor readings."""
        stale_readings = SensorReadings(
            temperature=72.0,
            humidity=50.0,
            timestamp=dt_util.utcnow() - timedelta(minutes=10),  # Too old
            temperature_available=True,
            humidity_available=True,
        )
        
        assert control_manager.validate_sensor_readings(stale_readings) is False

    def test_get_decision_reasoning(
        self, control_manager, valid_sensor_readings, default_controller_state
    ):
        """Test generation of decision reasoning."""
        action = control_manager.calculate_required_action(
            valid_sensor_readings, default_controller_state
        )
        
        reasoning = control_manager.get_decision_reasoning(
            valid_sensor_readings, default_controller_state, action
        )
        
        assert "Decision:" in reasoning
        assert "Reason:" in reasoning
        assert "Temperature:" in reasoning
        assert "Humidity:" in reasoning
        assert "Learned offset:" in reasoning

    def test_cooldown_affects_action_execution(
        self, control_manager, default_controller_state, valid_sensor_readings
    ):
        """Test that cooldown affects action execution capability."""
        # Set up cooldown condition
        control_manager._last_mode_change = dt_util.utcnow() - timedelta(seconds=60)
        control_manager._current_mode = HVAC_MODE_COOL
        
        # Create conditions that would normally trigger heating
        cold_readings = SensorReadings(
            temperature=70.0,
            humidity=50.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        action = control_manager.calculate_required_action(
            cold_readings, default_controller_state
        )
        
        assert action.action_type == HVAC_MODE_HEAT
        assert action.can_execute is False  # Should be blocked by cooldown
        assert action.cooldown_remaining > 0


class TestControlManagerEdgeCases:
    """Test edge cases and error conditions."""

    def test_temperature_sensor_unavailable(
        self, control_manager, default_controller_state
    ):
        """Test behavior when temperature sensor is unavailable."""
        temp_unavailable_readings = SensorReadings(
            temperature=None,
            humidity=65.0,  # Above threshold
            timestamp=dt_util.utcnow(),
            temperature_available=False,
            humidity_available=True,
        )
        
        action = control_manager.calculate_required_action(
            temp_unavailable_readings, default_controller_state
        )
        
        # Should still activate dry mode based on humidity
        assert action.action_type == HVAC_MODE_DRY

    def test_humidity_sensor_unavailable(
        self, control_manager, default_controller_state
    ):
        """Test behavior when humidity sensor is unavailable."""
        humidity_unavailable_readings = SensorReadings(
            temperature=74.0,  # Above threshold
            humidity=None,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=False,
        )
        
        action = control_manager.calculate_required_action(
            humidity_unavailable_readings, default_controller_state
        )
        
        # Should activate cooling based on temperature
        assert action.action_type == HVAC_MODE_COOL

    def test_both_sensors_unavailable(
        self, control_manager, default_controller_state
    ):
        """Test behavior when both sensors are unavailable."""
        no_sensors_readings = SensorReadings(
            temperature=None,
            humidity=None,
            timestamp=dt_util.utcnow(),
            temperature_available=False,
            humidity_available=False,
        )
        
        action = control_manager.calculate_required_action(
            no_sensors_readings, default_controller_state
        )
        
        # Should turn off when no sensor data available
        assert action.action_type == HVAC_MODE_OFF
        assert action.can_execute is False

    def test_zero_learned_offset(self, control_manager):
        """Test offset application with zero learned offset."""
        adjusted = control_manager._apply_learned_offset(72.0, 0.0, HVAC_MODE_COOL)
        assert adjusted == 72.0

    def test_negative_learned_offset(self, control_manager):
        """Test offset application with negative learned offset."""
        # Negative offset means minisplit reads cooler than actual
        adjusted = control_manager._apply_learned_offset(72.0, -3.0, HVAC_MODE_COOL)
        assert adjusted == 75.0  # 72 - (-3) = 75