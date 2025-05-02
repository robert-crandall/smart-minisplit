"""Configuration for tests."""
from unittest.mock import patch
import pytest

pytest.register_assert_rewrite("tests.common")

# This fixture is used to prevent HomeAssistant from attempting to create and dismiss persistent
# notifications. These calls would fail without this patch because the persistent_notification
# integration is never loaded during a test.
@pytest.fixture(name="mock_persistent_notification")
def mock_persistent_notification_fixture():
    """Mock the persistent notification."""
    with patch("homeassistant.components.persistent_notification.async_create"), patch(
        "homeassistant.components.persistent_notification.async_dismiss"
    ):
        yield
