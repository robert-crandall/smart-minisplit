"""Tests for the Smart Thermostat Controller climate platform."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate import (
    HVACAction,
    HVACMode,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.climate import SmartThermostatClimate
from custom_components.smart_thermostat_controller.const import (
    DOMAIN,
    HVAC_MODE_AUTO,
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
)
from custom_components.smart_thermostat_controller.coordinator import SmartThermostatCoordinator
from custom_components.smart_thermostat_controller.models import (
    ControllerState,
    SmartThermostatConfig,
    SensorReadings,
)


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    return SmartThermostatConfig(
        external_temp_sensor="sensor.external_temp",
        external_humidity_sensor="sensor.external_humidity",
        minisplit_entity="climate.minisplit",
        target_temperature=72.0,
        humidity_max_threshold=60.0,
        humidity_min_threshold=40.0,
        temperature_deadband=1.0,
        cooldown_period=900,
        learning_enabled=True,
        learning_period_days=7,
        default_cooling_offset=5.0,
        idle_temperature_offset=2.0,
        away_mode_enabled=False,
        away_min_temperature=65.0,
        away_max_temperature=78.0,
    )


@pytest.fixture
def mock_coordinator(mock_config):
    """Create a mock coordinator."""
    coordinator = MagicMock(spec=SmartThermostatCoordinator)
    coordinator.config = mock_config
    coordinator.hass = MagicMock()  # Add mock hass attribute
    coordinator.last_update_success = True
    coordinator.data = ControllerState(
        current_mode=HVAC_MODE_OFF,
        target_temperature=72.0,
        current_temperature=70.0,
        current_humidity=50.0,
        last_mode_change=None,
        learned_offset=5.0,
        offset_confidence=0.8,
        manual_override=False,
        cooldown_remaining=0,
        is_available=True,
    )
    coordinator.config_entry = MagicMock(spec=ConfigEntry)
    coordinator.config_entry.entry_id = "test_entry"
    coordinator.config_entry.data = {
        "external_temperature_sensor": "sensor.external_temp",
        "external_humidity_sensor": "sensor.external_humidity",
        "minisplit_climate_entity": "climate.minisplit",
        "target_temperature": 72.0,
    }
    coordinator.set_manual_override = MagicMock()
    coordinator.record_mode_change = AsyncMock()
    coordinator.async_update_config = AsyncMock()
    return coordinator


@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry"
    entry.data = {
        "external_temperature_sensor": "sensor.external_temp",
        "external_humidity_sensor": "sensor.external_humidity",
        "minisplit_climate_entity": "climate.minisplit",
        "target_temperature": 72.0,
    }
    return entry


@pytest.fixture
def climate_entity(mock_coordinator, mock_entry):
    """Create a climate entity for testing."""
    return SmartThermostatClimate(mock_coordinator, mock_entry)


class TestSmartThermostatClimate:
    """Test the SmartThermostatClimate class."""

    def test_init(self, climate_entity, mock_coordinator, mock_entry):
        """Test climate entity initialization."""
        assert climate_entity.coordinator == mock_coordinator
        assert climate_entity._entry == mock_entry
        assert climate_entity.unique_id == "test_entry_climate"
        assert climate_entity.name == "Smart Thermostat Controller"
        assert HVACMode.OFF in climate_entity.hvac_modes
        assert HVACMode.AUTO in climate_entity.hvac_modes
        assert HVACMode.HEAT in climate_entity.hvac_modes
        assert HVACMode.COOL in climate_entity.hvac_modes
        assert HVACMode.DRY in climate_entity.hvac_modes

    def test_current_temperature(self, climate_entity):
        """Test current temperature property."""
        assert climate_entity.current_temperature == 70.0
        
        # Test with no data
        climate_entity.coordinator.data = None
        assert climate_entity.current_temperature is None

    def test_current_humidity(self, climate_entity):
        """Test current humidity property."""
        assert climate_entity.current_humidity == 50
        
        # Test with no humidity data
        climate_entity.coordinator.data.current_humidity = None
        assert climate_entity.current_humidity is None
        
        # Test with no data
        climate_entity.coordinator.data = None
        assert climate_entity.current_humidity is None

    def test_target_temperature(self, climate_entity):
        """Test target temperature property."""
        assert climate_entity.target_temperature == 72.0
        
        # Test with no data
        climate_entity.coordinator.data = None
        assert climate_entity.target_temperature is None

    def test_hvac_mode_auto(self, climate_entity):
        """Test HVAC mode in automatic mode."""
        # In auto mode with system running
        climate_entity.coordinator.data.current_mode = HVAC_MODE_COOL
        climate_entity._manual_override = False
        assert climate_entity.hvac_mode == HVACMode.AUTO
        
        # In auto mode with system off
        climate_entity.coordinator.data.current_mode = HVAC_MODE_OFF
        assert climate_entity.hvac_mode == HVACMode.OFF

    def test_hvac_mode_manual(self, climate_entity):
        """Test HVAC mode in manual override mode."""
        climate_entity._manual_override = True
        
        # Test different manual modes
        climate_entity.coordinator.data.current_mode = HVAC_MODE_COOL
        assert climate_entity.hvac_mode == HVACMode.COOL
        
        climate_entity.coordinator.data.current_mode = HVAC_MODE_HEAT
        assert climate_entity.hvac_mode == HVACMode.HEAT
        
        climate_entity.coordinator.data.current_mode = HVAC_MODE_DRY
        assert climate_entity.hvac_mode == HVACMode.DRY
        
        climate_entity.coordinator.data.current_mode = HVAC_MODE_OFF
        assert climate_entity.hvac_mode == HVACMode.OFF

    def test_hvac_action(self, climate_entity):
        """Test HVAC action property."""
        # Test different actions
        climate_entity.coordinator.data.current_mode = HVAC_MODE_COOL
        assert climate_entity.hvac_action == HVACAction.COOLING
        
        climate_entity.coordinator.data.current_mode = HVAC_MODE_HEAT
        assert climate_entity.hvac_action == HVACAction.HEATING
        
        climate_entity.coordinator.data.current_mode = HVAC_MODE_DRY
        assert climate_entity.hvac_action == HVACAction.DRYING
        
        climate_entity.coordinator.data.current_mode = HVAC_MODE_OFF
        assert climate_entity.hvac_action == HVACAction.OFF

    def test_available(self, climate_entity):
        """Test availability property."""
        # Available when coordinator is successful and data is available
        assert climate_entity.available is True
        
        # Not available when coordinator update failed
        climate_entity.coordinator.last_update_success = False
        assert climate_entity.available is False
        
        # Not available when no data
        climate_entity.coordinator.last_update_success = True
        climate_entity.coordinator.data = None
        assert climate_entity.available is False
        
        # Not available when data shows unavailable
        climate_entity.coordinator.data = MagicMock()
        climate_entity.coordinator.data.is_available = False
        assert climate_entity.available is False

    def test_extra_state_attributes(self, climate_entity):
        """Test extra state attributes."""
        # Set up test data with timestamp
        test_time = dt_util.utcnow()
        climate_entity.coordinator.data.last_mode_change = test_time
        
        attributes = climate_entity.extra_state_attributes
        
        assert attributes["learned_offset"] == 5.0
        assert attributes["offset_confidence"] == "80.0%"
        assert attributes["manual_override"] is False
        assert attributes["cooldown_remaining"] == 0
        assert attributes["last_mode_change"] == test_time.isoformat()
        
        # Test with no data
        climate_entity.coordinator.data = None
        assert climate_entity.extra_state_attributes == {}

    @pytest.mark.asyncio
    async def test_async_set_temperature_valid(self, climate_entity):
        """Test setting valid temperature."""
        mock_hass = MagicMock()
        mock_hass.config_entries.async_update_entry = MagicMock()
        climate_entity.hass = mock_hass
        
        with patch.object(climate_entity, '_execute_automatic_control') as mock_control:
            
            await climate_entity.async_set_temperature(temperature=75.0)
            
            # Verify config entry was updated
            mock_hass.config_entries.async_update_entry.assert_called_once()
            call_args = mock_hass.config_entries.async_update_entry.call_args
            assert call_args[0][0] == climate_entity.coordinator.config_entry
            assert call_args[1]["data"]["target_temperature"] == 75.0
            
            # Verify coordinator config was updated
            climate_entity.coordinator.async_update_config.assert_called_once()
            
            # Verify automatic control was executed (not in manual override)
            mock_control.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_set_temperature_invalid(self, climate_entity):
        """Test setting invalid temperature."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        # Test temperature too low
        with pytest.raises(HomeAssistantError, match="outside valid range"):
            await climate_entity.async_set_temperature(temperature=30.0)
        
        # Test temperature too high
        with pytest.raises(HomeAssistantError, match="outside valid range"):
            await climate_entity.async_set_temperature(temperature=100.0)
        
        # Test no temperature provided
        await climate_entity.async_set_temperature()  # Should not raise

    @pytest.mark.asyncio
    async def test_async_set_temperature_manual_override(self, climate_entity):
        """Test setting temperature in manual override mode."""
        mock_hass = MagicMock()
        mock_hass.config_entries.async_update_entry = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = True
        
        with patch.object(climate_entity, '_execute_automatic_control') as mock_control:
            
            await climate_entity.async_set_temperature(temperature=75.0)
            
            # Should not execute automatic control in manual override
            mock_control.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_set_hvac_mode_off(self, climate_entity):
        """Test setting HVAC mode to OFF."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        with patch.object(climate_entity, '_set_minisplit_mode') as mock_set_mode:
            await climate_entity.async_set_hvac_mode(HVACMode.OFF)
            
            mock_set_mode.assert_called_once_with(HVAC_MODE_OFF)
            assert climate_entity._manual_override is False

    @pytest.mark.asyncio
    async def test_async_set_hvac_mode_auto(self, climate_entity):
        """Test setting HVAC mode to AUTO."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = True  # Start in manual override
        
        with patch.object(climate_entity, '_execute_automatic_control') as mock_control:
            await climate_entity.async_set_hvac_mode(HVACMode.AUTO)
            
            assert climate_entity._manual_override is False
            climate_entity.coordinator.set_manual_override.assert_called_once_with(False)
            mock_control.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_set_hvac_mode_manual(self, climate_entity):
        """Test setting HVAC mode to manual modes."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        with patch.object(climate_entity, '_set_minisplit_mode') as mock_set_mode:
            # Test cooling mode
            await climate_entity.async_set_hvac_mode(HVACMode.COOL)
            
            mock_set_mode.assert_called_once_with(HVAC_MODE_COOL)
            assert climate_entity._manual_override is True
            climate_entity.coordinator.set_manual_override.assert_called_with(True)
            
            # Test heating mode
            mock_set_mode.reset_mock()
            climate_entity.coordinator.set_manual_override.reset_mock()
            
            await climate_entity.async_set_hvac_mode(HVACMode.HEAT)
            
            mock_set_mode.assert_called_once_with(HVAC_MODE_HEAT)
            assert climate_entity._manual_override is True

    @pytest.mark.asyncio
    async def test_async_turn_on(self, climate_entity):
        """Test turning on the climate entity."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = True  # Start in manual override
        
        with patch.object(climate_entity, '_execute_automatic_control') as mock_control:
            await climate_entity.async_turn_on()
            
            assert climate_entity._manual_override is False
            climate_entity.coordinator.set_manual_override.assert_called_once_with(False)
            mock_control.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off(self, climate_entity):
        """Test turning off the climate entity."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        with patch.object(climate_entity, '_set_minisplit_mode') as mock_set_mode:
            await climate_entity.async_turn_off()
            
            mock_set_mode.assert_called_once_with(HVAC_MODE_OFF)
            assert climate_entity._manual_override is False
            climate_entity.coordinator.set_manual_override.assert_called_once_with(False)

    @pytest.mark.asyncio
    async def test_execute_automatic_control_success(self, climate_entity):
        """Test successful automatic control execution."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = False
        
        # Mock sensor readings
        mock_readings = SensorReadings(
            temperature=75.0,
            humidity=55.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Mock control action
        from custom_components.smart_thermostat_controller.models import ControlAction
        mock_action = ControlAction(
            action_type=HVAC_MODE_COOL,
            target_temperature=67.0,  # 72 - 5 offset
            reason="Temperature too high",
            can_execute=True,
            cooldown_remaining=0,
        )
        
        with patch.object(climate_entity, '_get_current_sensor_readings', return_value=mock_readings), \
             patch.object(climate_entity._control_manager, 'calculate_required_action', return_value=mock_action), \
             patch.object(climate_entity._control_manager, 'get_decision_reasoning', return_value="Test reasoning"), \
             patch.object(climate_entity, '_set_minisplit_mode') as mock_set_mode:
            
            await climate_entity._execute_automatic_control()
            
            mock_set_mode.assert_called_once_with(HVAC_MODE_COOL, 67.0)

    @pytest.mark.asyncio
    async def test_execute_automatic_control_cooldown(self, climate_entity):
        """Test automatic control during cooldown period."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = False
        
        # Mock sensor readings
        mock_readings = SensorReadings(
            temperature=75.0,
            humidity=55.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Mock control action with cooldown
        from custom_components.smart_thermostat_controller.models import ControlAction
        mock_action = ControlAction(
            action_type=HVAC_MODE_COOL,
            target_temperature=67.0,
            reason="Temperature too high",
            can_execute=False,
            cooldown_remaining=120,
        )
        
        with patch.object(climate_entity, '_get_current_sensor_readings', return_value=mock_readings), \
             patch.object(climate_entity._control_manager, 'calculate_required_action', return_value=mock_action), \
             patch.object(climate_entity._control_manager, 'get_decision_reasoning', return_value="Test reasoning"), \
             patch.object(climate_entity, '_set_minisplit_mode') as mock_set_mode:
            
            await climate_entity._execute_automatic_control()
            
            # Should not set mode during cooldown
            mock_set_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_automatic_control_manual_override(self, climate_entity):
        """Test automatic control skipped in manual override."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = True
        
        with patch.object(climate_entity, '_get_current_sensor_readings') as mock_readings:
            await climate_entity._execute_automatic_control()
            
            # Should not get sensor readings in manual override
            mock_readings.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_current_sensor_readings(self, climate_entity):
        """Test getting current sensor readings."""
        from homeassistant.util import dt as dt_util
        
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        # Mock sensor states with proper last_updated
        temp_state = MagicMock()
        temp_state.state = "75.5"
        temp_state.last_updated = dt_util.utcnow()
        humidity_state = MagicMock()
        humidity_state.state = "55.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        mock_hass.states.get = MagicMock(side_effect=lambda entity_id: {
            "sensor.external_temp": temp_state,
            "sensor.external_humidity": humidity_state,
        }.get(entity_id))
        
        readings = await climate_entity._get_current_sensor_readings()
        
        assert readings.temperature == 75.5
        assert readings.humidity == 55.0
        assert readings.temperature_available is True
        assert readings.humidity_available is True

    @pytest.mark.asyncio
    async def test_get_current_sensor_readings_unavailable(self, climate_entity):
        """Test getting sensor readings when sensors are unavailable."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        # Mock unavailable sensor states
        temp_state = MagicMock()
        temp_state.state = "unavailable"
        humidity_state = MagicMock()
        humidity_state.state = "unknown"
        
        mock_hass.states.get = MagicMock(side_effect=lambda entity_id: {
            "sensor.external_temp": temp_state,
            "sensor.external_humidity": humidity_state,
        }.get(entity_id))
        
        readings = await climate_entity._get_current_sensor_readings()
        
        assert readings.temperature is None
        assert readings.humidity is None
        assert readings.temperature_available is False
        assert readings.humidity_available is False

    @pytest.mark.asyncio
    async def test_get_current_sensor_readings_missing(self, climate_entity):
        """Test getting sensor readings when sensors are missing."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        # Mock missing sensors (return None)
        mock_hass.states.get = MagicMock(return_value=None)
        
        readings = await climate_entity._get_current_sensor_readings()
        
        assert readings.temperature is None
        assert readings.humidity is None
        assert readings.temperature_available is False
        assert readings.humidity_available is False

    @pytest.mark.asyncio
    async def test_set_minisplit_mode_off(self, climate_entity):
        """Test setting minisplit to OFF mode."""
        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()
        climate_entity.hass = mock_hass
        
        await climate_entity._set_minisplit_mode(HVAC_MODE_OFF)
        
        mock_hass.services.async_call.assert_called_once_with(
            "climate",
            "turn_off",
            {"entity_id": "climate.minisplit"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_set_minisplit_mode_with_temperature(self, climate_entity):
        """Test setting minisplit mode with target temperature."""
        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()
        climate_entity.hass = mock_hass
        
        await climate_entity._set_minisplit_mode(HVAC_MODE_COOL, 68.0)
        
        # Should call set_hvac_mode and set_temperature
        assert mock_hass.services.async_call.call_count == 2
        
        # Check set_hvac_mode call - service data is passed as positional arg
        hvac_call = mock_hass.services.async_call.call_args_list[0]
        assert hvac_call.args[0] == "climate"
        assert hvac_call.args[1] == "set_hvac_mode"
        service_data = hvac_call.args[2]
        assert service_data["entity_id"] == "climate.minisplit"
        assert service_data["hvac_mode"] == HVAC_MODE_COOL
        assert service_data["temperature"] == 68.0
        assert hvac_call.kwargs["blocking"] is True
        
        # Check set_temperature call
        temp_call = mock_hass.services.async_call.call_args_list[1]
        assert temp_call.args[0] == "climate"
        assert temp_call.args[1] == "set_temperature"
        temp_service_data = temp_call.args[2]
        assert temp_service_data["entity_id"] == "climate.minisplit"
        assert temp_service_data["temperature"] == 68.0
        assert temp_call.kwargs["blocking"] is True

    @pytest.mark.asyncio
    async def test_set_minisplit_mode_without_temperature(self, climate_entity):
        """Test setting minisplit mode without target temperature."""
        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()
        climate_entity.hass = mock_hass
        
        await climate_entity._set_minisplit_mode(HVAC_MODE_DRY)
        
        # Should only call set_hvac_mode
        mock_hass.services.async_call.assert_called_once_with(
            "climate",
            "set_hvac_mode",
            {
                "entity_id": "climate.minisplit",
                "hvac_mode": HVAC_MODE_DRY,
            },
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_set_minisplit_mode_error(self, climate_entity):
        """Test error handling when setting minisplit mode."""
        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Service call failed"))
        climate_entity.hass = mock_hass
        
        # The new error handling returns False instead of raising an exception
        result = await climate_entity._set_minisplit_mode(HVAC_MODE_COOL)
        assert result is False

    @pytest.mark.asyncio
    async def test_set_minisplit_mode_records_change(self, climate_entity):
        """Test that mode changes are recorded for cooldown tracking."""
        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()
        climate_entity.hass = mock_hass
        
        # Mock the control manager's record_mode_change method
        climate_entity._control_manager.record_mode_change = MagicMock()
        
        # Set current mode to different from new mode
        climate_entity.coordinator.data.current_mode = HVAC_MODE_OFF
        
        await climate_entity._set_minisplit_mode(HVAC_MODE_COOL)
        
        # Should record mode change
        climate_entity._control_manager.record_mode_change.assert_called_once_with(HVAC_MODE_COOL)
        climate_entity.coordinator.record_mode_change.assert_called_once_with(HVAC_MODE_COOL)

    def test_handle_coordinator_update(self, climate_entity):
        """Test handling coordinator updates."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        
        # Mock the parent method
        with patch('homeassistant.helpers.update_coordinator.CoordinatorEntity._handle_coordinator_update') as mock_parent:
            # Test with manual override from coordinator
            climate_entity.coordinator.data.manual_override = True
            climate_entity._handle_coordinator_update()
            
            assert climate_entity._manual_override is True
            mock_parent.assert_called_once()

    def test_handle_coordinator_update_auto_control(self, climate_entity):
        """Test coordinator update triggers automatic control."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = False
        
        with patch('homeassistant.helpers.update_coordinator.CoordinatorEntity._handle_coordinator_update'), \
             patch.object(mock_hass, 'async_create_task') as mock_create_task:
            
            climate_entity._handle_coordinator_update()
            
            # Should create task for automatic control
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_added_to_hass(self, climate_entity):
        """Test entity added to hass."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = False
        
        with patch('homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass') as mock_parent, \
             patch.object(climate_entity, '_execute_automatic_control') as mock_control:
            
            await climate_entity.async_added_to_hass()
            
            mock_parent.assert_called_once()
            mock_control.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_added_to_hass_manual_override(self, climate_entity):
        """Test entity added to hass in manual override mode."""
        mock_hass = MagicMock()
        climate_entity.hass = mock_hass
        climate_entity._manual_override = True
        
        with patch('homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass') as mock_parent, \
             patch.object(climate_entity, '_execute_automatic_control') as mock_control:
            
            await climate_entity.async_added_to_hass()
            
            mock_parent.assert_called_once()
            # Should not execute automatic control in manual override
            mock_control.assert_not_called()
