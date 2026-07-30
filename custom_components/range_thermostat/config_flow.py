"""Config and options flow for Range Thermostat."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DEADBAND,
    CONF_MIN_CYCLE_DURATION,
    CONF_OVERSHOOT,
    CONF_RESEND_INTERVAL,
    CONF_SENSOR_ENTITY,
    CONF_SENSOR_TIMEOUT,
    CONF_SINGLE_COMMAND,
    DEFAULT_DEADBAND,
    DEFAULT_MIN_CYCLE_DURATION,
    DEFAULT_OVERSHOOT,
    DEFAULT_RESEND_INTERVAL,
    DEFAULT_SENSOR_TIMEOUT,
    DEFAULT_SINGLE_COMMAND,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Range Thermostat"): selector.TextSelector(),
        vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="climate")
        ),
        vol.Required(CONF_SENSOR_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
    }
)


def _minutes(minimum: float, maximum: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


def _degrees(minimum: float, maximum: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=0.1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="°",
        )
    )


class RangeThermostatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the minisplit and the external sensor."""
        if user_input is not None:
            # One range thermostat per minisplit; two would fight each other.
            await self.async_set_unique_id(user_input[CONF_CLIMATE_ENTITY])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        """Return the options flow."""
        return RangeThermostatOptionsFlow()


class RangeThermostatOptionsFlow(OptionsFlow):
    """Handle the runtime tunables."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the tunables."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEADBAND,
                    default=options.get(CONF_DEADBAND, DEFAULT_DEADBAND),
                ): _degrees(0.1, 20),
                vol.Required(
                    CONF_MIN_CYCLE_DURATION,
                    default=options.get(
                        CONF_MIN_CYCLE_DURATION, DEFAULT_MIN_CYCLE_DURATION
                    ),
                ): _minutes(0, 240),
                vol.Required(
                    CONF_OVERSHOOT,
                    default=options.get(CONF_OVERSHOOT, DEFAULT_OVERSHOOT),
                ): _degrees(0, 20),
                vol.Required(
                    CONF_SENSOR_TIMEOUT,
                    default=options.get(CONF_SENSOR_TIMEOUT, DEFAULT_SENSOR_TIMEOUT),
                ): _minutes(1, 240),
                vol.Required(
                    CONF_RESEND_INTERVAL,
                    default=options.get(CONF_RESEND_INTERVAL, DEFAULT_RESEND_INTERVAL),
                ): _minutes(0, 240),
                vol.Required(
                    CONF_SINGLE_COMMAND,
                    default=options.get(CONF_SINGLE_COMMAND, DEFAULT_SINGLE_COMMAND),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
