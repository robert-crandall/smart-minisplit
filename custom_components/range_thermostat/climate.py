"""Range Thermostat climate entity."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ATTR_TARGET_TEMP_STEP,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    ATTR_COMMANDED_SETPOINT,
    ATTR_CONTROLLED_ENTITY,
    ATTR_LAST_MODE_CHANGE,
    ATTR_SENSOR_ENTITY,
    ATTR_SENSOR_STALE,
    ATTR_TIME_UNTIL_NEXT_ALLOWED_CHANGE,
    CONF_CLIMATE_ENTITY,
    CONF_DEADBAND,
    CONF_MIN_CYCLE_DURATION,
    CONF_OVERSHOOT,
    CONF_RESEND_INTERVAL,
    CONF_SENSOR_ENTITY,
    CONF_SENSOR_TIMEOUT,
    CONF_SINGLE_COMMAND,
    DEFAULT_BAND_CELSIUS,
    DEFAULT_BAND_FAHRENHEIT,
    DEFAULT_DEADBAND,
    DEFAULT_MIN_CYCLE_DURATION,
    DEFAULT_OVERSHOOT,
    DEFAULT_RESEND_INTERVAL,
    DEFAULT_SENSOR_TIMEOUT,
    DEFAULT_SINGLE_COMMAND,
    SAFETY_TICK,
)

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Range Thermostat entity from a config entry."""
    async_add_entities([RangeThermostat(entry)])


class RangeThermostat(ClimateEntity, RestoreEntity):
    """A dual-setpoint thermostat wrapping a single-setpoint climate entity."""

    _attr_should_poll = False
    _attr_hvac_modes = [HVACMode.HEAT_COOL, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the thermostat."""
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.data.get(CONF_NAME) or entry.title
        self._climate_entity_id: str = entry.data[CONF_CLIMATE_ENTITY]
        self._sensor_entity_id: str = entry.data[CONF_SENSOR_ENTITY]

        self._attr_hvac_mode = HVACMode.HEAT_COOL
        self._target_low: float | None = None
        self._target_high: float | None = None

        # Logical control state. IDLE means "we have not established control yet".
        self._state: HVACAction = HVACAction.IDLE
        self._last_mode_change: datetime | None = None
        self._last_commanded_mode: HVACMode | None = None
        self._last_commanded_setpoint: float | None = None
        self._last_command_at: datetime | None = None

        self._current_temperature: float | None = None
        self._sensor_stale = False
        self._stale_logged = False

        # Last known good limits from the underlying entity.
        self._limits: dict[str, float] = {}

        self._lock = asyncio.Lock()
        self._unsub_tick: Any = None

        self._load_options()

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    def _load_options(self) -> None:
        """Read the runtime tunables from the config entry options."""
        options = self._entry.options
        self._deadband = float(options.get(CONF_DEADBAND, DEFAULT_DEADBAND))
        self._min_cycle_duration = timedelta(
            minutes=float(
                options.get(CONF_MIN_CYCLE_DURATION, DEFAULT_MIN_CYCLE_DURATION)
            )
        )
        self._overshoot = float(options.get(CONF_OVERSHOOT, DEFAULT_OVERSHOOT))
        self._sensor_timeout = timedelta(
            minutes=float(options.get(CONF_SENSOR_TIMEOUT, DEFAULT_SENSOR_TIMEOUT))
        )
        self._resend_interval = float(
            options.get(CONF_RESEND_INTERVAL, DEFAULT_RESEND_INTERVAL)
        )
        self._single_command = bool(
            options.get(CONF_SINGLE_COMMAND, DEFAULT_SINGLE_COMMAND)
        )

    @property
    def _tick_interval(self) -> timedelta:
        """How often the periodic safety evaluation runs."""
        interval = SAFETY_TICK
        if self._resend_interval > 0:
            interval = min(interval, timedelta(minutes=self._resend_interval))
        return interval

    # ------------------------------------------------------------------
    # Limits inherited from the underlying climate entity
    # ------------------------------------------------------------------

    def _underlying_limit(self, attribute: str, fallback: float) -> float:
        """Read a numeric limit from the underlying entity, with caching."""
        state = self.hass.states.get(self._climate_entity_id)
        if state is not None and state.state not in UNAVAILABLE_STATES:
            value = state.attributes.get(attribute)
            if isinstance(value, (int, float)):
                self._limits[attribute] = float(value)
        return self._limits.get(attribute, fallback)

    @property
    def temperature_unit(self) -> str:
        """Return the unit the underlying climate entity is presented in.

        Home Assistant normalises every climate entity to the system unit, so the
        system unit is the underlying entity's unit as far as service calls go.
        """
        return self.hass.config.units.temperature_unit

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature the underlying entity accepts."""
        return self._underlying_limit(
            ATTR_MIN_TEMP,
            TemperatureConverter.convert(
                DEFAULT_MIN_TEMP, UnitOfTemperature.CELSIUS, self.temperature_unit
            ),
        )

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature the underlying entity accepts."""
        return self._underlying_limit(
            ATTR_MAX_TEMP,
            TemperatureConverter.convert(
                DEFAULT_MAX_TEMP, UnitOfTemperature.CELSIUS, self.temperature_unit
            ),
        )

    @property
    def target_temperature_step(self) -> float:
        """Return the step size the underlying entity uses."""
        default = 1.0 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 0.5
        return self._underlying_limit(ATTR_TARGET_TEMP_STEP, default)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def current_temperature(self) -> float | None:
        """Return the temperature read from the external sensor."""
        return self._current_temperature

    @property
    def target_temperature_low(self) -> float | None:
        """Return the bottom of the band."""
        return self._target_low

    @property
    def target_temperature_high(self) -> float | None:
        """Return the top of the band."""
        return self._target_high

    @property
    def hvac_action(self) -> HVACAction:
        """Return what the thermostat believes the unit is doing."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return debugging and automation attributes."""
        return {
            ATTR_CONTROLLED_ENTITY: self._climate_entity_id,
            ATTR_SENSOR_ENTITY: self._sensor_entity_id,
            ATTR_LAST_MODE_CHANGE: (
                self._last_mode_change.isoformat() if self._last_mode_change else None
            ),
            ATTR_TIME_UNTIL_NEXT_ALLOWED_CHANGE: self._cooldown_remaining(),
            ATTR_COMMANDED_SETPOINT: self._last_commanded_setpoint,
            ATTR_SENSOR_STALE: self._sensor_stale,
        }

    def _cooldown_remaining(self, now: datetime | None = None) -> int:
        """Return seconds left on the mode-change cooldown."""
        if self._last_mode_change is None:
            return 0
        now = now or dt_util.utcnow()
        remaining = self._min_cycle_duration - (now - self._last_mode_change)
        return max(0, int(remaining.total_seconds()))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore state and start listening."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in (HVACMode.HEAT_COOL, HVACMode.OFF):
                self._attr_hvac_mode = HVACMode(last_state.state)
            self._target_low = _as_float(
                last_state.attributes.get(ATTR_TARGET_TEMP_LOW)
            )
            self._target_high = _as_float(
                last_state.attributes.get(ATTR_TARGET_TEMP_HIGH)
            )

        if self._target_low is None or self._target_high is None:
            self._target_low, self._target_high = (
                DEFAULT_BAND_FAHRENHEIT
                if self.temperature_unit == UnitOfTemperature.FAHRENHEIT
                else DEFAULT_BAND_CELSIUS
            )

        # The cooldown is deliberately not restored; it is treated as expired.
        self._enforce_band(warn=False)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._sensor_entity_id], self._async_sensor_changed
            )
        )
        self.async_on_remove(
            self._entry.add_update_listener(self._async_options_updated)
        )
        self._start_tick()

        if self.hass.state is CoreState.running:
            await self._async_control()
        else:
            self.async_on_remove(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, self._async_hass_started
                )
            )

    async def async_will_remove_from_hass(self) -> None:
        """Stop the periodic evaluation."""
        self._stop_tick()
        await super().async_will_remove_from_hass()

    def _start_tick(self) -> None:
        self._unsub_tick = async_track_time_interval(
            self.hass, self._async_tick, self._tick_interval
        )

    def _stop_tick(self) -> None:
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None

    async def _async_hass_started(self, _event: Event) -> None:
        await self._async_control()
        self.async_write_ha_state()

    async def _async_tick(self, _now: datetime) -> None:
        await self._async_control()
        self.async_write_ha_state()

    async def _async_sensor_changed(self, _event: Event[EventStateChangedData]) -> None:
        await self._async_control()
        self.async_write_ha_state()

    async def _async_options_updated(
        self, _hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Apply new options in place, without a restart or an entry reload."""
        self._entry = entry
        previous_interval = self._tick_interval
        self._load_options()
        if self._tick_interval != previous_interval:
            self._stop_tick()
            self._start_tick()
        self._enforce_band()
        await self._async_control()
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Commands from the user / automations
    # ------------------------------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new band."""
        low = _as_float(kwargs.get(ATTR_TARGET_TEMP_LOW))
        high = _as_float(kwargs.get(ATTR_TARGET_TEMP_HIGH))
        if low is None and high is None:
            raise ServiceValidationError(
                "Range Thermostat requires target_temp_low and target_temp_high"
            )

        if low is not None:
            self._target_low = low
        if high is not None:
            self._target_high = high

        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            self._set_hvac_mode(HVACMode(hvac_mode))

        self._enforce_band()
        await self._async_control()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Turn the thermostat on or off."""
        if hvac_mode not in self._attr_hvac_modes:
            raise ServiceValidationError(f"Unsupported hvac mode: {hvac_mode}")
        self._set_hvac_mode(hvac_mode)
        await self._async_control()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn the thermostat on."""
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_turn_off(self) -> None:
        """Turn the thermostat off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    @callback
    def _set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == self._attr_hvac_mode:
            return
        self._attr_hvac_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            self._state = HVACAction.IDLE
            # A user-driven off/on is not a compressor cycle we need to protect
            # against, so the cooldown is cleared rather than started.
            self._last_mode_change = None

    # ------------------------------------------------------------------
    # Band validation
    # ------------------------------------------------------------------

    @callback
    def _enforce_band(self, warn: bool = True) -> None:
        """Keep the band wide enough to be controllable and inside the unit's limits."""
        low, high = self._target_low, self._target_high
        if low is None or high is None:
            return
        if high < low:
            low, high = high, low

        min_width = 2 * self._deadband
        if high - low < min_width:
            if warn:
                _LOGGER.warning(
                    "%s: band %.1f-%.1f is narrower than 2 x deadband (%.1f); "
                    "widening it to avoid continuous mode flipping",
                    self.entity_id or self._attr_name,
                    low,
                    high,
                    min_width,
                )
            middle = (low + high) / 2
            low = middle - min_width / 2
            high = middle + min_width / 2

        min_temp, max_temp = self.min_temp, self.max_temp
        if high - low >= max_temp - min_temp:
            low, high = min_temp, max_temp
        else:
            if low < min_temp:
                high += min_temp - low
                low = min_temp
            if high > max_temp:
                low -= high - max_temp
                high = max_temp

        self._target_low = round(low, 2)
        self._target_high = round(high, 2)

    def _effective_overshoot(self) -> float:
        """Clamp overshoot so a setpoint can never cross the middle of the band."""
        if self._target_low is None or self._target_high is None:
            return 0.0
        return min(self._overshoot, (self._target_high - self._target_low) / 2)

    # ------------------------------------------------------------------
    # Sensor
    # ------------------------------------------------------------------

    @callback
    def _refresh_sensor(self) -> bool:
        """Update the current temperature. Return True when the sensor is stale."""
        state = self.hass.states.get(self._sensor_entity_id)
        stale = True
        reason = "is unavailable"

        if state is not None and state.state not in UNAVAILABLE_STATES:
            value = _as_float(state.state)
            if value is None:
                reason = f"reported a non-numeric value ({state.state!r})"
            else:
                self._current_temperature = self._to_native_unit(value, state)
                last_seen = max(
                    state.last_updated,
                    getattr(state, "last_reported", None) or state.last_updated,
                )
                age = dt_util.utcnow() - last_seen
                if age > self._sensor_timeout:
                    reason = (
                        f"has not updated in {int(age.total_seconds() // 60)} minutes"
                    )
                else:
                    stale = False

        self._sensor_stale = stale
        if stale and not self._stale_logged:
            _LOGGER.warning(
                "%s: temperature sensor %s %s; holding the current state and issuing "
                "no further commands until it recovers",
                self.entity_id or self._attr_name,
                self._sensor_entity_id,
                reason,
            )
            self._stale_logged = True
        elif not stale and self._stale_logged:
            _LOGGER.info(
                "%s: temperature sensor %s recovered",
                self.entity_id or self._attr_name,
                self._sensor_entity_id,
            )
            self._stale_logged = False
        return stale

    def _to_native_unit(self, value: float, state: Any) -> float:
        """Convert a sensor reading into the thermostat's unit."""
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if (
            unit in (UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT)
            and unit != self.temperature_unit
        ):
            return TemperatureConverter.convert(value, unit, self.temperature_unit)
        return value

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------

    async def _async_control(self) -> None:
        """Evaluate the band and command the underlying unit if needed."""
        async with self._lock:
            await self._async_control_locked()

    async def _async_control_locked(self) -> None:
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_command_off()
            return

        if self._refresh_sensor():
            return

        temperature = self._current_temperature
        low, high = self._target_low, self._target_high
        if temperature is None or low is None or high is None:
            return

        if temperature < low - self._deadband:
            desired = HVACAction.HEATING
        elif temperature > high + self._deadband:
            desired = HVACAction.COOLING
        else:
            # Inside the band: hold whatever the unit is already doing.
            desired = self._state

        if desired is HVACAction.IDLE:
            # Nothing established yet and the room is comfortable. Leave the unit
            # alone; the band edges will trigger the first command.
            return

        overshoot = self._effective_overshoot()
        if desired is HVACAction.HEATING:
            mode = HVACMode.HEAT
            setpoint = round(low + overshoot, 2)
        else:
            mode = HVACMode.COOL
            setpoint = round(high - overshoot, 2)

        now = dt_util.utcnow()

        if desired is not self._state or mode != self._last_commanded_mode:
            if (remaining := self._cooldown_remaining(now)) > 0:
                _LOGGER.debug(
                    "%s: mode change to %s blocked for another %s seconds",
                    self.entity_id,
                    mode,
                    remaining,
                )
                return
            if await self._async_send(mode, setpoint):
                self._last_mode_change = now
                self._state = desired
        elif setpoint != self._last_commanded_setpoint:
            # Same mode: setpoint adjustments are never blocked by the cooldown.
            await self._async_send(mode, setpoint)
        elif self._resend_due(now):
            await self._async_send(mode, setpoint, force_mode=True)

    def _resend_due(self, now: datetime) -> bool:
        """Return True when the current command should be re-asserted."""
        if self._resend_interval <= 0 or self._last_command_at is None:
            return False
        return now - self._last_command_at >= timedelta(minutes=self._resend_interval)

    async def _async_command_off(self) -> None:
        """Command the underlying unit off, deduplicated."""
        now = dt_util.utcnow()
        if self._last_commanded_mode is HVACMode.OFF and not self._resend_due(now):
            return
        if not self._underlying_available():
            return
        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_HVAC_MODE,
                {
                    ATTR_ENTITY_ID: self._climate_entity_id,
                    ATTR_HVAC_MODE: HVACMode.OFF,
                },
                blocking=True,
                context=self._context,
            )
        except HomeAssistantError as err:
            _LOGGER.error(
                "%s: failed to turn off %s: %s",
                self.entity_id,
                self._climate_entity_id,
                err,
            )
            return
        self._last_commanded_mode = HVACMode.OFF
        self._last_commanded_setpoint = None
        self._last_command_at = now

    async def _async_send(
        self, mode: HVACMode, setpoint: float, *, force_mode: bool = False
    ) -> bool:
        """Bring the underlying unit to ``mode`` @ ``setpoint``.

        Home Assistant does not dispatch ``async_set_hvac_mode`` when
        ``hvac_mode`` rides along with ``climate.set_temperature``; it just
        forwards the kwarg and leaves it to the platform, and most platforms
        ignore it. So mode and setpoint go as two separate service calls, which
        every platform understands. ``single_command`` folds them back into one
        for platforms that do honour it -- notably ESPHome, where a second call
        means a second IR frame.

        Return True when the unit is now in the requested state.
        """
        if not self._underlying_available():
            _LOGGER.debug(
                "%s: %s is unavailable, skipping command",
                self.entity_id,
                self._climate_entity_id,
            )
            return False

        send_mode = force_mode or mode is not self._last_commanded_mode
        now = dt_util.utcnow()

        if send_mode and self._single_command:
            if not await self._async_call(
                SERVICE_SET_TEMPERATURE,
                {ATTR_HVAC_MODE: mode, ATTR_TEMPERATURE: setpoint},
                mode,
                setpoint,
            ):
                return False
            self._last_commanded_mode = mode
            self._last_commanded_setpoint = setpoint
            self._last_command_at = now
            _LOGGER.debug(
                "%s: commanded %s to %s @ %s",
                self.entity_id,
                self._climate_entity_id,
                mode,
                setpoint,
            )
            return True

        # Setpoint first. A unit briefly left in the old mode at the new
        # setpoint idles; the old setpoint under the new mode would run the
        # wrong direction until the second call lands.
        if not await self._async_call(
            SERVICE_SET_TEMPERATURE, {ATTR_TEMPERATURE: setpoint}, mode, setpoint
        ):
            return False
        self._last_commanded_setpoint = setpoint
        self._last_command_at = now

        if send_mode:
            if not await self._async_call(
                SERVICE_SET_HVAC_MODE, {ATTR_HVAC_MODE: mode}, mode, setpoint
            ):
                return False
            self._last_commanded_mode = mode

        _LOGGER.debug(
            "%s: commanded %s to %s @ %s",
            self.entity_id,
            self._climate_entity_id,
            mode,
            setpoint,
        )
        return True

    async def _async_call(
        self,
        service: str,
        data: dict[str, Any],
        mode: HVACMode,
        setpoint: float,
    ) -> bool:
        """Call one climate service on the underlying entity."""
        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                service,
                {ATTR_ENTITY_ID: self._climate_entity_id, **data},
                blocking=True,
                context=self._context,
            )
        except HomeAssistantError as err:
            _LOGGER.error(
                "%s: failed to command %s to %s @ %s via %s: %s",
                self.entity_id,
                self._climate_entity_id,
                mode,
                setpoint,
                service,
                err,
            )
            return False
        return True

    def _underlying_available(self) -> bool:
        state = self.hass.states.get(self._climate_entity_id)
        return state is not None and state.state not in UNAVAILABLE_STATES


def _as_float(value: Any) -> float | None:
    """Best-effort float conversion."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result  # reject NaN
