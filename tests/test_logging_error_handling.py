"""Tests for logging and error handling functionality."""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.const import (
    ERROR_SENSOR_UNAVAILABLE,
    ERROR_SENSOR_INVALID_VALUE,
    ERROR_SENSOR_TIMEOUT,
    ERROR_MINISPLIT_COMMAND_FAILED,
    TEMP_MIN_VALID,
    TEMP_MAX_VALID,
    HUMIDITY_MIN_VALID,
    HUMIDITY_MAX_VALID,
)
from custom_components.smart_thermostat_controller.error_handling import (
    ErrorRecoveryManager,
    SensorError,
    MinisplitError,
    ConfigurationError,
    validate_sensor_value,
    safe_call_service,
    validate_config_value,
)
from custom_components.smart_thermostat_controller.logging_utils import (
    SmartThermostatLogger,
    create_logger,
)


class TestSmartThermostatLogger:
    """Test SmartThermostatLogger functionality."""

    @pytest.fixture
    def hass(self):
        """Create a mock Home Assistant instance."""
        return MagicMock(spec=HomeAssistant)

    @pytest.fixture
    def logger(self, hass):
        """Create a SmartThermostatLogger instance."""
        return SmartThermostatLogger(hass, "test_component")

    def test_log_decision(self, logger):
        """Test decision logging."""
        sensor_data = {"temperature": 75.0, "humidity": 55.0}
        controller_state = {"target_temperature": 72.0, "current_mode": "cool"}
        
        with patch.object(logger._logger, 'info') as mock_info:
            logger.log_decision(
                decision="cool",
                reasoning="Temperature above target",
                sensor_data=sensor_data,
                controller_state=controller_state
            )
            
            mock_info.assert_called_once()
            args, kwargs = mock_info.call_args
            # Check the format string and arguments
            assert "Control Decision: %s | Reason: %s" == args[0]
            assert args[1] == "cool"
            assert args[2] == "Temperature above target"
            assert "decision_data" in kwargs["extra"]

    def test_log_sensor_error(self, logger):
        """Test sensor error logging."""
        with patch.object(logger._logger, 'error') as mock_error:
            logger.log_sensor_error(
                sensor_entity="sensor.temperature",
                error_type=ERROR_SENSOR_UNAVAILABLE,
                error_message="Sensor not found",
                sensor_value=None,
                recovery_action="Using fallback"
            )
            
            mock_error.assert_called_once()
            args, kwargs = mock_error.call_args
            # Check the format string and arguments
            assert "Sensor Error [%s]: %s (entity: %s, value: %s) - Recovery: %s" == args[0]
            assert args[1] == ERROR_SENSOR_UNAVAILABLE
            assert args[2] == "Sensor not found"
            assert args[3] == "sensor.temperature"
            assert args[4] is None
            assert args[5] == "Using fallback"
            assert "sensor_error_data" in kwargs["extra"]

    def test_log_config_change(self, logger):
        """Test configuration change logging."""
        with patch.object(logger._logger, 'info') as mock_info:
            logger.log_config_change(
                config_key="target_temperature",
                old_value=70.0,
                new_value=72.0,
                changed_by="user"
            )
            
            mock_info.assert_called_once()
            args, kwargs = mock_info.call_args
            # Check the format string and arguments
            assert "Config Change: %s changed from %s to %s (by: %s)" == args[0]
            assert args[1] == "target_temperature"
            assert args[2] == 70.0
            assert args[3] == 72.0
            assert args[4] == "user"
            assert "config_audit_data" in kwargs["extra"]

    def test_log_manual_override(self, logger):
        """Test manual override logging."""
        with patch.object(logger._logger, 'info') as mock_info:
            logger.log_manual_override(
                override_enabled=True,
                triggered_by="user",
                previous_mode="auto",
                new_mode="cool"
            )
            
            mock_info.assert_called_once()
            args, kwargs = mock_info.call_args
            # Check the format string and arguments
            assert "Manual Override %s (by: %s) - Mode: %s -> %s" == args[0]
            assert args[1] == "enabled"
            assert args[2] == "user"
            assert args[3] == "auto"
            assert args[4] == "cool"
            assert "override_audit_data" in kwargs["extra"]

    def test_log_graceful_degradation(self, logger):
        """Test graceful degradation logging."""
        with patch.object(logger._logger, 'warning') as mock_warning:
            logger.log_graceful_degradation(
                degradation_type="sensor_failure",
                reason="Temperature sensor unavailable",
                affected_features=["temperature_control"],
                fallback_behavior="Manual control only"
            )
            
            mock_warning.assert_called_once()
            args, kwargs = mock_warning.call_args
            assert "Graceful Degradation" in args[0]
            assert "degradation_data" in kwargs["extra"]

    def test_log_exception(self, logger):
        """Test exception logging."""
        test_exception = ValueError("Test error")
        
        with patch.object(logger._logger, 'error') as mock_error:
            logger.log_exception(
                operation="test_operation",
                exception=test_exception,
                context={"key": "value"},
                recovery_action="Retry operation"
            )
            
            mock_error.assert_called_once()
            args, kwargs = mock_error.call_args
            # Check the format string and arguments
            assert "Exception in %s: %s (%s) - Recovery: %s" == args[0]
            assert args[1] == "test_operation"
            assert args[2] == "Test error"
            assert args[3] == "ValueError"
            assert args[4] == "Retry operation"
            assert "exception_data" in kwargs["extra"]

    def test_error_count_tracking(self, logger):
        """Test error count tracking."""
        # Log multiple errors of the same type
        for _ in range(3):
            logger.log_sensor_error(
                sensor_entity="sensor.test",
                error_type=ERROR_SENSOR_UNAVAILABLE,
                error_message="Test error",
                recovery_action="Test recovery"
            )
        
        summary = logger.get_error_summary()
        assert summary["error_counts"][ERROR_SENSOR_UNAVAILABLE] == 3
        assert ERROR_SENSOR_UNAVAILABLE in summary["last_errors"]

    def test_reset_error_counts(self, logger):
        """Test resetting error counts."""
        # Log an error
        logger.log_sensor_error(
            sensor_entity="sensor.test",
            error_type=ERROR_SENSOR_UNAVAILABLE,
            error_message="Test error",
            recovery_action="Test recovery"
        )
        
        # Reset counts
        logger.reset_error_counts()
        
        summary = logger.get_error_summary()
        assert len(summary["error_counts"]) == 0
        assert len(summary["last_errors"]) == 0


class TestErrorRecoveryManager:
    """Test ErrorRecoveryManager functionality."""

    @pytest.fixture
    def hass(self):
        """Create a mock Home Assistant instance."""
        return MagicMock(spec=HomeAssistant)

    @pytest.fixture
    def logger(self, hass):
        """Create a SmartThermostatLogger instance."""
        return SmartThermostatLogger(hass, "test_component")

    @pytest.fixture
    def error_manager(self, hass, logger):
        """Create an ErrorRecoveryManager instance."""
        return ErrorRecoveryManager(hass, logger)

    def test_degraded_feature_management(self, error_manager):
        """Test degraded feature management."""
        feature = "temperature_control"
        
        # Initially not degraded
        assert not error_manager.is_feature_degraded(feature)
        
        # Add degraded feature
        error_manager.add_degraded_feature(feature, "Sensor failure")
        assert error_manager.is_feature_degraded(feature)
        
        # Remove degraded feature
        error_manager.remove_degraded_feature(feature)
        assert not error_manager.is_feature_degraded(feature)

    def test_error_frequency_tracking(self, error_manager):
        """Test error frequency tracking."""
        error_type = ERROR_SENSOR_UNAVAILABLE
        
        # Record multiple errors
        for _ in range(5):
            error_manager.record_error(error_type)
        
        # Check frequency
        frequency = error_manager.get_error_frequency(error_type, time_window_hours=1)
        assert frequency == 5

    def test_error_suppression(self, error_manager):
        """Test error suppression based on frequency."""
        error_type = ERROR_SENSOR_UNAVAILABLE
        
        # Record errors below threshold
        for _ in range(5):
            error_manager.record_error(error_type)
        
        assert not error_manager.should_suppress_error(error_type, max_per_hour=10)
        
        # Record errors above threshold
        for _ in range(10):
            error_manager.record_error(error_type)
        
        assert error_manager.should_suppress_error(error_type, max_per_hour=10)

    @pytest.mark.asyncio
    async def test_recovery_callbacks(self, error_manager):
        """Test recovery callback registration and execution."""
        error_type = "test_error"
        callback_called = False
        
        async def recovery_callback():
            nonlocal callback_called
            callback_called = True
        
        # Register callback
        error_manager.register_recovery_callback(error_type, recovery_callback)
        
        # Attempt recovery
        success = await error_manager.attempt_recovery(error_type)
        
        assert success
        assert callback_called


class TestSensorValidation:
    """Test sensor validation functionality."""

    @pytest.fixture
    def hass(self):
        """Create a mock Home Assistant instance."""
        return MagicMock(spec=HomeAssistant)

    @pytest.fixture
    def logger(self, hass):
        """Create a SmartThermostatLogger instance."""
        return SmartThermostatLogger(hass, "test_component")

    @pytest.fixture
    def error_manager(self, hass, logger):
        """Create an ErrorRecoveryManager instance."""
        return ErrorRecoveryManager(hass, logger)

    def test_validate_temperature_sensor_success(self, logger, error_manager):
        """Test successful temperature sensor validation."""
        state = MagicMock(spec=State)
        state.state = "72.5"
        state.last_updated = dt_util.utcnow()
        
        value, available = validate_sensor_value(
            state, "sensor.temperature", "temperature", logger, error_manager
        )
        
        assert value == 72.5
        assert available is True

    def test_validate_temperature_sensor_unavailable(self, logger, error_manager):
        """Test temperature sensor unavailable."""
        value, available = validate_sensor_value(
            None, "sensor.temperature", "temperature", logger, error_manager
        )
        
        assert value is None
        assert available is False

    def test_validate_temperature_sensor_invalid_state(self, logger, error_manager):
        """Test temperature sensor with invalid state."""
        state = MagicMock(spec=State)
        state.state = "unavailable"
        
        value, available = validate_sensor_value(
            state, "sensor.temperature", "temperature", logger, error_manager
        )
        
        assert value is None
        assert available is False

    def test_validate_temperature_sensor_invalid_value(self, logger, error_manager):
        """Test temperature sensor with invalid numeric value."""
        state = MagicMock(spec=State)
        state.state = "not_a_number"
        state.last_updated = dt_util.utcnow()
        
        value, available = validate_sensor_value(
            state, "sensor.temperature", "temperature", logger, error_manager
        )
        
        assert value is None
        assert available is False

    def test_validate_temperature_sensor_out_of_range(self, logger, error_manager):
        """Test temperature sensor with out-of-range value."""
        state = MagicMock(spec=State)
        state.state = "150.0"  # Above TEMP_MAX_VALID
        state.last_updated = dt_util.utcnow()
        
        value, available = validate_sensor_value(
            state, "sensor.temperature", "temperature", logger, error_manager
        )
        
        assert value is None
        assert available is False

    def test_validate_humidity_sensor_success(self, logger, error_manager):
        """Test successful humidity sensor validation."""
        state = MagicMock(spec=State)
        state.state = "55.0"
        state.last_updated = dt_util.utcnow()
        
        value, available = validate_sensor_value(
            state, "sensor.humidity", "humidity", logger, error_manager
        )
        
        assert value == 55.0
        assert available is True

    def test_validate_humidity_sensor_out_of_range(self, logger, error_manager):
        """Test humidity sensor with out-of-range value."""
        state = MagicMock(spec=State)
        state.state = "150.0"  # Above HUMIDITY_MAX_VALID
        state.last_updated = dt_util.utcnow()
        
        value, available = validate_sensor_value(
            state, "sensor.humidity", "humidity", logger, error_manager
        )
        
        assert value is None
        assert available is False


class TestServiceCalls:
    """Test safe service call functionality."""

    @pytest.fixture
    def hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.services = MagicMock()
        return hass

    @pytest.fixture
    def logger(self, hass):
        """Create a SmartThermostatLogger instance."""
        return SmartThermostatLogger(hass, "test_component")

    @pytest.fixture
    def error_manager(self, hass, logger):
        """Create an ErrorRecoveryManager instance."""
        return ErrorRecoveryManager(hass, logger)

    @pytest.mark.asyncio
    async def test_safe_call_service_success(self, hass, logger, error_manager):
        """Test successful service call."""
        hass.services.async_call = AsyncMock()
        
        success = await safe_call_service(
            hass, "climate", "set_temperature",
            {"entity_id": "climate.test", "temperature": 72},
            logger, error_manager, "climate.test"
        )
        
        assert success is True
        hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_safe_call_service_timeout(self, hass, logger, error_manager):
        """Test service call timeout."""
        hass.services.async_call = AsyncMock(side_effect=asyncio.TimeoutError())
        
        success = await safe_call_service(
            hass, "climate", "set_temperature",
            {"entity_id": "climate.test", "temperature": 72},
            logger, error_manager, "climate.test", timeout=1.0
        )
        
        assert success is False

    @pytest.mark.asyncio
    async def test_safe_call_service_exception(self, hass, logger, error_manager):
        """Test service call with exception."""
        hass.services.async_call = AsyncMock(side_effect=HomeAssistantError("Service failed"))
        
        success = await safe_call_service(
            hass, "climate", "set_temperature",
            {"entity_id": "climate.test", "temperature": 72},
            logger, error_manager, "climate.test"
        )
        
        assert success is False


class TestConfigValidation:
    """Test configuration validation functionality."""

    def test_validate_config_value_success(self):
        """Test successful config validation."""
        valid, error = validate_config_value(72.0, float, min_value=50.0, max_value=90.0)
        assert valid is True
        assert error is None

    def test_validate_config_value_wrong_type(self):
        """Test config validation with wrong type."""
        valid, error = validate_config_value("72", float)
        assert valid is False
        assert "Expected float" in error

    def test_validate_config_value_out_of_range(self):
        """Test config validation with out-of-range value."""
        valid, error = validate_config_value(100.0, float, min_value=50.0, max_value=90.0)
        assert valid is False
        assert "above maximum" in error

    def test_validate_config_value_not_in_allowed(self):
        """Test config validation with value not in allowed list."""
        valid, error = validate_config_value("invalid", str, allowed_values=["heat", "cool", "off"])
        assert valid is False
        assert "not in allowed values" in error


class TestExceptionClasses:
    """Test custom exception classes."""

    def test_sensor_error(self):
        """Test SensorError exception."""
        error = SensorError("Test message", "sensor.test", ERROR_SENSOR_UNAVAILABLE)
        assert str(error) == "Test message"
        assert error.sensor_entity == "sensor.test"
        assert error.error_type == ERROR_SENSOR_UNAVAILABLE

    def test_minisplit_error(self):
        """Test MinisplitError exception."""
        error = MinisplitError("Test message", "climate.test", ERROR_MINISPLIT_COMMAND_FAILED)
        assert str(error) == "Test message"
        assert error.minisplit_entity == "climate.test"
        assert error.error_type == ERROR_MINISPLIT_COMMAND_FAILED

    def test_configuration_error(self):
        """Test ConfigurationError exception."""
        error = ConfigurationError("Test message", "test_key")
        assert str(error) == "Test message"
        assert error.config_key == "test_key"


class TestLoggerCreation:
    """Test logger creation utilities."""

    @pytest.fixture
    def hass(self):
        """Create a mock Home Assistant instance."""
        return MagicMock(spec=HomeAssistant)

    def test_create_logger(self, hass):
        """Test logger creation."""
        logger = create_logger(hass, "test_component")
        assert isinstance(logger, SmartThermostatLogger)
        assert logger._component_name == "test_component"