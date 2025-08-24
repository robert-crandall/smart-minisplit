"""Tests for the learning manager."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.smart_thermostat_controller.learning_manager import LearningManager
from custom_components.smart_thermostat_controller.models import LearningConfig, TemperatureDataPoint


@pytest.fixture
def hass():
    """Mock Home Assistant instance."""
    return Mock(spec=HomeAssistant)


@pytest.fixture
def learning_config():
    """Default learning configuration."""
    return LearningConfig(
        enabled=True,
        period_days=7,
        min_data_points=10,
        confidence_threshold=0.7,
        max_offset=10.0,
    )


@pytest.fixture
def learning_manager(hass, learning_config):
    """Learning manager instance."""
    return LearningManager(hass, learning_config)


class TestLearningManagerInitialization:
    """Test learning manager initialization."""

    def test_initialization(self, hass, learning_config):
        """Test proper initialization."""
        manager = LearningManager(hass, learning_config)
        
        assert manager.learned_offset == 0.0
        assert manager.confidence == 0.0
        assert manager.data_point_count == 0

    def test_initialization_with_disabled_config(self, hass):
        """Test initialization with disabled learning."""
        config = LearningConfig(
            enabled=False,
            period_days=7,
            min_data_points=10,
        )
        manager = LearningManager(hass, config)
        
        assert manager.learned_offset == 0.0
        assert manager.confidence == 0.0


class TestDataCollection:
    """Test data collection functionality."""

    def test_collect_valid_data_point(self, learning_manager):
        """Test collecting a valid data point."""
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        assert learning_manager.data_point_count == 1

    def test_collect_data_point_heat_mode(self, learning_manager):
        """Test that data points are collected in heat mode."""
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="heat",
            minisplit_active=True,
        )
        
        assert learning_manager.data_point_count == 1

    def test_collect_data_point_wrong_mode(self, learning_manager):
        """Test that data points are not collected in wrong mode."""
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="dry",
            minisplit_active=True,
        )
        
        assert learning_manager.data_point_count == 0

    def test_collect_data_point_inactive_unit(self, learning_manager):
        """Test that data points are not collected when unit is inactive."""
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=False,
        )
        
        assert learning_manager.data_point_count == 0

    def test_collect_data_point_disabled_learning(self, hass):
        """Test that data points are not collected when learning is disabled."""
        config = LearningConfig(
            enabled=False,
            period_days=7,
            min_data_points=10,
        )
        manager = LearningManager(hass, config)
        
        manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        assert manager.data_point_count == 0

    def test_collect_invalid_temperature_data(self, learning_manager):
        """Test handling of invalid temperature data."""
        # This should not raise an exception but should log a warning
        learning_manager.collect_data_point(
            external_temperature=200.0,  # Invalid temperature
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        assert learning_manager.data_point_count == 0


class TestOffsetCalculation:
    """Test offset calculation and learning algorithms."""

    def test_insufficient_data_points(self, learning_manager):
        """Test behavior with insufficient data points."""
        # Add only a few data points (less than min_data_points)
        for i in range(5):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        assert learning_manager.learned_offset == 0.0
        assert learning_manager.confidence == 0.0

    def test_consistent_offset_calculation_cooling(self, learning_manager):
        """Test offset calculation with consistent cooling data."""
        # Add consistent data points with 5°F offset for cooling
        for i in range(20):
            learning_manager.collect_data_point(
                external_temperature=72.0 + (i % 3),  # Small variation
                internal_temperature=77.0 + (i % 3),  # Consistent 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        assert abs(learning_manager.get_learned_offset("cool") - 5.0) < 0.1
        assert learning_manager.get_confidence("cool") > 0.7
        # Heating should still be 0 with no data
        assert learning_manager.get_learned_offset("heat") == 0.0
        assert learning_manager.get_confidence("heat") == 0.0

    def test_consistent_offset_calculation_heating(self, learning_manager):
        """Test offset calculation with consistent heating data."""
        # Add consistent data points with -3°F offset for heating
        for i in range(20):
            learning_manager.collect_data_point(
                external_temperature=72.0 + (i % 3),  # Small variation
                internal_temperature=69.0 + (i % 3),  # Consistent -3°F offset
                minisplit_mode="heat",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        assert abs(learning_manager.get_learned_offset("heat") - (-3.0)) < 0.1
        assert learning_manager.get_confidence("heat") > 0.7
        # Cooling should still be 0 with no data
        assert learning_manager.get_learned_offset("cool") == 0.0
        assert learning_manager.get_confidence("cool") == 0.0

    def test_variable_offset_calculation(self, learning_manager):
        """Test offset calculation with variable data."""
        # Add data points with varying offsets for cooling
        offsets = [4.0, 5.0, 6.0, 4.5, 5.5, 4.8, 5.2, 4.7, 5.3, 4.9, 5.1]
        for i, offset in enumerate(offsets * 2):  # 22 data points
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=72.0 + offset,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should be close to the mean of the offsets (5.0)
        assert abs(learning_manager.get_learned_offset("cool") - 5.0) < 0.2
        assert learning_manager.get_confidence("cool") > 0.5

    def test_mixed_mode_offset_calculation(self, learning_manager):
        """Test offset calculation with data from both modes."""
        # Add cooling data with +5°F offset
        for i in range(15):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # +5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Add heating data with -2°F offset
        for i in range(15):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=70.0,  # -2°F offset
                minisplit_mode="heat",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Each mode should have its own offset
        assert abs(learning_manager.get_learned_offset("cool") - 5.0) < 0.1
        assert abs(learning_manager.get_learned_offset("heat") - (-2.0)) < 0.1
        assert learning_manager.get_confidence("cool") > 0.5
        assert learning_manager.get_confidence("heat") > 0.5

    def test_outlier_removal(self, learning_manager):
        """Test that outliers are properly removed."""
        # Add mostly consistent data with some outliers
        for i in range(15):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Add outliers
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=90.0,  # 18°F offset (outlier)
            minisplit_mode="cool",
            minisplit_active=True,
        )
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=65.0,  # -7°F offset (outlier)
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        learning_manager.force_recalculation()
        
        # Should still be close to 5°F despite outliers
        assert abs(learning_manager.get_learned_offset("cool") - 5.0) < 0.5

    def test_max_offset_clamping(self, learning_manager):
        """Test that calculated offset is clamped to max_offset."""
        # Add data points with very large offset
        for i in range(20):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=85.0,  # 13°F offset (exceeds max_offset of 10°F)
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should be clamped to max_offset
        assert learning_manager.get_learned_offset("cool") == 10.0


class TestConfidenceCalculation:
    """Test confidence calculation logic."""

    def test_confidence_with_consistent_data(self, learning_manager):
        """Test confidence calculation with very consistent data."""
        # Add very consistent data points
        for i in range(30):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,  # Exactly 5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should have high confidence due to consistency and quantity
        assert learning_manager.get_confidence("cool") > 0.8

    def test_confidence_with_inconsistent_data(self, learning_manager):
        """Test confidence calculation with inconsistent data."""
        # Add inconsistent data points
        offsets = [3.0, 7.0, 2.0, 8.0, 4.0, 6.0, 1.0, 9.0, 5.0, 5.5]
        for i, offset in enumerate(offsets * 2):  # 20 data points
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=72.0 + offset,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should have lower confidence due to inconsistency
        assert learning_manager.get_confidence("cool") < 0.7

    def test_confidence_with_minimal_data(self, learning_manager):
        """Test confidence calculation with minimal data."""
        # Add exactly min_data_points
        for i in range(10):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should have moderate confidence
        assert 0.3 < learning_manager.get_confidence("cool") < 0.8


class TestTemperatureAdjustment:
    """Test temperature adjustment functionality."""

    def test_adjustment_with_sufficient_confidence_cooling(self, learning_manager):
        """Test temperature adjustment when confidence is sufficient for cooling."""
        # Set up learning data with 5°F offset and high confidence
        for i in range(30):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should adjust target temperature by learned offset
        adjusted = learning_manager.get_adjusted_target_temperature(72.0, "cool")
        assert abs(adjusted - 67.0) < 0.1  # 72 - 5 = 67

    def test_adjustment_with_sufficient_confidence_heating(self, learning_manager):
        """Test temperature adjustment when confidence is sufficient for heating."""
        # Set up learning data with -3°F offset and high confidence
        for i in range(30):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=69.0,  # -3°F offset
                minisplit_mode="heat",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should adjust target temperature by learned offset
        adjusted = learning_manager.get_adjusted_target_temperature(72.0, "heat")
        assert abs(adjusted - 75.0) < 0.1  # 72 - (-3) = 75

    def test_no_adjustment_with_low_confidence(self, learning_manager):
        """Test no temperature adjustment when confidence is low."""
        # Add inconsistent data for low confidence
        offsets = [1.0, 9.0, 2.0, 8.0, 3.0, 7.0]
        for offset in offsets:
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=72.0 + offset,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should not adjust due to low confidence
        adjusted = learning_manager.get_adjusted_target_temperature(72.0, "cool")
        assert adjusted == 72.0

    def test_no_adjustment_when_disabled(self, hass):
        """Test no temperature adjustment when learning is disabled."""
        config = LearningConfig(
            enabled=False,
            period_days=7,
            min_data_points=10,
        )
        manager = LearningManager(hass, config)
        
        adjusted = manager.get_adjusted_target_temperature(72.0, "cool")
        assert adjusted == 72.0

    def test_no_adjustment_for_unknown_mode(self, learning_manager):
        """Test no temperature adjustment for unknown mode."""
        adjusted = learning_manager.get_adjusted_target_temperature(72.0, "dry")
        assert adjusted == 72.0


class TestDataCleanup:
    """Test data cleanup functionality."""

    def test_cleanup_old_data(self, learning_manager):
        """Test cleanup of old data points."""
        # Mock old data points
        old_time = dt_util.utcnow() - timedelta(days=10)
        recent_time = dt_util.utcnow() - timedelta(hours=1)
        
        # Add old data point manually
        old_point = TemperatureDataPoint(
            timestamp=old_time,
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        learning_manager._data_points.append(old_point)
        
        # Add recent data point
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        assert learning_manager.data_point_count == 2
        
        # Force cleanup
        learning_manager._cleanup_old_data()
        
        # Should only have recent data point
        assert learning_manager.data_point_count == 1

    def test_automatic_cleanup_trigger(self, learning_manager):
        """Test that cleanup is triggered automatically."""
        # Add enough data points to trigger cleanup (every 10 points)
        for i in range(11):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        # Should have triggered cleanup and recalculation
        assert learning_manager.data_point_count == 11


class TestStatusAndManagement:
    """Test status reporting and management functions."""

    def test_get_status_info(self, learning_manager):
        """Test status information reporting."""
        status = learning_manager.get_status_info()
        
        assert "enabled" in status
        assert "learned_offset" in status  # Backward compatibility
        assert "confidence" in status  # Backward compatibility
        assert "learned_offsets" in status
        assert "confidences" in status
        assert "data_points" in status
        assert "data_points_by_mode" in status
        assert "is_learning_active" in status
        
        assert status["enabled"] is True
        assert status["data_points"] == 0
        assert "cool" in status["learned_offsets"]
        assert "heat" in status["learned_offsets"]
        assert "cool" in status["is_learning_active"]
        assert "heat" in status["is_learning_active"]

    def test_reset_learning_data(self, learning_manager):
        """Test resetting learning data."""
        # Add some data
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        assert learning_manager.data_point_count == 1
        
        # Reset data
        learning_manager.reset_learning_data()
        
        assert learning_manager.data_point_count == 0
        assert learning_manager.get_learned_offset("cool") == 0.0
        assert learning_manager.get_learned_offset("heat") == 0.0
        assert learning_manager.get_confidence("cool") == 0.0
        assert learning_manager.get_confidence("heat") == 0.0

    def test_update_config(self, learning_manager):
        """Test updating configuration."""
        new_config = LearningConfig(
            enabled=True,
            period_days=14,
            min_data_points=20,
            confidence_threshold=0.8,
            max_offset=8.0,
        )
        
        learning_manager.update_config(new_config)
        
        # Should trigger recalculation with new config
        status = learning_manager.get_status_info()
        assert status["learning_period_days"] == 14
        assert status["min_data_points"] == 20
        assert status["confidence_threshold"] == 0.8


class TestModeBasedLearning:
    """Test mode-based learning functionality."""

    def test_get_learned_offset_for_modes(self, learning_manager):
        """Test getting learned offset for specific modes."""
        assert learning_manager.get_learned_offset("cool") == 0.0
        assert learning_manager.get_learned_offset("heat") == 0.0
        assert learning_manager.get_learned_offset("unknown") == 0.0

    def test_get_confidence_for_modes(self, learning_manager):
        """Test getting confidence for specific modes."""
        assert learning_manager.get_confidence("cool") == 0.0
        assert learning_manager.get_confidence("heat") == 0.0
        assert learning_manager.get_confidence("unknown") == 0.0

    def test_backward_compatibility_properties(self, learning_manager):
        """Test that backward compatibility properties work."""
        # Add some cooling data
        for i in range(15):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Backward compatibility properties should return cooling values
        assert learning_manager.learned_offset == learning_manager.get_learned_offset("cool")
        assert learning_manager.confidence == learning_manager.get_confidence("cool")

    def test_backward_compatibility_temperature_adjustment(self, learning_manager):
        """Test that temperature adjustment works without specifying mode."""
        # Add some cooling data
        for i in range(30):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should default to cooling mode when no mode specified
        adjusted_with_mode = learning_manager.get_adjusted_target_temperature(72.0, "cool")
        adjusted_without_mode = learning_manager.get_adjusted_target_temperature(72.0)
        
        assert adjusted_with_mode == adjusted_without_mode

    def test_status_info_includes_mode_data(self, learning_manager):
        """Test that status info includes mode-specific data."""
        # Add data for both modes
        for i in range(12):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        for i in range(8):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=69.0,
                minisplit_mode="heat",
                minisplit_active=True,
            )
        
        status = learning_manager.get_status_info()
        
        assert status["data_points_by_mode"]["cool"] == 12
        assert status["data_points_by_mode"]["heat"] == 8
        assert status["data_points"] == 20


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_data_points_list(self, learning_manager):
        """Test behavior with empty data points list."""
        learning_manager.force_recalculation()
        
        assert learning_manager.get_learned_offset("cool") == 0.0
        assert learning_manager.get_learned_offset("heat") == 0.0
        assert learning_manager.get_confidence("cool") == 0.0
        assert learning_manager.get_confidence("heat") == 0.0

    def test_single_data_point(self, learning_manager):
        """Test behavior with single data point."""
        learning_manager.collect_data_point(
            external_temperature=72.0,
            internal_temperature=77.0,
            minisplit_mode="cool",
            minisplit_active=True,
        )
        
        learning_manager.force_recalculation()
        
        # Should not calculate offset with insufficient data
        assert learning_manager.get_learned_offset("cool") == 0.0
        assert learning_manager.get_confidence("cool") == 0.0

    def test_all_identical_values(self, learning_manager):
        """Test behavior when all data points are identical."""
        for i in range(20):
            learning_manager.collect_data_point(
                external_temperature=72.0,
                internal_temperature=77.0,
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        # Should calculate correct offset with perfect consistency
        assert abs(learning_manager.get_learned_offset("cool") - 5.0) < 0.01
        assert learning_manager.get_confidence("cool") > 0.9

    def test_negative_offset(self, learning_manager):
        """Test handling of negative offset (internal sensor reads lower)."""
        for i in range(20):
            learning_manager.collect_data_point(
                external_temperature=77.0,
                internal_temperature=72.0,  # -5°F offset
                minisplit_mode="cool",
                minisplit_active=True,
            )
        
        learning_manager.force_recalculation()
        
        assert abs(learning_manager.get_learned_offset("cool") - (-5.0)) < 0.1
        
        # Adjustment should add the offset
        adjusted = learning_manager.get_adjusted_target_temperature(72.0, "cool")
        assert abs(adjusted - 77.0) < 0.1  # 72 - (-5) = 77