"""Control manager for the Smart Thermostat Controller integration."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import (
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
)
from .error_handling import ErrorRecoveryManager, with_error_handling
from .logging_utils import create_logger
from .models import (
    ControlAction,
    ControllerState,
    SensorReadings,
    SmartThermostatConfig,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ControlManager:
    """Manages control logic for the smart thermostat."""

    def __init__(self, hass: HomeAssistant, config: SmartThermosta            if old_switch_threshold != new_config.switch_threshold:
                self._log_config_change(
                    config_key="switch_threshold",
                    old_value=old_switch_threshold,
                    new_value=new_config.switch_threshold,ig) -> None:
        """Initialize the control manager."""
        self._hass = hass
        self._config = config
        self._last_mode_change: datetime | None = None
        self._current_mode = HVAC_MODE_OFF
        
        # Initialize logging and error handling
        self._logger = create_logger(hass, "control_manager")
        self._error_manager = ErrorRecoveryManager(hass, self._logger)
        
        self._logger.log_config_change(
            config_key="control_manager_initialized",
            old_value=None,
            new_value=f"cooldown_period: {config.cooldown_period}s",
            changed_by="system"
        )


    def calculate_required_action(
        self,
        sensor_readings: SensorReadings,
        controller_state: ControllerState,
    ) -> ControlAction:
        """
        Calculate the required control action based on sensor readings and state.
        
        Priority order:
        1. Heating if temperature is below target/away minimum - deadband
        2. Cooling if temperature is above target/away maximum + deadband
           - Use dry mode instead of cool if humidity > threshold
        3. Idle state if within acceptable ranges (maintains unit operation for comfort and longevity)
        
        Args:
            sensor_readings: Current sensor readings
            controller_state: Current controller state
            
        Returns:
            ControlAction with the recommended action
        """
        start_time = time.time()
        
        try:
            # Validate inputs
            if not self._validate_inputs(sensor_readings, controller_state):
                return ControlAction(
                    action_type=HVAC_MODE_OFF,
                    target_temperature=None,
                    reason="Invalid input data",
                    can_execute=False,
                )

            if not sensor_readings.is_valid:
                self._logger.log_graceful_degradation(
                    degradation_type="sensor_failure",
                    reason="Invalid or stale sensor readings",
                    affected_features=["automatic_control"],
                    fallback_behavior="System turned off until sensors recover"
                )
                return ControlAction(
                    action_type=HVAC_MODE_OFF,
                    target_temperature=None,
                    reason="Invalid or stale sensor readings",
                    can_execute=False,
                )

            # Check cooldown status
            cooldown_remaining = self._get_cooldown_remaining()
            can_execute = cooldown_remaining == 0

            # Determine effective temperature targets based on away mode
            heating_target, cooling_target = self._get_effective_temperature_targets(controller_state)

            # Priority 1: Heating if needed (with stickiness to prevent mode switching)
            if (
                sensor_readings.temperature_available
                and sensor_readings.temperature is not None
            ):
                # Calculate heating threshold with switch threshold
                # If currently in cooling mode, need extra switch threshold to switch to heating
                heating_threshold = heating_target - self._config.temperature_deadband
                if controller_state.current_mode in [HVAC_MODE_COOL, HVAC_MODE_DRY]:
                    heating_threshold -= self._config.switch_threshold
                
                temp_diff_heating = sensor_readings.temperature - heating_threshold
                
                if temp_diff_heating < 0:  # Temperature below heating threshold
                    # Apply learned offset to target temperature for minisplit
                    adjusted_target = self._apply_learned_offset(
                        heating_target,
                        controller_state.learned_offset,
                        HVAC_MODE_HEAT,
                    )
                    
                    reason_mode = "away" if controller_state.away_mode else "normal"
                    switch_note = f" (switch threshold: {self._config.switch_threshold:.1f}°F)" if controller_state.current_mode in [HVAC_MODE_COOL, HVAC_MODE_DRY] else ""
                    action = ControlAction(
                        action_type=HVAC_MODE_HEAT,
                        target_temperature=adjusted_target,
                        reason=f"Temperature {sensor_readings.temperature:.1f}°F < {reason_mode} heating threshold {heating_threshold:.1f}°F{switch_note}",
                        can_execute=can_execute,
                        cooldown_remaining=cooldown_remaining,
                    )
                    
                    self._logger.log_decision(
                        decision=action.action_type,
                        reasoning=f"Priority 1 - Heating needed ({reason_mode} mode): {action.reason}",
                        sensor_data={"temperature": sensor_readings.temperature, "temp_diff": temp_diff_heating},
                        controller_state={
                            "heating_target": heating_target,
                            "heating_threshold": heating_threshold,
                            "adjusted_target": adjusted_target,
                            "deadband": self._config.temperature_deadband,
                            "switch_threshold": self._config.switch_threshold,
                            "current_mode": controller_state.current_mode,
                            "away_mode": controller_state.away_mode
                        }
                    )
                    
                    return action

            # Priority 2: Cooling if needed (with dry mode for high humidity and stickiness)
            if (
                sensor_readings.temperature_available
                and sensor_readings.temperature is not None
            ):
                # Calculate cooling threshold with switch threshold
                # If currently in heating mode, need extra switch threshold to switch to cooling
                cooling_threshold = cooling_target + self._config.temperature_deadband
                if controller_state.current_mode == HVAC_MODE_HEAT:
                    cooling_threshold += self._config.switch_threshold
                
                temp_diff_cooling = sensor_readings.temperature - cooling_threshold
                
                if temp_diff_cooling > 0:  # Temperature above cooling threshold
                    # Check if humidity is high - use dry mode instead of cool
                    if (
                        sensor_readings.humidity_available
                        and sensor_readings.humidity is not None
                        and sensor_readings.humidity > self._config.humidity_max_threshold
                    ):
                        reason_mode = "away" if controller_state.away_mode else "normal"
                        switch_note = f" (switch threshold: {self._config.switch_threshold:.1f}°F)" if controller_state.current_mode == HVAC_MODE_HEAT else ""
                        action = ControlAction(
                            action_type=HVAC_MODE_DRY,
                            target_temperature=cooling_target,
                            reason=f"Temperature {sensor_readings.temperature:.1f}°F > {reason_mode} cooling threshold {cooling_threshold:.1f}°F AND humidity {sensor_readings.humidity:.1f}% > {self._config.humidity_max_threshold:.1f}%{switch_note}",
                            can_execute=can_execute,
                            cooldown_remaining=cooldown_remaining,
                        )
                        
                        self._logger.log_decision(
                            decision=action.action_type,
                            reasoning=f"Priority 2 - Cooling needed with high humidity ({reason_mode} mode), using dry mode: {action.reason}",
                            sensor_data={"temperature": sensor_readings.temperature, "humidity": sensor_readings.humidity, "temp_diff": temp_diff_cooling},
                            controller_state={
                                "cooling_target": cooling_target,
                                "cooling_threshold": cooling_threshold,
                                "humidity_threshold": self._config.humidity_max_threshold,
                                "deadband": self._config.temperature_deadband,
                                "switch_threshold": self._config.switch_threshold,
                                "current_mode": controller_state.current_mode,
                                "away_mode": controller_state.away_mode
                            }
                        )
                        
                        return action
                    else:
                        # Normal cooling - humidity is acceptable or not available
                        adjusted_target = self._apply_learned_offset(
                            cooling_target,
                            controller_state.learned_offset,
                            HVAC_MODE_COOL,
                        )
                        
                        reason_mode = "away" if controller_state.away_mode else "normal"
                        switch_note = f" (switch threshold: {self._config.switch_threshold:.1f}°F)" if controller_state.current_mode == HVAC_MODE_HEAT else ""
                        action = ControlAction(
                            action_type=HVAC_MODE_COOL,
                            target_temperature=adjusted_target,
                            reason=f"Temperature {sensor_readings.temperature:.1f}°F > {reason_mode} cooling threshold {cooling_threshold:.1f}°F{switch_note}",
                            can_execute=can_execute,
                            cooldown_remaining=cooldown_remaining,
                        )
                        
                        self._logger.log_decision(
                            decision=action.action_type,
                            reasoning=f"Priority 2 - Cooling needed ({reason_mode} mode): {action.reason}",
                            sensor_data={"temperature": sensor_readings.temperature, "temp_diff": temp_diff_cooling},
                            controller_state={
                                "cooling_target": cooling_target,
                                "cooling_threshold": cooling_threshold,
                                "adjusted_target": adjusted_target,
                                "deadband": self._config.temperature_deadband,
                                "switch_threshold": self._config.switch_threshold,
                                "current_mode": controller_state.current_mode,
                                "away_mode": controller_state.away_mode
                            }
                        )
                        
                        return action

            # Priority 3: Idle state if within acceptable ranges
            # Instead of turning off, maintain operation at offset temperature for comfort and longevity
            if (
                sensor_readings.temperature_available
                and sensor_readings.temperature is not None
            ):
                # Determine which idle mode based on current conditions and recent history
                # Use the midpoint between heating and cooling targets for idle decisions
                heating_target, cooling_target = self._get_effective_temperature_targets(controller_state)
                effective_target = (heating_target + cooling_target) / 2
                
                idle_mode, idle_target = self._calculate_idle_state(
                    sensor_readings.temperature,
                    effective_target,
                    controller_state.learned_offset,
                    controller_state.current_mode,
                    sensor_readings,
                )
                
                reason_mode = "away" if controller_state.away_mode else "normal"
                action = ControlAction(
                    action_type=idle_mode,
                    target_temperature=idle_target,
                    reason=f"Temperature within deadband - entering idle {idle_mode} mode at {idle_target:.1f}°F ({reason_mode} mode)",
                    can_execute=can_execute,
                    cooldown_remaining=cooldown_remaining,
                )
                
                self._logger.log_decision(
                    decision=action.action_type,
                    reasoning=f"Priority 3 - Idle state ({reason_mode} mode): {action.reason}",
                    sensor_data={
                        "temperature": sensor_readings.temperature,
                        "current_mode": controller_state.current_mode
                    },
                    controller_state={
                        "effective_target": effective_target,
                        "heating_target": heating_target,
                        "cooling_target": cooling_target,
                        "idle_target": idle_target,
                        "idle_offset": self._config.idle_temperature_offset,
                        "away_mode": controller_state.away_mode
                    }
                )
            else:
                # Fallback to off if no temperature sensor available
                action = ControlAction(
                    action_type=HVAC_MODE_OFF,
                    target_temperature=None,
                    reason="No temperature sensor available - turning off for safety",
                    can_execute=can_execute,
                    cooldown_remaining=cooldown_remaining,
                )
                
                self._logger.log_decision(
                    decision=action.action_type,
                    reasoning=f"Priority 3 - Safety fallback: {action.reason}",
                    sensor_data={"temperature_available": False},
                    controller_state={"away_mode": controller_state.away_mode}
                )
            
            # Log performance if slow
            duration_ms = (time.time() - start_time) * 1000
            if duration_ms > 100:  # Warn if takes more than 100ms
                self._logger.log_performance_warning(
                    operation="calculate_required_action",
                    duration_ms=duration_ms,
                    threshold_ms=100,
                    context={"action": action.action_type}
                )
            
            return action
            
        except Exception as err:
            self._logger.log_exception(
                operation="calculate_required_action",
                exception=err,
                context={
                    "sensor_readings": {
                        "temp": sensor_readings.temperature,
                        "humidity": sensor_readings.humidity,
                        "temp_available": sensor_readings.temperature_available,
                        "humidity_available": sensor_readings.humidity_available
                    },
                    "controller_state": {
                        "target_temp": controller_state.target_temperature,
                        "current_mode": controller_state.current_mode
                    }
                },
                recovery_action="Returning safe OFF action"
            )
            
            return ControlAction(
                action_type=HVAC_MODE_OFF,
                target_temperature=None,
                reason=f"Error in control calculation: {err}",
                can_execute=False,
            )

    def _apply_learned_offset(
        self,
        target_temperature: float,
        learned_offset: float,
        intended_mode: str,
    ) -> float:
        """
        Apply learned offset to compensate for minisplit thermostat inaccuracy.
        
        Args:
            target_temperature: The desired room temperature
            learned_offset: The learned offset from historical data
            intended_mode: The intended HVAC mode (heat/cool)
            
        Returns:
            Adjusted target temperature to send to minisplit
        """
        # Only apply offset for cooling mode (where we know the minisplit reads hot)
        if intended_mode == HVAC_MODE_COOL:
            # If minisplit reads 5°F hotter than actual, we need to set it 5°F lower
            adjusted_target = target_temperature - learned_offset
            _LOGGER.debug(
                "Applying cooling offset: target %.1f°F - offset %.1f°F = adjusted %.1f°F",
                target_temperature,
                learned_offset,
                adjusted_target,
            )
            return adjusted_target
        
        # For heating mode, use target temperature as-is (assuming heating is accurate)
        return target_temperature

    def _calculate_idle_state(
        self,
        current_temperature: float,
        target_temperature: float,
        learned_offset: float,
        current_mode: str,
        sensor_readings: SensorReadings | None = None,
    ) -> tuple[str, float]:
        """
        Calculate the appropriate idle state mode and temperature.
        
        The idle state keeps the unit running at a minimal level to:
        - Maintain air circulation for comfort
        - Reduce startup stress on equipment
        - Provide faster response when conditions change
        - Minimize mode switching by preferring current mode when appropriate
        
        Args:
            current_temperature: Current room temperature
            target_temperature: Desired target temperature
            learned_offset: Learned offset for cooling mode
            current_mode: Current operating mode
            sensor_readings: Current sensor readings for humidity check
            
        Returns:
            Tuple of (idle_mode, idle_target_temperature)
        """
        # Priority 1: Stay in current mode when entering idle to reduce switching
        # Only switch if the current mode doesn't make sense for conditions
        
        if current_mode in [HVAC_MODE_COOL, HVAC_MODE_DRY]:
            # Already in cooling-related mode - prefer to stay
            if current_temperature >= target_temperature - 1.0:  # Within reasonable range for cooling
                # Check if we should prefer dry mode for high humidity
                if (current_mode == HVAC_MODE_COOL 
                    and sensor_readings 
                    and sensor_readings.humidity_available 
                    and sensor_readings.humidity is not None
                    and sensor_readings.humidity > self._config.humidity_max_threshold):
                    # Switch to dry mode for high humidity
                    idle_mode = HVAC_MODE_DRY
                    idle_target = target_temperature
                    _LOGGER.debug(
                        "Idle dry mode: staying in dehumidification due to high humidity %.1f%% > %.1f%%",
                        sensor_readings.humidity,
                        self._config.humidity_max_threshold,
                    )
                else:
                    # Stay in current cooling-related mode
                    idle_mode = current_mode
                    if current_mode == HVAC_MODE_DRY:
                        idle_target = target_temperature
                    else:
                        idle_target = target_temperature - learned_offset + self._config.idle_temperature_offset
                    _LOGGER.debug(
                        "Idle %s: staying in current mode, target %.1f°F",
                        idle_mode,
                        idle_target,
                    )
                return idle_mode, idle_target
                
        elif current_mode == HVAC_MODE_HEAT:
            # Already in heating mode - prefer to stay if reasonable
            if current_temperature <= target_temperature + 1.0:  # Within reasonable range for heating
                idle_target = target_temperature - self._config.idle_temperature_offset
                idle_mode = HVAC_MODE_HEAT
                _LOGGER.debug(
                    "Idle heating: staying in current mode, target %.1f°F - idle_offset %.1f°F = %.1f°F",
                    target_temperature,
                    self._config.idle_temperature_offset,
                    idle_target,
                )
                return idle_mode, idle_target
        
        # Priority 2: If current mode doesn't make sense, choose based on temperature
        # This is fallback logic when we need to switch modes
        
        if current_temperature >= target_temperature:
            # Temperature is at or above target - use cooling idle
            # Check if humidity is high - prefer dry mode
            if (sensor_readings 
                and sensor_readings.humidity_available 
                and sensor_readings.humidity is not None
                and sensor_readings.humidity > self._config.humidity_max_threshold):
                idle_mode = HVAC_MODE_DRY
                idle_target = target_temperature
                _LOGGER.debug(
                    "Idle dry: high humidity %.1f%% > %.1f%%, target %.1f°F",
                    sensor_readings.humidity,
                    self._config.humidity_max_threshold,
                    idle_target,
                )
            else:
                idle_mode = HVAC_MODE_COOL
                idle_target = target_temperature - learned_offset + self._config.idle_temperature_offset
                _LOGGER.debug(
                    "Idle cooling: target %.1f°F - offset %.1f°F + idle_offset %.1f°F = %.1f°F",
                    target_temperature,
                    learned_offset,
                    self._config.idle_temperature_offset,
                    idle_target,
                )
        else:
            # Temperature is below target - use heating idle
            idle_target = target_temperature - self._config.idle_temperature_offset
            idle_mode = HVAC_MODE_HEAT
            _LOGGER.debug(
                "Idle heating: target %.1f°F - idle_offset %.1f°F = %.1f°F",
                target_temperature,
                self._config.idle_temperature_offset,
                idle_target,
            )
        
        return idle_mode, idle_target

    def _should_suppress_mode_change(
        self,
        current_mode: str,
        proposed_mode: str,
        current_temperature: float,
        target_temperature: float,
        humidity: float | None = None,
    ) -> bool:
        """
        Determine if a mode change should be suppressed to reduce unnecessary switching.
        
        Args:
            current_mode: Current HVAC mode
            proposed_mode: Proposed new HVAC mode  
            current_temperature: Current room temperature
            target_temperature: Target temperature
            humidity: Current humidity (if available)
            
        Returns:
            True if mode change should be suppressed, False otherwise
        """
        # Don't suppress if modes are the same
        if current_mode == proposed_mode:
            return False
            
        # Don't suppress if current mode is off
        if current_mode == HVAC_MODE_OFF:
            return False
            
        # Check if the current mode is still reasonable for conditions
        temp_diff = abs(current_temperature - target_temperature)
        
        # If temperature is very close to target (within 0.5°F), prefer to stay in current mode
        if temp_diff <= 0.5:
            _LOGGER.debug(
                "Suppressing mode change from %s to %s: temperature %.1f°F is close to target %.1f°F",
                current_mode,
                proposed_mode,
                current_temperature,
                target_temperature
            )
            return True
            
        # Special case: if in dry mode and humidity is still high, stay in dry mode
        if (current_mode == HVAC_MODE_DRY 
            and humidity is not None 
            and humidity > self._config.humidity_max_threshold - 5.0):  # 5% buffer
            _LOGGER.debug(
                "Suppressing mode change from dry to %s: humidity %.1f%% still elevated",
                proposed_mode,
                humidity
            )
            return True
            
        return False

    def _get_effective_temperature_targets(
        self,
        controller_state: ControllerState,
    ) -> tuple[float, float]:
        """
        Get the effective heating and cooling targets based on away mode.
        
        Args:
            controller_state: Current controller state
            
        Returns:
            Tuple of (heating_target, cooling_target)
        """
        if controller_state.away_mode and self._config.away_mode_enabled:
            # Use away mode temperature bounds
            heating_target = self._config.away_min_temperature
            cooling_target = self._config.away_max_temperature
            
            _LOGGER.debug(
                "Using away mode targets: heating %.1f°F, cooling %.1f°F",
                heating_target,
                cooling_target,
            )
        else:
            # Use normal target temperature for both heating and cooling
            heating_target = controller_state.target_temperature
            cooling_target = controller_state.target_temperature
            
            _LOGGER.debug(
                "Using normal targets: heating %.1f°F, cooling %.1f°F",
                heating_target,
                cooling_target,
            )
        
        return heating_target, cooling_target

    def can_change_mode(self, new_mode: str) -> bool:
        """
        Check if a mode change is allowed based on cooldown period.
        
        Args:
            new_mode: The requested new mode
            
        Returns:
            True if mode change is allowed, False if in cooldown
        """
        if new_mode == self._current_mode:
            return True
            
        return self._get_cooldown_remaining() == 0

    def record_mode_change(self, new_mode: str) -> None:
        """
        Record a mode change for cooldown tracking.
        
        Args:
            new_mode: The new mode that was activated
        """
        try:
            if new_mode != self._current_mode:
                old_mode = self._current_mode
                self._last_mode_change = dt_util.utcnow()
                self._current_mode = new_mode
                
                self._logger.log_config_change(
                    config_key="current_mode",
                    old_value=old_mode,
                    new_value=new_mode,
                    changed_by="control_manager"
                )
                
                self._logger.log_decision(
                    decision="mode_change_recorded",
                    reasoning=f"Mode changed from {old_mode} to {new_mode}, cooldown period started",
                    controller_state={
                        "old_mode": old_mode,
                        "new_mode": new_mode,
                        "cooldown_period": self._config.cooldown_period
                    }
                )
        except Exception as err:
            self._logger.log_exception(
                operation="record_mode_change",
                exception=err,
                context={"new_mode": new_mode, "current_mode": self._current_mode},
                recovery_action="Mode change recording failed, cooldown tracking may be inaccurate"
            )

    def get_remaining_cooldown(self) -> int:
        """
        Get the remaining cooldown time in seconds.
        
        Returns:
            Remaining cooldown time in seconds, 0 if no cooldown active
        """
        return self._get_cooldown_remaining()

    def _get_cooldown_remaining(self) -> int:
        """Calculate remaining cooldown time in seconds."""
        if self._last_mode_change is None:
            return 0
            
        now = dt_util.utcnow()
        elapsed = (now - self._last_mode_change).total_seconds()
        remaining = max(0, self._config.cooldown_period - elapsed)
        
        return int(remaining)

    def validate_sensor_readings(self, sensor_readings: SensorReadings) -> bool:
        """
        Validate that sensor readings are within acceptable ranges.
        
        Args:
            sensor_readings: Sensor readings to validate
            
        Returns:
            True if readings are valid, False otherwise
        """
        if not sensor_readings.is_valid:
            return False
            
        # Validate temperature range
        if (
            sensor_readings.temperature_available
            and sensor_readings.temperature is not None
        ):
            if not -50 <= sensor_readings.temperature <= 120:
                _LOGGER.warning(
                    "Temperature reading %.1f°F is out of valid range (-50°F to 120°F)",
                    sensor_readings.temperature,
                )
                return False
                
        # Validate humidity range
        if (
            sensor_readings.humidity_available
            and sensor_readings.humidity is not None
        ):
            if not 0 <= sensor_readings.humidity <= 100:
                _LOGGER.warning(
                    "Humidity reading %.1f%% is out of valid range (0%% to 100%%)",
                    sensor_readings.humidity,
                )
                return False
                
        return True

    def get_decision_reasoning(
        self,
        sensor_readings: SensorReadings,
        controller_state: ControllerState,
        action: ControlAction,
    ) -> str:
        """
        Generate detailed reasoning for a control decision.
        
        Args:
            sensor_readings: Current sensor readings
            controller_state: Current controller state
            action: The recommended action
            
        Returns:
            Detailed reasoning string for logging and diagnostics
        """
        reasoning_parts = [
            f"Decision: {action.action_type}",
            f"Reason: {action.reason}",
        ]
        
        if sensor_readings.temperature is not None:
            reasoning_parts.append(
                f"Temperature: {sensor_readings.temperature:.1f}°F (target: {controller_state.target_temperature:.1f}°F, deadband: ±{self._config.temperature_deadband:.1f}°F)"
            )
            
        if sensor_readings.humidity is not None:
            reasoning_parts.append(
                f"Humidity: {sensor_readings.humidity:.1f}% (max threshold: {self._config.humidity_max_threshold:.1f}%)"
            )
            
        if controller_state.learned_offset != 0:
            reasoning_parts.append(
                f"Learned offset: {controller_state.learned_offset:.1f}°F (confidence: {controller_state.offset_confidence:.1%})"
            )
            
        if action.cooldown_remaining > 0:
            reasoning_parts.append(
                f"Cooldown: {action.cooldown_remaining}s remaining"
            )
            
        return " | ".join(reasoning_parts)

    def _validate_inputs(
        self,
        sensor_readings: SensorReadings,
        controller_state: ControllerState,
    ) -> bool:
        """
        Validate input parameters for control calculations.
        
        Args:
            sensor_readings: Sensor readings to validate
            controller_state: Controller state to validate
            
        Returns:
            True if inputs are valid, False otherwise
        """
        try:
            # Validate sensor readings
            if sensor_readings is None:
                self._logger.log_sensor_error(
                    sensor_entity="unknown",
                    error_type="invalid_input",
                    error_message="Sensor readings is None",
                    recovery_action="Using safe defaults"
                )
                return False
                
            # Validate controller state
            if controller_state is None:
                self._logger.log_exception(
                    operation="validate_inputs",
                    exception=ValueError("Controller state is None"),
                    recovery_action="Using safe defaults"
                )
                return False
                
            # Validate target temperature
            if (controller_state.target_temperature is None or 
                not 50 <= controller_state.target_temperature <= 90):
                self._logger.log_exception(
                    operation="validate_inputs",
                    exception=ValueError(f"Invalid target temperature: {controller_state.target_temperature}"),
                    context={"target_temperature": controller_state.target_temperature},
                    recovery_action="Using safe defaults"
                )
                return False
                
            return True
            
        except Exception as err:
            self._logger.log_exception(
                operation="validate_inputs",
                exception=err,
                recovery_action="Input validation failed, using safe defaults"
            )
            return False

    def update_config(self, new_config: SmartThermostatConfig) -> None:
        """
        Update control manager configuration.
        
        Args:
            new_config: New configuration to apply
        """
        try:
            old_cooldown = self._config.cooldown_period
            old_deadband = self._config.temperature_deadband
            old_humidity_max = self._config.humidity_max_threshold
            old_idle_offset = self._config.idle_temperature_offset
            old_switch_threshold = self._config.switch_threshold
            
            self._config = new_config
            
            # Log configuration changes
            if old_cooldown != new_config.cooldown_period:
                self._logger.log_config_change(
                    config_key="cooldown_period",
                    old_value=old_cooldown,
                    new_value=new_config.cooldown_period,
                    changed_by="config_update"
                )
                
            if old_deadband != new_config.temperature_deadband:
                self._logger.log_config_change(
                    config_key="temperature_deadband",
                    old_value=old_deadband,
                    new_value=new_config.temperature_deadband,
                    changed_by="config_update"
                )
                
            if old_humidity_max != new_config.humidity_max_threshold:
                self._logger.log_config_change(
                    config_key="humidity_max_threshold",
                    old_value=old_humidity_max,
                    new_value=new_config.humidity_max_threshold,
                    changed_by="config_update"
                )
                
            if old_idle_offset != new_config.idle_temperature_offset:
                self._logger.log_config_change(
                    config_key="idle_temperature_offset",
                    old_value=old_idle_offset,
                    new_value=new_config.idle_temperature_offset,
                    changed_by="config_update"
                )
                
            if old_switch_threshold != new_config.switch_threshold:
                self._logger.log_config_change(
                    config_key="switch_threshold",
                    old_value=old_switch_threshold,
                    new_value=new_config.switch_threshold,
                    changed_by="config_update"
                )
                
        except Exception as err:
            self._logger.log_exception(
                operation="update_config",
                exception=err,
                context={"new_config": str(new_config)},
                recovery_action="Configuration update failed, using previous config"
            )

    def get_status_info(self) -> dict[str, any]:
        """
        Get current control manager status information.
        
        Returns:
            Dictionary with status information
        """
        try:
            return {
                "current_mode": self._current_mode,
                "last_mode_change": self._last_mode_change.isoformat() if self._last_mode_change else None,
                "cooldown_remaining": self._get_cooldown_remaining(),
                "cooldown_period": self._config.cooldown_period,
                "temperature_deadband": self._config.temperature_deadband,
                "humidity_max_threshold": self._config.humidity_max_threshold,
                "idle_temperature_offset": self._config.idle_temperature_offset,
                "switch_threshold": self._config.switch_threshold,
                "error_summary": self._error_manager.get_error_summary() if hasattr(self, '_error_manager') else {},
            }
        except Exception as err:
            self._logger.log_exception(
                operation="get_status_info",
                exception=err,
                recovery_action="Returning minimal status info"
            )
            return {
                "current_mode": self._current_mode,
                "error": str(err)
            }
