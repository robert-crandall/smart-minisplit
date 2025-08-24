"""Cooldown manager for equipment protection."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from homeassistant.util import dt as dt_util

from .const import DEFAULT_COOLDOWN_PERIOD

_LOGGER = logging.getLogger(__name__)


class CooldownManager:
    """Manages cooldown periods to protect equipment from rapid mode switching."""

    def __init__(self, cooldown_period: int = DEFAULT_COOLDOWN_PERIOD) -> None:
        """Initialize the cooldown manager.
        
        Args:
            cooldown_period: Minimum seconds between mode changes
        """
        self._cooldown_period = cooldown_period
        self._last_mode_change: Optional[datetime] = None
        self._current_mode: Optional[str] = None
        self._startup_time = dt_util.utcnow()
        self._mode_change_history: Dict[str, datetime] = {}
        
        _LOGGER.debug(
            "CooldownManager initialized with %d second cooldown period",
            cooldown_period
        )

    @property
    def cooldown_period(self) -> int:
        """Get the current cooldown period in seconds."""
        return self._cooldown_period

    def set_cooldown_period(self, period: int) -> None:
        """Update the cooldown period.
        
        Args:
            period: New cooldown period in seconds
        """
        if period < 0:
            raise ValueError("Cooldown period must be non-negative")
        
        old_period = self._cooldown_period
        self._cooldown_period = period
        
        _LOGGER.debug(
            "Cooldown period updated from %d to %d seconds",
            old_period, period
        )

    def can_change_mode(self, new_mode: str) -> bool:
        """Check if a mode change is allowed based on cooldown constraints.
        
        Args:
            new_mode: The mode to change to
            
        Returns:
            True if mode change is allowed, False if in cooldown
        """
        # Allow if this is the first mode change
        if self._last_mode_change is None:
            return self._is_startup_cooldown_complete()
        
        # Allow if changing to the same mode (no actual change)
        if new_mode == self._current_mode:
            return True
        
        # Check if enough time has passed since last change
        now = dt_util.utcnow()
        time_since_change = (now - self._last_mode_change).total_seconds()
        
        can_change = time_since_change >= self._cooldown_period
        
        _LOGGER.debug(
            "Mode change check: current=%s, new=%s, time_since_change=%.1fs, "
            "cooldown_period=%ds, can_change=%s",
            self._current_mode, new_mode, time_since_change,
            self._cooldown_period, can_change
        )
        
        return can_change

    def record_mode_change(self, new_mode: str) -> None:
        """Record a mode change timestamp.
        
        Args:
            new_mode: The mode that was changed to
        """
        now = dt_util.utcnow()
        old_mode = self._current_mode
        
        self._last_mode_change = now
        self._current_mode = new_mode
        self._mode_change_history[new_mode] = now
        
        _LOGGER.info(
            "Mode change recorded: %s -> %s at %s",
            old_mode, new_mode, now.isoformat()
        )

    def get_remaining_cooldown(self) -> int:
        """Get remaining cooldown time in seconds.
        
        Returns:
            Seconds remaining in cooldown period, 0 if no cooldown active
        """
        # Check startup cooldown first
        if not self._is_startup_cooldown_complete():
            startup_elapsed = (dt_util.utcnow() - self._startup_time).total_seconds()
            startup_remaining = max(0, self._cooldown_period - startup_elapsed)
            if startup_remaining > 0:
                return int(startup_remaining)
        
        # Check mode change cooldown
        if self._last_mode_change is None:
            return 0
        
        now = dt_util.utcnow()
        elapsed = (now - self._last_mode_change).total_seconds()
        remaining = max(0, self._cooldown_period - elapsed)
        
        return int(remaining)

    def get_cooldown_status(self) -> Dict[str, any]:
        """Get detailed cooldown status information.
        
        Returns:
            Dictionary with cooldown status details
        """
        remaining = self.get_remaining_cooldown()
        is_startup = not self._is_startup_cooldown_complete()
        
        status = {
            "in_cooldown": remaining > 0,
            "remaining_seconds": remaining,
            "cooldown_period": self._cooldown_period,
            "current_mode": self._current_mode,
            "last_mode_change": self._last_mode_change,
            "startup_cooldown": is_startup,
            "startup_time": self._startup_time,
        }
        
        return status

    def reset_startup_cooldown(self) -> None:
        """Reset the startup cooldown timer.
        
        This can be used when the integration is reloaded or restarted.
        """
        old_startup = self._startup_time
        self._startup_time = dt_util.utcnow()
        
        _LOGGER.debug(
            "Startup cooldown reset from %s to %s",
            old_startup.isoformat(), self._startup_time.isoformat()
        )

    def get_time_since_mode(self, mode: str) -> Optional[int]:
        """Get time in seconds since a specific mode was last active.
        
        Args:
            mode: The mode to check
            
        Returns:
            Seconds since mode was active, None if mode never recorded
        """
        if mode not in self._mode_change_history:
            return None
        
        now = dt_util.utcnow()
        elapsed = (now - self._mode_change_history[mode]).total_seconds()
        return int(elapsed)

    def clear_history(self) -> None:
        """Clear all mode change history.
        
        This resets the cooldown manager to initial state but preserves
        the current cooldown period setting.
        """
        _LOGGER.debug("Clearing cooldown manager history")
        
        self._last_mode_change = None
        self._current_mode = None
        self._mode_change_history.clear()
        self._startup_time = dt_util.utcnow()

    def _is_startup_cooldown_complete(self) -> bool:
        """Check if the initial startup cooldown period has elapsed.
        
        Returns:
            True if startup cooldown is complete
        """
        now = dt_util.utcnow()
        startup_elapsed = (now - self._startup_time).total_seconds()
        return startup_elapsed >= self._cooldown_period

    def __repr__(self) -> str:
        """Return string representation of cooldown manager."""
        return (
            f"CooldownManager(period={self._cooldown_period}s, "
            f"current_mode={self._current_mode}, "
            f"remaining={self.get_remaining_cooldown()}s)"
        )