"""Constants for the Range Thermostat integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "range_thermostat"

# Config entry data
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_SENSOR_ENTITY = "sensor_entity"

# Options
CONF_DEADBAND = "deadband"
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_OVERSHOOT = "overshoot"
CONF_SENSOR_TIMEOUT = "sensor_timeout"
CONF_RESEND_INTERVAL = "resend_interval"

DEFAULT_DEADBAND = 1.0
DEFAULT_MIN_CYCLE_DURATION = 15  # minutes
DEFAULT_OVERSHOOT = 0.0
DEFAULT_SENSOR_TIMEOUT = 15  # minutes
DEFAULT_RESEND_INTERVAL = 0  # minutes, 0 disables re-assertion

# Periodic safety evaluation, independent of sensor updates.
SAFETY_TICK = timedelta(minutes=5)

# Starting band when there is nothing to restore.
DEFAULT_BAND_FAHRENHEIT = (68.0, 72.0)
DEFAULT_BAND_CELSIUS = (20.0, 22.0)

# Exposed state attributes
ATTR_CONTROLLED_ENTITY = "controlled_entity"
ATTR_SENSOR_ENTITY = "sensor_entity"
ATTR_LAST_MODE_CHANGE = "last_mode_change"
ATTR_TIME_UNTIL_NEXT_ALLOWED_CHANGE = "time_until_next_allowed_change"
ATTR_COMMANDED_SETPOINT = "commanded_setpoint"
ATTR_SENSOR_STALE = "sensor_stale"
