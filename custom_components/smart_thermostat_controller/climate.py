"""Climate platform for Smart Thermostat Controller."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ERROR_MINISPLIT_COMMAND_FAILED,
    ERROR_SENSOR_UNAVAILABLE,
    HVAC_MODE_AUTO,
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
)
from .control_manager import ControlManager
from .coordinator import SmartThermostatCoordinator
from .error_handling import ErrorRecoveryManager, safe_call_service, validate_sensor_value
from .logging_utils import create_logger
from .models import ControllerState, SensorReadings

_LOGGER = logging.getLogger(__name__)

# Map our internal modes to Home Assistant HVAC modes
HVAC_MODE_MAP = {
    HVAC_MODE_OFF: HVACMode.OFF,
    HVAC_MODE_HEAT: HVACMode.HEAT,
    HVAC_MODE_COOL: HVACMode.COOL,
    HVAC_MODE_DRY: HVACMode.DRY,
    HVAC_MODE_AUTO: HVACMode.AUTO,
}

# Reverse mapping for setting modes
REVERSE_HVAC_MODE_MAP = {v: k for k, v in HVAC_MODE_MAP.items()}

# Map our internal modes to HVAC actions
HVAC_ACTION_MAP = {
    HVAC_MODE_OFF: HVACAction.OFF,
    HVAC_MODE_HEAT: HVACAction.HEATING,
    HVAC_MODE_COOL: HVACAction.COOLING,
    HVAC_MODE_DRY: HVACAction.DRYING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Thermostat Controller climate platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Create the smart thermostat climate entity
    climate_entity = SmartThermostatClimate(coordinator, entry)
    
    async_add_entities([climate_entity], True)


class SmartThermostatClimate(CoordinatorEntity[SmartThermostatCoordinator], ClimateEntity):
    """Smart Thermostat Controller climate entity."""

    def __init__(
        self,
        coordinator: SmartThermostatCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the smart thermostat climate entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._control_manager = ControlManager(coordinator.hass, coordinator.config)
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._attr_name = "Smart Thermostat Controller"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Smart Thermostat Controller",
            "manufacturer": "Smart Thermostat Controller",
            "model": "Smart Climate Control",
            "sw_version": "1.0.0",
        }
        
        # Set supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        
        # Set supported HVAC modes
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.AUTO,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.DRY,
        ]
        
        # Temperature settings
        self._attr_temperature_unit = "°F"
        self._attr_min_temp = 50.0
        self._attr_max_temp = 90.0
        self._attr_target_temperature_step = 1.0
        
        # Initialize state
        self._manual_override = False
        self._last_auto_action: str | None = None
        
        # Initialize logging and error handling
        self._logger = create_logger(coordinator.hass, "climate")
        self._error_manager = ErrorRecoveryManager(coordinator.hass, self._logger)
        
        # Register recovery callbacks
        self._error_manager.register_recovery_callback(
            ERROR_SENSOR_UNAVAILABLE, 
            self._attempt_sensor_recovery
        )
        self._error_manager.register_recovery_callback(
            ERROR_MINISPLIT_COMMAND_FAILED,
            self._attempt_minisplit_recovery
        )
        
        self._logger.log_config_change(
            config_key="climate_entity_initialized",
            old_value=None,
            new_value=f"entity_id: {self._attr_unique_id}",
            changed_by="system"
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature from external sensor."""
        if self.coordinator.data:
            return self.coordinator.data.current_temperature
        return None

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity from external sensor."""
        if self.coordinator.data and self.coordinator.data.current_humidity is not None:
            return int(self.coordinator.data.current_humidity)
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.coordinator.data:
            return self.coordinator.data.target_temperature
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        if not self.coordinator.data:
            return HVACMode.OFF
            
        if self._manual_override:
            # In manual override, return the actual minisplit mode
            current_mode = self.coordinator.data.current_mode
            return HVAC_MODE_MAP.get(current_mode, HVACMode.OFF)
        else:
            # In auto mode, always show AUTO unless system is off
            if self.coordinator.data.current_mode == HVAC_MODE_OFF:
                return HVACMode.OFF
            return HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action."""
        if not self.coordinator.data:
            return HVACAction.OFF
            
        current_mode = self.coordinator.data.current_mode
        return HVAC_ACTION_MAP.get(current_mode, HVACAction.OFF)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.coordinator.data.is_available
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}
            
        attributes = {
            "learned_offset": self.coordinator.data.learned_offset,
            "offset_confidence": f"{self.coordinator.data.offset_confidence:.1%}",
            "manual_override": self.coordinator.data.manual_override,
            "cooldown_remaining": self.coordinator.data.cooldown_remaining,
            "away_mode": self.coordinator.data.away_mode,
        }
        
        if self.coordinator.data.last_mode_change:
            attributes["last_mode_change"] = self.coordinator.data.last_mode_change.isoformat()
            
        return attributes

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        start_time = time.time()
        temperature = kwargs.get("temperature")
        
        try:
            if temperature is None:
                self._logger.log_exception(
                    operation="set_temperature",
                    exception=ValueError("No temperature provided"),
                    context={"kwargs": kwargs}
                )
                return
                
            if not self.min_temp <= temperature <= self.max_temp:
                error_msg = (
                    f"Temperature {temperature} is outside valid range "
                    f"({self.min_temp}-{self.max_temp})"
                )
                self._logger.log_exception(
                    operation="set_temperature",
                    exception=ValueError(error_msg),
                    context={"temperature": temperature, "valid_range": (self.min_temp, self.max_temp)}
                )
                raise HomeAssistantError(error_msg)
            
            old_temperature = self.coordinator.config.target_temperature
            
            self._logger.log_config_change(
                config_key="target_temperature",
                old_value=old_temperature,
                new_value=temperature,
                changed_by="user"
            )
            
            # Update coordinator config with new target temperature
            new_config_data = self.coordinator.config_entry.data.copy()
            new_config_data["target_temperature"] = temperature
            
            # Update the config entry
            self.hass.config_entries.async_update_entry(
                self.coordinator.config_entry,
                data=new_config_data,
            )
            
            # Update coordinator config
            await self.coordinator.async_update_config(new_config_data)
            
            # If not in manual override, trigger control logic
            if not self._manual_override:
                await self._execute_automatic_control()
                
            # Log performance if slow
            duration_ms = (time.time() - start_time) * 1000
            if duration_ms > 1000:  # Warn if takes more than 1 second
                self._logger.log_performance_warning(
                    operation="set_temperature",
                    duration_ms=duration_ms,
                    threshold_ms=1000,
                    context={"temperature": temperature}
                )
                
        except Exception as err:
            self._logger.log_exception(
                operation="set_temperature",
                exception=err,
                context={"temperature": temperature, "kwargs": kwargs},
                recovery_action="Temperature change aborted"
            )
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        start_time = time.time()
        old_mode = self.hvac_mode
        
        try:
            self._logger.log_config_change(
                config_key="hvac_mode",
                old_value=old_mode.value if old_mode else None,
                new_value=hvac_mode.value,
                changed_by="user"
            )
            
            if hvac_mode == HVACMode.OFF:
                # Turn off the system
                success = await self._set_minisplit_mode(HVAC_MODE_OFF)
                if success:
                    self._manual_override = False
                    self._logger.log_manual_override(
                        override_enabled=False,
                        triggered_by="user",
                        previous_mode=old_mode.value if old_mode else None,
                        new_mode="off"
                    )
                
            elif hvac_mode == HVACMode.AUTO:
                # Enable automatic control
                old_override = self._manual_override
                self._manual_override = False
                self.coordinator.set_manual_override(False)
                
                if old_override:
                    self._logger.log_manual_override(
                        override_enabled=False,
                        triggered_by="user",
                        previous_mode="manual",
                        new_mode="auto"
                    )
                
                await self._execute_automatic_control()
                
            else:
                # Manual mode - set specific mode and enable override
                internal_mode = REVERSE_HVAC_MODE_MAP.get(hvac_mode)
                if internal_mode:
                    old_override = self._manual_override
                    self._manual_override = True
                    self.coordinator.set_manual_override(True)
                    
                    if not old_override:
                        self._logger.log_manual_override(
                            override_enabled=True,
                            triggered_by="user",
                            previous_mode="auto",
                            new_mode=internal_mode
                        )
                    
                    await self._set_minisplit_mode(internal_mode)
                else:
                    error_msg = f"Unsupported HVAC mode: {hvac_mode}"
                    self._logger.log_exception(
                        operation="set_hvac_mode",
                        exception=ValueError(error_msg),
                        context={"hvac_mode": hvac_mode}
                    )
                    raise HomeAssistantError(error_msg)
                    
            # Log performance if slow
            duration_ms = (time.time() - start_time) * 1000
            if duration_ms > 2000:  # Warn if takes more than 2 seconds
                self._logger.log_performance_warning(
                    operation="set_hvac_mode",
                    duration_ms=duration_ms,
                    threshold_ms=2000,
                    context={"hvac_mode": hvac_mode.value}
                )
                
        except Exception as err:
            self._logger.log_exception(
                operation="set_hvac_mode",
                exception=err,
                context={"hvac_mode": hvac_mode.value, "old_mode": old_mode.value if old_mode else None},
                recovery_action="HVAC mode change aborted"
            )
            raise

    async def async_turn_on(self) -> None:
        """Turn on the climate entity."""
        try:
            self._logger.log_config_change(
                config_key="power_state",
                old_value="off",
                new_value="on",
                changed_by="user"
            )
            
            # Enable automatic control
            old_override = self._manual_override
            self._manual_override = False
            self.coordinator.set_manual_override(False)
            
            if old_override:
                self._logger.log_manual_override(
                    override_enabled=False,
                    triggered_by="user",
                    previous_mode="manual",
                    new_mode="auto"
                )
            
            await self._execute_automatic_control()
            
        except Exception as err:
            self._logger.log_exception(
                operation="turn_on",
                exception=err,
                recovery_action="Turn on operation aborted"
            )
            raise

    async def async_turn_off(self) -> None:
        """Turn off the climate entity."""
        try:
            self._logger.log_config_change(
                config_key="power_state",
                old_value="on",
                new_value="off",
                changed_by="user"
            )
            
            # Turn off the minisplit
            success = await self._set_minisplit_mode(HVAC_MODE_OFF)
            if success:
                old_override = self._manual_override
                self._manual_override = False
                self.coordinator.set_manual_override(False)
                
                if old_override:
                    self._logger.log_manual_override(
                        override_enabled=False,
                        triggered_by="user",
                        previous_mode="manual",
                        new_mode="off"
                    )
                    
        except Exception as err:
            self._logger.log_exception(
                operation="turn_off",
                exception=err,
                recovery_action="Turn off operation aborted"
            )
            raise

    async def _execute_automatic_control(self) -> None:
        """Execute automatic control logic."""
        if self._manual_override or not self.coordinator.data:
            return
            
        start_time = time.time()
        
        try:
            # Get current sensor readings
            sensor_readings = await self._get_current_sensor_readings()
            
            # Check for sensor failures and handle gracefully
            if not sensor_readings.temperature_available:
                self._error_manager.add_degraded_feature(
                    "temperature_control",
                    "External temperature sensor unavailable"
                )
                return
            else:
                # Restore feature if it was degraded
                if self._error_manager.is_feature_degraded("temperature_control"):
                    self._error_manager.remove_degraded_feature("temperature_control")
            
            if not sensor_readings.humidity_available:
                if not self._error_manager.is_feature_degraded("humidity_control"):
                    self._error_manager.add_degraded_feature(
                        "humidity_control",
                        "External humidity sensor unavailable"
                    )
            else:
                # Restore feature if it was degraded
                if self._error_manager.is_feature_degraded("humidity_control"):
                    self._error_manager.remove_degraded_feature("humidity_control")
            
            # Calculate required action
            action = self._control_manager.calculate_required_action(
                sensor_readings, self.coordinator.data
            )
            
            # Log decision reasoning
            reasoning = self._control_manager.get_decision_reasoning(
                sensor_readings, self.coordinator.data, action
            )
            
            # Log the decision with detailed context
            self._logger.log_decision(
                decision=action.action_type,
                reasoning=reasoning,
                sensor_data={
                    "temperature": sensor_readings.temperature,
                    "humidity": sensor_readings.humidity,
                    "temperature_available": sensor_readings.temperature_available,
                    "humidity_available": sensor_readings.humidity_available,
                },
                controller_state={
                    "current_mode": self.coordinator.data.current_mode,
                    "target_temperature": self.coordinator.data.target_temperature,
                    "learned_offset": self.coordinator.data.learned_offset,
                    "cooldown_remaining": action.cooldown_remaining,
                }
            )
            
            # Execute action if allowed
            if action.can_execute and action.action_type != self.coordinator.data.current_mode:
                success = await self._set_minisplit_mode(action.action_type, action.target_temperature)
                if success:
                    self._last_auto_action = action.action_type
            elif not action.can_execute:
                self._logger.log_decision(
                    decision="delayed",
                    reasoning=f"Action {action.action_type} delayed due to cooldown ({action.cooldown_remaining}s remaining)",
                    controller_state={"cooldown_remaining": action.cooldown_remaining}
                )
                
            # Log performance if slow
            duration_ms = (time.time() - start_time) * 1000
            if duration_ms > 5000:  # Warn if takes more than 5 seconds
                self._logger.log_performance_warning(
                    operation="execute_automatic_control",
                    duration_ms=duration_ms,
                    threshold_ms=5000,
                    context={"action": action.action_type}
                )
                
        except Exception as err:
            self._logger.log_exception(
                operation="execute_automatic_control",
                exception=err,
                context={
                    "manual_override": self._manual_override,
                    "coordinator_data_available": self.coordinator.data is not None
                },
                recovery_action="Automatic control skipped, will retry on next cycle"
            )

    async def _get_current_sensor_readings(self) -> SensorReadings:
        """Get current sensor readings with comprehensive error handling."""
        from homeassistant.util import dt as dt_util
        
        timestamp = dt_util.utcnow()
        
        # Get temperature from external sensor with validation
        temp_state = self.hass.states.get(self.coordinator.config.external_temp_sensor)
        temperature, temp_available = validate_sensor_value(
            temp_state,
            self.coordinator.config.external_temp_sensor,
            "temperature",
            self._logger,
            self._error_manager
        )
        
        # Get humidity from external sensor with validation
        humidity_state = self.hass.states.get(self.coordinator.config.external_humidity_sensor)
        humidity, humidity_available = validate_sensor_value(
            humidity_state,
            self.coordinator.config.external_humidity_sensor,
            "humidity",
            self._logger,
            self._error_manager
        )
        
        return SensorReadings(
            temperature=temperature,
            humidity=humidity,
            timestamp=timestamp,
            temperature_available=temp_available,
            humidity_available=humidity_available,
        )

    async def _set_minisplit_mode(
        self, 
        mode: str, 
        target_temp: float | None = None
    ) -> bool:
        """Set the minisplit to the specified mode.
        
        Returns:
            True if successful, False otherwise
        """
        minisplit_entity = self.coordinator.config.minisplit_entity
        
        try:
            success = True
            
            if mode == HVAC_MODE_OFF:
                # Turn off the minisplit
                success = await safe_call_service(
                    self.hass,
                    "climate",
                    "turn_off",
                    {"entity_id": minisplit_entity},
                    self._logger,
                    self._error_manager,
                    entity_id=minisplit_entity
                )
            else:
                # Use climate.set_temperature which can handle both mode and temperature in one atomic call
                service_data = {
                    "entity_id": minisplit_entity,
                    "hvac_mode": mode,
                }
                
                if target_temp is not None:
                    service_data["temperature"] = target_temp
                    
                success = await safe_call_service(
                    self.hass,
                    "climate",
                    "set_temperature",
                    service_data,
                    self._logger,
                    self._error_manager,
                    entity_id=minisplit_entity
                )
            
            if success:
                # Record mode change for cooldown tracking
                if self.coordinator.data and mode != self.coordinator.data.current_mode:
                    self._control_manager.record_mode_change(mode)
                    await self.coordinator.record_mode_change(mode)
                    
                self._logger.log_decision(
                    decision="minisplit_command_sent",
                    reasoning=f"Successfully set minisplit to mode {mode}" + 
                             (f" with temperature {target_temp}°F" if target_temp else ""),
                    controller_state={"new_mode": mode, "target_temp": target_temp}
                )
                
                # Remove degraded feature if it was previously degraded
                if self._error_manager.is_feature_degraded("minisplit_control"):
                    self._error_manager.remove_degraded_feature("minisplit_control")
            else:
                # Add degraded feature if command failed
                if not self._error_manager.is_feature_degraded("minisplit_control"):
                    self._error_manager.add_degraded_feature(
                        "minisplit_control",
                        f"Failed to set minisplit to mode {mode}"
                    )
                    
            return success
            
        except Exception as err:
            self._logger.log_exception(
                operation="set_minisplit_mode",
                exception=err,
                context={"mode": mode, "target_temp": target_temp, "entity": minisplit_entity},
                recovery_action="Minisplit command failed, will retry on next cycle"
            )
            
            # Add degraded feature
            if not self._error_manager.is_feature_degraded("minisplit_control"):
                self._error_manager.add_degraded_feature(
                    "minisplit_control",
                    f"Exception setting minisplit mode: {err}"
                )
                
            return False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            # Update manual override status from coordinator
            if self.coordinator.data:
                old_override = self._manual_override
                self._manual_override = self.coordinator.data.manual_override
                
                # Log override changes
                if old_override != self._manual_override:
                    self._logger.log_manual_override(
                        override_enabled=self._manual_override,
                        triggered_by="coordinator",
                        previous_mode="auto" if old_override else "manual",
                        new_mode="manual" if self._manual_override else "auto"
                    )
                
            # If not in manual override, execute automatic control
            if not self._manual_override and self.coordinator.data:
                # Schedule automatic control execution
                self.hass.async_create_task(self._execute_automatic_control())
                
            super()._handle_coordinator_update()
            
        except Exception as err:
            self._logger.log_exception(
                operation="handle_coordinator_update",
                exception=err,
                recovery_action="Coordinator update handling failed, entity state may be inconsistent"
            )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        try:
            await super().async_added_to_hass()
            
            self._logger.log_config_change(
                config_key="entity_added_to_hass",
                old_value=None,
                new_value=self._attr_unique_id,
                changed_by="system"
            )
            
            # Start automatic control if not in manual override
            if not self._manual_override:
                await self._execute_automatic_control()
                
        except Exception as err:
            self._logger.log_exception(
                operation="async_added_to_hass",
                exception=err,
                recovery_action="Entity initialization may be incomplete"
            )

    async def async_will_remove_from_hass(self) -> None:
        """When entity is being removed from hass."""
        try:
            self._logger.log_config_change(
                config_key="entity_removed_from_hass",
                old_value=self._attr_unique_id,
                new_value=None,
                changed_by="system"
            )
            
            await super().async_will_remove_from_hass()
            
        except Exception as err:
            self._logger.log_exception(
                operation="async_will_remove_from_hass",
                exception=err,
                recovery_action="Entity cleanup may be incomplete"
            )

    async def _attempt_sensor_recovery(self) -> None:
        """Attempt to recover from sensor failures."""
        try:
            # Check if sensors are now available
            sensor_readings = await self._get_current_sensor_readings()
            
            recovered_features = []
            if sensor_readings.temperature_available and self._error_manager.is_feature_degraded("temperature_control"):
                self._error_manager.remove_degraded_feature("temperature_control")
                recovered_features.append("temperature_control")
                
            if sensor_readings.humidity_available and self._error_manager.is_feature_degraded("humidity_control"):
                self._error_manager.remove_degraded_feature("humidity_control")
                recovered_features.append("humidity_control")
                
            if recovered_features:
                self._logger.log_recovery(
                    recovery_type="sensor_recovery",
                    recovered_from="sensor_unavailable",
                    restored_features=recovered_features
                )
                
        except Exception as err:
            self._logger.log_exception(
                operation="attempt_sensor_recovery",
                exception=err,
                recovery_action="Sensor recovery attempt failed"
            )

    async def _attempt_minisplit_recovery(self) -> None:
        """Attempt to recover from minisplit failures."""
        try:
            # Check if minisplit is now available
            minisplit_state = self.hass.states.get(self.coordinator.config.minisplit_entity)
            
            if minisplit_state and minisplit_state.state != "unavailable":
                if self._error_manager.is_feature_degraded("minisplit_control"):
                    self._error_manager.remove_degraded_feature("minisplit_control")
                    self._logger.log_recovery(
                        recovery_type="minisplit_recovery",
                        recovered_from="minisplit_unavailable",
                        restored_features=["minisplit_control"]
                    )
                    
        except Exception as err:
            self._logger.log_exception(
                operation="attempt_minisplit_recovery",
                exception=err,
                recovery_action="Minisplit recovery attempt failed"
            )
