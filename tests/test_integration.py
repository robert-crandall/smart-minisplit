"""Integration tests for the Smart Mini Split Controller integration."""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
from homeassistant.setup import async_setup_component
from homeassistant.helpers.entity_component import EntityComponent
from custom_components.smart_mini_split import (
    DOMAIN,
    CONF_ENTITY_ID,
    CONF_EXTERNAL_SENSOR,
    CONF_VALID_RANGE,
    CONF_ADJUSTMENT_STEP,
    CONF_TRIGGER_THRESHOLD,
    CONF_RESET_THRESHOLD,
    CONF_COOLDOWN_MINUTES,
    SERVICE_FORCE_ADJUSTMENT,
    SERVICE_TOGGLE_AUTOMATION,
    SERVICE_CLEAR_OVERRIDE,
)


@pytest.fixture
def hass(loop):
    """Return a Home Assistant object."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.config = {}
    
    # Define helper methods to simulate HA behavior
    async def async_start():
        pass
    
    hass.async_start = async_start
    
    def get_state(entity_id):
        """Get the state of an entity."""
        if entity_id == "climate.minisplit":
            return MagicMock(
                state="auto",
                attributes={
                    "temperature": 70,
                    "min_temp": 60,
                    "max_temp": 90,
                    "current_temperature": 68,
                }
            )
        elif entity_id == "sensor.temp_sensor":
            return MagicMock(state="72")
        return None
    
    hass.states.get = get_state
    
    # Create mock service registry
    services = {}
    def register_service(domain, service, callback, schema=None):
        services[(domain, service)] = callback
    
    async def call_service(domain, service, data=None, blocking=False):
        if blocking and (domain, service) in services:
            await services[(domain, service)](MagicMock(data=data or {}))
    
    hass.services.async_register = register_service
    hass.services.async_call = call_service
    
    return hass


async def test_setup_and_services(hass):
    """Test setting up the integration and calling services."""
    # Set up the integration
    config = {
        DOMAIN: {
            CONF_ENTITY_ID: "climate.minisplit",
            CONF_EXTERNAL_SENSOR: "sensor.temp_sensor",
            CONF_VALID_RANGE: [65, 75],
            CONF_ADJUSTMENT_STEP: 10,
            CONF_TRIGGER_THRESHOLD: 3,
            CONF_RESET_THRESHOLD: 1,
            CONF_COOLDOWN_MINUTES: 5,
        }
    }
    
    with patch("custom_components.smart_mini_split.log_entry"), \
         patch("custom_components.smart_mini_split.async_track_time_interval"):
        result = await async_setup_component(hass, DOMAIN, config)
        assert result is True
        assert DOMAIN in hass.data
        
        # Verify controller was initialized
        controller = hass.data[DOMAIN]
        assert controller.entity_id == "climate.minisplit"
        assert controller.external_sensor == "sensor.temp_sensor"
        
        # Test toggle_automation service
        await hass.services.async_call(
            DOMAIN, 
            SERVICE_TOGGLE_AUTOMATION, 
            {"enabled": False},
            blocking=True
        )
        assert controller.automation_enabled is False
        
        # Test force_adjustment service
        with patch.object(controller, "async_check_temperatures") as mock_check:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_FORCE_ADJUSTMENT,
                {},
                blocking=True
            )
            assert mock_check.called
        
        # Test clear_override service
        controller.override_detected = True
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEAR_OVERRIDE,
            {},
            blocking=True
        )
        assert controller.override_detected is False


@pytest.mark.parametrize(
    "external_temp,initial_setpoint,expected_adjustment",
    [
        (75, 70, 80),  # External temp higher than setpoint, should increase
        (65, 70, 60),  # External temp lower than setpoint, should decrease
        (71, 70, None),  # External temp within threshold, should not adjust
    ]
)
async def test_temperature_adjustments(hass, external_temp, initial_setpoint, expected_adjustment):
    """Test temperature adjustments based on external temperature."""
    # Set up the integration
    config = {
        DOMAIN: {
            CONF_ENTITY_ID: "climate.minisplit",
            CONF_EXTERNAL_SENSOR: "sensor.temp_sensor",
        }
    }
    
    # Set initial states
    hass.states.get = MagicMock(side_effect=lambda entity_id: 
        MagicMock(
            state="auto" if entity_id == "climate.minisplit" else str(external_temp),
            attributes={
                "temperature": initial_setpoint,
                "min_temp": 60,
                "max_temp": 90,
                "current_temperature": initial_setpoint - 2,
            } if entity_id == "climate.minisplit" else {}
        ) if entity_id in ["climate.minisplit", "sensor.temp_sensor"] else None
    )
    
    with patch("custom_components.smart_mini_split.log_entry"), \
         patch("custom_components.smart_mini_split.async_track_time_interval"):
        # Initialize the integration
        result = await async_setup_component(hass, DOMAIN, config)
        assert result is True
        controller = hass.data[DOMAIN]
        
        # Force an adjustment check
        service_calls = []
        
        # Mock the service call to track parameters
        async def async_call(domain, service, data, blocking=False):
            service_calls.append((domain, service, data))
        
        hass.services.async_call = async_call
        
        # Run the check
        await controller.async_check_temperatures()
        
        # Verify the correct adjustment (if any)
        if expected_adjustment is not None:
            assert len(service_calls) == 1
            domain, service, data = service_calls[0]
            assert domain == "climate"
            assert service == "set_temperature"
            assert data["temperature"] == expected_adjustment
        else:
            assert len(service_calls) == 0
