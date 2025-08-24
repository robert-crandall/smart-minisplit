"""Tests for the cooldown manager."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from custom_components.smart_thermostat_controller.cooldown_manager import CooldownManager
from custom_components.smart_thermostat_controller.const import DEFAULT_COOLDOWN_PERIOD


class TestCooldownManager:
    """Test the CooldownManager class."""

    def test_initialization(self):
        """Test cooldown manager initialization."""
        # Test with default cooldown period
        manager = CooldownManager()
        assert manager.cooldown_period == DEFAULT_COOLDOWN_PERIOD
        assert manager.get_remaining_cooldown() >= 0
        
        # Test with custom cooldown period
        custom_period = 600  # 10 minutes
        manager = CooldownManager(custom_period)
        assert manager.cooldown_period == custom_period

    def test_set_cooldown_period(self):
        """Test updating cooldown period."""
        manager = CooldownManager(300)
        
        # Test valid period update
        manager.set_cooldown_period(600)
        assert manager.cooldown_period == 600
        
        # Test zero period (allowed)
        manager.set_cooldown_period(0)
        assert manager.cooldown_period == 0
        
        # Test negative period (should raise error)
        with pytest.raises(ValueError, match="Cooldown period must be non-negative"):
            manager.set_cooldown_period(-1)

    @patch('homeassistant.util.dt.utcnow')
    def test_startup_cooldown(self, mock_utcnow):
        """Test initial startup cooldown logic."""
        # Mock initial time
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(300)  # 5 minute cooldown
        
        # Should not allow mode change during startup cooldown
        assert not manager.can_change_mode("cool")
        assert manager.get_remaining_cooldown() == 300
        
        # Move time forward but not enough
        mock_utcnow.return_value = start_time + timedelta(seconds=200)
        assert not manager.can_change_mode("cool")
        assert manager.get_remaining_cooldown() == 100
        
        # Move time forward past startup cooldown
        mock_utcnow.return_value = start_time + timedelta(seconds=300)
        assert manager.can_change_mode("cool")
        assert manager.get_remaining_cooldown() == 0

    @patch('homeassistant.util.dt.utcnow')
    def test_mode_change_tracking(self, mock_utcnow):
        """Test mode change recording and tracking."""
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(300)
        
        # Skip startup cooldown
        mock_utcnow.return_value = start_time + timedelta(seconds=300)
        
        # First mode change should be allowed
        assert manager.can_change_mode("cool")
        manager.record_mode_change("cool")
        
        # Immediate second change should not be allowed
        assert not manager.can_change_mode("heat")
        assert manager.get_remaining_cooldown() == 300
        
        # Same mode change should be allowed
        assert manager.can_change_mode("cool")
        
        # Move time forward partially
        mock_utcnow.return_value = start_time + timedelta(seconds=450)
        assert not manager.can_change_mode("heat")
        assert manager.get_remaining_cooldown() == 150
        
        # Move time forward past cooldown
        mock_utcnow.return_value = start_time + timedelta(seconds=600)
        assert manager.can_change_mode("heat")
        assert manager.get_remaining_cooldown() == 0

    @patch('homeassistant.util.dt.utcnow')
    def test_multiple_mode_changes(self, mock_utcnow):
        """Test multiple sequential mode changes."""
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(300)
        
        # Skip startup cooldown
        mock_utcnow.return_value = start_time + timedelta(seconds=300)
        
        # First change: off -> cool
        manager.record_mode_change("cool")
        
        # Second change after cooldown: cool -> heat
        mock_utcnow.return_value = start_time + timedelta(seconds=600)
        assert manager.can_change_mode("heat")
        manager.record_mode_change("heat")
        
        # Third change after cooldown: heat -> off
        mock_utcnow.return_value = start_time + timedelta(seconds=900)
        assert manager.can_change_mode("off")
        manager.record_mode_change("off")
        
        # Verify history tracking
        assert manager.get_time_since_mode("cool") == 600
        assert manager.get_time_since_mode("heat") == 300
        assert manager.get_time_since_mode("off") == 0

    def test_get_cooldown_status(self):
        """Test cooldown status information."""
        manager = CooldownManager(300)
        
        status = manager.get_cooldown_status()
        
        # Check required fields
        assert "in_cooldown" in status
        assert "remaining_seconds" in status
        assert "cooldown_period" in status
        assert "current_mode" in status
        assert "last_mode_change" in status
        assert "startup_cooldown" in status
        assert "startup_time" in status
        
        # Check initial values
        assert status["cooldown_period"] == 300
        assert status["current_mode"] is None
        assert status["last_mode_change"] is None
        assert isinstance(status["startup_cooldown"], bool)

    @patch('homeassistant.util.dt.utcnow')
    def test_reset_startup_cooldown(self, mock_utcnow):
        """Test resetting startup cooldown."""
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(300)
        
        # Move time forward partially through startup
        mock_utcnow.return_value = start_time + timedelta(seconds=150)
        assert not manager.can_change_mode("cool")
        
        # Reset startup cooldown
        reset_time = start_time + timedelta(seconds=150)
        mock_utcnow.return_value = reset_time
        manager.reset_startup_cooldown()
        
        # Should still be in cooldown from new startup time
        assert not manager.can_change_mode("cool")
        assert manager.get_remaining_cooldown() == 300
        
        # Move forward from reset time
        mock_utcnow.return_value = reset_time + timedelta(seconds=300)
        assert manager.can_change_mode("cool")

    def test_get_time_since_mode(self):
        """Test getting time since specific mode was active."""
        manager = CooldownManager(300)
        
        # Mode never recorded should return None
        assert manager.get_time_since_mode("cool") is None
        
        with patch('homeassistant.util.dt.utcnow') as mock_utcnow:
            start_time = datetime(2023, 1, 1, 12, 0, 0)
            mock_utcnow.return_value = start_time
            
            # Skip startup and record mode
            mock_utcnow.return_value = start_time + timedelta(seconds=300)
            manager.record_mode_change("cool")
            
            # Check time since mode
            mock_utcnow.return_value = start_time + timedelta(seconds=450)
            assert manager.get_time_since_mode("cool") == 150
            
            # Record another mode
            manager.record_mode_change("heat")
            mock_utcnow.return_value = start_time + timedelta(seconds=600)
            
            assert manager.get_time_since_mode("cool") == 300
            assert manager.get_time_since_mode("heat") == 150

    def test_clear_history(self):
        """Test clearing cooldown manager history."""
        manager = CooldownManager(300)
        
        with patch('homeassistant.util.dt.utcnow') as mock_utcnow:
            start_time = datetime(2023, 1, 1, 12, 0, 0)
            mock_utcnow.return_value = start_time + timedelta(seconds=300)
            
            # Record some mode changes
            manager.record_mode_change("cool")
            manager.record_mode_change("heat")
            
            # Verify history exists
            assert manager.get_time_since_mode("cool") is not None
            assert manager.get_time_since_mode("heat") is not None
            
            # Clear history
            clear_time = start_time + timedelta(seconds=600)
            mock_utcnow.return_value = clear_time
            manager.clear_history()
            
            # Verify history is cleared
            assert manager.get_time_since_mode("cool") is None
            assert manager.get_time_since_mode("heat") is None
            
            # Should be back in startup cooldown
            assert not manager.can_change_mode("cool")

    @patch('homeassistant.util.dt.utcnow')
    def test_zero_cooldown_period(self, mock_utcnow):
        """Test behavior with zero cooldown period."""
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(0)
        
        # Should allow immediate mode changes
        assert manager.can_change_mode("cool")
        manager.record_mode_change("cool")
        
        # Should allow immediate subsequent changes
        assert manager.can_change_mode("heat")
        manager.record_mode_change("heat")
        
        assert manager.get_remaining_cooldown() == 0

    @patch('homeassistant.util.dt.utcnow')
    def test_edge_case_exact_cooldown_timing(self, mock_utcnow):
        """Test edge case where mode change happens exactly at cooldown expiry."""
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(300)
        
        # Skip startup cooldown
        mock_utcnow.return_value = start_time + timedelta(seconds=300)
        manager.record_mode_change("cool")
        
        # Move to exactly cooldown expiry time
        mock_utcnow.return_value = start_time + timedelta(seconds=600)
        assert manager.can_change_mode("heat")
        assert manager.get_remaining_cooldown() == 0

    def test_repr(self):
        """Test string representation of cooldown manager."""
        manager = CooldownManager(300)
        repr_str = repr(manager)
        
        assert "CooldownManager" in repr_str
        assert "period=300s" in repr_str
        assert "current_mode=None" in repr_str
        assert "remaining=" in repr_str

    @patch('homeassistant.util.dt.utcnow')
    def test_startup_vs_mode_change_cooldown_priority(self, mock_utcnow):
        """Test that startup cooldown takes priority over mode change cooldown."""
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(300)
        
        # Move forward slightly but still in startup cooldown
        mock_utcnow.return_value = start_time + timedelta(seconds=100)
        
        # Even though no mode change has occurred, should still be in cooldown
        assert not manager.can_change_mode("cool")
        assert manager.get_remaining_cooldown() == 200
        
        status = manager.get_cooldown_status()
        assert status["startup_cooldown"] is True
        assert status["in_cooldown"] is True


class TestCooldownManagerIntegration:
    """Integration tests for cooldown manager with realistic scenarios."""

    @patch('homeassistant.util.dt.utcnow')
    def test_realistic_hvac_cycle(self, mock_utcnow):
        """Test a realistic HVAC control cycle."""
        start_time = datetime(2023, 7, 15, 14, 0, 0)  # Hot summer day
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(300)  # 5 minute cooldown
        
        # System starts up - wait for startup cooldown
        mock_utcnow.return_value = start_time + timedelta(minutes=5)
        
        # Temperature rises, need cooling
        assert manager.can_change_mode("cool")
        manager.record_mode_change("cool")
        
        # Temperature satisfied quickly, try to turn off (should be blocked)
        mock_utcnow.return_value = start_time + timedelta(minutes=6)
        assert not manager.can_change_mode("off")
        
        # Wait for cooldown, then turn off
        mock_utcnow.return_value = start_time + timedelta(minutes=10)
        assert manager.can_change_mode("off")
        manager.record_mode_change("off")
        
        # Humidity spike, need dry mode (should be blocked)
        mock_utcnow.return_value = start_time + timedelta(minutes=12)
        assert not manager.can_change_mode("dry")
        
        # Wait for cooldown, then activate dry mode
        mock_utcnow.return_value = start_time + timedelta(minutes=15)
        assert manager.can_change_mode("dry")
        manager.record_mode_change("dry")
        
        # Verify timing history
        assert manager.get_time_since_mode("cool") == 600  # 10 minutes ago
        assert manager.get_time_since_mode("off") == 300   # 5 minutes ago
        assert manager.get_time_since_mode("dry") == 0     # Current mode

    @patch('homeassistant.util.dt.utcnow')
    def test_emergency_override_scenario(self, mock_utcnow):
        """Test scenario where emergency override might be needed."""
        start_time = datetime(2023, 1, 15, 8, 0, 0)  # Cold winter morning
        mock_utcnow.return_value = start_time
        
        manager = CooldownManager(600)  # 10 minute cooldown for this test
        
        # Skip startup
        mock_utcnow.return_value = start_time + timedelta(minutes=10)
        
        # Start heating
        manager.record_mode_change("heat")
        
        # Immediate need to switch to cooling (emergency scenario)
        mock_utcnow.return_value = start_time + timedelta(minutes=11)
        
        # Normal cooldown would block this
        assert not manager.can_change_mode("cool")
        assert manager.get_remaining_cooldown() == 540  # 9 minutes left
        
        # In a real emergency, the system might need to override cooldown
        # This test documents the current behavior - override logic would
        # need to be implemented at a higher level
        
        # Wait for full cooldown
        mock_utcnow.return_value = start_time + timedelta(minutes=20)
        assert manager.can_change_mode("cool")