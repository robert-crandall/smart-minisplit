# 🧩 Custom Component Requirements: Smart Mini Split Controller

## 📌 Goal

Build a Home Assistant **custom integration** (`smart_mini_split`) that intelligently manages a mini split heat/cool unit by comparing its internal set temperature against readings from an **external thermometer**.

---

## ✅ Core Features

### 🎯 1. External Temperature-Based Control

- Compare external thermometer reading (`sensor.awair_element_110243_temperature`) with the mini split’s set temperature (`climate.minisplit.temperature`).
- Every minute, evaluate the difference between the external temperature and the target setpoint.
- Adjust the mini split's set temperature **up/down by 10°F** if the difference exceeds a configurable threshold (default: 2°F).
- Return the setpoint to normal when the external temperature stabilizes within a tolerance range (default: 1°F).

---

### 🧠 2. Smart Override Detection

- Recognize manual overrides by the user:
  - If set temperature is within the valid range (64°F–74°F), it is considered a **real/manual setpoint**.
  - Any set temperature outside this range is assumed to be **automation-controlled**.
- Suspend automatic adjustments temporarily if a manual override is detected.

---

### ⏱ 3. Cooldown Timer

- After each automated adjustment, wait a configurable cooldown period (default: 5 minutes) before re-evaluating.
- Prevents frequent toggling or rapid-fire adjustments.

---

### 📖 4. Logbook Logging

- Log key actions to Home Assistant’s logbook:
  - Every check: log external temp, setpoint, delta, cooldown status, and logic path
  - Every adjustment: log what change was made and why
- Optional: toggle verbose logging via configuration

---

## 🧩 Optional Enhancements

- **Humidity trigger support**: Add optional control based on humidity sensor.
- **GUI card integration**: Provide a Lovelace card for:
  - External temperature
  - Current setpoint
  - Adjustment history
  - Override switch
- **Mode control**: Allow switching between `cool`, `heat`, and `dry` based on environmental conditions or user rules.
- **Service calls**: Allow user to:
  - Force an adjustment
  - Toggle automation on/off
  - Clear override

---

## 🔧 Configuration Options

```yaml
smart_mini_split:
  entity_id: climate.minisplit
  external_sensor: sensor.awair_element_110243_temperature
  valid_range: [64, 74]
  adjustment_step: 10
  trigger_threshold: 2
  reset_threshold: 1
  cooldown_minutes: 5
  log_level: info  # or debug
