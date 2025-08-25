"""Simplified integration tests for the Smart Thermostat Controller."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.climate import SmartThermostatClimate
from custom_components.smart_thermostat_controller.coordinator import SmartThermostatCoordinator
from custom_components.smart_thermostat_controller.control_manager import ControlManager
from custom_components.smart_thermostat_controller.learning_manager import LearningManager
from custom_components.smart_thermostat_controller.const import (
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
)
from custom_components.smart_thermostat_controller.models import (
    ControllerState,
    SmartThermostatConfig,
    SensorReadings,
    TemperatureDataPoint,
    LearningConfig,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.fixture
def integration_config():
    """Create integration test configuration."""
    return {
        "external_temperature_sensor": "sensor.room_temp",
        "external_humidity_sensor": "sensor.room_humidity", 
        "minisplit_climate_entity": "climate.bedroom_ac",
        "target_temperature": 72.0,
        "humidity_max_threshold": 60.0,
        "humidity_min_threshold": 40.0,
        "temperature_deadband": 1.0,
        "cooldown_period": 300,
        "learning_enabled": True,
        "learning_period_days": 7,
        "default_cooling_offset": 5.0,
    }


@pytest.fixture
def mock_config_entry(integration_config):
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_integration"
    entry.data = integration_config
    return entry


class TestCompleteControlScenarios:
    """Test complete control scenarios from sensor input to minisplit action."""

    async def test_cooling_scenario_complete_flow(self, mock_hass, integration_config):
        """Test complete cooling scenario: hot room -> cooling action."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create sensor readings: room too hot
        sensor_readings = SensorReadings(
            temperature=75.0,  # 3°F above target
            humidity=45.0,     # Normal humidity
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Create controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=75.0,
            current_humidity=45.0,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Execute control decision
        action = control_manager.calculate_required_action(sensor_readings, controller_state)
        
        # Verify cooling was selected with offset compensation
        assert action.action_type == HVAC_MODE_COOL
        assert action.target_temperature == 67.0  # 72 - 5 (learned offset)
        assert action.can_execute is True
        assert "Temperature 75.0°F > normal cooling threshold" in action.reason

    async def test_dehumidification_priority_scenario(self, mock_hass, integration_config):
        """Test that humidity control takes priority over temperature control."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create sensor readings: temperature fine, humidity high
        sensor_readings = SensorReadings(
            temperature=72.5,  # Within deadband
            humidity=65.0,     # Above 60% threshold
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Create controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=72.5,
            current_humidity=65.0,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Execute control decision
        action = control_manager.calculate_required_action(sensor_readings, controller_state)
        
        # Verify dry mode was selected (humidity priority)
        assert action.action_type == HVAC_MODE_DRY
        assert "entering idle dry mode" in action.reason

    async def test_heating_scenario_complete_flow(self, mock_hass, integration_config):
        """Test complete heating scenario: cold room -> heating action."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create sensor readings: room too cold
        sensor_readings = SensorReadings(
            temperature=69.0,  # 3°F below target
            humidity=45.0,     # Normal humidity
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Create controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=69.0,
            current_humidity=45.0,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Execute control decision
        action = control_manager.calculate_required_action(sensor_readings, controller_state)
        
        # Verify heating was selected (no offset for heating)
        assert action.action_type == HVAC_MODE_HEAT
        assert action.target_temperature == 72.0  # No offset for heating
        assert "Temperature 69.0°F < normal heating threshold" in action.reason

    async def test_cooldown_prevents_mode_change(self, mock_hass, integration_config):
        """Test that cooldown period prevents rapid mode changes."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Set recent mode change (2 minutes ago, cooldown is 5 minutes)
        control_manager._last_mode_change = dt_util.utcnow() - timedelta(seconds=120)
        control_manager._current_mode = HVAC_MODE_HEAT
        
        # Create sensor readings: room needs cooling
        sensor_readings = SensorReadings(
            temperature=75.0,  # Too hot
            humidity=45.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Create controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_HEAT,
            target_temperature=72.0,
            current_temperature=75.0,
            current_humidity=45.0,
            last_mode_change=dt_util.utcnow() - timedelta(seconds=120),
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=180,  # 3 minutes remaining
            is_available=True,
        )
        
        # Execute control decision
        action = control_manager.calculate_required_action(sensor_readings, controller_state)
        
        # Verify action is recommended but cannot execute due to cooldown
        assert action.action_type == HVAC_MODE_COOL
        assert action.can_execute is False
        assert action.cooldown_remaining > 0


class TestSensorFailureAndRecovery:
    """Test sensor failure scenarios and recovery mechanisms."""

    async def test_temperature_sensor_failure_graceful_degradation(self, mock_hass, integration_config):
        """Test graceful degradation when temperature sensor fails."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create sensor readings: temperature unavailable, humidity high
        sensor_readings = SensorReadings(
            temperature=None,  # Unavailable
            humidity=65.0,     # High humidity
            timestamp=dt_util.utcnow(),
            temperature_available=False,
            humidity_available=True,
        )
        
        # Create controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=None,
            current_humidity=65.0,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Execute control decision
        action = control_manager.calculate_required_action(sensor_readings, controller_state)
        
        # Should turn off for safety when temperature sensor is unavailable
        assert action.action_type == HVAC_MODE_OFF
        assert "No temperature sensor available" in action.reason

    async def test_humidity_sensor_failure_temperature_only_control(self, mock_hass, integration_config):
        """Test temperature-only control when humidity sensor fails."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create sensor readings: humidity unavailable, temperature needs cooling
        sensor_readings = SensorReadings(
            temperature=75.0,  # Too hot
            humidity=None,     # Unavailable
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=False,
        )
        
        # Create controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=75.0,
            current_humidity=None,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Execute control decision
        action = control_manager.calculate_required_action(sensor_readings, controller_state)
        
        # Should activate cooling based on temperature only
        assert action.action_type == HVAC_MODE_COOL
        assert action.target_temperature == 67.0  # With offset
        assert "Temperature 75.0°F > normal cooling threshold" in action.reason

    async def test_all_sensors_unavailable_safe_shutdown(self, mock_hass, integration_config):
        """Test safe shutdown when all sensors are unavailable."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create sensor readings: all unavailable
        sensor_readings = SensorReadings(
            temperature=None,
            humidity=None,
            timestamp=dt_util.utcnow() - timedelta(minutes=10),  # Stale timestamp
            temperature_available=False,
            humidity_available=False,
        )
        
        # Create controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_COOL,  # Currently running
            target_temperature=72.0,
            current_temperature=None,
            current_humidity=None,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Execute control decision
        action = control_manager.calculate_required_action(sensor_readings, controller_state)
        
        # Should not make control changes when sensors are unavailable
        assert action.action_type == HVAC_MODE_OFF
        assert action.can_execute is False
        assert "Invalid or stale sensor readings" in action.reason


class TestLearningAlgorithmAccuracy:
    """Test learning algorithm accuracy with controlled test data."""

    def test_learning_algorithm_with_consistent_offset(self):
        """Test learning algorithm with consistent 5°F cooling offset."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=10,  # Lower for testing
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add consistent data points with 5°F offset during cooling
        for i in range(20):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # Consistent 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Verify learned offset is accurate
        assert abs(learning_manager.learned_offset - 5.0) < 0.1
        assert learning_manager.confidence > 0.8

    def test_learning_algorithm_with_variable_offset(self):
        """Test learning algorithm with variable offset data."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=10,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add variable data points (4-6°F offset range)
        offsets = [4.0, 4.5, 5.0, 5.5, 6.0] * 4  # 20 points
        for offset in offsets:
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=72.0 + offset,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Verify learned offset is average (5.0°F) with lower confidence
        assert abs(learning_manager.learned_offset - 5.0) < 0.2
        assert 0.5 < learning_manager.confidence < 0.9  # Lower confidence due to variability

    def test_learning_algorithm_outlier_rejection(self):
        """Test that learning algorithm rejects outliers."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=10,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add mostly consistent data with some outliers
        for i in range(15):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # Consistent 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Add outliers
        for i in range(3):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=85.0,  # 13°F outlier
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Verify outliers didn't significantly affect the learned offset
        assert abs(learning_manager.learned_offset - 5.0) < 0.5
        assert learning_manager.confidence > 0.6

    def test_learning_algorithm_insufficient_data(self):
        """Test learning algorithm behavior with insufficient data."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=50,  # High threshold
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add only a few data points
        for i in range(10):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Verify no learning occurred due to insufficient data
        assert learning_manager.learned_offset == 0.0
        assert learning_manager.confidence == 0.0


class TestConfigurationFlowValidation:
    """Test configuration flow validation with various sensor combinations."""

    def test_config_flow_validation_logic(self):
        """Test configuration flow validation with different sensor combinations."""
        # Test valid configuration
        valid_config = {
            "external_temperature_sensor": "sensor.room_temp",
            "external_humidity_sensor": "sensor.room_humidity",
            "minisplit_climate_entity": "climate.bedroom_ac",
            "target_temperature": 72.0,
            "humidity_max_threshold": 60.0,
            "humidity_min_threshold": 40.0,
            "temperature_deadband": 1.0,
            "cooldown_period": 300,
            "learning_enabled": True,
            "learning_period_days": 7,
            "default_cooling_offset": 5.0,
        }
        
        # Verify config can be created
        config = SmartThermostatConfig.from_config_entry(valid_config)
        assert config.external_temp_sensor == "sensor.room_temp"
        assert config.external_humidity_sensor == "sensor.room_humidity"
        assert config.minisplit_entity == "climate.bedroom_ac"
        assert config.target_temperature == 72.0

    def test_different_sensor_combinations(self):
        """Test configuration with different sensor entity combinations."""
        base_config = {
            "minisplit_climate_entity": "climate.bedroom_ac",
            "target_temperature": 72.0,
            "humidity_max_threshold": 60.0,
            "humidity_min_threshold": 40.0,
            "temperature_deadband": 1.0,
            "cooldown_period": 300,
            "learning_enabled": True,
            "learning_period_days": 7,
            "default_cooling_offset": 5.0,
        }
        
        # Test different sensor combinations
        sensor_combinations = [
            {
                "external_temperature_sensor": "sensor.ecobee_temperature",
                "external_humidity_sensor": "sensor.ecobee_humidity",
            },
            {
                "external_temperature_sensor": "sensor.xiaomi_temp",
                "external_humidity_sensor": "sensor.xiaomi_humidity",
            },
            {
                "external_temperature_sensor": "sensor.dht22_temperature",
                "external_humidity_sensor": "sensor.dht22_humidity",
            },
        ]
        
        for sensors in sensor_combinations:
            config_data = {**base_config, **sensors}
            config = SmartThermostatConfig.from_config_entry(config_data)
            
            assert config.external_temp_sensor == sensors["external_temperature_sensor"]
            assert config.external_humidity_sensor == sensors["external_humidity_sensor"]
            assert config.minisplit_entity == "climate.bedroom_ac"


class TestPerformanceValidation:
    """Test performance requirements."""

    async def test_control_decision_performance(self, mock_hass, integration_config):
        """Test that control decisions are made quickly."""
        import time
        
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create test sensor readings
        sensor_readings = SensorReadings(
            temperature=75.0,
            humidity=55.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Create test controller state
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=75.0,
            current_humidity=55.0,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Measure decision performance
        start_time = time.time()
        
        # Make multiple control decisions
        for _ in range(100):
            action = control_manager.calculate_required_action(
                sensor_readings, controller_state
            )
            assert action is not None
        
        end_time = time.time()
        avg_decision_time = (end_time - start_time) / 100
        
        # Verify decisions are made quickly (under 10ms each)
        assert avg_decision_time < 0.01, f"Average decision time {avg_decision_time:.4f}s exceeds 10ms limit"

    def test_learning_algorithm_performance(self):
        """Test learning algorithm performance with reasonable dataset."""
        import time
        
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=50,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add reasonable amount of data (7 days * 24 readings per day = 168 points)
        start_time = time.time()
        
        now = dt_util.utcnow()
        for day in range(7):
            for hour in range(24):
                timestamp = now - timedelta(days=day, hours=hour)
                learning_manager.collect_data_point(
                    external_temperature=72.0 + (hour % 5) * 0.1,  # Slight variation
                    internal_temperature=77.0 + (hour % 5) * 0.1,
                    minisplit_mode="cool",
                    minisplit_active=True,
                )
        
        data_collection_time = time.time() - start_time
        
        # Test recalculation performance
        recalc_start = time.time()
        learning_manager.force_recalculation()
        recalc_time = time.time() - recalc_start
        
        # Performance assertions
        assert data_collection_time < 1.0, f"Data collection took {data_collection_time:.2f}s, exceeds 1s limit"
        assert recalc_time < 0.1, f"Recalculation took {recalc_time:.3f}s, exceeds 0.1s limit"
        
        # Verify learning worked
        assert learning_manager.learned_offset > 0
        assert learning_manager.confidence > 0
