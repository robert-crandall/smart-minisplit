"""Integration tests for the Smart Thermostat Controller."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.climate import SmartThermostatClimate
from custom_components.smart_thermostat_controller.coordinator import SmartThermostatCoordinator
from custom_components.smart_thermostat_controller.control_manager import ControlManager
from custom_components.smart_thermostat_controller.learning_manager import LearningManager
from custom_components.smart_thermostat_controller.cooldown_manager import CooldownManager
from custom_components.smart_thermostat_controller.const import (
    DOMAIN,
    HVAC_MODE_AUTO,
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


def create_test_coordinator(mock_hass, mock_config_entry, current_temp=72.0, current_humidity=45.0, current_mode=HVAC_MODE_OFF):
    """Create a properly configured test coordinator."""
    with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
         patch('homeassistant.helpers.frame.report_usage'), \
         patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
        
        coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
        coordinator.hass = mock_hass
        coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
        coordinator.entry = mock_config_entry
        coordinator._historical_data = []
        coordinator._learned_offset = 5.0
        coordinator._offset_confidence = 0.8
        coordinator._last_mode_change = None
        coordinator._manual_override = False
        coordinator._store = MagicMock()
        coordinator._store.async_load = AsyncMock(return_value=None)
        coordinator._store.async_save = AsyncMock()
        
        # Initialize logging and error handling
        from custom_components.smart_thermostat_controller.logging_utils import create_logger
        from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
        coordinator._logger = create_logger(mock_hass, "coordinator")
        coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
        
        # Set up coordinator data
        coordinator.data = ControllerState(
            current_mode=current_mode,
            target_temperature=72.0,
            current_temperature=current_temp,
            current_humidity=current_humidity,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        coordinator.last_update_success = True
        
        return coordinator


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

    async def test_cooling_scenario_complete_flow(self, mock_hass, mock_config_entry):
        """Test complete cooling scenario: hot room -> cooling action."""
        # Setup: Room is too hot, humidity is normal
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # 3°F above target
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"  # Normal humidity
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        minisplit_state.attributes = {"current_temperature": 80.0}
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator and climate entity
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute automatic control
            await climate_entity._execute_automatic_control()
            
            # Verify cooling was activated with offset compensation
            assert mock_hass.services.async_call.call_count >= 1
            
            # Find the set_hvac_mode call
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            
            hvac_call = hvac_calls[0]
            assert hvac_call.args[0] == "climate"
            assert hvac_call.args[2]["entity_id"] == "climate.bedroom_ac"
            assert hvac_call.args[2]["hvac_mode"] == HVAC_MODE_COOL
            # Target should be adjusted by learned offset: 72 - 5 = 67
            assert hvac_call.args[2]["temperature"] == 67.0

    async def test_dehumidification_priority_scenario(self, mock_hass, mock_config_entry):
        """Test that humidity control takes priority over temperature control."""
        # Setup: Room temperature is fine, but humidity is too high
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.5"  # Within deadband
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "65.0"  # Above 60% threshold
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator and climate entity
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute automatic control
            await climate_entity._execute_automatic_control()
            
            # Verify dry mode was activated (humidity priority)
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            
            hvac_call = hvac_calls[0]
            assert hvac_call.args[2]["hvac_mode"] == HVAC_MODE_DRY

    async def test_heating_scenario_complete_flow(self, mock_hass, mock_config_entry):
        """Test complete heating scenario: cold room -> heating action."""
        # Setup: Room is too cold
        temp_state = MagicMock(spec=State)
        temp_state.state = "69.0"  # 3°F below target
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"  # Normal humidity
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator and climate entity
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute automatic control
            await climate_entity._execute_automatic_control()
            
            # Verify heating was activated (no offset for heating)
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            
            hvac_call = hvac_calls[0]
            assert hvac_call.args[2]["hvac_mode"] == HVAC_MODE_HEAT
            assert hvac_call.args[2]["temperature"] == 72.0  # No offset for heating

    async def test_cooldown_prevents_mode_change(self, mock_hass, mock_config_entry):
        """Test that cooldown period prevents rapid mode changes."""
        # Setup: Room needs cooling but recent mode change occurred
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # Too hot
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "heat"  # Currently heating
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator with recent mode change
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            # Set recent mode change (2 minutes ago, cooldown is 5 minutes)
            coordinator._last_mode_change = dt_util.utcnow() - timedelta(seconds=120)
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute automatic control
            await climate_entity._execute_automatic_control()
            
            # Verify no mode change occurred due to cooldown
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) == 0  # No calls should be made during cooldown


class TestSensorFailureAndRecovery:
    """Test sensor failure scenarios and recovery mechanisms."""

    async def test_temperature_sensor_failure_graceful_degradation(self, mock_hass, mock_config_entry):
        """Test graceful degradation when temperature sensor fails."""
        # Setup: Temperature sensor unavailable, humidity sensor working
        temp_state = MagicMock(spec=State)
        temp_state.state = "unavailable"
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "65.0"  # High humidity
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator and climate entity
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute automatic control
            await climate_entity._execute_automatic_control()
            
            # Should still activate dry mode based on humidity alone
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            
            hvac_call = hvac_calls[0]
            assert hvac_call.args[2]["hvac_mode"] == HVAC_MODE_DRY

    async def test_humidity_sensor_failure_temperature_only_control(self, mock_hass, mock_config_entry):
        """Test temperature-only control when humidity sensor fails."""
        # Setup: Humidity sensor unavailable, temperature sensor working
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # Too hot
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "unknown"
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator and climate entity
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute automatic control
            await climate_entity._execute_automatic_control()
            
            # Should activate cooling based on temperature only
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            
            hvac_call = hvac_calls[0]
            assert hvac_call.args[2]["hvac_mode"] == HVAC_MODE_COOL

    async def test_all_sensors_unavailable_safe_shutdown(self, mock_hass, mock_config_entry):
        """Test safe shutdown when all sensors are unavailable."""
        # Setup: All sensors unavailable
        temp_state = MagicMock(spec=State)
        temp_state.state = "unavailable"
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "unavailable"
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"  # Currently running
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator and climate entity
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute automatic control
            await climate_entity._execute_automatic_control()
            
            # Should not make any control changes when sensors are unavailable
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) == 0

    async def test_sensor_recovery_resumes_control(self, mock_hass, mock_config_entry):
        """Test that control resumes when sensors recover from failure."""
        # Create coordinator and climate entity
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Phase 1: Sensors unavailable
            temp_state_unavailable = MagicMock(spec=State)
            temp_state_unavailable.state = "unavailable"
            
            humidity_state_unavailable = MagicMock(spec=State)
            humidity_state_unavailable.state = "unavailable"
            
            minisplit_state = MagicMock(spec=State)
            minisplit_state.state = "off"
            
            mock_hass.states.get.side_effect = lambda entity_id: {
                "sensor.room_temp": temp_state_unavailable,
                "sensor.room_humidity": humidity_state_unavailable,
                "climate.bedroom_ac": minisplit_state,
            }.get(entity_id)
            
            # Execute control - should not make changes
            await climate_entity._execute_automatic_control()
            initial_call_count = mock_hass.services.async_call.call_count
            
            # Phase 2: Sensors recover
            temp_state_recovered = MagicMock(spec=State)
            temp_state_recovered.state = "75.0"  # Too hot
            temp_state_recovered.last_updated = dt_util.utcnow()
            
            humidity_state_recovered = MagicMock(spec=State)
            humidity_state_recovered.state = "45.0"  # Normal
            humidity_state_recovered.last_updated = dt_util.utcnow()
            
            mock_hass.states.get.side_effect = lambda entity_id: {
                "sensor.room_temp": temp_state_recovered,
                "sensor.room_humidity": humidity_state_recovered,
                "climate.bedroom_ac": minisplit_state,
            }.get(entity_id)
            
            # Execute control - should now activate cooling
            await climate_entity._execute_automatic_control()
            
            # Verify control resumed after sensor recovery
            assert mock_hass.services.async_call.call_count > initial_call_count
            
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            
            hvac_call = hvac_calls[-1]  # Get the most recent call
            assert hvac_call.args[2]["hvac_mode"] == HVAC_MODE_COOL


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
        now = dt_util.utcnow()
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

    def test_learning_algorithm_mode_specific_offsets(self):
        """Test that learning algorithm tracks offsets separately for heating and cooling."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=10,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add cooling data with 5°F offset
        for i in range(15):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Add heating data with 2°F offset
        for i in range(15):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=74.0,  # 2°F offset
                minisplit_mode="heat",
                minisplit_active=True,
            )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Verify mode-specific offsets
        assert abs(learning_manager.get_learned_offset("cool") - 5.0) < 0.1
        assert abs(learning_manager.get_learned_offset("heat") - 2.0) < 0.1
        assert learning_manager.get_confidence("cool") > 0.7
        assert learning_manager.get_confidence("heat") > 0.7


class TestConfigurationFlowEndToEnd:
    """Test configuration flow end-to-end with various sensor combinations."""

    def test_config_flow_validation_logic(self):
        """Test configuration flow validation with different sensor combinations."""
        from custom_components.smart_thermostat_controller.config_flow import SmartThermostatConfigFlow
        
        flow = SmartThermostatConfigFlow()
        
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

    async def test_config_flow_threshold_validation(self):
        """Test threshold validation in config flow."""
        from custom_components.smart_thermostat_controller.config_flow import SmartThermostatConfigFlow
        
        flow = SmartThermostatConfigFlow()
        
        # Test valid thresholds
        valid_input = {
            "humidity_min_threshold": 40.0,
            "humidity_max_threshold": 60.0,
        }
        
        errors = await flow._validate_step_thresholds(valid_input)
        assert errors == {}
        
        # Test invalid thresholds (min > max)
        invalid_input = {
            "humidity_min_threshold": 70.0,
            "humidity_max_threshold": 50.0,
        }
        
        errors = await flow._validate_step_thresholds(invalid_input)
        assert "humidity_max_threshold" in errors
        assert errors["humidity_max_threshold"] == "max_must_be_greater_than_min"

    def test_config_model_validation(self):
        """Test configuration model validation."""
        # Test valid config
        valid_data = {
            "external_temperature_sensor": "sensor.temp",
            "external_humidity_sensor": "sensor.humidity",
            "minisplit_climate_entity": "climate.ac",
            "target_temperature": 72.0,
            "humidity_max_threshold": 60.0,
            "humidity_min_threshold": 40.0,
            "temperature_deadband": 1.0,
            "cooldown_period": 300,
            "learning_enabled": True,
            "learning_period_days": 7,
            "default_cooling_offset": 5.0,
        }
        
        config = SmartThermostatConfig.from_config_entry(valid_data)
        assert config.target_temperature == 72.0
        
        # Test learning config creation
        learning_config = config.get_learning_config()
        assert learning_config.enabled is True
        assert learning_config.period_days == 7

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


class TestPerformanceAndResourceUsage:
    """Test performance and resource usage of the integration."""

    async def test_data_update_frequency_performance(self, mock_hass, mock_config_entry):
        """Test that data updates complete within acceptable time limits."""
        import time
        
        # Setup mock sensors with valid data
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.0"
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        minisplit_state.attributes = {"current_temperature": 77.0}
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            # Measure update performance
            start_time = time.time()
            
            # Perform multiple updates
            for _ in range(10):
                await coordinator._async_update_data()
            
            end_time = time.time()
            avg_update_time = (end_time - start_time) / 10
            
            # Verify updates complete quickly (under 100ms each)
            assert avg_update_time < 0.1, f"Average update time {avg_update_time:.3f}s exceeds 100ms limit"

    def test_memory_usage_with_large_historical_data(self):
        """Test memory usage with large amounts of historical data."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=30,  # Longer period
            min_data_points=50,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add large amount of historical data
        now = dt_util.utcnow()
        for i in range(1000):  # 1000 data points
            timestamp = now - timedelta(minutes=i)
            learning_manager.collect_data_point(
                external_temperature=72.0 + (i % 10) * 0.1,  # Slight variation
                internal_temperature=77.0 + (i % 10) * 0.1,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Verify data cleanup works
        initial_count = learning_manager.data_point_count
        learning_manager.force_recalculation()  # Triggers cleanup
        
        # Should have cleaned up old data (older than 30 days)
        assert learning_manager.data_point_count <= initial_count
        
        # Verify learning still works with cleaned data
        assert learning_manager.learned_offset > 0
        assert learning_manager.confidence > 0

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

    def test_historical_data_cleanup_efficiency(self):
        """Test that historical data cleanup is efficient."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=50,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add data spanning more than the retention period
        now = dt_util.utcnow()
        
        # Add old data (should be cleaned up)
        for i in range(100):
            old_timestamp = now - timedelta(days=10, minutes=i)
            learning_manager._data_points.append(
                TemperatureDataPoint(
                    timestamp=old_timestamp,
                    external_temperature=72.0,
                    internal_temperature=77.0,
                    minisplit_mode="cool",
                    minisplit_active=True,
                )
            )
        
        # Add recent data (should be kept)
        for i in range(50):
            recent_timestamp = now - timedelta(hours=i)
            learning_manager._data_points.append(
                TemperatureDataPoint(
                    timestamp=recent_timestamp,
                    external_temperature=72.0,
                    internal_temperature=77.0,
                    minisplit_mode="cool",
                    minisplit_active=True,
                )
            )
        
        # Verify initial data count
        assert learning_manager.data_point_count == 150
        
        # Trigger cleanup
        learning_manager._cleanup_old_data()
        
        # Verify old data was removed, recent data kept
        assert learning_manager.data_point_count == 50
        
        # Verify all remaining data is within retention period
        cutoff_time = now - timedelta(days=7)
        for point in learning_manager._data_points:
            assert point.timestamp > cutoff_time

    async def test_concurrent_operations_thread_safety(self, mock_hass, mock_config_entry):
        """Test thread safety with concurrent operations."""
        import asyncio
        
        # Setup mock sensors
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.0"
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        minisplit_state.attributes = {"current_temperature": 77.0}
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            # Create multiple concurrent tasks
            async def update_task():
                return await coordinator._async_update_data()
            
            async def mode_change_task():
                await coordinator.record_mode_change("cool")
            
            # Run concurrent operations
            tasks = []
            for _ in range(5):
                tasks.append(asyncio.create_task(update_task()))
                tasks.append(asyncio.create_task(mode_change_task()))
            
            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Verify no exceptions occurred
            for result in results:
                if isinstance(result, Exception):
                    pytest.fail(f"Concurrent operation failed: {result}")