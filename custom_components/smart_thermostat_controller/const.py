"""Constants for the Smart Thermostat Controller integration."""
from __future__ import annotations

from typing import Final

# Integration domain
DOMAIN: Final = "smart_thermostat_controller"

# Configuration keys
CONF_EXTERNAL_TEMP_SENSOR: Final = "external_temperature_sensor"
CONF_EXTERNAL_HUMIDITY_SENSOR: Final = "external_humidity_sensor"
CONF_MINISPLIT_ENTITY: Final = "minisplit_climate_entity"
CONF_TARGET_TEMPERATURE: Final = "target_temperature"
CONF_HUMIDITY_MAX_THRESHOLD: Final = "humidity_max_threshold"
CONF_HUMIDITY_MIN_THRESHOLD: Final = "humidity_min_threshold"
CONF_TEMPERATURE_DEADBAND: Final = "temperature_deadband"
CONF_COOLDOWN_PERIOD: Final = "cooldown_period"
CONF_LEARNING_ENABLED: Final = "learning_enabled"
CONF_LEARNING_PERIOD_DAYS: Final = "learning_period_days"
CONF_DEFAULT_COOLING_OFFSET: Final = "default_cooling_offset"
CONF_IDLE_TEMPERATURE_OFFSET: Final = "idle_temperature_offset"

# Default values
DEFAULT_TARGET_TEMPERATURE: Final = 72.0
DEFAULT_HUMIDITY_MAX_THRESHOLD: Final = 60.0
DEFAULT_HUMIDITY_MIN_THRESHOLD: Final = 40.0
DEFAULT_TEMPERATURE_DEADBAND: Final = 1.0
DEFAULT_COOLDOWN_PERIOD: Final = 300  # 5 minutes in seconds
DEFAULT_LEARNING_ENABLED: Final = True
DEFAULT_LEARNING_PERIOD_DAYS: Final = 7
DEFAULT_COOLING_OFFSET: Final = 5.0
DEFAULT_IDLE_TEMPERATURE_OFFSET: Final = 2.0  # Temperature offset for idle state

# Update intervals
UPDATE_INTERVAL_SECONDS: Final = 30

# Data storage keys
DATA_COORDINATOR: Final = "coordinator"
DATA_HISTORICAL: Final = "historical_data"

# HVAC modes
HVAC_MODE_HEAT: Final = "heat"
HVAC_MODE_COOL: Final = "cool"
HVAC_MODE_DRY: Final = "dry"
HVAC_MODE_OFF: Final = "off"
HVAC_MODE_AUTO: Final = "auto"

# Sensor types
SENSOR_CURRENT_MODE: Final = "current_mode"
SENSOR_LEARNED_OFFSET: Final = "learned_offset"
SENSOR_COOLDOWN_STATUS: Final = "cooldown_status"
SENSOR_OFFSET_CONFIDENCE: Final = "offset_confidence"
SENSOR_MANUAL_OVERRIDE: Final = "manual_override"

# Logging constants
LOG_LEVEL_DEBUG: Final = "debug"
LOG_LEVEL_INFO: Final = "info"
LOG_LEVEL_WARNING: Final = "warning"
LOG_LEVEL_ERROR: Final = "error"

# Error types
ERROR_SENSOR_UNAVAILABLE: Final = "sensor_unavailable"
ERROR_SENSOR_INVALID_VALUE: Final = "sensor_invalid_value"
ERROR_SENSOR_TIMEOUT: Final = "sensor_timeout"
ERROR_MINISPLIT_UNAVAILABLE: Final = "minisplit_unavailable"
ERROR_MINISPLIT_COMMAND_FAILED: Final = "minisplit_command_failed"
ERROR_CONFIG_INVALID: Final = "config_invalid"
ERROR_DATA_CORRUPTION: Final = "data_corruption"

# Sensor validation ranges
TEMP_MIN_VALID: Final = -50.0
TEMP_MAX_VALID: Final = 120.0
HUMIDITY_MIN_VALID: Final = 0.0
HUMIDITY_MAX_VALID: Final = 100.0

# Sensor timeout (seconds)
SENSOR_TIMEOUT_SECONDS: Final = 300  # 5 minutes
