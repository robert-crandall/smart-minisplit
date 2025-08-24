"""Data models for the Smart Thermostat Controller integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class SmartThermostatConfig:
    """Configuration data for the smart thermostat."""
    
    external_temp_sensor: str
    external_humidity_sensor: str
    minisplit_entity: str
    target_temperature: float
    humidity_max_threshold: float
    humidity_min_threshold: float
    temperature_deadband: float
    cooldown_period: int
    learning_enabled: bool
    learning_period_days: int
    default_cooling_offset: float

    @classmethod
    def from_config_entry(cls, config_data: dict[str, Any]) -> SmartThermostatConfig:
        """Create config from Home Assistant config entry data."""
        return cls(
            external_temp_sensor=config_data["external_temperature_sensor"],
            external_humidity_sensor=config_data["external_humidity_sensor"],
            minisplit_entity=config_data["minisplit_climate_entity"],
            target_temperature=config_data.get("target_temperature", 72.0),
            humidity_max_threshold=config_data.get("humidity_max_threshold", 60.0),
            humidity_min_threshold=config_data.get("humidity_min_threshold", 40.0),
            temperature_deadband=config_data.get("temperature_deadband", 1.0),
            cooldown_period=config_data.get("cooldown_period", 300),
            learning_enabled=config_data.get("learning_enabled", True),
            learning_period_days=config_data.get("learning_period_days", 7),
            default_cooling_offset=config_data.get("default_cooling_offset", 5.0),
        )

    def get_learning_config(self) -> LearningConfig:
        """Get learning configuration from main config."""
        return LearningConfig(
            enabled=self.learning_enabled,
            period_days=self.learning_period_days,
            min_data_points=50,  # Default from LearningConfig
            confidence_threshold=0.7,  # Default from LearningConfig
            max_offset=10.0,  # Default from LearningConfig
        )


@dataclass
class ControllerState:
    """Current state of the smart thermostat controller."""
    
    current_mode: str
    target_temperature: float
    current_temperature: float | None
    current_humidity: float | None
    last_mode_change: datetime | None
    learned_offset: float
    offset_confidence: float
    manual_override: bool
    cooldown_remaining: int
    is_available: bool = True

    def __post_init__(self) -> None:
        """Validate state after initialization."""
        if self.current_temperature is not None:
            if not -50 <= self.current_temperature <= 120:
                raise ValueError(f"Temperature {self.current_temperature} out of valid range")
        
        if self.current_humidity is not None:
            if not 0 <= self.current_humidity <= 100:
                raise ValueError(f"Humidity {self.current_humidity} out of valid range")


@dataclass
class TemperatureDataPoint:
    """Historical temperature data point for learning."""
    
    timestamp: datetime
    external_temperature: float
    internal_temperature: float
    minisplit_mode: str
    minisplit_active: bool

    def __post_init__(self) -> None:
        """Validate data point after initialization."""
        if not -50 <= self.external_temperature <= 120:
            raise ValueError(f"External temperature {self.external_temperature} out of valid range")
        
        if not -50 <= self.internal_temperature <= 120:
            raise ValueError(f"Internal temperature {self.internal_temperature} out of valid range")


@dataclass
class LearningConfig:
    """Configuration for the learning algorithm."""
    
    enabled: bool
    period_days: int
    min_data_points: int = 50
    confidence_threshold: float = 0.7
    max_offset: float = 10.0

    def __post_init__(self) -> None:
        """Validate learning config after initialization."""
        if self.period_days <= 0:
            raise ValueError("Learning period must be positive")
        
        if not 0 <= self.confidence_threshold <= 1:
            raise ValueError("Confidence threshold must be between 0 and 1")


@dataclass
class SensorReadings:
    """Current sensor readings."""
    
    temperature: float | None
    humidity: float | None
    timestamp: datetime
    temperature_available: bool = True
    humidity_available: bool = True

    @property
    def is_valid(self) -> bool:
        """Check if readings are valid and recent."""
        if not self.temperature_available and not self.humidity_available:
            return False
        
        # Check if readings are recent (within 5 minutes)
        from homeassistant.util import dt as dt_util
        now = dt_util.utcnow()
        age_seconds = (now - self.timestamp).total_seconds()
        return age_seconds < 300


@dataclass
class ControlAction:
    """Represents a control action to be taken."""
    
    action_type: str  # "heat", "cool", "dry", "off"
    target_temperature: float | None
    reason: str
    can_execute: bool = True
    cooldown_remaining: int = 0

    def __post_init__(self) -> None:
        """Validate control action after initialization."""
        valid_actions = {"heat", "cool", "dry", "off"}
        if self.action_type not in valid_actions:
            raise ValueError(f"Invalid action type: {self.action_type}")