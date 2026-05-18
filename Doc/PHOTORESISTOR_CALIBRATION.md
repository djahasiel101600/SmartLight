# Photoresistor Calibration Guide

## Overview

The photoresistor is connected to Arduino pin A2 with a 10 kΩ resistor divider. The Arduino returns a raw ADC reading (0–1023), which is converted to lux using a calibration curve and smoothed with an Exponential Moving Average (EMA) filter before being passed to the closed-loop lux controller.

This guide explains how to calibrate the photoresistor using a handheld lux meter.

---

## Hardware Setup

**Components:**

- Photoresistor (estimated 5 kΩ–10 kΩ resistance range)
- 10 kΩ resistor (voltage divider)
- Arduino A2 analog input
- Voltage divider circuit: **3.3 V** → Photoresistor → A2 → 10 kΩ → GND
- AREF pin connected to the same **3.3 V** rail

**ADC reference voltage:** 3.3 V (firmware uses `analogReference(EXTERNAL)`).  
ADC reading 0 = 0 V, ADC reading 1023 = 3.3 V — full 10-bit resolution.

**Expected ADC range:** 0–1023 (10-bit ADC)

---

## How Calibration Works

### Log-Linear Interpolation

The system converts raw ADC readings to lux using **piecewise log-linear interpolation** over the `PHOTORESISTOR_CALIBRATION_POINTS` dictionary. This method interpolates linearly in log(lux) space, which accurately models the LDR's power-law illuminance–resistance relationship ($R \propto E^{-\gamma}$):

$$\text{lux} = \exp\!\Bigl(\ln(\text{lux}_1) + t \cdot \bigl(\ln(\text{lux}_2) - \ln(\text{lux}_1)\bigr)\Bigr), \quad t = \frac{\text{ADC} - \text{ADC}_1}{\text{ADC}_2 - \text{ADC}_1}$$

This is significantly more accurate than plain linear interpolation, especially in the steep high-lux region (ADC 560–621) where a few ADC units span hundreds of lux.

- ADC values below the lowest calibration point are clamped to the lowest lux value.
- ADC values above the highest calibration point are clamped to the highest lux value.
- ADC values between two points are log-linearly interpolated.

### EMA Smoothing

After calibration conversion, an **Exponential Moving Average** filter suppresses ADC noise:

$$\text{lux}_\text{smooth} = \alpha \cdot \text{lux}_\text{new} + (1 - \alpha) \cdot \text{lux}_\text{prev}$$

The current setting is `PHOTORESISTOR_SMOOTHING_ALPHA = 0.15`, which averages approximately 6 recent samples. This balances noise suppression against control responsiveness for the 2-second controller tick interval.

---

## Calibration Procedure

### Step 1: Enable Photoresistor Mode

In `config.py`, ensure:

```python
PHOTORESISTOR_ENABLED = True
```

### Step 2: Collect Calibration Data

You need at least **2 calibration points** (ADC value → lux value pairs). More points improve accuracy, particularly in transition zones.

**Process:**

1. Start the SmartLight system with the photoresistor and lux meter in position.
2. Place the lux meter sensor next to the photoresistor.
3. Adjust room lighting to different levels (dim, medium, bright, very bright).
4. For each light level, record:
   - **Arduino ADC raw value** (0–1023) — visible in terminal output from `[Photoresistor]` logs.
   - **Lux meter reading** — read from the handheld meter.

**Recommended light levels to cover:**

```
Light Level         | Lux Meter  | Arduino ADC (approx)
─────────────────────────────────────────────────────────
Very dim (night)    |    15–25   |    100–220
Dim (evening lamp)  |    50–100  |    400–450
Medium (room)       |   150–300  |    500–570
Bright (reading)    |   500–750  |    590–620
Very bright (day)   |  1000+     |    620+
```

Focus on collecting **dense points in the 550–625 ADC zone** (500–1400 lux) since this is where the sensor is most sensitive and interpolation error is highest.

### Step 3: Update Calibration Points

Edit `config.py` and update the `PHOTORESISTOR_CALIBRATION_POINTS` dictionary:

```python
PHOTORESISTOR_CALIBRATION_POINTS: dict = {
    adc_value: lux_value,
    # Add as many pairs as you measured
    115: 19,
    214: 24,
    392: 61,
    442: 100,
    506: 156,
    561: 368,
    595: 733,
    611: 1077,
    621: 1394,
}
```

### Step 4: Validate Calibration

1. Restart the SmartLight system.
2. Monitor terminal output for `[Photoresistor]` log lines showing `raw_adc` and smoothed lux.
3. Compare SmartLight lux estimates against your lux meter at several light levels.
4. If readings are consistently off by a fixed factor, adjust `LUX_CALIBRATION_SCALE` in `config.py`:

```python
LUX_CALIBRATION_SCALE = <meter_reading> / <system_lux_output>
```

5. If readings have a consistent offset (bias), adjust `LUX_CALIBRATION_OFFSET`.

---

## Tuning EMA Smoothing

| `PHOTORESISTOR_SMOOTHING_ALPHA` | Effective samples averaged | Behaviour                                      |
| :-----------------------------: | :------------------------: | ---------------------------------------------- |
|              0.05               |            ~20             | Very smooth; slow to follow fast light changes |
|        0.15 _(default)_         |             ~6             | Balanced — good for dimmer control             |
|              0.30               |             ~3             | Slightly noisy; faster response                |
|              0.50               |             ~2             | Minimal smoothing; noisy for controller        |
|              1.00               |          1 (raw)           | No smoothing                                   |

For a 2-second controller tick interval, `0.10`–`0.20` is the recommended range. Values above `0.3` may cause the controller to over-react to momentary ADC spikes.

---

## Troubleshooting

### No photoresistor readings appearing

**Symptoms:** Terminal shows `[Photoresistor] ERROR polling ADC`

**Solutions:**

- Verify `PHOTORESISTOR_ENABLED = True` in `config.py`.
- Check that the Arduino firmware handles the `PHOTOLUX?` serial command.
- Confirm the Arduino is connected and the correct port is set in `DIMMER_PORT`.

### Readings are very high or very low

**Symptoms:** Lux values don't match the meter.

**Causes:**

- Photoresistor sensitivity mismatch (e.g., 20 kΩ LDR with 10 kΩ divider shifts the ADC range).
- Poor physical alignment between lux meter and photoresistor.
- Calibration points don't cover the relevant lux range.

**Solutions:**

1. Collect calibration points that cover the full operational lux range.
2. Add extra points in the steep high-lux zone (ADC 560–625).
3. Use `LUX_CALIBRATION_SCALE` and `LUX_CALIBRATION_OFFSET` for a global correction if the curve shape is right but the scale is off.

### Dimmer oscillates or overshoots

**Symptoms:** Brightness steps up and down repeatedly without settling.

**Checks:**

1. Ensure `LUX_CONTROL_INTERVAL` (2.0 s) is larger than `PHOTORESISTOR_POLL_INTERVAL` (0.5 s) plus bulb settle time (~1 s). The controller should never fire on a stale lux reading.
2. Lower `PHOTORESISTOR_SMOOTHING_ALPHA` (e.g., to `0.10`) to reduce noise-driven steps.
3. Reduce `LUX_STEP_SIZE` from 2 to 1 for finer control.
4. Verify calibration accuracy in the activity's target lux range — large calibration errors cause the controller to misread its position relative to the dead-band.

### Controller stuck at 1% or 100%

**Symptoms:** Brightness rails at a limit and never enters the target band.

**Cause:** Ambient light from other sources (e.g., sunlight, other lamps) is already above (or below) the target range, so the controller cannot compensate with the dimmer alone.

**Expected behaviour:** This is correct — the controller will hold at the rail (1% or 100%) until ambient conditions change. For Idle with strong daylight, the light will dim to 1% and eventually trigger auto-off after 90 seconds.

---

## References

- **LDR Physics:** Photoresistors follow $R \propto E^{-\gamma}$ where $\gamma \approx 0.5$–$0.9$, giving a power-law (log-log) response curve.
- **Log-linear interpolation accuracy:** ±5–15% achievable with well-spaced calibration points in log space, compared to ±15–30% for linear interpolation in the steep high-lux zone.
- **IES Illuminance Targets:** IESNA Lighting Handbook, Table 3.1 — task illuminance recommendations.
- **EMA filter:** $\alpha = 0.15$ gives an effective time constant of $T \approx (1/\alpha - 1) \times \text{poll\_interval} = 5.7 \times 0.5\,\text{s} \approx 2.8\,\text{s}$.
