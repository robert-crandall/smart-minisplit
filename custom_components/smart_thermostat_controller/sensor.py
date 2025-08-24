"""Sensor platform for Smart Thermostat Controller."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartThermostatCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key="current_mode",
        name="Current Mode",
        icon="mdi:thermostat",
        entity_category=None,  # Main status sensor
    ),
    SensorEntityDescription(
        key="learned_offset",
        name="Learned Offset",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-plus",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="offset_confidence",
        name="Offset Confidence",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cooldown_remaining",
        name="Cooldown Remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="manual_override",
        name="Manual Override",
        icon="mdi:hand-back-right",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="sensor_status",
        name="Sensor Status",
        icon="mdi:sensor",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="learning_data_points",
        name="Learning Data Points",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:database",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="last_mode_change",
        name="Last Mode Change",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Thermostat Controller sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        SmartThermostatSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    
    async_add_entities(entities)


class SmartThermostatSensor(CoordinatorEntity[SmartThermostatCoordinator], SensorEntity):
    """Representation of a Smart Thermostat Controller sensor."""

    def __init__(
        self,
        coordinator: SmartThermostatCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "name": "Smart Thermostat Controller",
            "manufacturer": "Smart Thermostat Controller",
            "model": "Smart Thermostat Controller",
            "sw_version": "1.0.0",
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        state = self.coordinator.data
        
        if self.entity_description.key == "current_mode":
            return state.current_mode
        
        elif self.entity_description.key == "learned_offset":
            return round(state.learned_offset, 2)
        
        elif self.entity_description.key == "offset_confidence":
            return round(state.offset_confidence * 100, 1)  # Convert to percentage
        
        elif self.entity_description.key == "cooldown_remaining":
            return state.cooldown_remaining
        
        elif self.entity_description.key == "manual_override":
            return "On" if state.manual_override else "Off"
        
        elif self.entity_description.key == "sensor_status":
            return self._get_sensor_status()
        
        elif self.entity_description.key == "learning_data_points":
            return len(self.coordinator.historical_data)
        
        elif self.entity_description.key == "last_mode_change":
            return state.last_mode_change
        
        return None

    def _get_sensor_status(self) -> str:
        """Get the overall sensor status."""
        state = self.coordinator.data
        if not state:
            return "Unknown"
        
        issues = []
        
        # Check temperature sensor
        if state.current_temperature is None:
            issues.append("Temperature sensor unavailable")
        
        # Check humidity sensor
        if state.current_humidity is None:
            issues.append("Humidity sensor unavailable")
        
        # Check if system is available
        if not state.is_available:
            issues.append("System unavailable")
        
        if not issues:
            return "OK"
        elif len(issues) == 1:
            return issues[0]
        else:
            return f"{len(issues)} issues"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return None

        state = self.coordinator.data
        base_attrs = {
            "integration": DOMAIN,
            "config_entry_id": self.coordinator.config_entry.entry_id,
        }

        # Add specific attributes based on sensor type
        if self.entity_description.key == "current_mode":
            base_attrs.update({
                "target_temperature": state.target_temperature,
                "current_temperature": state.current_temperature,
                "current_humidity": state.current_humidity,
            })
        
        elif self.entity_description.key == "learned_offset":
            base_attrs.update({
                "confidence": round(state.offset_confidence, 3),
                "data_points": len(self.coordinator.historical_data),
                "learning_enabled": self.coordinator.config.learning_enabled,
            })
        
        elif self.entity_description.key == "offset_confidence":
            base_attrs.update({
                "learned_offset": round(state.learned_offset, 2),
                "data_points": len(self.coordinator.historical_data),
                "threshold": 0.7,  # Confidence threshold for using learned offset
            })
        
        elif self.entity_description.key == "cooldown_remaining":
            base_attrs.update({
                "cooldown_period": self.coordinator.config.cooldown_period,
                "last_mode_change": state.last_mode_change,
                "can_change_mode": state.cooldown_remaining == 0,
            })
        
        elif self.entity_description.key == "manual_override":
            base_attrs.update({
                "automatic_control": not state.manual_override,
                "override_timestamp": None,  # Could be added to coordinator if needed
            })
        
        elif self.entity_description.key == "sensor_status":
            base_attrs.update({
                "temperature_sensor": self.coordinator.config.external_temp_sensor,
                "humidity_sensor": self.coordinator.config.external_humidity_sensor,
                "minisplit_entity": self.coordinator.config.minisplit_entity,
                "temperature_available": state.current_temperature is not None,
                "humidity_available": state.current_humidity is not None,
                "system_available": state.is_available,
            })
        
        elif self.entity_description.key == "learning_data_points":
            base_attrs.update({
                "learning_period_days": self.coordinator.config.learning_period_days,
                "min_data_points": 10,  # Minimum for learning
                "learning_active": len(self.coordinator.historical_data) >= 10,
            })
        
        elif self.entity_description.key == "last_mode_change":
            base_attrs.update({
                "cooldown_remaining": state.cooldown_remaining,
                "previous_mode": None,  # Could be tracked in coordinator
            })

        return base_attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def icon(self) -> str | None:
        """Return the icon for the sensor."""
        # Dynamic icons based on state
        if self.entity_description.key == "current_mode":
            mode = self.native_value
            if mode == "heat":
                return "mdi:fire"
            elif mode == "cool":
                return "mdi:snowflake"
            elif mode == "dry":
                return "mdi:water-percent"
            elif mode == "off":
                return "mdi:power-off"
            else:
                return "mdi:thermostat"
        
        elif self.entity_description.key == "manual_override":
            if self.coordinator.data and self.coordinator.data.manual_override:
                return "mdi:hand-back-right"
            else:
                return "mdi:auto-mode"
        
        elif self.entity_description.key == "sensor_status":
            status = self.native_value
            if status == "OK":
                return "mdi:check-circle"
            else:
                return "mdi:alert-circle"
        
        elif self.entity_description.key == "cooldown_remaining":
            if self.coordinator.data and self.coordinator.data.cooldown_remaining > 0:
                return "mdi:timer-sand"
            else:
                return "mdi:timer-sand-empty"
        
        return self.entity_description.icon