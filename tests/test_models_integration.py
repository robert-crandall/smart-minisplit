"""Tests for models integration with learning manager."""
from custom_components.smart_thermostat_controller.models import SmartThermostatConfig, LearningConfig


def test_smart_thermostat_config_get_learning_config():
    """Test that SmartThermostatConfig can create LearningConfig."""
    config_data = {
        "external_temperature_sensor": "sensor.temp",
        "external_humidity_sensor": "sensor.humidity", 
        "minisplit_climate_entity": "climate.minisplit",
        "learning_enabled": True,
        "learning_period_days": 14,
    }
    
    config = SmartThermostatConfig.from_config_entry(config_data)
    learning_config = config.get_learning_config()
    
    assert isinstance(learning_config, LearningConfig)
    assert learning_config.enabled is True
    assert learning_config.period_days == 14
    assert learning_config.min_data_points == 50  # Default
    assert learning_config.confidence_threshold == 0.7  # Default
    assert learning_config.max_offset == 10.0  # Default


def test_smart_thermostat_config_get_learning_config_disabled():
    """Test LearningConfig creation when learning is disabled."""
    config_data = {
        "external_temperature_sensor": "sensor.temp",
        "external_humidity_sensor": "sensor.humidity", 
        "minisplit_climate_entity": "climate.minisplit",
        "learning_enabled": False,
        "learning_period_days": 7,
    }
    
    config = SmartThermostatConfig.from_config_entry(config_data)
    learning_config = config.get_learning_config()
    
    assert isinstance(learning_config, LearningConfig)
    assert learning_config.enabled is False
    assert learning_config.period_days == 7