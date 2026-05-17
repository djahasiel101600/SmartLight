# Photoresistor Calibration Guide

## Overview

The photoresistor is connected to Arduino pin A2 with a 10kΩ resistor divider. The Arduino returns a raw ADC reading (0-1023), which must be converted to lux using a calibration curve.

This guide explains how to calibrate the photoresistor using your handheld lux meter.

## Hardware Setup

**Components:**

- Photoresistor (estimated 5kΩ-10kΩ resistance range)
- 10kΩ resistor (divider)
- Arduino A2 analog input
- Voltage divider circuit: **3.3 V** → Photoresistor → A2 → 10kΩ → GND
- AREF pin connected to the same **3.3 V** rail

**ADC reference voltage:** 3.3 V (firmware uses `analogReference(EXTERNAL)`).
ADC reading 0 = 0 V, ADC reading 1023 = 3.3 V — full 10-bit resolution.

**Expected ADC range:** 0-1023 (10-bit ADC)

## Calibration Procedure

### Step 1: Enable Photoresistor Mode

In `config.py`, ensure:

```python
PHOTORESISTOR_ENABLED = True
```

### Step 2: Collect Calibration Data

You need at least **2 calibration points** (ADC value → lux value pairs). More points improve accuracy.

**Process:**

1. Start the SmartLight system in a room with the photoresistor and your lux meter
2. Place the lux meter sensor next to the photoresistor
3. Adjust room lighting to different levels (dim, medium, bright)
4. For each light level, record:
   - **Arduino ADC raw value** (0-1023) — visible in terminal output from `[Photoresistor]` logs or by polling the Arduino
   - **Lux meter reading** — read from the handheld meter

**Example measurements:**

```
Light Level    | Lux Meter | Arduino ADC
────────────────────────────────────────
Dim (evening)  |    20 lux |        100
Medium (room)  |   100 lux |        500
Bright (day)   |  1000 lux |       1000
```

### Step 3: Update Calibration Points

Edit `config.py` and update the `PHOTORESISTOR_CALIBRATION_POINTS` dictionary:

```python
PHOTORESISTOR_CALIBRATION_POINTS: dict = {
    100: 20,      # Raw ADC 100 ≈ 20 lux (dim light)
    500: 100,     # Raw ADC 500 ≈ 100 lux (medium light)
    1000: 1000,   # Raw ADC 1000 ≈ 1000 lux (bright light)
}
```

The system uses **linear interpolation** between calibration points:

- ADC values below the first point are clamped to the first lux value
- ADC values above the last point are clamped to the last lux value
- ADC values between points are linearly interpolated

### Step 4: Validate Calibration

1. Restart the SmartLight system
2. Monitor terminal output for photoresistor readings
3. Compare SmartLight lux estimates against your lux meter in various light conditions
4. If readings are consistently off, repeat the calibration process

## Troubleshooting

### No photoresistor readings appearing

**Symptoms:** Terminal shows `[Photoresistor] ERROR polling ADC`

**Solutions:**

- Verify Arduino is receiving the `PHOTOLUX?` command (check Arduino serial monitor)
- Check `PHOTORESISTOR_ENABLED = True` in config.py
- Verify the Arduino firmware includes the photoresistor command handler

### Readings are very high or very low

**Symptoms:** Lux values don't match your meter

**Causes:**

- Photoresistor sensitivity mismatch (e.g., using 20kΩ photoresistor with 10kΩ divider)
- Poor light coupling between lux meter and photoresistor
- Non-linear photoresistor response (some sensors have logarithmic sensitivity)

**Solutions:**

1. Collect more calibration points to improve interpolation accuracy
2. Move the lux meter closer to the photoresistor
3. If response is non-linear, use power-law calibration (advanced):
   - Fit an exponential model: `lux = A * ADC^B`
   - Manually implement custom conversion in `_adc_to_lux()` method

### Dimmer not responding to photoresistor changes

**Symptoms:** Light brightness doesn't adjust with lux changes

**Checks:**

1. Verify `PHOTORESISTOR_POLL_INTERVAL` is reasonable (default 0.5s)
2. Check that lux readings are within `ACTIVITY_LUX_RANGE` for the current activity
3. Verify dimmer is not in a test mode (test modes bypass lux control)
4. Check Arduino is receiving dimmer commands (see `dimmer_manager.py` logs)

## Advanced: Custom Sensitivity Model

If linear interpolation is insufficient, you can implement a custom conversion in `dimmer_manager.py`:

```python
def _adc_to_lux(self, raw_adc: int) -> float:
    """Custom non-linear conversion."""
    # Example: Power-law model lux = A * ADC^B
    A = 0.0001  # calibration constant
    B = 1.8     # power exponent (tune based on your photoresistor)
    return A * (raw_adc ** B)
```

## References

- **Photoresistor Typical Response:** Most photoresistors have logarithmic sensitivity (darker at low light, compressed at high light)
- **Linear Calibration Accuracy:** ±10-20% typically achievable with 3-5 calibration points
- **Ambient Temperature:** Photoresistor sensitivity varies slightly with temperature (typically ~0.05%/°C); recalibrate if room temperature changes significantly

## Support

For issues or questions:

1. Check the SmartLight debug logs (`applog/`) for clues
2. Verify Arduino `PHOTOLUX?` responses using Arduino serial monitor
3. Compare raw ADC readings to expected photoresistor V-I characteristics
