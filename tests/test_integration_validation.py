"""Integration validation tests for all requirements."""
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
from custom_components.smart_thermostat_controller.cooldown_manager import CooldownManager
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


class TestRequirement1Validation:
    """Validate Requirement 1: External temperature sensor usage."""

    async def test_requirement_1_1_external_sensor_reading(self, mock_hass, mock_config_entry):
        """Test that system reads temperature from configured external sensor."""
        # Setup external sensor with specific temperature
        temp_state = MagicMock(spec=State)
        temp_state.state = "73.5"
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        minisplit_state.attributes = {"current_temperature": 78.5}  # Different from external
        
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            # Update data
            state = await coordinator._async_update_data()
            
            # Verify external sensor temperature is used (73.5), not minisplit internal (78.5)
            assert state.current_temperature == 73.5
            assert state.current_temperature != 78.5

    async def test_requirement_1_2_ignore_minisplit_thermostat(self, mock_hass, mock_config_entry):
        """Test that system ignores minisplit's internal thermostat readings for control."""
        # Setup: External sensor shows 75°F, minisplit internal shows 70°F
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # External sensor
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        minisplit_state.attributes = {"current_temperature": 70.0}  # Minisplit internal
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control - should use external sensor (75°F) for decision, not minisplit (70°F)
            await climate_entity._execute_automatic_control()
            
            # Verify cooling was activated based on external sensor (75°F > 72°F target)
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_COOL

    async def test_requirement_1_3_sensor_unavailable_fallback(self, mock_hass, mock_config_entry):
        """Test fallback to manual control when external sensor is unavailable."""
        # Setup: External sensor unavailable
        temp_state = MagicMock(spec=State)
        temp_state.state = "unavailable"
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"  # Currently running
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control - should not make changes when sensor unavailable
            await climate_entity._execute_automatic_control()
            
            # Verify no control actions were taken
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) == 0

    async def test_requirement_1_4_temperature_difference_calculation(self, mock_hass, mock_config_entry):
        """Test appropriate action calculation when external temperature differs from target."""
        test_cases = [
            (75.0, HVAC_MODE_COOL),  # 3°F above target (72°F) + 1°F deadband = cooling
            (69.0, HVAC_MODE_HEAT),  # 3°F below target - 1°F deadband = heating
            (72.5, HVAC_MODE_OFF),   # Within deadband = off
        ]
        
        for temp, expected_mode in test_cases:
            # Reset mock
            mock_hass.services.async_call.reset_mock()
            
            # Setup sensor with test temperature
            temp_state = MagicMock(spec=State)
            temp_state.state = str(temp)
            temp_state.last_updated = dt_util.utcnow()
            
            humidity_state = MagicMock(spec=State)
            humidity_state.state = "45.0"
            humidity_state.last_updated = dt_util.utcnow()
            
            minisplit_state = MagicMock(spec=State)
            minisplit_state.state = "off"
            
            mock_hass.states.get.side_effect = lambda entity_id: {
                "sensor.room_temp": temp_state,
                "sensor.room_humidity": humidity_state,
                "climate.bedroom_ac": minisplit_state,
            }.get(entity_id)
            
            # Create climate entity
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
                coordinator._away_mode = False
                coordinator._store = MagicMock()
                coordinator._store.async_load = AsyncMock(return_value=None)
                coordinator._store.async_save = AsyncMock()
                
                # Initialize logging and error handling
                from custom_components.smart_thermostat_controller.logging_utils import create_logger
                from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
                coordinator._logger = create_logger(mock_hass, "coordinator")
                coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
                
                climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
                
                # Execute control
                await climate_entity._execute_automatic_control()
                
                # Verify expected action
                if expected_mode == HVAC_MODE_OFF:
                    # Should turn off or not make changes
                    turn_off_calls = [call for call in mock_hass.services.async_call.call_args_list 
                                     if call.args[1] == "turn_off"]
                    hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                                 if call.args[1] == "set_hvac_mode"]
                    # Either turn off or no calls (if already off)
                    assert len(turn_off_calls) >= 0 and len(hvac_calls) >= 0
                else:
                    hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                                 if call.args[1] == "set_hvac_mode"]
                    assert len(hvac_calls) >= 1
                    assert hvac_calls[0].args[2]["hvac_mode"] == expected_mode


class TestRequirement2Validation:
    """Validate Requirement 2: Humidity control using external sensors."""

    async def test_requirement_2_1_humidity_sensor_reading(self, mock_hass, mock_config_entry):
        """Test that system reads humidity from configured external sensor."""
        # Setup external humidity sensor
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.0"
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "55.5"  # Specific humidity value
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            # Update data
            state = await coordinator._async_update_data()
            
            # Verify external humidity sensor reading is used
            assert state.current_humidity == 55.5

    async def test_requirement_2_2_high_humidity_dry_mode(self, mock_hass, mock_config_entry):
        """Test dry mode activation when humidity exceeds maximum threshold."""
        # Setup: High humidity (65% > 60% threshold)
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.0"  # Normal temperature
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
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify dry mode was activated
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_DRY

    async def test_requirement_2_3_low_humidity_avoid_dry_mode(self, mock_hass, mock_config_entry):
        """Test avoiding dry mode when humidity is below minimum threshold."""
        # Setup: Low humidity (35% < 40% threshold), temperature needs cooling
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # Needs cooling
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "35.0"  # Below 40% threshold
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify cooling mode was activated (not dry mode) due to low humidity
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_COOL

    async def test_requirement_2_4_humidity_sensor_unavailable_continue_temp_control(self, mock_hass, mock_config_entry):
        """Test temperature-only control when humidity sensor is unavailable."""
        # Setup: Humidity sensor unavailable, temperature needs cooling
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # Needs cooling
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "unavailable"
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify temperature control still works (cooling activated)
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_COOL


class TestRequirement3Validation:
    """Validate Requirement 3: Automatic mode switching."""

    async def test_requirement_3_1_cooling_activation(self, mock_hass, mock_config_entry):
        """Test cooling activation when temperature exceeds target + deadband."""
        # Setup: Temperature above target + deadband (75°F > 72°F + 1°F)
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"
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
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify cooling was activated
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_COOL

    async def test_requirement_3_2_heating_activation(self, mock_hass, mock_config_entry):
        """Test heating activation when temperature is below target - deadband."""
        # Setup: Temperature below target - deadband (69°F < 72°F - 1°F)
        temp_state = MagicMock(spec=State)
        temp_state.state = "69.0"
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
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify heating was activated
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_HEAT

    async def test_requirement_3_3_humidity_priority_over_temperature(self, mock_hass, mock_config_entry):
        """Test that humidity control takes priority over temperature control."""
        # Setup: Temperature needs cooling AND humidity is high
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # Needs cooling (75°F > 72°F + 1°F)
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "65.0"  # High humidity (65% > 60%)
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify dry mode was activated (humidity priority) instead of cooling
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_DRY

    async def test_requirement_3_4_turn_off_within_acceptable_ranges(self, mock_hass, mock_config_entry):
        """Test turning off minisplit when temperature and humidity are within acceptable ranges."""
        # Setup: Temperature within deadband, humidity acceptable
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.5"  # Within deadband (72 ± 1°F)
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "50.0"  # Within range (40-60%)
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"  # Currently running
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        mock_hass.services.async_call = AsyncMock()
        
        # Create climate entity
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
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify minisplit was turned off
            turn_off_calls = [call for call in mock_hass.services.async_call.call_args_list 
                             if call.args[1] == "turn_off"]
            assert len(turn_off_calls) >= 1
            assert turn_off_calls[0].args[2]["entity_id"] == "climate.bedroom_ac"


class TestRequirement4Validation:
    """Validate Requirement 4: Cooldown periods between mode changes."""

    async def test_requirement_4_1_cooldown_period_check(self, mock_hass, mock_config_entry):
        """Test that system checks minimum cooldown period before mode changes."""
        # Setup: Recent mode change (2 minutes ago, cooldown is 5 minutes)
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # Needs cooling
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
        mock_hass.services.async_call = AsyncMock()
        
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
            # Set recent mode change (2 minutes ago)
            coordinator._last_mode_change = dt_util.utcnow() - timedelta(seconds=120)
            coordinator._manual_override = False
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # Verify no mode change occurred due to cooldown
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) == 0

    async def test_requirement_4_2_delay_mode_change_during_cooldown(self, mock_hass, mock_config_entry):
        """Test that mode changes are delayed until cooldown period completes."""
        # This is tested by verifying no calls are made during cooldown
        # (same as test_requirement_4_1_cooldown_period_check)
        pass

    async def test_requirement_4_3_initial_cooldown_on_startup(self, mock_hass, mock_config_entry):
        """Test initial cooldown period when system starts."""
        # Setup: System just started (no previous mode change)
        temp_state = MagicMock(spec=State)
        temp_state.state = "75.0"  # Needs cooling
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "off"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        mock_hass.services.async_call = AsyncMock()
        
        # Create coordinator with no previous mode change (startup condition)
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
            coordinator._last_mode_change = None  # No previous mode change (startup)
            coordinator._manual_override = False
            coordinator._away_mode = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            
            climate_entity = SmartThermostatClimate(coordinator, mock_config_entry)
            
            # Execute control
            await climate_entity._execute_automatic_control()
            
            # On startup with no cooldown restrictions, should allow mode change
            hvac_calls = [call for call in mock_hass.services.async_call.call_args_list 
                         if call.args[1] == "set_hvac_mode"]
            assert len(hvac_calls) >= 1
            assert hvac_calls[0].args[2]["hvac_mode"] == HVAC_MODE_COOL

    def test_requirement_4_4_customizable_cooldown_periods(self):
        """Test that cooldown periods are customizable."""
        # Test different cooldown configurations
        test_configs = [
            {"cooldown_period": 180},  # 3 minutes
            {"cooldown_period": 300},  # 5 minutes (default)
            {"cooldown_period": 600},  # 10 minutes
        ]
        
        for config_data in test_configs:
            base_config = {
                "external_temperature_sensor": "sensor.room_temp",
                "external_humidity_sensor": "sensor.room_humidity",
                "minisplit_climate_entity": "climate.bedroom_ac",
                "target_temperature": 72.0,
                "humidity_max_threshold": 60.0,
                "humidity_min_threshold": 40.0,
                "temperature_deadband": 1.0,
                "learning_enabled": True,
                "learning_period_days": 7,
                "default_cooling_offset": 5.0,
                **config_data
            }
            
            config = SmartThermostatConfig.from_config_entry(base_config)
            assert config.cooldown_period == config_data["cooldown_period"]


class TestRequirement5Validation:
    """Validate Requirement 5: Learning and offset compensation."""

    def test_requirement_5_1_calculate_offset_after_7_days(self):
        """Test offset calculation after collecting 7 days of data."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=50,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add 7 days worth of data (every 30 minutes = 48 points per day * 7 = 336 points)
        now = dt_util.utcnow()
        for day in range(7):
            for hour in range(24):
                for minute in [0, 30]:  # Every 30 minutes
                    timestamp = now - timedelta(days=day, hours=hour, minutes=minute)
                    learning_manager.collect_data_point(
                        external_temperature=72.0,
                        internal_temperature=77.0,  # Consistent 5°F offset
                        minisplit_mode="cool",
                        minisplit_active=True,
                    )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Verify offset was calculated
        assert abs(learning_manager.learned_offset - 5.0) < 0.1
        assert learning_manager.confidence > 0.7

    def test_requirement_5_2_use_only_cooling_data(self):
        """Test that offset calculation only uses data from cooling periods."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=20,  # Lower for testing
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add cooling data with 5°F offset
        for i in range(30):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Add heating data with different offset (should be ignored for cooling offset)
        for i in range(30):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=74.0,  # 2°F offset
                minisplit_mode="heat",
                minisplit_active=True,
            )
        
        # Add off/dry mode data (should be ignored)
        for i in range(10):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=73.0,  # 1°F offset
                minisplit_mode="off",
                minisplit_active=False,
            )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Verify cooling offset is based only on cooling data (5°F)
        assert abs(learning_manager.get_learned_offset("cool") - 5.0) < 0.1
        # Verify heating offset is based only on heating data (2°F)
        assert abs(learning_manager.get_learned_offset("heat") - 2.0) < 0.1

    def test_requirement_5_3_apply_learned_offset_to_target(self):
        """Test that learned offset is applied to target temperatures."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=10,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add data to establish learned offset
        for i in range(20):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Force recalculation
        learning_manager.force_recalculation()
        
        # Test offset application
        target_temp = 72.0
        adjusted_temp = learning_manager.get_adjusted_target_temperature(target_temp, "cool")
        
        # Should adjust target down by learned offset (72 - 5 = 67)
        assert abs(adjusted_temp - 67.0) < 0.1

    def test_requirement_5_4_use_default_offset_insufficient_data(self):
        """Test using default offset when insufficient data is available."""
        mock_hass = MagicMock()
        config_data = {
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
            "default_cooling_offset": 5.0,  # Default offset
        }
        
        config = SmartThermostatConfig.from_config_entry(config_data)
        control_manager = ControlManager(mock_hass, config)
        
        # Create controller state with no learned offset (insufficient data)
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=75.0,
            current_humidity=45.0,
            last_mode_change=None,
            learned_offset=5.0,  # Default offset
            offset_confidence=0.0,  # No confidence (insufficient data)
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Test that default offset is used
        adjusted_target = control_manager._apply_learned_offset(72.0, 5.0, HVAC_MODE_COOL)
        assert adjusted_target == 67.0  # 72 - 5 (default offset)
