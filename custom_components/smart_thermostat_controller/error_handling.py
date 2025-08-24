"""Error handling utilities for Smart Thermostat Controller."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    ERROR_CONFIG_INVALID,
    ERROR_DATA_CORRUPTION,
    ERROR_MINISPLIT_COMMAND_FAILED,
    ERROR_MINISPLIT_UNAVAILABLE,
    ERROR_SENSOR_INVALID_VALUE,
    ERROR_SENSOR_TIMEOUT,
    ERROR_SENSOR_UNAVAILABLE,
    HUMIDITY_MAX_VALID,
    HUMIDITY_MIN_VALID,
    SENSOR_TIMEOUT_SECONDS,
    TEMP_MAX_VALID,
    TEMP_MIN_VALID,
)
from .logging_utils import SmartThermostatLogger

_LOGGER = logging.getLogger(__name__)

T = TypeVar('T')


class SensorError(HomeAssistantError):
    """Base exception for sensor-related errors."""
    
    def __init__(self, message: str, sensor_entity: str, error_type: str) -> None:
        """Initialize sensor error.
        
        Args:
            message: Error message
            sensor_entity: Entity ID of the problematic sensor
            error_type: Type of error (from ERROR_* constants)
        """
        super().__init__(message)
        self.sensor_entity = sensor_entity
        self.error_type = error_type


class MinisplitError(HomeAssistantError):
    """Base exception for minisplit-related errors."""
    
    def __init__(self, message: str, minisplit_entity: str, error_type: str) -> None:
        """Initialize minisplit error.
        
        Args:
            message: Error message
            minisplit_entity: Entity ID of the minisplit
            error_type: Type of error (from ERROR_* constants)
        """
        super().__init__(message)
        self.minisplit_entity = minisplit_entity
        self.error_type = error_type


class ConfigurationError(HomeAssistantError):
    """Exception for configuration-related errors."""
    
    def __init__(self, message: str, config_key: Optional[str] = None) -> None:
        """Initialize configuration error.
        
        Args:
            message: Error message
            config_key: The configuration key that caused the error
        """
        super().__init__(message)
        self.config_key = config_key


class ErrorRecoveryManager:
    """Manages error recovery and graceful degradation."""
    
    def __init__(self, hass: HomeAssistant, logger: SmartThermostatLogger) -> None:
        """Initialize error recovery manager.
        
        Args:
            hass: Home Assistant instance
            logger: Logger instance for this component
        """
        self._hass = hass
        self._logger = logger
        self._degraded_features: set[str] = set()
        self._error_history: Dict[str, list[datetime]] = {}
        self._recovery_callbacks: Dict[str, list[Callable]] = {}
        
    def register_recovery_callback(self, error_type: str, callback: Callable) -> None:
        """Register a callback to be called when recovering from an error.
        
        Args:
            error_type: Type of error to recover from
            callback: Callback function to call on recovery
        """
        if error_type not in self._recovery_callbacks:
            self._recovery_callbacks[error_type] = []
        self._recovery_callbacks[error_type].append(callback)
        
    def add_degraded_feature(self, feature: str, reason: str) -> None:
        """Mark a feature as degraded.
        
        Args:
            feature: Name of the degraded feature
            reason: Reason for degradation
        """
        if feature not in self._degraded_features:
            self._degraded_features.add(feature)
            self._logger.log_graceful_degradation(
                degradation_type="feature_degraded",
                reason=reason,
                affected_features=[feature],
                fallback_behavior=f"Feature {feature} disabled, system continues with reduced functionality"
            )
            
    def remove_degraded_feature(self, feature: str) -> None:
        """Mark a feature as recovered.
        
        Args:
            feature: Name of the recovered feature
        """
        if feature in self._degraded_features:
            self._degraded_features.remove(feature)
            self._logger.log_recovery(
                recovery_type="feature_restored",
                recovered_from=f"degraded_{feature}",
                restored_features=[feature]
            )
            
    def is_feature_degraded(self, feature: str) -> bool:
        """Check if a feature is currently degraded.
        
        Args:
            feature: Name of the feature to check
            
        Returns:
            True if feature is degraded, False otherwise
        """
        return feature in self._degraded_features
        
    def record_error(self, error_type: str) -> None:
        """Record an error occurrence for tracking.
        
        Args:
            error_type: Type of error that occurred
        """
        now = dt_util.utcnow()
        if error_type not in self._error_history:
            self._error_history[error_type] = []
        self._error_history[error_type].append(now)
        
        # Keep only recent errors (last 24 hours)
        cutoff = now - timedelta(hours=24)
        self._error_history[error_type] = [
            timestamp for timestamp in self._error_history[error_type]
            if timestamp > cutoff
        ]
        
    def get_error_frequency(self, error_type: str, time_window_hours: int = 1) -> int:
        """Get the frequency of a specific error type.
        
        Args:
            error_type: Type of error to check
            time_window_hours: Time window to check (in hours)
            
        Returns:
            Number of errors in the time window
        """
        if error_type not in self._error_history:
            return 0
            
        cutoff = dt_util.utcnow() - timedelta(hours=time_window_hours)
        return len([
            timestamp for timestamp in self._error_history[error_type]
            if timestamp > cutoff
        ])
        
    def should_suppress_error(self, error_type: str, max_per_hour: int = 10) -> bool:
        """Check if error logging should be suppressed due to frequency.
        
        Args:
            error_type: Type of error to check
            max_per_hour: Maximum errors per hour before suppression
            
        Returns:
            True if error should be suppressed, False otherwise
        """
        return self.get_error_frequency(error_type) >= max_per_hour
        
    async def attempt_recovery(self, error_type: str) -> bool:
        """Attempt to recover from a specific error type.
        
        Args:
            error_type: Type of error to recover from
            
        Returns:
            True if recovery was successful, False otherwise
        """
        if error_type in self._recovery_callbacks:
            try:
                for callback in self._recovery_callbacks[error_type]:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                return True
            except Exception as err:
                self._logger.log_exception(
                    operation=f"recovery_from_{error_type}",
                    exception=err,
                    context={"error_type": error_type}
                )
                return False
        return False


def validate_sensor_value(
    state: Optional[State],
    sensor_entity: str,
    sensor_type: str,
    logger: SmartThermostatLogger,
    error_manager: ErrorRecoveryManager,
) -> tuple[Optional[float], bool]:
    """Validate a sensor value and handle errors gracefully.
    
    Args:
        state: Home Assistant state object
        sensor_entity: Entity ID of the sensor
        sensor_type: Type of sensor ("temperature" or "humidity")
        logger: Logger instance
        error_manager: Error recovery manager
        
    Returns:
        Tuple of (validated_value, is_available)
    """
    if state is None:
        error_manager.record_error(ERROR_SENSOR_UNAVAILABLE)
        if not error_manager.should_suppress_error(ERROR_SENSOR_UNAVAILABLE):
            logger.log_sensor_error(
                sensor_entity=sensor_entity,
                error_type=ERROR_SENSOR_UNAVAILABLE,
                error_message=f"{sensor_type.title()} sensor entity not found",
                recovery_action="Using fallback behavior"
            )
        return None, False
        
    if state.state in ("unavailable", "unknown", "none", None):
        error_manager.record_error(ERROR_SENSOR_UNAVAILABLE)
        if not error_manager.should_suppress_error(ERROR_SENSOR_UNAVAILABLE):
            logger.log_sensor_error(
                sensor_entity=sensor_entity,
                error_type=ERROR_SENSOR_UNAVAILABLE,
                error_message=f"{sensor_type.title()} sensor is unavailable (state: {state.state})",
                recovery_action="Using fallback behavior"
            )
        return None, False
        
    # Check if sensor data is stale
    if hasattr(state, 'last_updated') and state.last_updated is not None:
        try:
            age = (dt_util.utcnow() - state.last_updated).total_seconds()
            if age > SENSOR_TIMEOUT_SECONDS:
                error_manager.record_error(ERROR_SENSOR_TIMEOUT)
                if not error_manager.should_suppress_error(ERROR_SENSOR_TIMEOUT):
                    logger.log_sensor_error(
                        sensor_entity=sensor_entity,
                        error_type=ERROR_SENSOR_TIMEOUT,
                        error_message=f"{sensor_type.title()} sensor data is stale ({age:.0f}s old)",
                        sensor_value=state.state,
                        recovery_action="Using fallback behavior"
                    )
                return None, False
        except (TypeError, AttributeError):
            # Handle cases where last_updated is not a proper datetime
            pass
    
    # Validate numeric value
    try:
        value = float(state.state)
    except (ValueError, TypeError) as err:
        error_manager.record_error(ERROR_SENSOR_INVALID_VALUE)
        if not error_manager.should_suppress_error(ERROR_SENSOR_INVALID_VALUE):
            logger.log_sensor_error(
                sensor_entity=sensor_entity,
                error_type=ERROR_SENSOR_INVALID_VALUE,
                error_message=f"{sensor_type.title()} sensor has invalid value: {err}",
                sensor_value=state.state,
                recovery_action="Using fallback behavior"
            )
        return None, False
        
    # Validate value range
    if sensor_type == "temperature":
        if not TEMP_MIN_VALID <= value <= TEMP_MAX_VALID:
            error_manager.record_error(ERROR_SENSOR_INVALID_VALUE)
            if not error_manager.should_suppress_error(ERROR_SENSOR_INVALID_VALUE):
                logger.log_sensor_error(
                    sensor_entity=sensor_entity,
                    error_type=ERROR_SENSOR_INVALID_VALUE,
                    error_message=f"Temperature {value}°F is outside valid range ({TEMP_MIN_VALID}°F to {TEMP_MAX_VALID}°F)",
                    sensor_value=value,
                    recovery_action="Using fallback behavior"
                )
            return None, False
    elif sensor_type == "humidity":
        if not HUMIDITY_MIN_VALID <= value <= HUMIDITY_MAX_VALID:
            error_manager.record_error(ERROR_SENSOR_INVALID_VALUE)
            if not error_manager.should_suppress_error(ERROR_SENSOR_INVALID_VALUE):
                logger.log_sensor_error(
                    sensor_entity=sensor_entity,
                    error_type=ERROR_SENSOR_INVALID_VALUE,
                    error_message=f"Humidity {value}% is outside valid range ({HUMIDITY_MIN_VALID}% to {HUMIDITY_MAX_VALID}%)",
                    sensor_value=value,
                    recovery_action="Using fallback behavior"
                )
            return None, False
            
    return value, True


async def safe_call_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_data: Dict[str, Any],
    logger: SmartThermostatLogger,
    error_manager: ErrorRecoveryManager,
    entity_id: Optional[str] = None,
    timeout: float = 10.0,
) -> bool:
    """Safely call a Home Assistant service with error handling.
    
    Args:
        hass: Home Assistant instance
        domain: Service domain
        service: Service name
        service_data: Service data
        logger: Logger instance
        error_manager: Error recovery manager
        entity_id: Entity ID for error reporting
        timeout: Service call timeout
        
    Returns:
        True if service call was successful, False otherwise
    """
    try:
        await asyncio.wait_for(
            hass.services.async_call(domain, service, service_data, blocking=True),
            timeout=timeout
        )
        return True
        
    except asyncio.TimeoutError:
        error_manager.record_error(ERROR_MINISPLIT_COMMAND_FAILED)
        logger.log_minisplit_error(
            minisplit_entity=entity_id or "unknown",
            error_type=ERROR_MINISPLIT_COMMAND_FAILED,
            error_message=f"Service call {domain}.{service} timed out after {timeout}s",
            attempted_action=f"{domain}.{service}",
            recovery_action="Will retry on next update cycle"
        )
        return False
        
    except Exception as err:
        error_manager.record_error(ERROR_MINISPLIT_COMMAND_FAILED)
        logger.log_minisplit_error(
            minisplit_entity=entity_id or "unknown",
            error_type=ERROR_MINISPLIT_COMMAND_FAILED,
            error_message=f"Service call {domain}.{service} failed: {err}",
            attempted_action=f"{domain}.{service}",
            recovery_action="Will retry on next update cycle"
        )
        return False


def with_error_handling(
    logger: SmartThermostatLogger,
    operation_name: str,
    error_manager: Optional[ErrorRecoveryManager] = None,
    suppress_exceptions: bool = True,
    default_return: Any = None,
):
    """Decorator for adding comprehensive error handling to methods.
    
    Args:
        logger: Logger instance
        operation_name: Name of the operation for logging
        error_manager: Error recovery manager (optional)
        suppress_exceptions: Whether to suppress exceptions and return default
        default_return: Default value to return on error
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Union[T, Any]]:
        async def async_wrapper(*args, **kwargs) -> Union[T, Any]:
            try:
                return await func(*args, **kwargs)
            except Exception as err:
                logger.log_exception(
                    operation=operation_name,
                    exception=err,
                    context={"args": str(args), "kwargs": str(kwargs)}
                )
                if error_manager:
                    error_manager.record_error("operation_failed")
                if suppress_exceptions:
                    return default_return
                raise
                
        def sync_wrapper(*args, **kwargs) -> Union[T, Any]:
            try:
                return func(*args, **kwargs)
            except Exception as err:
                logger.log_exception(
                    operation=operation_name,
                    exception=err,
                    context={"args": str(args), "kwargs": str(kwargs)}
                )
                if error_manager:
                    error_manager.record_error("operation_failed")
                if suppress_exceptions:
                    return default_return
                raise
                
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
            
    return decorator


def validate_config_value(
    value: Any,
    expected_type: type,
    min_value: Optional[Union[int, float]] = None,
    max_value: Optional[Union[int, float]] = None,
    allowed_values: Optional[list] = None,
) -> tuple[bool, Optional[str]]:
    """Validate a configuration value.
    
    Args:
        value: Value to validate
        expected_type: Expected type of the value
        min_value: Minimum allowed value (for numeric types)
        max_value: Maximum allowed value (for numeric types)
        allowed_values: List of allowed values
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check type
    if not isinstance(value, expected_type):
        return False, f"Expected {expected_type.__name__}, got {type(value).__name__}"
        
    # Check allowed values
    if allowed_values is not None and value not in allowed_values:
        return False, f"Value {value} not in allowed values: {allowed_values}"
        
    # Check numeric ranges
    if isinstance(value, (int, float)):
        if min_value is not None and value < min_value:
            return False, f"Value {value} is below minimum {min_value}"
        if max_value is not None and value > max_value:
            return False, f"Value {value} is above maximum {max_value}"
            
    return True, None