"""Constants for the Smart Mini Split Controller integration."""

DOMAIN = "smart_mini_split"

# Configuration
CONF_EXTERNAL_SENSOR = "external_sensor"
CONF_VALID_RANGE = "valid_range"
CONF_ADJUSTMENT_STEP = "adjustment_step"
CONF_TRIGGER_THRESHOLD = "trigger_threshold"
CONF_RESET_THRESHOLD = "reset_threshold"
CONF_COOLDOWN_MINUTES = "cooldown_minutes"
CONF_LOG_LEVEL = "log_level"

# Default values
DEFAULT_VALID_RANGE = [64, 74]
DEFAULT_ADJUSTMENT_STEP = 10
DEFAULT_TRIGGER_THRESHOLD = 2
DEFAULT_RESET_THRESHOLD = 1
DEFAULT_COOLDOWN_MINUTES = 5
DEFAULT_LOG_LEVEL = "info"

# Services
SERVICE_FORCE_ADJUSTMENT = "force_adjustment"
SERVICE_TOGGLE_AUTOMATION = "toggle_automation" 
SERVICE_CLEAR_OVERRIDE = "clear_override"
