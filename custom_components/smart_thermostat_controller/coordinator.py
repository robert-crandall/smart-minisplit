"""Data coordinator for Smart Thermostat Controller."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, 
    UPDATE_INTERVAL_SECONDS, 
    DATA_HISTORICAL,
    ERROR_DATA_CORRUPTION,
    ERROR_SENSOR_UNAVAILABLE,
)
from .error_handling import ErrorRecoveryManager, validate_sensor_value
from .logging_utils import create_logger
from .models import (
    SmartThermostatConfig,
    ControllerState,
    SensorReadings,
    TemperatureDataPoint,
)

_LOGGER = logging.getLogger(__name__)


class SmartThermostatCoordinator(DataUpdateCoordinator[ControllerState]):
    """Coordinator for managing Smart Thermostat Controller data updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.config = SmartThermostatConfig.from_config_entry(entry.data)
        self.entry = entry
        self._historical_data: list[TemperatureDataPoint] = []
        self._learned_offset = self.config.default_cooling_offset
        self._offset_confidence = 0.0
        self._last_mode_change: datetime | None = None
        self._manual_override = False
        
        # Initialize logging and error handling
        self._logger = create_logger(hass, "coordinator")
        self._error_manager = ErrorRecoveryManager(hass, self._logger)
        
        # Initialize storage for persistent data
        self._store = Store(
            hass,
            version=1,
            key=f"{DOMAIN}_{entry.entry_id}",
            encoder=self._encode_data,
        )
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        
        self._logger.log_config_change(
            config_key="coordinator_initialized",
            old_value=None,
            new_value=f"entry_id: {entry.entry_id}, update_interval: {UPDATE_INTERVAL_SECONDS}s",
            changed_by="system"
        )

    async def async_setup(self) -> None:
        """Set up the coordinator and load persistent data."""
        try:
            await self._load_persistent_data()
            self._logger.log_config_change(
                config_key="coordinator_setup_complete",
                old_value=None,
                new_value="persistent_data_loaded",
                changed_by="system"
            )
        except Exception as err:
            self._logger.log_exception(
                operation="async_setup",
                exception=err,
                recovery_action="Coordinator setup failed, using defaults"
            )
            # Initialize with defaults if loading fails
            self._historical_data = []
            self._learned_offset = self.config.default_cooling_offset
            self._offset_confidence = 0.0

    async def _async_update_data(self) -> ControllerState:
        """Fetch data from sensors and update controller state."""
        start_time = time.time()
        
        try:
            # Fetch current sensor readings
            sensor_readings = await self._fetch_sensor_data()
            
            # Check for sensor recovery
            if sensor_readings.temperature_available and self._error_manager.is_feature_degraded("temperature_sensor"):
                self._error_manager.remove_degraded_feature("temperature_sensor")
                
            if sensor_readings.humidity_available and self._error_manager.is_feature_degraded("humidity_sensor"):
                self._error_manager.remove_degraded_feature("humidity_sensor")
            
            # Update historical data if we have valid readings
            if sensor_readings.is_valid and sensor_readings.temperature is not None:
                await self._update_historical_data(sensor_readings)
            
            # Calculate learned offset if learning is enabled
            if self.config.learning_enabled:
                await self._update_learned_offset()
            
            # Get current minisplit mode
            current_mode = await self._get_current_minisplit_mode()
            
            # Create and return current state
            state = ControllerState(
                current_mode=current_mode,
                target_temperature=self.config.target_temperature,
                current_temperature=sensor_readings.temperature,
                current_humidity=sensor_readings.humidity,
                last_mode_change=self._last_mode_change,
                learned_offset=self._learned_offset,
                offset_confidence=self._offset_confidence,
                manual_override=self._manual_override,
                cooldown_remaining=self._calculate_cooldown_remaining(),
                is_available=sensor_readings.temperature_available,
            )
            
            # Log performance if slow
            duration_ms = (time.time() - start_time) * 1000
            if duration_ms > 2000:  # Warn if takes more than 2 seconds
                self._logger.log_performance_warning(
                    operation="async_update_data",
                    duration_ms=duration_ms,
                    threshold_ms=2000,
                    context={
                        "sensor_temp_available": sensor_readings.temperature_available,
                        "sensor_humidity_available": sensor_readings.humidity_available,
                        "historical_data_points": len(self._historical_data)
                    }
                )
            
            return state
            
        except Exception as err:
            self._logger.log_exception(
                operation="async_update_data",
                exception=err,
                context={
                    "config": {
                        "temp_sensor": self.config.external_temp_sensor,
                        "humidity_sensor": self.config.external_humidity_sensor,
                        "minisplit": self.config.minisplit_entity
                    }
                },
                recovery_action="Update failed, will retry on next cycle"
            )
            raise UpdateFailed(f"Error communicating with sensors: {err}") from err

    async def _fetch_sensor_data(self) -> SensorReadings:
        """Fetch data from external temperature and humidity sensors with comprehensive error handling."""
        timestamp = dt_util.utcnow()
        
        # Fetch temperature sensor data with validation
        temp_state = self.hass.states.get(self.config.external_temp_sensor)
        temperature, temp_available = validate_sensor_value(
            temp_state,
            self.config.external_temp_sensor,
            "temperature",
            self._logger,
            self._error_manager
        )
        
        # Track temperature sensor degradation
        if not temp_available and not self._error_manager.is_feature_degraded("temperature_sensor"):
            self._error_manager.add_degraded_feature(
                "temperature_sensor",
                f"Temperature sensor {self.config.external_temp_sensor} unavailable"
            )
        
        # Fetch humidity sensor data with validation
        humidity_state = self.hass.states.get(self.config.external_humidity_sensor)
        humidity, humidity_available = validate_sensor_value(
            humidity_state,
            self.config.external_humidity_sensor,
            "humidity",
            self._logger,
            self._error_manager
        )
        
        # Track humidity sensor degradation
        if not humidity_available and not self._error_manager.is_feature_degraded("humidity_sensor"):
            self._error_manager.add_degraded_feature(
                "humidity_sensor",
                f"Humidity sensor {self.config.external_humidity_sensor} unavailable"
            )
        
        return SensorReadings(
            temperature=temperature,
            humidity=humidity,
            timestamp=timestamp,
            temperature_available=temp_available,
            humidity_available=humidity_available,
        )

    async def _get_current_minisplit_mode(self) -> str:
        """Get the current mode of the minisplit unit."""
        try:
            minisplit_state = self.hass.states.get(self.config.minisplit_entity)
            if minisplit_state is None:
                _LOGGER.warning("Minisplit entity %s not found", self.config.minisplit_entity)
                return "off"
            
            return minisplit_state.state if minisplit_state.state != "unavailable" else "off"
            
        except Exception as err:
            _LOGGER.error("Error getting minisplit mode: %s", err)
            return "off"

    async def _update_historical_data(self, sensor_readings: SensorReadings) -> None:
        """Update historical temperature data for learning."""
        if not self.config.learning_enabled or sensor_readings.temperature is None:
            return
            
        try:
            # Get minisplit internal temperature if available
            minisplit_state = self.hass.states.get(self.config.minisplit_entity)
            if minisplit_state is None:
                return
                
            # Get internal temperature from minisplit attributes
            internal_temp = None
            if hasattr(minisplit_state, 'attributes'):
                internal_temp = minisplit_state.attributes.get('current_temperature')
                
            if internal_temp is None:
                return
                
            try:
                internal_temp = float(internal_temp)
            except (ValueError, TypeError):
                return
            
            # Create data point
            data_point = TemperatureDataPoint(
                timestamp=sensor_readings.timestamp,
                external_temperature=sensor_readings.temperature,
                internal_temperature=internal_temp,
                minisplit_mode=minisplit_state.state,
                minisplit_active=minisplit_state.state in ("cool", "heat", "dry"),
            )
            
            # Add to historical data
            self._historical_data.append(data_point)
            
            # Clean up old data (keep only learning period)
            cutoff_date = dt_util.utcnow() - timedelta(days=self.config.learning_period_days)
            self._historical_data = [
                dp for dp in self._historical_data 
                if dp.timestamp > cutoff_date
            ]
            
            # Save to persistent storage periodically
            if len(self._historical_data) % 10 == 0:  # Save every 10 data points
                await self._save_persistent_data()
                
        except Exception as err:
            _LOGGER.error("Error updating historical data: %s", err)

    async def _update_learned_offset(self) -> None:
        """Update the learned temperature offset based on historical data."""
        if not self.config.learning_enabled:
            return
            
        try:
            # Filter data for cooling periods only
            cooling_data = [
                dp for dp in self._historical_data
                if dp.minisplit_mode == "cool" and dp.minisplit_active
            ]
            
            if len(cooling_data) < 10:  # Need minimum data points
                self._offset_confidence = 0.0
                return
            
            # Calculate average offset
            offsets = [
                dp.internal_temperature - dp.external_temperature
                for dp in cooling_data
            ]
            
            if not offsets:
                return
                
            # Calculate statistics
            avg_offset = sum(offsets) / len(offsets)
            
            # Calculate confidence based on data consistency
            if len(offsets) > 1:
                variance = sum((x - avg_offset) ** 2 for x in offsets) / len(offsets)
                std_dev = variance ** 0.5
                # Higher confidence for more consistent data
                self._offset_confidence = min(1.0, max(0.0, 1.0 - (std_dev / 5.0)))
            else:
                self._offset_confidence = 0.1
            
            # Apply learned offset if confidence is high enough
            if self._offset_confidence > 0.5:
                self._learned_offset = avg_offset
                _LOGGER.info("Updated learned offset to %.2f°F (confidence: %.2f)", 
                           self._learned_offset, self._offset_confidence)
            
        except Exception as err:
            _LOGGER.error("Error updating learned offset: %s", err)

    def _calculate_cooldown_remaining(self) -> int:
        """Calculate remaining cooldown time in seconds."""
        if self._last_mode_change is None:
            return 0
            
        elapsed = (dt_util.utcnow() - self._last_mode_change).total_seconds()
        remaining = max(0, self.config.cooldown_period - elapsed)
        return int(remaining)

    async def _load_persistent_data(self) -> None:
        """Load persistent data from storage."""
        try:
            data = await self._store.async_load()
            if data is not None:
                # Decode the data manually since we can't use a custom decoder
                decoded_data = self._decode_data(data)
                self._historical_data = decoded_data.get("historical_data", [])
                self._learned_offset = decoded_data.get("learned_offset", self.config.default_cooling_offset)
                self._offset_confidence = decoded_data.get("offset_confidence", 0.0)
                
                # Parse last mode change timestamp
                last_change_str = decoded_data.get("last_mode_change")
                if last_change_str:
                    self._last_mode_change = datetime.fromisoformat(last_change_str)
                    
                _LOGGER.info("Loaded %d historical data points", len(self._historical_data))
                
        except Exception as err:
            _LOGGER.error("Error loading persistent data: %s", err)
            # Initialize with defaults
            self._historical_data = []
            self._learned_offset = self.config.default_cooling_offset
            self._offset_confidence = 0.0

    async def _save_persistent_data(self) -> None:
        """Save persistent data to storage."""
        try:
            data = {
                "historical_data": self._historical_data,
                "learned_offset": self._learned_offset,
                "offset_confidence": self._offset_confidence,
                "last_mode_change": self._last_mode_change.isoformat() if self._last_mode_change else None,
            }
            # Encode the data before saving
            encoded_data = self._encode_data(data)
            await self._store.async_save(encoded_data)
            
        except Exception as err:
            _LOGGER.error("Error saving persistent data: %s", err)

    def _encode_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Encode data for storage."""
        encoded = data.copy()
        
        # Convert TemperatureDataPoint objects to dictionaries
        if "historical_data" in encoded:
            encoded["historical_data"] = [
                {
                    "timestamp": dp.timestamp.isoformat(),
                    "external_temperature": dp.external_temperature,
                    "internal_temperature": dp.internal_temperature,
                    "minisplit_mode": dp.minisplit_mode,
                    "minisplit_active": dp.minisplit_active,
                }
                for dp in encoded["historical_data"]
            ]
        
        return encoded

    def _decode_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Decode data from storage."""
        decoded = data.copy()
        
        # Convert dictionaries back to TemperatureDataPoint objects
        if "historical_data" in decoded:
            decoded["historical_data"] = [
                TemperatureDataPoint(
                    timestamp=datetime.fromisoformat(dp["timestamp"]),
                    external_temperature=dp["external_temperature"],
                    internal_temperature=dp["internal_temperature"],
                    minisplit_mode=dp["minisplit_mode"],
                    minisplit_active=dp["minisplit_active"],
                )
                for dp in decoded["historical_data"]
            ]
        
        return decoded

    async def record_mode_change(self, new_mode: str) -> None:
        """Record a mode change timestamp."""
        self._last_mode_change = dt_util.utcnow()
        await self._save_persistent_data()
        _LOGGER.info("Recorded mode change to %s", new_mode)

    def set_manual_override(self, override: bool) -> None:
        """Set manual override status."""
        self._manual_override = override
        _LOGGER.info("Manual override %s", "enabled" if override else "disabled")



    @property
    def historical_data(self) -> list[TemperatureDataPoint]:
        """Return historical temperature data."""
        return self._historical_data.copy()

    @property
    def learned_offset(self) -> float:
        """Return the current learned offset."""
        return self._learned_offset

    @property
    def offset_confidence(self) -> float:
        """Return the confidence in the learned offset."""
        return self._offset_confidence

    async def async_update_config(self, new_config: dict[str, Any]) -> None:
        """Update configuration and refresh data."""
        self.config = SmartThermostatConfig.from_config_entry(new_config)
        await self.async_refresh()

    async def async_shutdown(self) -> None:
        """Shutdown coordinator and save data."""
        await self._save_persistent_data()
        _LOGGER.info("Coordinator shutdown complete")
