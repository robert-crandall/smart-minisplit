"""Config flow for Smart Thermostat Controller."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import (
    CONF_AWAY_MAX_TEMPERATURE,
    CONF_AWAY_MIN_TEMPERATURE,
    CONF_AWAY_MODE_ENABLED,
    CONF_COOLDOWN_PERIOD,
    CONF_DEFAULT_COOLING_OFFSET,
    CONF_EXTERNAL_HUMIDITY_SENSOR,
    CONF_EXTERNAL_TEMP_SENSOR,
    CONF_HUMIDITY_MAX_THRESHOLD,
    CONF_HUMIDITY_MIN_THRESHOLD,
    CONF_IDLE_TEMPERATURE_OFFSET,
    CONF_LEARNING_ENABLED,
    CONF_LEARNING_PERIOD_DAYS,
    CONF_MINISPLIT_ENTITY,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_DEADBAND,
    DEFAULT_AWAY_MAX_TEMPERATURE,
    DEFAULT_AWAY_MIN_TEMPERATURE,
    DEFAULT_AWAY_MODE_ENABLED,
    DEFAULT_COOLDOWN_PERIOD,
    DEFAULT_COOLING_OFFSET,
    DEFAULT_HUMIDITY_MAX_THRESHOLD,
    DEFAULT_HUMIDITY_MIN_THRESHOLD,
    DEFAULT_IDLE_TEMPERATURE_OFFSET,
    DEFAULT_LEARNING_ENABLED,
    DEFAULT_LEARNING_PERIOD_DAYS,
    DEFAULT_TARGET_TEMPERATURE,
    DEFAULT_TEMPERATURE_DEADBAND,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SmartThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Thermostat Controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._config_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate the input
            errors = await self._validate_step_user(user_input)
            
            if not errors:
                self._config_data.update(user_input)
                return await self.async_step_sensors()

        # Get available entities for selection
        entity_registry = async_get_entity_registry(self.hass)
        climate_entities = [
            entity.entity_id
            for entity in entity_registry.entities.values()
            if entity.domain == "climate"
        ]

        schema = vol.Schema({
            vol.Required(CONF_NAME, default="Smart Thermostat"): str,
            vol.Required(CONF_MINISPLIT_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="climate",
                    multiple=False,
                )
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "climate_count": str(len(climate_entities))
            },
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle sensor selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_step_sensors(user_input)
            
            if not errors:
                self._config_data.update(user_input)
                return await self.async_step_thresholds()

        schema = vol.Schema({
            vol.Required(CONF_EXTERNAL_TEMP_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="temperature",
                    multiple=False,
                )
            ),
            vol.Required(CONF_EXTERNAL_HUMIDITY_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="humidity",
                    multiple=False,
                )
            ),
        })

        return self.async_show_form(
            step_id="sensors",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle threshold configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_step_thresholds(user_input)
            
            if not errors:
                self._config_data.update(user_input)
                return await self.async_step_advanced()

        schema = vol.Schema({
            vol.Required(
                CONF_TARGET_TEMPERATURE, 
                default=DEFAULT_TARGET_TEMPERATURE
            ): vol.All(vol.Coerce(float), vol.Range(min=50, max=90)),
            vol.Required(
                CONF_HUMIDITY_MAX_THRESHOLD, 
                default=DEFAULT_HUMIDITY_MAX_THRESHOLD
            ): vol.All(vol.Coerce(float), vol.Range(min=30, max=80)),
            vol.Required(
                CONF_HUMIDITY_MIN_THRESHOLD, 
                default=DEFAULT_HUMIDITY_MIN_THRESHOLD
            ): vol.All(vol.Coerce(float), vol.Range(min=20, max=70)),
            vol.Required(
                CONF_TEMPERATURE_DEADBAND, 
                default=DEFAULT_TEMPERATURE_DEADBAND
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5.0)),
        })

        return self.async_show_form(
            step_id="thresholds",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle advanced configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_step_advanced(user_input)
            
            if not errors:
                self._config_data.update(user_input)
                
                # Create the config entry
                return self.async_create_entry(
                    title=self._config_data[CONF_NAME],
                    data=self._config_data,
                )

        schema = vol.Schema({
            vol.Required(
                CONF_COOLDOWN_PERIOD, 
                default=DEFAULT_COOLDOWN_PERIOD
            ): vol.All(vol.Coerce(int), vol.Range(min=60, max=1800)),
            vol.Required(
                CONF_LEARNING_ENABLED, 
                default=DEFAULT_LEARNING_ENABLED
            ): bool,
            vol.Required(
                CONF_LEARNING_PERIOD_DAYS, 
                default=DEFAULT_LEARNING_PERIOD_DAYS
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Required(
                CONF_DEFAULT_COOLING_OFFSET, 
                default=DEFAULT_COOLING_OFFSET
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=15)),
            vol.Required(
                CONF_IDLE_TEMPERATURE_OFFSET, 
                default=DEFAULT_IDLE_TEMPERATURE_OFFSET
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5.0)),
            vol.Required(
                CONF_AWAY_MODE_ENABLED, 
                default=DEFAULT_AWAY_MODE_ENABLED
            ): bool,
            vol.Required(
                CONF_AWAY_MIN_TEMPERATURE, 
                default=DEFAULT_AWAY_MIN_TEMPERATURE
            ): vol.All(vol.Coerce(float), vol.Range(min=50, max=85)),
            vol.Required(
                CONF_AWAY_MAX_TEMPERATURE, 
                default=DEFAULT_AWAY_MAX_TEMPERATURE
            ): vol.All(vol.Coerce(float), vol.Range(min=60, max=95)),
        })

        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors,
        )

    async def _validate_step_user(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate user step input."""
        errors: dict[str, str] = {}

        # Check if minisplit entity exists and is available
        minisplit_entity = user_input.get(CONF_MINISPLIT_ENTITY)
        if minisplit_entity:
            state = self.hass.states.get(minisplit_entity)
            if state is None:
                errors[CONF_MINISPLIT_ENTITY] = "entity_not_found"
            elif state.domain != "climate":
                errors[CONF_MINISPLIT_ENTITY] = "invalid_entity_domain"

        # Check for duplicate entries
        name = user_input.get(CONF_NAME, "")
        for entry in self._async_current_entries():
            if entry.data.get(CONF_NAME) == name:
                errors[CONF_NAME] = "name_exists"
                break

        return errors

    async def _validate_step_sensors(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate sensor step input."""
        errors: dict[str, str] = {}

        # Validate temperature sensor
        temp_sensor = user_input.get(CONF_EXTERNAL_TEMP_SENSOR)
        if temp_sensor:
            state = self.hass.states.get(temp_sensor)
            if state is None:
                errors[CONF_EXTERNAL_TEMP_SENSOR] = "entity_not_found"
            elif state.domain != "sensor":
                errors[CONF_EXTERNAL_TEMP_SENSOR] = "invalid_entity_domain"
            else:
                # Try to get numeric value
                try:
                    temp_value = float(state.state)
                    if not -50 <= temp_value <= 120:
                        errors[CONF_EXTERNAL_TEMP_SENSOR] = "invalid_temperature_range"
                except (ValueError, TypeError):
                    errors[CONF_EXTERNAL_TEMP_SENSOR] = "invalid_temperature_value"

        # Validate humidity sensor
        humidity_sensor = user_input.get(CONF_EXTERNAL_HUMIDITY_SENSOR)
        if humidity_sensor:
            state = self.hass.states.get(humidity_sensor)
            if state is None:
                errors[CONF_EXTERNAL_HUMIDITY_SENSOR] = "entity_not_found"
            elif state.domain != "sensor":
                errors[CONF_EXTERNAL_HUMIDITY_SENSOR] = "invalid_entity_domain"
            else:
                # Try to get numeric value
                try:
                    humidity_value = float(state.state)
                    if not 0 <= humidity_value <= 100:
                        errors[CONF_EXTERNAL_HUMIDITY_SENSOR] = "invalid_humidity_range"
                except (ValueError, TypeError):
                    errors[CONF_EXTERNAL_HUMIDITY_SENSOR] = "invalid_humidity_value"

        # Check that sensors are different
        if (temp_sensor and humidity_sensor and 
            temp_sensor == humidity_sensor):
            errors[CONF_EXTERNAL_HUMIDITY_SENSOR] = "sensors_must_be_different"

        return errors

    async def _validate_step_thresholds(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate threshold step input."""
        errors: dict[str, str] = {}

        humidity_min = user_input.get(CONF_HUMIDITY_MIN_THRESHOLD, 0)
        humidity_max = user_input.get(CONF_HUMIDITY_MAX_THRESHOLD, 100)

        # Validate humidity thresholds
        if humidity_min >= humidity_max:
            errors[CONF_HUMIDITY_MAX_THRESHOLD] = "max_must_be_greater_than_min"

        return errors

    async def _validate_step_advanced(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate advanced step input."""
        errors: dict[str, str] = {}

        # Validate away mode temperature ranges
        if (
            user_input.get(CONF_AWAY_MODE_ENABLED, False) and
            CONF_AWAY_MIN_TEMPERATURE in user_input and
            CONF_AWAY_MAX_TEMPERATURE in user_input
        ):
            away_min = user_input[CONF_AWAY_MIN_TEMPERATURE]
            away_max = user_input[CONF_AWAY_MAX_TEMPERATURE]
            
            if away_max <= away_min:
                errors["away_max_temperature"] = "away_max_must_be_greater_than_min"

        return errors

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SmartThermostatOptionsFlow:
        """Get the options flow for this handler."""
        return SmartThermostatOptionsFlow(config_entry)


class SmartThermostatOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Smart Thermostat Controller."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        return await self.async_step_thresholds()

    async def async_step_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle threshold options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_thresholds(user_input)
            
            if not errors:
                return await self.async_step_advanced_options(user_input)

        # Get current values from config entry
        current_data = {**self.config_entry.data, **self.config_entry.options}

        schema = vol.Schema({
            vol.Required(
                CONF_TARGET_TEMPERATURE,
                default=current_data.get(CONF_TARGET_TEMPERATURE, DEFAULT_TARGET_TEMPERATURE)
            ): vol.All(vol.Coerce(float), vol.Range(min=50, max=90)),
            vol.Required(
                CONF_HUMIDITY_MAX_THRESHOLD,
                default=current_data.get(CONF_HUMIDITY_MAX_THRESHOLD, DEFAULT_HUMIDITY_MAX_THRESHOLD)
            ): vol.All(vol.Coerce(float), vol.Range(min=30, max=80)),
            vol.Required(
                CONF_HUMIDITY_MIN_THRESHOLD,
                default=current_data.get(CONF_HUMIDITY_MIN_THRESHOLD, DEFAULT_HUMIDITY_MIN_THRESHOLD)
            ): vol.All(vol.Coerce(float), vol.Range(min=20, max=70)),
            vol.Required(
                CONF_TEMPERATURE_DEADBAND,
                default=current_data.get(CONF_TEMPERATURE_DEADBAND, DEFAULT_TEMPERATURE_DEADBAND)
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5.0)),
        })

        return self.async_show_form(
            step_id="thresholds",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_advanced_options(
        self, threshold_input: dict[str, Any], user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle advanced options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_advanced_options(user_input)
            
            if not errors:
                # Combine threshold and advanced options
                all_options = {**threshold_input, **user_input}
                return self.async_create_entry(title="", data=all_options)

        # Get current values from config entry
        current_data = {**self.config_entry.data, **self.config_entry.options}

        schema = vol.Schema({
            vol.Required(
                CONF_COOLDOWN_PERIOD,
                default=current_data.get(CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD)
            ): vol.All(vol.Coerce(int), vol.Range(min=60, max=1800)),
            vol.Required(
                CONF_LEARNING_ENABLED,
                default=current_data.get(CONF_LEARNING_ENABLED, DEFAULT_LEARNING_ENABLED)
            ): bool,
            vol.Required(
                CONF_LEARNING_PERIOD_DAYS,
                default=current_data.get(CONF_LEARNING_PERIOD_DAYS, DEFAULT_LEARNING_PERIOD_DAYS)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Required(
                CONF_DEFAULT_COOLING_OFFSET,
                default=current_data.get(CONF_DEFAULT_COOLING_OFFSET, DEFAULT_COOLING_OFFSET)
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=15)),
            vol.Required(
                CONF_IDLE_TEMPERATURE_OFFSET,
                default=current_data.get(CONF_IDLE_TEMPERATURE_OFFSET, DEFAULT_IDLE_TEMPERATURE_OFFSET)
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5.0)),
            vol.Required(
                CONF_AWAY_MODE_ENABLED,
                default=current_data.get(CONF_AWAY_MODE_ENABLED, DEFAULT_AWAY_MODE_ENABLED)
            ): bool,
            vol.Required(
                CONF_AWAY_MIN_TEMPERATURE,
                default=current_data.get(CONF_AWAY_MIN_TEMPERATURE, DEFAULT_AWAY_MIN_TEMPERATURE)
            ): vol.All(vol.Coerce(float), vol.Range(min=50, max=85)),
            vol.Required(
                CONF_AWAY_MAX_TEMPERATURE,
                default=current_data.get(CONF_AWAY_MAX_TEMPERATURE, DEFAULT_AWAY_MAX_TEMPERATURE)
            ): vol.All(vol.Coerce(float), vol.Range(min=60, max=95)),
        })

        return self.async_show_form(
            step_id="advanced_options",
            data_schema=schema,
            errors=errors,
        )

    async def _validate_thresholds(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate threshold options."""
        errors: dict[str, str] = {}

        humidity_min = user_input.get(CONF_HUMIDITY_MIN_THRESHOLD, 0)
        humidity_max = user_input.get(CONF_HUMIDITY_MAX_THRESHOLD, 100)

        if humidity_min >= humidity_max:
            errors[CONF_HUMIDITY_MAX_THRESHOLD] = "max_must_be_greater_than_min"

        return errors

    async def _validate_advanced_options(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate advanced options."""
        errors: dict[str, str] = {}

        # Validate away mode temperature ranges
        if (
            user_input.get(CONF_AWAY_MODE_ENABLED, False) and
            CONF_AWAY_MIN_TEMPERATURE in user_input and
            CONF_AWAY_MAX_TEMPERATURE in user_input
        ):
            away_min = user_input[CONF_AWAY_MIN_TEMPERATURE]
            away_max = user_input[CONF_AWAY_MAX_TEMPERATURE]
            
            if away_max <= away_min:
                errors["away_max_temperature"] = "away_max_must_be_greater_than_min"

        return errors
