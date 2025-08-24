"""Learning manager for thermostat offset compensation."""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .models import LearningConfig, TemperatureDataPoint

_LOGGER = logging.getLogger(__name__)


class LearningManager:
    """Manages learning and compensation for thermostat offset."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: LearningConfig,
    ) -> None:
        """Initialize the learning manager."""
        self._hass = hass
        self._config = config
        self._data_points: list[TemperatureDataPoint] = []
        # Track offsets separately for each mode
        self._learned_offsets: dict[str, float] = {
            "cool": 0.0,
            "heat": 0.0,
        }
        self._confidences: dict[str, float] = {
            "cool": 0.0,
            "heat": 0.0,
        }
        self._last_cleanup: datetime = dt_util.utcnow()

    @property
    def learned_offset(self) -> float:
        """Get the current learned offset for cooling mode (backward compatibility)."""
        return self._learned_offsets["cool"]

    @property
    def confidence(self) -> float:
        """Get the confidence level of the learned offset for cooling mode (backward compatibility)."""
        return self._confidences["cool"]

    def get_learned_offset(self, mode: str) -> float:
        """Get the learned offset for a specific mode."""
        return self._learned_offsets.get(mode, 0.0)

    def get_confidence(self, mode: str) -> float:
        """Get the confidence level for a specific mode."""
        return self._confidences.get(mode, 0.0)

    @property
    def data_point_count(self) -> int:
        """Get the number of stored data points."""
        return len(self._data_points)

    def collect_data_point(
        self,
        external_temperature: float,
        internal_temperature: float,
        minisplit_mode: str,
        minisplit_active: bool,
    ) -> None:
        """Collect a temperature data point for learning.
        
        Args:
            external_temperature: Temperature from external sensor
            internal_temperature: Temperature from minisplit's internal sensor
            minisplit_mode: Current mode of the minisplit (heat/cool/dry/off)
            minisplit_active: Whether the minisplit is actively running
        """
        if not self._config.enabled:
            return

        # Only collect data during heating or cooling modes when the unit is active
        # This is when the offset is most apparent and consistent
        if minisplit_mode not in ["cool", "heat"] or not minisplit_active:
            return

        try:
            data_point = TemperatureDataPoint(
                timestamp=dt_util.utcnow(),
                external_temperature=external_temperature,
                internal_temperature=internal_temperature,
                minisplit_mode=minisplit_mode,
                minisplit_active=minisplit_active,
            )
            
            self._data_points.append(data_point)
            
            _LOGGER.debug(
                "Collected data point: external=%.1f°F, internal=%.1f°F, offset=%.1f°F",
                external_temperature,
                internal_temperature,
                internal_temperature - external_temperature,
            )
            
            # Trigger cleanup and recalculation periodically
            if len(self._data_points) % 10 == 0:
                self._cleanup_old_data()
                self._recalculate_offset()
                
        except ValueError as err:
            _LOGGER.warning("Invalid data point rejected: %s", err)

    def _cleanup_old_data(self) -> None:
        """Remove data points older than the learning period."""
        if not self._data_points:
            return

        cutoff_time = dt_util.utcnow() - timedelta(days=self._config.period_days)
        initial_count = len(self._data_points)
        
        self._data_points = [
            point for point in self._data_points
            if point.timestamp > cutoff_time
        ]
        
        removed_count = initial_count - len(self._data_points)
        if removed_count > 0:
            _LOGGER.debug("Cleaned up %d old data points", removed_count)
        
        self._last_cleanup = dt_util.utcnow()

    def _recalculate_offset(self) -> None:
        """Recalculate the learned offset and confidence for each mode."""
        if not self._config.enabled:
            for mode in ["cool", "heat"]:
                self._learned_offsets[mode] = 0.0
                self._confidences[mode] = 0.0
            return

        # Calculate offsets separately for each mode
        for mode in ["cool", "heat"]:
            mode_data_points = [
                point for point in self._data_points
                if point.minisplit_mode == mode
            ]

            if len(mode_data_points) < self._config.min_data_points:
                self._learned_offsets[mode] = 0.0
                self._confidences[mode] = 0.0
                continue

            # Calculate offsets for this mode
            offsets = [
                point.internal_temperature - point.external_temperature
                for point in mode_data_points
            ]

            if not offsets:
                self._learned_offsets[mode] = 0.0
                self._confidences[mode] = 0.0
                continue

            # Remove outliers using interquartile range method
            filtered_offsets = self._remove_outliers(offsets)
            
            if len(filtered_offsets) < self._config.min_data_points // 2:
                _LOGGER.warning(
                    "Too many outliers removed for %s mode, using all data points for offset calculation",
                    mode
                )
                filtered_offsets = offsets

            # Calculate mean offset
            mean_offset = statistics.mean(filtered_offsets)
            
            # Clamp offset to reasonable bounds
            self._learned_offsets[mode] = max(
                -self._config.max_offset,
                min(self._config.max_offset, mean_offset)
            )

            # Calculate confidence based on data consistency and quantity
            self._confidences[mode] = self._calculate_confidence(filtered_offsets)

            _LOGGER.info(
                "Updated learned offset for %s mode: %.2f°F (confidence: %.1f%%, %d data points)",
                mode,
                self._learned_offsets[mode],
                self._confidences[mode] * 100,
                len(filtered_offsets),
            )

    def _remove_outliers(self, values: list[float]) -> list[float]:
        """Remove outliers using the interquartile range method."""
        if len(values) < 4:
            return values

        sorted_values = sorted(values)
        n = len(sorted_values)
        
        # Calculate quartiles
        q1_idx = n // 4
        q3_idx = 3 * n // 4
        q1 = sorted_values[q1_idx]
        q3 = sorted_values[q3_idx]
        
        # Calculate IQR and bounds
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        # Filter outliers
        filtered = [v for v in values if lower_bound <= v <= upper_bound]
        
        outlier_count = len(values) - len(filtered)
        if outlier_count > 0:
            _LOGGER.debug("Removed %d outliers from offset calculation", outlier_count)
        
        return filtered

    def _calculate_confidence(self, offsets: list[float]) -> float:
        """Calculate confidence level based on data quantity and consistency."""
        if not offsets:
            return 0.0

        # Base confidence on data quantity
        data_confidence = min(1.0, len(offsets) / (self._config.min_data_points * 2))
        
        # Adjust confidence based on data consistency (lower standard deviation = higher confidence)
        if len(offsets) > 1:
            std_dev = statistics.stdev(offsets)
            # Normalize standard deviation (assume good consistency if std_dev < 1.0°F)
            consistency_confidence = max(0.0, 1.0 - (std_dev / 2.0))
        else:
            consistency_confidence = 0.5

        # Combine both factors
        combined_confidence = (data_confidence * 0.6) + (consistency_confidence * 0.4)
        
        return min(1.0, combined_confidence)

    def get_adjusted_target_temperature(self, target_temperature: float, mode: str = "cool") -> float:
        """Get target temperature adjusted for learned offset.
        
        Args:
            target_temperature: The desired room temperature
            mode: The current mode (heat/cool), defaults to "cool" for backward compatibility
            
        Returns:
            Adjusted temperature to send to the minisplit
        """
        if not self._config.enabled or mode not in self._learned_offsets:
            return target_temperature

        confidence = self._confidences.get(mode, 0.0)
        if confidence < self._config.confidence_threshold:
            return target_temperature

        learned_offset = self._learned_offsets[mode]

        # Adjust the target temperature by the learned offset
        # If internal sensor reads 5°F higher, we need to set target 5°F lower
        adjusted = target_temperature - learned_offset
        
        _LOGGER.debug(
            "Adjusted target temperature for %s mode: %.1f°F -> %.1f°F (offset: %.2f°F)",
            mode,
            target_temperature,
            adjusted,
            learned_offset,
        )
        
        return adjusted

    def get_status_info(self) -> dict[str, Any]:
        """Get current learning status information."""
        # Count data points by mode
        cool_data_points = len([p for p in self._data_points if p.minisplit_mode == "cool"])
        heat_data_points = len([p for p in self._data_points if p.minisplit_mode == "heat"])
        
        return {
            "enabled": self._config.enabled,
            "learned_offset": self._learned_offsets["cool"],  # Backward compatibility
            "confidence": self._confidences["cool"],  # Backward compatibility
            "learned_offsets": self._learned_offsets.copy(),
            "confidences": self._confidences.copy(),
            "data_points": len(self._data_points),
            "data_points_by_mode": {
                "cool": cool_data_points,
                "heat": heat_data_points,
            },
            "min_data_points": self._config.min_data_points,
            "confidence_threshold": self._config.confidence_threshold,
            "learning_period_days": self._config.period_days,
            "is_learning_active": {
                "cool": (
                    self._config.enabled and 
                    self._confidences["cool"] >= self._config.confidence_threshold
                ),
                "heat": (
                    self._config.enabled and 
                    self._confidences["heat"] >= self._config.confidence_threshold
                ),
            },
        }

    def force_recalculation(self) -> None:
        """Force immediate recalculation of offset and cleanup."""
        self._cleanup_old_data()
        self._recalculate_offset()

    def reset_learning_data(self) -> None:
        """Reset all learning data and start fresh."""
        _LOGGER.info("Resetting all learning data")
        self._data_points.clear()
        for mode in ["cool", "heat"]:
            self._learned_offsets[mode] = 0.0
            self._confidences[mode] = 0.0

    def update_config(self, config: LearningConfig) -> None:
        """Update learning configuration."""
        self._config = config
        _LOGGER.info("Updated learning configuration")
        
        # Trigger immediate recalculation with new config
        self.force_recalculation()