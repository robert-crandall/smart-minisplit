"""Logging utilities for Smart Thermostat Controller."""
from __future__ import annotations

import logging
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ERROR_CONFIG_INVALID,
    ERROR_DATA_CORRUPTION,
    ERROR_MINISPLIT_COMMAND_FAILED,
    ERROR_MINISPLIT_UNAVAILABLE,
    ERROR_SENSOR_INVALID_VALUE,
    ERROR_SENSOR_TIMEOUT,
    ERROR_SENSOR_UNAVAILABLE,
)

_LOGGER = logging.getLogger(__name__)


class SmartThermostatLogger:
    """Enhanced logging utility for Smart Thermostat Controller."""

    def __init__(self, hass: HomeAssistant, component_name: str) -> None:
        """Initialize the logger.
        
        Args:
            hass: Home Assistant instance
            component_name: Name of the component using this logger
        """
        self._hass = hass
        self._component_name = component_name
        self._logger = logging.getLogger(f"{__name__}.{component_name}")
        self._error_counts: Dict[str, int] = {}
        self._last_errors: Dict[str, datetime] = {}

    def log_decision(
        self,
        decision: str,
        reasoning: str,
        sensor_data: Optional[Dict[str, Any]] = None,
        controller_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a control decision with detailed reasoning.
        
        Args:
            decision: The decision made (e.g., "cool", "heat", "off")
            reasoning: Detailed reasoning for the decision
            sensor_data: Current sensor readings
            controller_state: Current controller state
        """
        log_data = {
            "component": self._component_name,
            "decision": decision,
            "reasoning": reasoning,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        if sensor_data:
            log_data["sensor_data"] = sensor_data
            
        if controller_state:
            log_data["controller_state"] = controller_state
            
        self._logger.info(
            "Control Decision: %s | Reason: %s",
            decision,
            reasoning,
            extra={"decision_data": log_data}
        )

    def log_sensor_error(
        self,
        sensor_entity: str,
        error_type: str,
        error_message: str,
        sensor_value: Optional[Any] = None,
        recovery_action: Optional[str] = None,
    ) -> None:
        """Log sensor-related errors with recovery information.
        
        Args:
            sensor_entity: Entity ID of the problematic sensor
            error_type: Type of error (from ERROR_* constants)
            error_message: Detailed error message
            sensor_value: The problematic sensor value (if any)
            recovery_action: Action taken to recover from the error
        """
        self._increment_error_count(error_type)
        
        error_data = {
            "component": self._component_name,
            "sensor_entity": sensor_entity,
            "error_type": error_type,
            "error_message": error_message,
            "sensor_value": sensor_value,
            "recovery_action": recovery_action,
            "error_count": self._error_counts[error_type],
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        self._logger.error(
            "Sensor Error [%s]: %s (entity: %s, value: %s) - Recovery: %s",
            error_type,
            error_message,
            sensor_entity,
            sensor_value,
            recovery_action or "None",
            extra={"sensor_error_data": error_data}
        )

    def log_minisplit_error(
        self,
        minisplit_entity: str,
        error_type: str,
        error_message: str,
        attempted_action: Optional[str] = None,
        recovery_action: Optional[str] = None,
    ) -> None:
        """Log minisplit-related errors.
        
        Args:
            minisplit_entity: Entity ID of the minisplit
            error_type: Type of error (from ERROR_* constants)
            error_message: Detailed error message
            attempted_action: The action that failed
            recovery_action: Action taken to recover from the error
        """
        self._increment_error_count(error_type)
        
        error_data = {
            "component": self._component_name,
            "minisplit_entity": minisplit_entity,
            "error_type": error_type,
            "error_message": error_message,
            "attempted_action": attempted_action,
            "recovery_action": recovery_action,
            "error_count": self._error_counts[error_type],
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        self._logger.error(
            "Minisplit Error [%s]: %s (entity: %s, action: %s) - Recovery: %s",
            error_type,
            error_message,
            minisplit_entity,
            attempted_action,
            recovery_action or "None",
            extra={"minisplit_error_data": error_data}
        )

    def log_config_change(
        self,
        config_key: str,
        old_value: Any,
        new_value: Any,
        changed_by: Optional[str] = None,
    ) -> None:
        """Log configuration changes for audit purposes.
        
        Args:
            config_key: The configuration key that changed
            old_value: Previous value
            new_value: New value
            changed_by: Who/what initiated the change
        """
        audit_data = {
            "component": self._component_name,
            "config_key": config_key,
            "old_value": old_value,
            "new_value": new_value,
            "changed_by": changed_by or "system",
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        self._logger.info(
            "Config Change: %s changed from %s to %s (by: %s)",
            config_key,
            old_value,
            new_value,
            changed_by or "system",
            extra={"config_audit_data": audit_data}
        )

    def log_manual_override(
        self,
        override_enabled: bool,
        triggered_by: Optional[str] = None,
        previous_mode: Optional[str] = None,
        new_mode: Optional[str] = None,
    ) -> None:
        """Log manual override events for audit purposes.
        
        Args:
            override_enabled: Whether override was enabled or disabled
            triggered_by: Who/what triggered the override
            previous_mode: Mode before override
            new_mode: Mode after override
        """
        audit_data = {
            "component": self._component_name,
            "override_enabled": override_enabled,
            "triggered_by": triggered_by or "user",
            "previous_mode": previous_mode,
            "new_mode": new_mode,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        action = "enabled" if override_enabled else "disabled"
        self._logger.info(
            "Manual Override %s (by: %s) - Mode: %s -> %s",
            action,
            triggered_by or "user",
            previous_mode or "unknown",
            new_mode or "unknown",
            extra={"override_audit_data": audit_data}
        )

    def log_graceful_degradation(
        self,
        degradation_type: str,
        reason: str,
        affected_features: list[str],
        fallback_behavior: str,
    ) -> None:
        """Log graceful degradation events.
        
        Args:
            degradation_type: Type of degradation (e.g., "sensor_failure")
            reason: Reason for degradation
            affected_features: List of features that are affected
            fallback_behavior: Description of fallback behavior
        """
        degradation_data = {
            "component": self._component_name,
            "degradation_type": degradation_type,
            "reason": reason,
            "affected_features": affected_features,
            "fallback_behavior": fallback_behavior,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        self._logger.warning(
            "Graceful Degradation [%s]: %s - Affected: %s - Fallback: %s",
            degradation_type,
            reason,
            ", ".join(affected_features),
            fallback_behavior,
            extra={"degradation_data": degradation_data}
        )

    def log_recovery(
        self,
        recovery_type: str,
        recovered_from: str,
        restored_features: list[str],
    ) -> None:
        """Log recovery from errors or degraded states.
        
        Args:
            recovery_type: Type of recovery (e.g., "sensor_restored")
            recovered_from: What we recovered from
            restored_features: List of features that were restored
        """
        recovery_data = {
            "component": self._component_name,
            "recovery_type": recovery_type,
            "recovered_from": recovered_from,
            "restored_features": restored_features,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        self._logger.info(
            "Recovery [%s]: Recovered from %s - Restored: %s",
            recovery_type,
            recovered_from,
            ", ".join(restored_features),
            extra={"recovery_data": recovery_data}
        )

    def log_exception(
        self,
        operation: str,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None,
        recovery_action: Optional[str] = None,
    ) -> None:
        """Log exceptions with full context and stack trace.
        
        Args:
            operation: The operation that failed
            exception: The exception that occurred
            context: Additional context information
            recovery_action: Action taken to recover
        """
        exception_data = {
            "component": self._component_name,
            "operation": operation,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "context": context or {},
            "recovery_action": recovery_action,
            "stack_trace": traceback.format_exc(),
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        self._logger.error(
            "Exception in %s: %s (%s) - Recovery: %s",
            operation,
            str(exception),
            type(exception).__name__,
            recovery_action or "None",
            extra={"exception_data": exception_data}
        )

    def log_performance_warning(
        self,
        operation: str,
        duration_ms: float,
        threshold_ms: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log performance warnings for slow operations.
        
        Args:
            operation: The operation that was slow
            duration_ms: How long it took in milliseconds
            threshold_ms: The threshold that was exceeded
            context: Additional context information
        """
        perf_data = {
            "component": self._component_name,
            "operation": operation,
            "duration_ms": duration_ms,
            "threshold_ms": threshold_ms,
            "context": context or {},
            "timestamp": dt_util.utcnow().isoformat(),
        }
        
        self._logger.warning(
            "Performance Warning: %s took %.1fms (threshold: %.1fms)",
            operation,
            duration_ms,
            threshold_ms,
            extra={"performance_data": perf_data}
        )

    def get_error_summary(self) -> Dict[str, Any]:
        """Get a summary of errors that have occurred.
        
        Returns:
            Dictionary with error counts and last occurrence times
        """
        return {
            "error_counts": self._error_counts.copy(),
            "last_errors": {
                error_type: timestamp.isoformat()
                for error_type, timestamp in self._last_errors.items()
            },
            "component": self._component_name,
        }

    def reset_error_counts(self) -> None:
        """Reset error counters."""
        self._error_counts.clear()
        self._last_errors.clear()
        self._logger.info("Error counters reset for component: %s", self._component_name)

    def _increment_error_count(self, error_type: str) -> None:
        """Increment error count for a specific error type."""
        self._error_counts[error_type] = self._error_counts.get(error_type, 0) + 1
        self._last_errors[error_type] = dt_util.utcnow()


def create_logger(hass: HomeAssistant, component_name: str) -> SmartThermostatLogger:
    """Create a SmartThermostatLogger instance.
    
    Args:
        hass: Home Assistant instance
        component_name: Name of the component
        
    Returns:
        Configured logger instance
    """
    return SmartThermostatLogger(hass, component_name)


def log_startup(hass: HomeAssistant, version: str, config_summary: Dict[str, Any]) -> None:
    """Log integration startup information.
    
    Args:
        hass: Home Assistant instance
        version: Integration version
        config_summary: Summary of configuration
    """
    logger = logging.getLogger(f"{__name__}.startup")
    
    startup_data = {
        "integration": DOMAIN,
        "version": version,
        "config_summary": config_summary,
        "timestamp": dt_util.utcnow().isoformat(),
    }
    
    logger.info(
        "Smart Thermostat Controller v%s starting up with config: %s",
        version,
        config_summary,
        extra={"startup_data": startup_data}
    )


def log_shutdown(hass: HomeAssistant, reason: str) -> None:
    """Log integration shutdown information.
    
    Args:
        hass: Home Assistant instance
        reason: Reason for shutdown
    """
    logger = logging.getLogger(f"{__name__}.shutdown")
    
    shutdown_data = {
        "integration": DOMAIN,
        "reason": reason,
        "timestamp": dt_util.utcnow().isoformat(),
    }
    
    logger.info(
        "Smart Thermostat Controller shutting down: %s",
        reason,
        extra={"shutdown_data": shutdown_data}
    )