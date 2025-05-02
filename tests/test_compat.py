"""Tests for the compat module."""
import sys
import unittest
from unittest.mock import patch, MagicMock

import pytest


class TestCompatModule(unittest.TestCase):
    """Test the compatibility module."""

    def test_imports_with_modern_paths(self):
        """Test imports work with modern Home Assistant paths."""
        # Create mock modules with modern import paths
        mock_modules = {
            'homeassistant.const': MagicMock(
                CONF_ENTITY_ID='entity_id',
                ATTR_ENTITY_ID='entity_id',
                CONF_NAME='name',
                ATTR_TEMPERATURE='temperature',
                UnitOfTemperature=MagicMock(FAHRENHEIT='°F', CELSIUS='°C'),
            ),
            'homeassistant.components.climate.const': MagicMock(
                DOMAIN='climate',
                SERVICE_SET_TEMPERATURE='set_temperature',
            ),
        }
        
        # Patch sys.modules with our mocks
        with patch.dict('sys.modules', **mock_modules):
            # Force reload of the module to use our mocks
            if 'custom_components.smart_mini_split.compat' in sys.modules:
                del sys.modules['custom_components.smart_mini_split.compat']
            
            # Import the module and check that imports worked
            from custom_components.smart_mini_split.compat import (
                CONF_ENTITY_ID,
                ATTR_ENTITY_ID,
                CONF_NAME,
                ATTR_TEMPERATURE,
                UnitOfTemperature,
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
            )
            
            self.assertEqual(CONF_ENTITY_ID, 'entity_id')
            self.assertEqual(ATTR_ENTITY_ID, 'entity_id')
            self.assertEqual(CONF_NAME, 'name')
            self.assertEqual(ATTR_TEMPERATURE, 'temperature')
            self.assertEqual(UnitOfTemperature.FAHRENHEIT, '°F')
            self.assertEqual(CLIMATE_DOMAIN, 'climate')
            self.assertEqual(SERVICE_SET_TEMPERATURE, 'set_temperature')

    def test_imports_with_legacy_paths(self):
        """Test imports work with legacy Home Assistant paths."""
        # Create mock modules with legacy import paths
        mock_modules = {
            'homeassistant.const': MagicMock(
                CONF_ENTITY_ID='entity_id',
                ATTR_ENTITY_ID='entity_id',
                CONF_NAME='name',
                SERVICE_SET_TEMPERATURE='set_temperature',
            ),
            'homeassistant.components.climate.const': MagicMock(
                DOMAIN='climate',
                ATTR_TEMPERATURE='temperature',
                UnitOfTemperature=MagicMock(FAHRENHEIT='°F', CELSIUS='°C'),
            ),
        }
        
        # Remove modern imports
        mock_modules['homeassistant.const'].ATTR_TEMPERATURE = None
        mock_modules['homeassistant.const'].UnitOfTemperature = None
        
        # Patch sys.modules with our mocks
        with patch.dict('sys.modules', **mock_modules):
            # Force reload of the module to use our mocks
            if 'custom_components.smart_mini_split.compat' in sys.modules:
                del sys.modules['custom_components.smart_mini_split.compat']
            
            # Import the module and check that imports worked via fallbacks
            from custom_components.smart_mini_split.compat import (
                CONF_ENTITY_ID,
                ATTR_ENTITY_ID,
                CONF_NAME,
                ATTR_TEMPERATURE,
                UnitOfTemperature,
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
            )
            
            self.assertEqual(CONF_ENTITY_ID, 'entity_id')
            self.assertEqual(ATTR_ENTITY_ID, 'entity_id')
            self.assertEqual(CONF_NAME, 'name')
            self.assertEqual(ATTR_TEMPERATURE, 'temperature')
            self.assertEqual(UnitOfTemperature.FAHRENHEIT, '°F')
            self.assertEqual(CLIMATE_DOMAIN, 'climate')
            self.assertEqual(SERVICE_SET_TEMPERATURE, 'set_temperature')

    def test_imports_with_fallback_definitions(self):
        """Test imports work with fallback definitions when all imports fail."""
        # Create mock modules with no imports
        mock_modules = {
            'homeassistant.const': MagicMock(),
            'homeassistant.components.climate.const': MagicMock(),
        }
        
        # Set attributes to None to simulate import failures
        mock_modules['homeassistant.const'].ATTR_TEMPERATURE = None
        mock_modules['homeassistant.const'].UnitOfTemperature = None
        mock_modules['homeassistant.components.climate.const'].ATTR_TEMPERATURE = None
        mock_modules['homeassistant.components.climate.const'].UnitOfTemperature = None
        
        # Patch sys.modules with our mocks
        with patch.dict('sys.modules', **mock_modules):
            # Also patch import error when trying specific imports
            with patch('importlib.import_module', side_effect=ImportError):
                # Force reload of the module to use our mocks
                if 'custom_components.smart_mini_split.compat' in sys.modules:
                    del sys.modules['custom_components.smart_mini_split.compat']
                
                # Even with complete failure, the fallback should provide basic functionality
                from custom_components.smart_mini_split.compat import (
                    UnitOfTemperature,
                    CLIMATE_DOMAIN,
                    SERVICE_SET_TEMPERATURE,
                )
                
                # Check that fallback definitions work
                self.assertEqual(UnitOfTemperature.FAHRENHEIT, '°F')
                self.assertEqual(CLIMATE_DOMAIN, 'climate')
                self.assertEqual(SERVICE_SET_TEMPERATURE, 'set_temperature')
