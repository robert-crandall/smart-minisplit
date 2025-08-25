"""Tests for the Smart Thermostat Controller coordinator."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.coordinator import SmartThermostatCoordinator
from custom_components.smart_thermostat_controller.models import (
    SmartThermostatConfig,
    TemperatureDataPoint,
    SensorReadings,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.data = {
        "external_temperature_sensor": "sensor.temp",
        "external_humidity_sensor": "sensor.humidity",
        "minisplit_climate_entity": "climate.minisplit",
        "target_temperature": 72.0,
        "humidity_max_threshold": 60.0,
        "humidity_min_threshold": 40.0,
        "temperature_deadband": 1.0,
        "cooldown_period": 300,
        "learning_enabled": True,
        "learning_period_days": 7,
        "default_cooling_offset": 5.0,
    }
    return entry


@pytest.fixture
def coordinator(mock_hass, mock_config_entry):
    """Create a coordinator instance."""
    with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
         patch('homeassistant.helpers.frame.report_usage'), \
         patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
        coord = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
        coord.hass = mock_hass
        coord.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
        coord.entry = mock_config_entry
        coord._historical_data = []
        coord._learned_offset = coord.config.default_cooling_offset
        coord._offset_confidence = 0.0
        coord._last_mode_change = None
        coord._manual_override = False
        coord._away_mode = False
        coord._store = MagicMock()
        coord._store.async_load = AsyncMock(return_value=None)
        coord._store.async_save = AsyncMock()
        
        # Initialize logging and error handling for tests
        from custom_components.smart_thermostat_controller.logging_utils import create_logger
        from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
        coord._logger = create_logger(mock_hass, "coordinator")
        coord._error_manager = ErrorRecoveryManager(mock_hass, coord._logger)
        
        return coord


class TestSmartThermostatCoordinator:
    """Test the SmartThermostatCoordinator class."""

    def test_init(self, coordinator):
        """Test coordinator initialization."""
        assert coordinator.config.external_temp_sensor == "sensor.temp"
        assert coordinator.config.external_humidity_sensor == "sensor.humidity"
        assert coordinator.config.minisplit_entity == "climate.minisplit"
        assert coordinator._learned_offset == 5.0
        assert coordinator._offset_confidence == 0.0
        assert coordinator._manual_override is False

    async def test_fetch_sensor_data_success(self, coordinator, mock_hass):
        """Test successful sensor data fetching."""
        # Mock sensor states
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.5"
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.temp": temp_state,
            "sensor.humidity": humidity_state,
        }.get(entity_id)
        
        readings = await coordinator._fetch_sensor_data()
        
        assert readings.temperature == 72.5
        assert readings.humidity == 45.0
        assert readings.temperature_available is True
        assert readings.humidity_available is True
        assert readings.is_valid is True

    async def test_fetch_sensor_data_unavailable_sensors(self, coordinator, mock_hass):
        """Test handling of unavailable sensors."""
        # Mock unavailable sensor states
        temp_state = MagicMock(spec=State)
        temp_state.state = "unavailable"
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "unknown"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.temp": temp_state,
            "sensor.humidity": humidity_state,
        }.get(entity_id)
        
        readings = await coordinator._fetch_sensor_data()
        
        assert readings.temperature is None
        assert readings.humidity is None
        assert readings.temperature_available is False
        assert readings.humidity_available is False
        assert readings.is_valid is False

    async def test_fetch_sensor_data_missing_sensors(self, coordinator, mock_hass):
        """Test handling of missing sensors."""
        # Mock missing sensors (return None)
        mock_hass.states.get.return_value = None
        
        readings = await coordinator._fetch_sensor_data()
        
        assert readings.temperature is None
        assert readings.humidity is None
        assert readings.temperature_available is False
        assert readings.humidity_available is False
        assert readings.is_valid is False

    async def test_fetch_sensor_data_invalid_values(self, coordinator, mock_hass):
        """Test handling of invalid sensor values."""
        # Mock invalid sensor states
        temp_state = MagicMock(spec=State)
        temp_state.state = "not_a_number"
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "150"  # Out of range
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.temp": temp_state,
            "sensor.humidity": humidity_state,
        }.get(entity_id)
        
        readings = await coordinator._fetch_sensor_data()
        
        assert readings.temperature is None
        assert readings.humidity is None
        assert readings.temperature_available is False
        assert readings.humidity_available is False

    async def test_fetch_sensor_data_out_of_range_temperature(self, coordinator, mock_hass):
        """Test handling of out-of-range temperature values."""
        temp_state = MagicMock(spec=State)
        temp_state.state = "150"  # Out of valid range
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.temp": temp_state,
            "sensor.humidity": humidity_state,
        }.get(entity_id)
        
        readings = await coordinator._fetch_sensor_data()
        
        assert readings.temperature is None
        assert readings.temperature_available is False
        assert readings.humidity == 45.0
        assert readings.humidity_available is True

    async def test_get_current_minisplit_mode(self, coordinator, mock_hass):
        """Test getting current minisplit mode."""
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        
        mock_hass.states.get.return_value = minisplit_state
        
        mode = await coordinator._get_current_minisplit_mode()
        assert mode == "cool"

    async def test_get_current_minisplit_mode_unavailable(self, coordinator, mock_hass):
        """Test getting minisplit mode when unavailable."""
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "unavailable"
        
        mock_hass.states.get.return_value = minisplit_state
        
        mode = await coordinator._get_current_minisplit_mode()
        assert mode == "off"

    async def test_get_current_minisplit_mode_missing(self, coordinator, mock_hass):
        """Test getting minisplit mode when entity is missing."""
        mock_hass.states.get.return_value = None
        
        mode = await coordinator._get_current_minisplit_mode()
        assert mode == "off"

    async def test_update_historical_data(self, coordinator, mock_hass):
        """Test updating historical temperature data."""
        # Mock minisplit state with internal temperature
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        minisplit_state.attributes = {"current_temperature": 77.0}
        
        mock_hass.states.get.return_value = minisplit_state
        
        # Create sensor readings
        readings = SensorReadings(
            temperature=72.0,
            humidity=45.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        initial_count = len(coordinator._historical_data)
        await coordinator._update_historical_data(readings)
        
        assert len(coordinator._historical_data) == initial_count + 1
        
        data_point = coordinator._historical_data[-1]
        assert data_point.external_temperature == 72.0
        assert data_point.internal_temperature == 77.0
        assert data_point.minisplit_mode == "cool"
        assert data_point.minisplit_active is True

    async def test_update_historical_data_learning_disabled(self, coordinator, mock_hass):
        """Test that historical data is not updated when learning is disabled."""
        coordinator.config.learning_enabled = False
        
        readings = SensorReadings(
            temperature=72.0,
            humidity=45.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        initial_count = len(coordinator._historical_data)
        await coordinator._update_historical_data(readings)
        
        assert len(coordinator._historical_data) == initial_count

    async def test_update_learned_offset(self, coordinator):
        """Test updating learned offset from historical data."""
        # Add some historical cooling data
        now = dt_util.utcnow()
        for i in range(15):
            data_point = TemperatureDataPoint(
                timestamp=now - timedelta(minutes=i),
                external_temperature=72.0,
                internal_temperature=77.0,  # 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
            coordinator._historical_data.append(data_point)
        
        await coordinator._update_learned_offset()
        
        assert coordinator._learned_offset == 5.0
        assert coordinator._offset_confidence > 0.5

    async def test_update_learned_offset_insufficient_data(self, coordinator):
        """Test learned offset with insufficient data."""
        # Add only a few data points
        now = dt_util.utcnow()
        for i in range(5):
            data_point = TemperatureDataPoint(
                timestamp=now - timedelta(minutes=i),
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
            coordinator._historical_data.append(data_point)
        
        await coordinator._update_learned_offset()
        
        assert coordinator._offset_confidence == 0.0

    async def test_update_learned_offset_learning_disabled(self, coordinator):
        """Test that offset is not updated when learning is disabled."""
        coordinator.config.learning_enabled = False
        original_offset = coordinator._learned_offset
        
        await coordinator._update_learned_offset()
        
        assert coordinator._learned_offset == original_offset

    def test_calculate_cooldown_remaining(self, coordinator):
        """Test cooldown calculation."""
        # No previous mode change
        assert coordinator._calculate_cooldown_remaining() == 0
        
        # Recent mode change
        coordinator._last_mode_change = dt_util.utcnow() - timedelta(seconds=100)
        remaining = coordinator._calculate_cooldown_remaining()
        assert 190 <= remaining <= 210  # Should be around 200 seconds
        
        # Old mode change
        coordinator._last_mode_change = dt_util.utcnow() - timedelta(seconds=400)
        assert coordinator._calculate_cooldown_remaining() == 0

    async def test_record_mode_change(self, coordinator):
        """Test recording mode changes."""
        with patch.object(coordinator, '_save_persistent_data', new_callable=AsyncMock):
            await coordinator.record_mode_change("cool")
            
            assert coordinator._last_mode_change is not None
            assert (dt_util.utcnow() - coordinator._last_mode_change).total_seconds() < 1

    def test_set_manual_override(self, coordinator):
        """Test setting manual override."""
        coordinator.set_manual_override(True)
        assert coordinator._manual_override is True
        
        coordinator.set_manual_override(False)
        assert coordinator._manual_override is False

    async def test_async_update_data_success(self, coordinator, mock_hass):
        """Test successful data update."""
        # Mock sensor states
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.5"
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.temp": temp_state,
            "sensor.humidity": humidity_state,
            "climate.minisplit": minisplit_state,
        }.get(entity_id)
        
        with patch.object(coordinator, '_update_historical_data', new_callable=AsyncMock), \
             patch.object(coordinator, '_update_learned_offset', new_callable=AsyncMock):
            
            state = await coordinator._async_update_data()
            
            assert state.current_temperature == 72.5
            assert state.current_humidity == 45.0
            assert state.current_mode == "cool"
            assert state.target_temperature == 72.0
            assert state.is_available is True

    async def test_async_update_data_sensor_error(self, coordinator, mock_hass):
        """Test data update with sensor errors."""
        # Mock sensor error
        mock_hass.states.get.side_effect = Exception("Sensor error")
        
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    async def test_persistent_data_encoding_decoding(self, coordinator):
        """Test data encoding and decoding for storage."""
        # Create test data
        now = dt_util.utcnow()
        test_data = {
            "historical_data": [
                TemperatureDataPoint(
                    timestamp=now,
                    external_temperature=72.0,
                    internal_temperature=77.0,
                    minisplit_mode="cool",
                    minisplit_active=True,
                )
            ],
            "learned_offset": 5.0,
            "offset_confidence": 0.8,
            "last_mode_change": now.isoformat(),
        }
        
        # Test encoding
        encoded = coordinator._encode_data(test_data)
        assert isinstance(encoded["historical_data"], list)
        assert isinstance(encoded["historical_data"][0], dict)
        assert encoded["historical_data"][0]["timestamp"] == now.isoformat()
        
        # Test decoding
        decoded = coordinator._decode_data(encoded)
        assert isinstance(decoded["historical_data"], list)
        assert isinstance(decoded["historical_data"][0], TemperatureDataPoint)
        assert decoded["historical_data"][0].timestamp == now

    async def test_load_persistent_data_success(self, coordinator):
        """Test successful loading of persistent data."""
        test_data = {
            "historical_data": [],
            "learned_offset": 4.5,
            "offset_confidence": 0.7,
            "last_mode_change": dt_util.utcnow().isoformat(),
        }
        
        with patch.object(coordinator._store, 'async_load', return_value=test_data):
            await coordinator._load_persistent_data()
            
            assert coordinator._learned_offset == 4.5
            assert coordinator._offset_confidence == 0.7
            assert coordinator._last_mode_change is not None

    async def test_load_persistent_data_no_data(self, coordinator):
        """Test loading when no persistent data exists."""
        with patch.object(coordinator._store, 'async_load', return_value=None):
            await coordinator._load_persistent_data()
            
            assert coordinator._learned_offset == 5.0  # Default value
            assert coordinator._offset_confidence == 0.0
            assert coordinator._last_mode_change is None

    async def test_load_persistent_data_error(self, coordinator):
        """Test handling of errors during data loading."""
        with patch.object(coordinator._store, 'async_load', side_effect=Exception("Load error")):
            await coordinator._load_persistent_data()
            
            # Should fall back to defaults
            assert coordinator._learned_offset == 5.0
            assert coordinator._offset_confidence == 0.0
            assert len(coordinator._historical_data) == 0

    async def test_save_persistent_data_success(self, coordinator):
        """Test successful saving of persistent data."""
        with patch.object(coordinator._store, 'async_save', new_callable=AsyncMock) as mock_save:
            await coordinator._save_persistent_data()
            
            mock_save.assert_called_once()
            saved_data = mock_save.call_args[0][0]
            assert "historical_data" in saved_data
            assert "learned_offset" in saved_data
            assert "offset_confidence" in saved_data

    async def test_save_persistent_data_error(self, coordinator):
        """Test handling of errors during data saving."""
        with patch.object(coordinator._store, 'async_save', side_effect=Exception("Save error")):
            # Should not raise exception
            await coordinator._save_persistent_data()

    async def test_async_shutdown(self, coordinator):
        """Test coordinator shutdown."""
        with patch.object(coordinator, '_save_persistent_data', new_callable=AsyncMock) as mock_save:
            await coordinator.async_shutdown()
            mock_save.assert_called_once()

    async def test_historical_data_cleanup(self, coordinator):
        """Test cleanup of old historical data."""
        # Add old data points
        old_time = dt_util.utcnow() - timedelta(days=10)
        recent_time = dt_util.utcnow() - timedelta(hours=1)
        
        old_data_point = TemperatureDataPoint(
            timestamp=old_time,
            external_temperature=70.0,
            internal_temperature=75.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        recent_data_point = TemperatureDataPoint(
            timestamp=recent_time,
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        coordinator._historical_data = [old_data_point, recent_data_point]
        
        # Mock sensor readings to trigger cleanup
        readings = SensorReadings(
            temperature=72.0,
            humidity=45.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        # Mock minisplit state
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        minisplit_state.attributes = {"current_temperature": 77.0}
        coordinator.hass.states.get.return_value = minisplit_state
        
        await coordinator._update_historical_data(readings)
        
        # Old data should be removed, recent data and new data should remain
        assert len(coordinator._historical_data) == 2  # recent + new
        assert all(dp.timestamp > old_time for dp in coordinator._historical_data)
