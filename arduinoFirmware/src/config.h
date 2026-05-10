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
// CONFIRMED DEAD ZONES on this hardware (60 Hz / dimmable LED bulb):
//
//   Zone A — 60 Hz timer overflow (setPower 0-15):
//     powerBuf[0-15] = 526-600, all > 520 half-cycle ticks.
//     The TRIAC never resets within the half-cycle; dimCounter overflows into
//     the next half-cycle and fires near the zero crossing = full brightness.
//     FIX: 0% uses setState(OFF) in applyChannel(). Values 1-15 are skipped.
//
//   Zone B — near-cutoff dim (setPower 16-34):
//     Fires at 96-77% into the half-cycle. Leaves 96-1440 us of conduction.
//     setPower(16) = dead (96 us, LED driver can't sustain).
//     setPower(17-34) = extremely dim or unreliable flicker.
//     FIX: logical 10% and 20% are remapped to setPower(35) and setPower(40),
//     the first confirmed reliable dim levels.
//
//   Zone C — LED driver dead zone (setPower 55-71):
//     powerBuf values 274-186, firing at ~36-54% into half-cycle.
//     The switching converter inside this LED bulb cannot regulate at these
//     phase angles — bulb cuts off completely. This is hardware-specific.
//     FIX: logical 60% jumps directly to setPower(72), the first confirmed
//     reliable high-range value.
//
// CONFIRMED WORKING RANGES:
//   Low range:  setPower 35-54  (logical 10%-50%)
//   High range: setPower 72-99  (logical 60%-100%)
//
// HOW TO TUNE:
//   1. Flash with DEBUG_MODE = true.
//   2. Open serial monitor at 9600 baud.
//   3. Send  RAW:<n>  to test a raw setPower(n) directly (e.g. "RAW:72").
//   4. Adjust the failing entry and reflash.
//
static const uint8_t BRIGHTNESS_LUT[11] = {
    0,  // 0%  -> OFF via setState(OFF); this value is never passed to setPower
    35, // 10% -> first confirmed reliable dim  (powerBuf=400, 77% into cycle)
    40, // 20% -> slight step up                (powerBuf=370, 71% into cycle)
    44, // 30% -> confirmed working             (powerBuf=340, 65% into cycle)
    49, // 40% ->                               (powerBuf=310, 60% into cycle)
    54, // 50% -> confirmed working             (powerBuf=280, 54% into cycle)
    72, // 60% -> SKIPS dead zone (55-71); jumps to high range (powerBuf=168)
    79, // 70% -> confirmed working             (powerBuf=126, 24% into cycle)
    84, // 80% -> confirmed working             (powerBuf= 96, 18% into cycle)
    91, // 90% -> confirmed working             (powerBuf= 54, 10% into cycle)
    99, // 100%-> confirmed working             (powerBuf=  8,  2% into cycle)
}