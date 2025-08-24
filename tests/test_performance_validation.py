"""Performance validation tests for the Smart Thermostat Controller."""
from __future__ import annotations

import pytest
import time
import asyncio
import psutil
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.climate import SmartThermostatClimate
from custom_components.smart_thermostat_controller.coordinator import SmartThermostatCoordinator
from custom_components.smart_thermostat_controller.control_manager import ControlManager
from custom_components.smart_thermostat_controller.learning_manager import LearningManager
from custom_components.smart_thermostat_controller.const import (
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
)
from custom_components.smart_thermostat_controller.models import (
    ControllerState,
    SmartThermostatConfig,
    SensorReadings,
    TemperatureDataPoint,
    LearningConfig,
)

pytestmark = pytest.mark.asyncio


class TestDataUpdateFrequencyPerformance:
    """Test data update frequency and performance requirements."""

    async def test_coordinator_update_performance_under_load(self, mock_hass, mock_config_entry):
        """Test coordinator update performance under high load conditions."""
        # Setup mock sensors
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.0"
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        minisplit_state.attributes = {"current_temperature": 77.0}
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            coordinator._away_mode = False
            
            # Performance test: 100 rapid updates
            start_time = time.time()
            update_times = []
            
            for i in range(100):
                update_start = time.time()
                await coordinator._async_update_data()
                update_end = time.time()
                update_times.append(update_end - update_start)
            
            total_time = time.time() - start_time
            avg_update_time = sum(update_times) / len(update_times)
            max_update_time = max(update_times)
            
            # Performance assertions
            assert avg_update_time < 0.050, f"Average update time {avg_update_time:.3f}s exceeds 50ms limit"
            assert max_update_time < 0.100, f"Max update time {max_update_time:.3f}s exceeds 100ms limit"
            assert total_time < 10.0, f"Total time for 100 updates {total_time:.3f}s exceeds 10s limit"
            
            print(f"Performance metrics:")
            print(f"  Average update time: {avg_update_time*1000:.1f}ms")
            print(f"  Max update time: {max_update_time*1000:.1f}ms")
            print(f"  Total time for 100 updates: {total_time:.2f}s")

    async def test_control_decision_performance_benchmark(self, mock_hass, integration_config):
        """Benchmark control decision performance."""
        config = SmartThermostatConfig.from_config_entry(integration_config)
        control_manager = ControlManager(mock_hass, config)
        
        # Create test data
        sensor_readings = SensorReadings(
            temperature=75.0,
            humidity=55.0,
            timestamp=dt_util.utcnow(),
            temperature_available=True,
            humidity_available=True,
        )
        
        controller_state = ControllerState(
            current_mode=HVAC_MODE_OFF,
            target_temperature=72.0,
            current_temperature=75.0,
            current_humidity=55.0,
            last_mode_change=None,
            learned_offset=5.0,
            offset_confidence=0.8,
            manual_override=False,
            cooldown_remaining=0,
            is_available=True,
        )
        
        # Performance test: 1000 control decisions
        start_time = time.time()
        decision_times = []
        
        for i in range(1000):
            decision_start = time.time()
            action = control_manager.calculate_required_action(sensor_readings, controller_state)
            decision_end = time.time()
            decision_times.append(decision_end - decision_start)
            assert action is not None
        
        total_time = time.time() - start_time
        avg_decision_time = sum(decision_times) / len(decision_times)
        max_decision_time = max(decision_times)
        
        # Performance assertions
        assert avg_decision_time < 0.005, f"Average decision time {avg_decision_time:.4f}s exceeds 5ms limit"
        assert max_decision_time < 0.020, f"Max decision time {max_decision_time:.4f}s exceeds 20ms limit"
        assert total_time < 10.0, f"Total time for 1000 decisions {total_time:.3f}s exceeds 10s limit"
        
        print(f"Control decision performance:")
        print(f"  Average decision time: {avg_decision_time*1000:.2f}ms")
        print(f"  Max decision time: {max_decision_time*1000:.2f}ms")
        print(f"  Decisions per second: {1000/total_time:.0f}")

    def test_learning_algorithm_performance_with_large_dataset(self):
        """Test learning algorithm performance with large historical datasets."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=30,
            min_data_points=100,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Add large dataset (30 days * 48 readings per day = 1440 data points)
        now = dt_util.utcnow()
        data_generation_start = time.time()
        
        for day in range(30):
            for hour in range(24):
                for minute in [0, 30]:  # Every 30 minutes
                    timestamp = now - timedelta(days=day, hours=hour, minutes=minute)
                    learning_manager.collect_data_point(
                        external_temperature=72.0 + (day % 5) * 0.1,  # Slight variation
                        internal_temperature=77.0 + (day % 5) * 0.1,
                        minisplit_mode="cool",
                        minisplit_active=True,
                    )
        
        data_generation_time = time.time() - data_generation_start
        
        # Test recalculation performance
        recalc_start = time.time()
        learning_manager.force_recalculation()
        recalc_time = time.time() - recalc_start
        
        # Test cleanup performance
        cleanup_start = time.time()
        learning_manager._cleanup_old_data()
        cleanup_time = time.time() - cleanup_start
        
        # Performance assertions
        assert data_generation_time < 5.0, f"Data generation took {data_generation_time:.2f}s, exceeds 5s limit"
        assert recalc_time < 1.0, f"Recalculation took {recalc_time:.3f}s, exceeds 1s limit"
        assert cleanup_time < 0.5, f"Cleanup took {cleanup_time:.3f}s, exceeds 0.5s limit"
        
        print(f"Learning algorithm performance with {learning_manager.data_point_count} data points:")
        print(f"  Data generation time: {data_generation_time:.2f}s")
        print(f"  Recalculation time: {recalc_time:.3f}s")
        print(f"  Cleanup time: {cleanup_time:.3f}s")

    async def test_concurrent_operations_performance(self, mock_hass, mock_config_entry):
        """Test performance under concurrent operations."""
        # Setup mock sensors
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.0"
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        minisplit_state.attributes = {"current_temperature": 77.0}
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            coordinator._away_mode = False

            # Define concurrent operations
            async def update_operation():
                return await coordinator._async_update_data()
            
            async def mode_change_operation():
                await coordinator.record_mode_change("cool")
            
            async def config_update_operation():
                new_config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
                await coordinator.async_update_config(new_config)
            
            # Run concurrent operations
            start_time = time.time()
            
            tasks = []
            for _ in range(10):  # 10 of each operation type
                tasks.append(asyncio.create_task(update_operation()))
                tasks.append(asyncio.create_task(mode_change_operation()))
                tasks.append(asyncio.create_task(config_update_operation()))
            
            # Wait for all tasks
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            total_time = time.time() - start_time
            
            # Check for exceptions
            exceptions = [r for r in results if isinstance(r, Exception)]
            assert len(exceptions) == 0, f"Concurrent operations failed: {exceptions}"
            
            # Performance assertion
            assert total_time < 5.0, f"Concurrent operations took {total_time:.2f}s, exceeds 5s limit"
            
            print(f"Concurrent operations performance:")
            print(f"  Total time for 30 concurrent operations: {total_time:.2f}s")
            print(f"  Operations per second: {30/total_time:.1f}")


class TestMemoryUsageValidation:
    """Test memory usage and resource consumption."""

    def test_memory_usage_with_historical_data_growth(self):
        """Test memory usage as historical data grows."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=30,
            min_data_points=100,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        
        # Measure initial memory
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Add data in batches and measure memory growth
        batch_size = 500
        memory_measurements = []
        
        for batch in range(5):  # 5 batches of 500 = 2500 data points
            # Add batch of data
            now = dt_util.utcnow()
            for i in range(batch_size):
                timestamp = now - timedelta(minutes=i + batch * batch_size)
                learning_manager.collect_data_point(
                    external_temperature=72.0 + (i % 10) * 0.1,
                    internal_temperature=77.0 + (i % 10) * 0.1,
                    minisplit_mode="cool",
                    minisplit_active=True,
                )
            
            # Measure memory after batch
            current_memory = process.memory_info().rss / 1024 / 1024  # MB
            memory_growth = current_memory - initial_memory
            memory_measurements.append({
                'batch': batch + 1,
                'data_points': learning_manager.data_point_count,
                'memory_mb': current_memory,
                'growth_mb': memory_growth
            })
        
        # Test cleanup effectiveness
        pre_cleanup_memory = process.memory_info().rss / 1024 / 1024
        learning_manager.force_recalculation()  # Triggers cleanup
        post_cleanup_memory = process.memory_info().rss / 1024 / 1024
        
        # Memory usage assertions
        final_growth = memory_measurements[-1]['growth_mb']
        assert final_growth < 50, f"Memory growth {final_growth:.1f}MB exceeds 50MB limit"
        
        # Verify cleanup reduces memory or keeps it stable
        memory_change = post_cleanup_memory - pre_cleanup_memory
        assert memory_change < 10, f"Memory increased {memory_change:.1f}MB after cleanup"
        
        print(f"Memory usage validation:")
        for measurement in memory_measurements:
            print(f"  Batch {measurement['batch']}: {measurement['data_points']} points, "
                  f"{measurement['memory_mb']:.1f}MB (+{measurement['growth_mb']:.1f}MB)")
        print(f"  After cleanup: {post_cleanup_memory:.1f}MB")

    def test_memory_leak_detection_over_time(self):
        """Test for memory leaks during extended operation."""
        mock_hass = MagicMock()
        learning_config = LearningConfig(
            enabled=True,
            period_days=7,
            min_data_points=50,
            confidence_threshold=0.7,
            max_offset=10.0,
        )
        
        learning_manager = LearningManager(mock_hass, learning_config)
        process = psutil.Process(os.getpid())
        
        # Simulate extended operation with data cycling
        memory_samples = []
        
        for cycle in range(10):  # 10 cycles of operation
            # Add data
            now = dt_util.utcnow()
            for i in range(100):
                timestamp = now - timedelta(minutes=i)
                learning_manager.collect_data_point(
                    external_temperature=72.0,
                    internal_temperature=77.0,
                    minisplit_mode="cool",
                    minisplit_active=True,
                )
            
            # Force cleanup and recalculation
            learning_manager.force_recalculation()
            
            # Measure memory
            memory_mb = process.memory_info().rss / 1024 / 1024
            memory_samples.append(memory_mb)
        
        # Check for memory leak (increasing trend)
        if len(memory_samples) >= 3:
            # Calculate trend (should be stable, not increasing)
            early_avg = sum(memory_samples[:3]) / 3
            late_avg = sum(memory_samples[-3:]) / 3
            memory_increase = late_avg - early_avg
            
            assert memory_increase < 10, f"Potential memory leak detected: {memory_increase:.1f}MB increase"
            
            print(f"Memory leak detection:")
            print(f"  Early cycles average: {early_avg:.1f}MB")
            print(f"  Late cycles average: {late_avg:.1f}MB")
            print(f"  Memory change: {memory_increase:+.1f}MB")

    async def test_resource_usage_under_stress(self, mock_hass, mock_config_entry):
        """Test resource usage under stress conditions."""
        # Setup mock sensors
        temp_state = MagicMock(spec=State)
        temp_state.state = "72.0"
        temp_state.last_updated = dt_util.utcnow()
        
        humidity_state = MagicMock(spec=State)
        humidity_state.state = "45.0"
        humidity_state.last_updated = dt_util.utcnow()
        
        minisplit_state = MagicMock(spec=State)
        minisplit_state.state = "cool"
        minisplit_state.attributes = {"current_temperature": 77.0}
        
        mock_hass.states.get.side_effect = lambda entity_id: {
            "sensor.room_temp": temp_state,
            "sensor.room_humidity": humidity_state,
            "climate.bedroom_ac": minisplit_state,
        }.get(entity_id)
        
        # Create coordinator
        with patch('custom_components.smart_thermostat_controller.coordinator.Store'), \
             patch('homeassistant.helpers.frame.report_usage'), \
             patch('homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__', return_value=None):
            
            coordinator = SmartThermostatCoordinator.__new__(SmartThermostatCoordinator)
            coordinator.hass = mock_hass
            coordinator.config = SmartThermostatConfig.from_config_entry(mock_config_entry.data)
            coordinator.entry = mock_config_entry
            coordinator._historical_data = []
            coordinator._learned_offset = 5.0
            coordinator._offset_confidence = 0.8
            coordinator._last_mode_change = None
            coordinator._manual_override = False
            coordinator._store = MagicMock()
            coordinator._store.async_load = AsyncMock(return_value=None)
            coordinator._store.async_save = AsyncMock()
            
            # Initialize logging and error handling
            from custom_components.smart_thermostat_controller.logging_utils import create_logger
            from custom_components.smart_thermostat_controller.error_handling import ErrorRecoveryManager
            coordinator._logger = create_logger(mock_hass, "coordinator")
            coordinator._error_manager = ErrorRecoveryManager(mock_hass, coordinator._logger)
            coordinator._away_mode = False

            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss / 1024 / 1024
            initial_cpu_percent = process.cpu_percent()
            
            # Stress test: rapid updates for 30 seconds
            start_time = time.time()
            update_count = 0
            
            while time.time() - start_time < 30:  # 30 seconds
                await coordinator._async_update_data()
                update_count += 1
                
                # Brief pause to allow CPU measurement
                await asyncio.sleep(0.01)
            
            final_memory = process.memory_info().rss / 1024 / 1024
            final_cpu_percent = process.cpu_percent()
            
            # Resource usage assertions
            memory_growth = final_memory - initial_memory
            assert memory_growth < 20, f"Memory growth {memory_growth:.1f}MB exceeds 20MB limit during stress test"
            
            updates_per_second = update_count / 30
            assert updates_per_second > 10, f"Update rate {updates_per_second:.1f}/s too low during stress test"
            
            print(f"Stress test results (30 seconds):")
            print(f"  Updates performed: {update_count}")
            print(f"  Updates per second: {updates_per_second:.1f}")
            print(f"  Memory growth: {memory_growth:.1f}MB")
            print(f"  CPU usage: {final_cpu_percent:.1f}%")


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.fixture
def integration_config():
    """Create integration test configuration."""
    return {
        "external_temperature_sensor": "sensor.room_temp",
        "external_humidity_sensor": "sensor.room_humidity", 
        "minisplit_climate_entity": "climate.bedroom_ac",
        "target_temperature": 72.0,
        "humidity_max_threshold": 60.0,
        "humidity_min_threshold": 40.0,
        "temperature_deadband": 1.0,
        "cooldown_period": 300,
        "learning_enabled": True,
        "learning_period_days": 7,
        "default_cooling_offset": 5.0,
    }


@pytest.fixture
def mock_config_entry(integration_config):
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_performance"
    entry.data = integration_config
    return entry


if __name__ == "__main__":
    # Run performance tests directly
    pytest.main([__file__, "-v", "-s"])
