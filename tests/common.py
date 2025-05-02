"""Common test utilities."""
import asyncio
from unittest.mock import patch, MagicMock
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_TEMPERATURE

async def setup_test_component(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up the smart_mini_split component for testing."""
    config_copy = {**config}
    return await hass.async_add_executor_job(_setup_component, hass, config_copy)


def _setup_component(hass: HomeAssistant, config: Dict):
    """Set up a component synchronously."""
    from custom_components.smart_mini_split import async_setup
    loop = asyncio.new_event_loop()
    return loop.run_until_complete(async_setup(hass, config))


class MockState:
    """Mock a HomeAssistant state."""
    
    def __init__(self, entity_id: str, state: str, attributes: Dict[str, Any] = None):
        """Initialize the mock state."""
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class MockHomeAssistant:
    """Provide a test instance of Home Assistant."""

    def __init__(self):
        """Initialize mock Home Assistant."""
        self.states = {}
        self.services = MagicMock()
        self.data = {}
        self.config = {}

    def get_state(self, entity_id: str) -> Optional[MockState]:
        """Get state by entity ID."""
        return self.states.get(entity_id)

    def set_state(self, entity_id: str, state: str, attributes: Dict[str, Any] = None):
        """Set a state."""
        self.states[entity_id] = MockState(entity_id, state, attributes)

    def reset(self):
        """Reset the mock."""
        self.states.clear()
        self.data.clear()
        self.services.reset_mock()


def setup_mock_climate_state(hass, entity_id, temp, min_temp=60, max_temp=90):
    """Set up a mock climate entity state."""
    hass.set_state(entity_id, "auto", {
        ATTR_TEMPERATURE: temp,
        "min_temp": min_temp,
        "max_temp": max_temp,
        "current_temperature": temp - 2,
        "hvac_mode": "auto",
        "hvac_action": "idle",
    })
