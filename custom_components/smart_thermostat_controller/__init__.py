"""Smart Thermostat Controller integration for Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import SmartThermostatCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Smart Thermostat Controller integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Thermostat Controller from a config entry."""
    _LOGGER.debug("Setting up Smart Thermostat Controller entry: %s", entry.entry_id)
    
    # Create coordinator for managing data updates
    coordinator = SmartThermostatCoordinator(hass, entry)
    
    # Set up coordinator and load persistent data
    await coordinator.async_setup()
    
    # Store coordinator in hass data
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Perform initial data fetch
    await coordinator.async_config_entry_first_refresh()
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services
    await _async_setup_services(hass)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Smart Thermostat Controller entry: %s", entry.entry_id)
    
    # Get coordinator and shut it down
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()
    
    # Unload platforms
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the Smart Thermostat Controller."""
    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv
    
    async def async_set_away_mode(call) -> None:
        """Handle set away mode service call."""
        entity_id = call.data.get("entity_id")
        away_mode = call.data.get("away_mode", False)
        
        # Find the coordinator for this entity
        coordinator = None
        for entry_id, coord in hass.data[DOMAIN].items():
            if hasattr(coord, 'set_away_mode'):
                coordinator = coord
                break
        
        if coordinator:
            coordinator.set_away_mode(away_mode)
            await coordinator.async_request_refresh()
            _LOGGER.info("Away mode set to %s", away_mode)
        else:
            _LOGGER.error("No Smart Thermostat Controller found")
    
    # Register the service only once
    if not hass.services.has_service(DOMAIN, "set_away_mode"):
        hass.services.async_register(
            DOMAIN,
            "set_away_mode",
            async_set_away_mode,
            schema=vol.Schema({
                vol.Optional("entity_id"): cv.entity_id,
                vol.Required("away_mode"): bool,
            }),
        )
