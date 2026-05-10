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
// BRIGHTNESS LOOKUP TABLE  (60 Hz calibration — confirmed by hardware scan)
// =============================================================================
//
// HARDWARE TEST RESULTS (60 Hz / 230 V / dimmable LED bulb):
//
//   Zone A — 60 Hz timer OVERFLOW  (setPower 1-15):
//     powerBuf[1-15] = 520-600, all >= 520 half-cycle ticks at 60 Hz.
//     dimCounter never reaches the target within the current half-cycle;
//     it carries over and fires 80-1267 us into the NEXT half-cycle.
//     Result: near-FULL brightness regardless of which value 1-15 is set.
//     All values appear identically bright — unusable for dimming.
//     FIX: 0% uses setState(OFF). Values 1-22 are skipped entirely.
//
//   Zone B — LED driver minimum threshold  (setPower 16-22):
//     Fires very late in the half-cycle; conduction window < 560 us.
//     LED driver switching converter cannot start up — bulb stays OFF.
//     FIX: low range starts at setPower(23), the first confirmed dim level.
//
//   WORKING LOW RANGE  (setPower 23-58)  — confirmed OK:
//     Bulb dims from lowest visible brightness up to medium.
//
//   Zone C — bulb-specific LED driver dead zone  (setPower 59-64):
//     The switching converter inside this LED bulb cannot regulate at
//     these specific phase angles — bulb cuts off completely.
//     This is hardware-specific (not a 60 Hz library issue).
//     FIX: jump from low range top (58) directly to high range start (64).
//
//   WORKING HIGH RANGE  (setPower 64-99)  — confirmed OK:
//     Bulb brightens from lowest high-range level up to maximum.
//
// DISTRIBUTION — 10 steps evenly spread across the two working bands:
//   Low  band (23-58, 36 values): steps 10%-50%  -> 23, 32, 41, 50, 58
//   High band (64-99, 36 values): steps 60%-100% -> 64, 73, 82, 91, 99
//
// HOW TO TUNE:
//   1. Flash dimmerTester with DEBUG_MODE = true.
//   2. Open serial monitor at 9600 baud.
//   3. Send  RAW:<n>  to test a raw setPower(n) directly (e.g. "RAW:64").
//   4. Adjust the failing entry here and reflash the main firmware.
//
static const uint8_t BRIGHTNESS_LUT[11] = {
    0,  // 0%  -> OFF via setState(OFF); value never passed to setPower()
    23, // 10% -> low range start  (first confirmed dim level)
    32, // 20%
    41, // 30%
    50, // 40%
    58, // 50% -> low range end
    75, // 60% -> high range start (skips dead zone 59-64)
    80, // 70%
    85, // 80%
    91, // 90%
    99, // 100%
};