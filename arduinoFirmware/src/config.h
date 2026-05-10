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
// BRIGHTNESS LOOKUP TABLE  (60 Hz calibration)
// =============================================================================
//
// The RBDDimmer powerBuf[] is tuned for 50 Hz (625 timer ticks per half-cycle).
// At 60 Hz there are only ~520 ticks, so setPower(0-14) never fires the TRIAC
// (powerBuf[0-14] = 526-600, all > 520) — those inputs produce no light.
// setPower(16) gives powerBuf[16] = 514, safely within the 60 Hz window.
//
// Additionally, some LED drivers have narrow dead zones at specific phase-cut
// angles (reported: setPower(50) and setPower(80) turn the bulb off).
//
// This table maps the 11 logical levels (0%, 10%, ... 100%) to safe setPower()
// values that avoid both the 60 Hz cutoff and the known LED dead zones.
// Values in between are linearly interpolated by mapBrightness() in main.cpp.
//
// HOW TO TUNE:
//   1. Flash firmware with DEBUG_MODE = true.
//   2. Open serial monitor at 9600 baud.
//   3. Send  RAW:<n>  (e.g. "RAW:54") to test a raw setPower(n) value directly
//      without reflashing. Observe whether the bulb responds correctly.
//   4. Adjust the entry for the failing level and reflash.
//
static const uint8_t BRIGHTNESS_LUT[11] = {
    0,  // 0%  -> explicit off (always 0)
    16, // 10% -> first reliable level at 60 Hz (powerBuf[16] = 514 < 520)
    26, // 20%
    35, // 30%
    44, // 40%
    54, // 50% -> shifted +4 to skip setPower(50) dead zone
    63, // 60%
    72, // 70%
    84, // 80% -> shifted +4 to skip setPower(80) dead zone
    91, // 90%
    99, // 100% (library internally clamps >=99 -> 99)
};
