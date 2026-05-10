#pragma once

// =============================================================================
// PIN CONFIGURATION
// =============================================================================

const int ZC_PIN = 2;
const int PWM_PIN_CH1 = 9;
const int PWM_PIN_CH2 = 10;
const int STATUS_LED = 13;

// =============================================================================
// SERIAL CONFIGURATION
// =============================================================================

const int SERIAL_BAUD = 9600;
const int BUFFER_SIZE = 64;
const unsigned long SERIAL_TIMEOUT_MS = 100;

// =============================================================================
// TIMING CONFIGURATION
// =============================================================================

const unsigned long COMMAND_TIMEOUT = 60000;   // ms before safety timeout
const unsigned long HEARTBEAT_INTERVAL = 1000; // ms between heartbeat prints

// =============================================================================
// FADING CONFIGURATION
// =============================================================================

// Set ENABLE_FADING to true after the 10-step brightness test passes.
const bool ENABLE_FADING = true;
const int FADE_STEP_SIZE = 2; // % per tick
const int FADE_DELAY_MS = 20; // tick interval — 2%/20ms = 100% in 1 second

// =============================================================================
// DEBUG MODE
// =============================================================================

// When true, prints [DEBUG] lines and [HEARTBEAT] lines to the serial monitor.
// Set to false before deploying to Raspberry Pi.
const bool DEBUG_MODE = false;

// =============================================================================
// BRIGHTNESS MAPPING — confirmed hardware working ranges (60 Hz)
// =============================================================================
//
// CONFIRMED DEAD ZONES (hardware scan results — 60 Hz / 230 V / dimmable LED):
//
//   Zone A — 60 Hz timer OVERFLOW  (setPower 1-15):
//     powerBuf[1-15] >= 520 ticks; exceeds the 60 Hz half-cycle length.
//     Fires into the NEXT half-cycle — appears near-full brightness.
//     All 15 values look identical. Completely unusable for dimming.
//     FIX: 0% uses setState(OFF). Low band starts at 23 instead.
//
//   Zone B — LED driver minimum threshold  (setPower 16-22):
//     Conduction window too small for the LED driver to sustain operation.
//     Bulb stays completely off.
//
//   WORKING LOW BAND:  setPower(23..40)  — confirmed monotonically increasing.
//     Maps to logical input range 1%..50%.
//     NOTE: setPower(41-58) were initially labelled OK (bulb lit) but hardware
//     testing revealed the brightness plateaus at setPower(50) == setPower(40)
//     and then drops (setPower(60) is dimmer than setPower(40)). The root cause
//     is the RBDDimmer powerBuf[] table being 50 Hz calibrated — the sinusoidal
//     correction curve bunches up at 60 Hz, producing a flat/inverted region in
//     the 41-64 range for this bulb. DIM_LOW_END is capped at 40 to stay safely
//     within the confirmed monotonic region.
//
//   Zone C — non-monotonic plateau/dip region  (setPower 41-64):
//     41-58: bulb lit but brightness plateaus — no meaningful increase above 40.
//     59:    dead (bulb off).
//     60:    bulb lit but LOWER brightness than setPower(40) — reverse effect.
//     61-64: dead (bulb off).
//     This entire range is unusable for monotonic control.
//     FIX: high band starts at 65, jumping cleanly over the entire region.
//
//   WORKING HIGH BAND:  setPower(65..99)  — confirmed OK by hardware scan.
//     Maps to logical input range 51%..100%.
//
// MAPPING STRATEGY (implemented in mapBrightness() in main.cpp):
//   Input  1%..50%  -> linearly interpolated across DIM_LOW_START..DIM_LOW_END
//   Input 51%..100% -> linearly interpolated across DIM_HIGH_START..DIM_HIGH_END
//
// MONOTONICITY GUARANTEE:
//   Linear interpolation within each ascending band is always non-decreasing.
//   At the boundary: output(50%) = DIM_LOW_END = 40,
//                    output(51%) = DIM_HIGH_START = 65.
//   65 > 40, so the output sequence never drops at the crossover.
//   No output value ever falls inside a dead or non-monotonic zone.
//
// To calibrate for a different bulb: adjust only the four constants below
// and reflash. The monotonicity guarantee holds for any values where
// DIM_LOW_END < DIM_HIGH_START and both bands are confirmed monotonic.
//
const uint8_t DIM_LOW_START = 23;  // low  band start — logical  1%
const uint8_t DIM_LOW_END = 40;    // low  band end   — logical 50%  (last confirmed monotonic step)
const uint8_t DIM_HIGH_START = 65; // high band start — logical 51%
const uint8_t DIM_HIGH_END = 99;   // high band end   — logical 100%