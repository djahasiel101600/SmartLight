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
const bool ENABLE_FADING = false;
const int FADE_STEP_SIZE = 2; // % per tick
const int FADE_DELAY_MS = 20; // tick interval — 2%/20ms = 100% in 1 second

// =============================================================================
// DEBUG MODE
// =============================================================================

// When true, prints [DEBUG] lines and [HEARTBEAT] lines to the serial monitor.
// Set to false before deploying to Raspberry Pi.
const bool DEBUG_MODE = true;

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
//   WORKING LOW BAND:  setPower(23..50)  — confirmed monotonically increasing.
//     Maps to logical input range 1%..50%.
//     Hardware verified: setPower(10,20,30,40,50) each produce a visible step up.
//
//   Zone C — non-monotonic region  (setPower 51-64):
//     51-58: unconfirmed (VERIFY on next fine scan).
//     59:    dead (bulb off).
//     60:    bulb lit but LOWER brightness than setPower(50) — reverse effect
//            caused by 50 Hz LUT compression at 60 Hz.
//     61-64: dead (bulb off).
//     This entire range is unusable for monotonic control.
//     FIX: high band starts at 65, jumping cleanly over the entire region.
//
//   WORKING HIGH BAND:  setPower(65..89)  — confirmed monotonically increasing.
//     Maps to logical input range 51%..100%.
//     NOTE: setPower(90-99) plateau — setPower(90) == setPower(99) in brightness.
//     DIM_HIGH_END capped at 89 (last confirmed step before the plateau).
//
// MAPPING STRATEGY (implemented in mapBrightness() in main.cpp):
//   Input  1%..50%  -> linearly interpolated across DIM_LOW_START..DIM_LOW_END
//   Input 51%..100% -> linearly interpolated across DIM_HIGH_START..DIM_HIGH_END
//
// MONOTONICITY GUARANTEE:
//   Linear interpolation within each ascending band is always non-decreasing.
//   At the boundary: output(50%) = DIM_LOW_END = 50,
//                    output(51%) = DIM_HIGH_START = 65.
//   65 > 50, so the output sequence never drops at the crossover.
//   No output value ever falls inside a dead or non-monotonic zone.
//
// To calibrate for a different bulb: adjust only the four constants below
// and reflash. The monotonicity guarantee holds for any values where
// DIM_LOW_END < DIM_HIGH_START and both bands are confirmed monotonic.
//
const uint8_t DIM_LOW_START = 23;  // low  band start — logical  1%
const uint8_t DIM_LOW_END = 50;    // low  band end   — logical 50%  (last confirmed monotonic step)
const uint8_t DIM_HIGH_START = 65; // high band start — logical 51%
const uint8_t DIM_HIGH_END = 89;   // high band end   — logical 100% (90-99 plateau — capped at 89)