"""Tests for the Smart Mini Split Controller integration."""
import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call

import pytest
from homeassistant.setup import async_setup_component
from custom_components.smart_mini_split.compat import (
    ATTR_TEMPERATURE,
    ATTR_ENTITY_ID,
    UnitOfTemperature,
)
from custom_components.smart_mini_split import (
    DOMAIN,
    SmartMiniSplitController,
    CONF_ENTITY_ID,
    CONF_EXTERNAL_SENSOR,
)
from tests.common import MockHomeAssistant, setup_mock_climate_state


class TestSmartMiniSplitController(unittest.TestCase):
    """Test the Smart Mini Split Controller."""

    def setUp(self):
        """Set up the test case."""
        self.hass = MockHomeAssistant()
        self.climate_entity = "climate.minisplit"
        self.external_sensor = "sensor.awair_element_temperature"
        
        # Mock services
        self.hass.services.async_call = MagicMock()
        self.hass.services.async_register = MagicMock()
        
        # Mock states
        setup_mock_climate_state(self.hass, self.climate_entity, 70)
        self.hass.set_state(self.external_sensor, "72")
        
        # Mock logbook
        self.log_entry_mock = MagicMock()
        
        # Create controller
        self.config = {
            CONF_ENTITY_ID: self.climate_entity,
            CONF_EXTERNAL_SENSOR: self.external_sensor,
        }
        
    def tearDown(self):
        """Clean up after each test."""
        self.hass.reset()

    @patch('custom_components.smart_mini_split.log_entry')
    @patch('custom_components.smart_mini_split.async_track_time_interval')
    async def test_initialization(self, mock_track_time_interval, mock_log_entry):
        """Test controller initialization."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Check that timer was set up
        mock_track_time_interval.assert_called_once()
        
        # Check that logbook entry was created
        mock_log_entry.assert_called()
        
        # Check that initial real setpoint was set
        self.assertEqual(controller.real_setpoint, 70)

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_check_temperatures_with_override(self, mock_log_entry):
        """Test temperature check with manual override."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Initial state
        self.assertEqual(controller.real_setpoint, 70)
        
        # Simulate manual override
        setup_mock_climate_state(self.hass, self.climate_entity, 65)  # In valid range
        
        # Should detect override
        await controller.async_check_temperatures()
        self.assertEqual(controller.real_setpoint, 65)
        self.assertTrue(controller.override_detected)
        
        # Override should be cleared on next check
        await controller.async_check_temperatures()
        self.assertFalse(controller.override_detected)

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_adjust_temperature_when_warmer(self, mock_log_entry):
        """Test temperature adjustment when external temp is warmer."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Set external temp to be warmer than real setpoint by more than threshold
        self.hass.set_state(self.external_sensor, "73")  # 3 degrees higher than real setpoint (70)
        
        await controller.async_check_temperatures()
        
        # Should adjust setpoint up by adjustment_step (10)
        self.hass.services.async_call.assert_called_once_with(
            "climate", 
            "set_temperature",
            {ATTR_ENTITY_ID: self.climate_entity, ATTR_TEMPERATURE: 80},
            blocking=True,
        )
        
        # Check cooldown was set
        self.assertIsNotNone(controller.last_adjustment_time)

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_adjust_temperature_when_cooler(self, mock_log_entry):
        """Test temperature adjustment when external temp is cooler."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Set external temp to be cooler than real setpoint by more than threshold
        self.hass.set_state(self.external_sensor, "67")  # 3 degrees lower than real setpoint (70)
        
        await controller.async_check_temperatures()
        
        # Should adjust setpoint down by adjustment_step (10)
        self.hass.services.async_call.assert_called_once_with(
            "climate", 
            "set_temperature",
            {ATTR_ENTITY_ID: self.climate_entity, ATTR_TEMPERATURE: 60},
            blocking=True,
        )

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_reset_to_real_setpoint(self, mock_log_entry):
        """Test resetting to real setpoint when temperature stabilizes."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Manually set current setpoint different from real setpoint
        controller.real_setpoint = 70
        setup_mock_climate_state(self.hass, self.climate_entity, 80)
        
        # Set external temp close to real setpoint (within reset threshold)
        self.hass.set_state(self.external_sensor, "70.5")  # Within 1 degree of real setpoint
        
        await controller.async_check_temperatures()
        
        # Should reset to real setpoint
        self.hass.services.async_call.assert_called_once_with(
            "climate", 
            "set_temperature",
            {ATTR_ENTITY_ID: self.climate_entity, ATTR_TEMPERATURE: 70},
            blocking=True,
        )

    @patch('datetime.datetime')
    @patch('custom_components.smart_mini_split.log_entry')
    async def test_cooldown_period(self, mock_log_entry, mock_datetime):
        """Test that adjustments respect the cooldown period."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Set up cooldown period
        now = datetime.now()
        mock_datetime.now.return_value = now
        controller.last_adjustment_time = now - timedelta(minutes=2)  # 2 minutes ago
        
        # Set external temp to be warmer than real setpoint by more than threshold
        self.hass.set_state(self.external_sensor, "73")  # 3 degrees higher
        
        await controller.async_check_temperatures()
        
        # Should not adjust due to cooldown
        self.hass.services.async_call.assert_not_called()
        
        # Now simulate cooldown time passed
        mock_datetime.now.return_value = now + timedelta(minutes=5)
        
        await controller.async_check_temperatures()
        
        # Should adjust setpoint
        self.hass.services.async_call.assert_called_once()

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_force_adjustment(self, mock_log_entry):
        """Test forcing an adjustment."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Set up cooldown period
        controller.last_adjustment_time = datetime.now()
        
        # Set external temp to be warmer than real setpoint by more than threshold
        self.hass.set_state(self.external_sensor, "73")  # 3 degrees higher
        
        # Regular check should respect cooldown
        await controller.async_check_temperatures()
        self.hass.services.async_call.assert_not_called()
        
        # Force adjustment should bypass cooldown
        await controller.async_force_adjustment()
        self.hass.services.async_call.assert_called_once()

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_toggle_automation(self, mock_log_entry):
        """Test toggling the automation on and off."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Set external temp to be warmer than real setpoint by more than threshold
        self.hass.set_state(self.external_sensor, "73")  # 3 degrees higher
        
        # Turn off automation
        await controller.async_toggle_automation(False)
        self.assertFalse(controller.automation_enabled)
        
        # Check temperatures should do nothing when automation is off
        await controller.async_check_temperatures()
        self.hass.services.async_call.assert_not_called()
        
        # Turn automation back on
        await controller.async_toggle_automation(True)
        self.assertTrue(controller.automation_enabled)
        
        # Check temperatures should now work
        await controller.async_check_temperatures()
        self.hass.services.async_call.assert_called_once()

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_clear_override(self, mock_log_entry):
        """Test clearing manual override."""
        controller = SmartMiniSplitController(self.hass, self.config)
        await controller.async_initialize()
        
        # Set override flag
        controller.override_detected = True
        
        # Clear override
        await controller.async_clear_override()
        self.assertFalse(controller.override_detected)

    @patch('custom_components.smart_mini_split.log_entry')
    async def test_max_temp_limit(self, mock_log_entry):
        """Test respecting the max temperature limit."""
        controller = SmartMiniSplitController(self.hass, self.config)
        
        # Set max temp to 75
        setup_mock_climate_state(self.hass, self.climate_entity, 70, max_temp=75)
        
        await controller.async_initialize()
        
        # Verify max_setpoint was properly set
        self.assertEqual(controller.max_setpoint, 75)
        
        # Set external temp high enough to trigger adjustment beyond max
        self.hass.set_state(self.external_sensor, "73")  # 3 degrees higher
        
        await controller.async_check_temperatures()
        
        # Should adjust setpoint up but cap at max_temp
        self.hass.services.async_call.assert_called_once_with(
            "climate", 
            "set_temperature",
            {ATTR_ENTITY_ID: self.climate_entity, ATTR_TEMPERATURE: 75},  # Not 80
            blocking=True,
        )
