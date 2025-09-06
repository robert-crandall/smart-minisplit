import pytest
from types import SimpleNamespace
from datetime import datetime

class FakeState:
    def __init__(self, state, **attributes):
        self.state = state
        self.attributes = attributes

class FakeStates:
    def __init__(self):
        self._data = {}
    def get(self, entity_id):
        return self._data.get(entity_id)
    def set(self, entity_id, state, **attrs):
        self._data[entity_id] = FakeState(state, **attrs)

class FakeServices:
    async def async_call(self, domain, service, service_data, blocking=False):
        # For now, just store last call if needed for assertions later
        self.last_call = (domain, service, service_data, blocking)

class FakeHass:
    def __init__(self):
        self.states = FakeStates()
        self.services = FakeServices()

@pytest.fixture
def fake_hass():
    return FakeHass()
