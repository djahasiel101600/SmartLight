/*
  RobotDyn 2-Channel AC Light Dimmer Control - RPi4 Optimized

  Follows the official RBDDimmer SerialMonitorDim example exactly:
    - begin(NORMAL_MODE, ON)  — ISR runs continuously, setPower(0) = light off
    - setPower() is the only brightness control call; setState() never used
    - ENABLE_FADING = false for direct 0-100% testing (set true after verified)
*/

#include <RBDdimmer.h>

// =============================================================================
// CONFIGURATION  (UNCHANGED)
// =============================================================================

const int ZC_PIN = 2;
const int PWM_PIN_CH1 = 9;
const int PWM_PIN_CH2 = 10;
const int STATUS_LED = 13;

const int SERIAL_BAUD = 9600;
const int BUFFER_SIZE = 64;

const unsigned long COMMAND_TIMEOUT = 60000;
const unsigned long HEARTBEAT_INTERVAL = 1000;
const unsigned long SERIAL_TIMEOUT_MS = 100;

const bool ENABLE_FADING = false; // Set true after 10-step brightness test passes
const int FADE_STEP_SIZE = 2;
const int FADE_DELAY_MS = 20;

unsigned long blinkUntil = 0;
const bool DEBUG_MODE = false;

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
// This table maps the 11 logical levels (0%, 10%, … 100%) to safe setPower()
// values that avoid both the 60 Hz cutoff and the known LED dead zones.
// Values in between are linearly interpolated by mapBrightness().
//
// TUNING: adjust any entry if a level appears off/wrong on your bulb.
// Use the serial command  RAW:<n>  to test individual setPower(n) values live
// without reflashing firmware (e.g. send "RAW:54" → setPower(54) directly).
//
static const uint8_t BRIGHTNESS_LUT[11] = {
    0,  // 0%  → explicit off  (always 0)
    16, // 10% → first reliable level at 60 Hz (powerBuf[16] = 514 < 520)
    26, // 20%
    35, // 30%
    44, // 40%
    54, // 50% → shifted +4 to skip setPower(50) dead zone
    63, // 60%
    72, // 70%
    84, // 80% → shifted +4 to skip setPower(80) dead zone
    91, // 90%
    99, // 100% (library internally clamps ≥99 → 99)
};

// =============================================================================
// DIMMER OBJECTS
// =============================================================================

dimmerLamp dimmer1(PWM_PIN_CH1);
dimmerLamp dimmer2(PWM_PIN_CH2);

// =============================================================================
// GLOBAL STATE
// =============================================================================

char serialBuffer[BUFFER_SIZE];
int bufferIndex = 0;

// All brightness values below are in the *requested* 0–100 space (what the
// Pi sent / what STATUS reports). The perceptual curve is applied only at
// the moment we hand a value to the dimmer driver.
int currentBrightness_CH1 = 0;
int currentBrightness_CH2 = 0;
int targetBrightness_CH1 = 0;
int targetBrightness_CH2 = 0;

// Sub-percent accumulators for smooth time-based fading.
// Stored ×100 so we can do integer math without floats in the hot loop.
long fadeAccum_CH1 = 0; // = currentBrightness_CH1 * 100
long fadeAccum_CH2 = 0;

unsigned long lastCommandTime = 0;
unsigned long lastHeartbeatTime = 0;
unsigned long lastFadeTickMicros = 0;

bool timeoutEnabled = true;
bool processingCommand = false;
bool piConnected = false;

// =============================================================================
// FORWARD DECLARATIONS
// =============================================================================
void sendReadySignal();
void runLightPOST();
void statusBlink(int count);
void processSerialInput();
void processCommand(char *command);
void updateFading();
void checkSafetyTimeout();
void sendHeartbeat();
void setBothChannels(int pct);
void setChannel(int channel, int pct);
int validateBrightness(char *brightnessStr);
void sendCommandAck(char *behavior, int brightness);
void sendResponse(const char *message);
void sendError(const char *error);
void sendStatus(const char *status);
void sendStatusReport();
void logBrightnessChange(char *behavior, int brightness);
void resetDevice();
void disconnectDevice();
void printDebug(const char *label, int value);
void printDebug(const char *label, const char *value);

// Internal helpers
static uint8_t mapBrightness(int pct);
static void applyChannel(uint8_t channel, int requestedPct);

// =============================================================================
// SETUP
// =============================================================================

void setup()
{
    Serial.begin(SERIAL_BAUD);
    Serial.setTimeout(SERIAL_TIMEOUT_MS);

    pinMode(STATUS_LED, OUTPUT);

    // begin(NORMAL_MODE, ON) matches the official RBDDimmer example exactly.
    // The ZC ISR runs continuously; setPower(0) suppresses TRIAC firing —
    // no setState() calls needed or wanted after this point.
    dimmer1.begin(NORMAL_MODE, ON);
    dimmer2.begin(NORMAL_MODE, ON);
    dimmer1.setPower(0);
    dimmer2.setPower(0);

    currentBrightness_CH1 = 0;
    currentBrightness_CH2 = 0;
    targetBrightness_CH1 = 0;
    targetBrightness_CH2 = 0;
    fadeAccum_CH1 = 0;
    fadeAccum_CH2 = 0;

    lastFadeTickMicros = micros();

    delay(100);
    sendReadySignal();
    statusBlink(3);
}

// =============================================================================
// POST
// =============================================================================

void runLightPOST()
{
    const int POST_STEP_MS = 15;

    Serial.println("POST: Light ramp test started");

    // Ramp up
    for (int pct = 0; pct <= 100; pct++)
    {
        applyChannel(1, pct);
        applyChannel(2, pct);
        currentBrightness_CH1 = pct;
        currentBrightness_CH2 = pct;
        delay(POST_STEP_MS);
    }

    delay(500);

    // Ramp down
    for (int pct = 100; pct >= 0; pct--)
    {
        applyChannel(1, pct);
        applyChannel(2, pct);
        currentBrightness_CH1 = pct;
        currentBrightness_CH2 = pct;
        delay(POST_STEP_MS);
    }

    targetBrightness_CH1 = 0;
    targetBrightness_CH2 = 0;
    fadeAccum_CH1 = 0;
    fadeAccum_CH2 = 0;

    Serial.println("POST: Light ramp test complete");
}

// =============================================================================
// MAIN LOOP
// =============================================================================

void loop()
{
    processSerialInput();

    if (ENABLE_FADING)
    {
        updateFading();
    }

    if (timeoutEnabled)
    {
        checkSafetyTimeout();
    }

    sendHeartbeat();

    digitalWrite(STATUS_LED, (millis() < blinkUntil) ? HIGH : LOW);

    delay(2); // smaller than before so fade ticks are sampled more evenly
}

// =============================================================================
// SERIAL
// =============================================================================

void processSerialInput()
{
    while (Serial.available() > 0)
    {
        char inChar = Serial.read();

        if (inChar == '\n' || inChar == '\r')
        {
            if (bufferIndex > 0)
            {
                serialBuffer[bufferIndex] = '\0';
                processCommand(serialBuffer);
                bufferIndex = 0;
            }
        }
        else if (bufferIndex < BUFFER_SIZE - 1)
        {
            serialBuffer[bufferIndex++] = inChar;
        }
        else
        {
            bufferIndex = 0;
            sendError("Command too long");
        }

        lastCommandTime = millis();
    }
}

void processCommand(char *command)
{
    processingCommand = true;

    if (strcmp(command, "PING") == 0)
    {
        if (!piConnected)
        {
            piConnected = true;
            Serial.println("STATUS: Pi reconnected via PING");
        }
        sendResponse("PONG");
        processingCommand = false;
        return;
    }

    if (strcmp(command, "STATUS") == 0)
    {
        sendStatusReport();
        processingCommand = false;
        return;
    }
    if (strcmp(command, "DISABLE_TIMEOUT") == 0)
    {
        timeoutEnabled = false;
        sendResponse("Timeout disabled");
        processingCommand = false;
        return;
    }
    if (strcmp(command, "ENABLE_TIMEOUT") == 0)
    {
        timeoutEnabled = true;
        sendResponse("Timeout enabled");
        processingCommand = false;
        return;
    }
    if (strcmp(command, "RESET") == 0)
    {
        resetDevice();
        processingCommand = false;
        return;
    }
    if (strcmp(command, "DISCONNECT") == 0)
    {
        disconnectDevice();
        processingCommand = false;
        return;
    }

    // RAW:<n> — bypass BRIGHTNESS_LUT and call setPower(n) directly.
    // Use this to identify safe setPower() values for your specific bulb,
    // then update the BRIGHTNESS_LUT constants above accordingly.
    if (strncmp(command, "RAW:", 4) == 0)
    {
        int rawVal = atoi(command + 4);
        if (rawVal < 0)
            rawVal = 0;
        if (rawVal > 99)
            rawVal = 99;
        dimmer1.setPower((uint8_t)rawVal);
        dimmer2.setPower((uint8_t)rawVal);
        Serial.print("RAW_SET:");
        Serial.println(rawVal);
        processingCommand = false;
        return;
    }

    char *colonPos = strchr(command, ':');
    if (colonPos == NULL)
    {
        sendError("Invalid format. Use BEHAVIOR:BRIGHTNESS");
        processingCommand = false;
        return;
    }

    *colonPos = '\0';
    char *behavior = command;
    char *brightnessStr = colonPos + 1;

    int brightness = validateBrightness(brightnessStr);
    if (brightness < 0)
    {
        processingCommand = false;
        return;
    }

    if (!piConnected)
    {
        piConnected = true;
        Serial.println("STATUS: Pi connected — light active");
        runLightPOST();
    }

    if (ENABLE_FADING)
    {
        targetBrightness_CH1 = brightness;
        targetBrightness_CH2 = brightness;
    }
    else
    {
        setBothChannels(brightness);
    }

    sendCommandAck(behavior, brightness);

    if (DEBUG_MODE)
        logBrightnessChange(behavior, brightness);

    blinkUntil = millis() + 160;
    processingCommand = false;
}

// =============================================================================
// BRIGHTNESS CONTROL
// =============================================================================
//
// mapBrightness() translates a logical 0–100% to a safe setPower() value
// via the BRIGHTNESS_LUT anchor points with linear interpolation.
// This corrects for the 60 Hz calibration mismatch and LED dead zones.
//
static uint8_t mapBrightness(int pct)
{
    if (pct <= 0)
        return BRIGHTNESS_LUT[0];
    if (pct >= 100)
        return BRIGHTNESS_LUT[10];

    int lo = pct / 10;
    int hi = lo + 1;
    int frac = pct % 10;
    // Integer linear interpolation between adjacent LUT entries
    int mapped = (int)BRIGHTNESS_LUT[lo] +
                 ((int)BRIGHTNESS_LUT[hi] - (int)BRIGHTNESS_LUT[lo]) * frac / 10;
    return (uint8_t)mapped;
}

// applyChannel() mirrors the official RBDDimmer SerialMonitorDim example:
// only setPower() is called — no setState(), no branch logic, no state flags.
// The ZC ISR is always running; setPower(0) is a clean "off" by design.
//
static void applyChannel(uint8_t channel, int requestedPct)
{
    if (requestedPct < 0)
        requestedPct = 0;
    if (requestedPct > 100)
        requestedPct = 100;

    uint8_t physical = mapBrightness(requestedPct);

    if (DEBUG_MODE)
    {
        Serial.print("[DEBUG] ch=");
        Serial.print(channel);
        Serial.print(" logical=");
        Serial.print(requestedPct);
        Serial.print(" physical=");
        Serial.println(physical);
    }

    if (channel == 1)
        dimmer1.setPower(physical);
    else
        dimmer2.setPower(physical);
}

void setBothChannels(int pct)
{
    applyChannel(1, pct);
    applyChannel(2, pct);
    currentBrightness_CH1 = pct;
    currentBrightness_CH2 = pct;
    targetBrightness_CH1 = pct;
    targetBrightness_CH2 = pct;
    fadeAccum_CH1 = (long)pct * 100;
    fadeAccum_CH2 = (long)pct * 100;
}

void setChannel(int channel, int pct)
{
    if (channel == 1)
    {
        if (ENABLE_FADING)
        {
            targetBrightness_CH1 = pct;
        }
        else
        {
            applyChannel(1, pct);
            currentBrightness_CH1 = pct;
            targetBrightness_CH1 = pct;
            fadeAccum_CH1 = (long)pct * 100;
        }
    }
    else if (channel == 2)
    {
        if (ENABLE_FADING)
        {
            targetBrightness_CH2 = pct;
        }
        else
        {
            applyChannel(2, pct);
            currentBrightness_CH2 = pct;
            targetBrightness_CH2 = pct;
            fadeAccum_CH2 = (long)pct * 100;
        }
    }
}

// =============================================================================
// FADE ENGINE  (time-based, sub-percent precision)
// =============================================================================
//
// We compute how many "% × 100" units we should advance based on real
// elapsed time, not a simple counter. This makes transitions smooth even
// when loop() jitters because of serial activity or heartbeats.
//
// Speed equivalence with the original config:
//   FADE_STEP_SIZE / FADE_DELAY_MS  =  2 % / 20 ms  =  100 % / 1000 ms
// We preserve that exact ramp speed.
//
void updateFading()
{
    unsigned long now = micros();
    unsigned long dt = now - lastFadeTickMicros;

    // Limit update rate to about every 2 ms — frequent enough to look smooth,
    // light enough to not starve serial.
    if (dt < 2000UL)
        return;
    lastFadeTickMicros = now;

    // Units per microsecond, scaled ×100 to match the accumulator scale.
    // rate = (FADE_STEP_SIZE * 100) / (FADE_DELAY_MS * 1000) per µs
    //      = FADE_STEP_SIZE / (FADE_DELAY_MS * 10)            per µs
    // For default 2 / 20 → 0.01 units(×100) per µs → 10000 per second.
    // We multiply first to keep precision in integer math.
    long advance = (long)dt * FADE_STEP_SIZE / (FADE_DELAY_MS * 10L);
    if (advance <= 0)
        return;

    // ---- Channel 1 ----
    long target1 = (long)targetBrightness_CH1 * 100;
    if (fadeAccum_CH1 != target1)
    {
        if (fadeAccum_CH1 < target1)
        {
            fadeAccum_CH1 += advance;
            if (fadeAccum_CH1 > target1)
                fadeAccum_CH1 = target1;
        }
        else
        {
            fadeAccum_CH1 -= advance;
            if (fadeAccum_CH1 < target1)
                fadeAccum_CH1 = target1;
        }

        int newPct = (int)(fadeAccum_CH1 / 100);
        if (newPct != currentBrightness_CH1)
        {
            currentBrightness_CH1 = newPct;
            applyChannel(1, newPct);
        }
    }

    // ---- Channel 2 ----
    long target2 = (long)targetBrightness_CH2 * 100;
    if (fadeAccum_CH2 != target2)
    {
        if (fadeAccum_CH2 < target2)
        {
            fadeAccum_CH2 += advance;
            if (fadeAccum_CH2 > target2)
                fadeAccum_CH2 = target2;
        }
        else
        {
            fadeAccum_CH2 -= advance;
            if (fadeAccum_CH2 < target2)
                fadeAccum_CH2 = target2;
        }

        int newPct = (int)(fadeAccum_CH2 / 100);
        if (newPct != currentBrightness_CH2)
        {
            currentBrightness_CH2 = newPct;
            applyChannel(2, newPct);
        }
    }

    if (DEBUG_MODE && (currentBrightness_CH1 != targetBrightness_CH1 ||
                       currentBrightness_CH2 != targetBrightness_CH2))
    {
        printDebug("Fading CH1", currentBrightness_CH1);
    }
}

// =============================================================================
// VALIDATION & HOUSEKEEPING (unchanged behavior)
// =============================================================================

int validateBrightness(char *brightnessStr)
{
    for (int i = 0; brightnessStr[i] != '\0'; i++)
    {
        if (!isdigit(brightnessStr[i]))
        {
            sendError("Brightness must be a number");
            return -1;
        }
    }

    int brightness = atoi(brightnessStr);
    if (brightness < 0 || brightness > 100)
    {
        char errorMsg[50];
        snprintf(errorMsg, sizeof(errorMsg), "Brightness out of range (0-100): %d", brightness);
        sendError(errorMsg);
        return -1;
    }
    return brightness;
}

void checkSafetyTimeout()
{
    if (lastCommandTime > 0 && (millis() - lastCommandTime) > COMMAND_TIMEOUT)
    {
        targetBrightness_CH1 = 0;
        targetBrightness_CH2 = 0;
        sendStatus("TIMEOUT - Lights fading OFF");
        lastCommandTime = millis();
        blinkUntil = millis() + 320;
    }
}

void sendHeartbeat()
{
    if (millis() - lastHeartbeatTime >= HEARTBEAT_INTERVAL)
    {
        if (DEBUG_MODE)
        {
            Serial.print("[HEARTBEAT] CH1:");
            Serial.print(currentBrightness_CH1);
            Serial.print("% CH2:");
            Serial.print(currentBrightness_CH2);
            Serial.println("%");
        }
        lastHeartbeatTime = millis();
    }
}

// =============================================================================
// RESPONSES (unchanged strings — protocol preserved)
// =============================================================================

void sendReadySignal() { Serial.println("READY: RobotDyn Dimmer Controller v3.0 (ZC-Sync)"); }

void sendCommandAck(char *behavior, int brightness)
{
    Serial.print("OK:");
    Serial.print(behavior);
    Serial.print(":");
    Serial.println(brightness);
}

void sendResponse(const char *message)
{
    Serial.print("RESPONSE:");
    Serial.println(message);
}
void sendError(const char *error)
{
    Serial.print("ERROR:");
    Serial.println(error);
}
void sendStatus(const char *status)
{
    Serial.print("STATUS:");
    Serial.println(status);
}

void sendStatusReport()
{
    Serial.print("REPORT:CH1=");
    Serial.print(currentBrightness_CH1);
    Serial.print(",CH2=");
    Serial.print(currentBrightness_CH2);
    Serial.print(",TIMEOUT=");
    Serial.println(timeoutEnabled ? "ON" : "OFF");
}

void logBrightnessChange(char *behavior, int brightness)
{
    printDebug("Behavior", behavior);
    printDebug("Brightness%", brightness);
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

void printDebug(const char *label, int value)
{
    Serial.print("[DEBUG] ");
    Serial.print(label);
    Serial.print(": ");
    Serial.println(value);
}

void printDebug(const char *label, const char *value)
{
    Serial.print("[DEBUG] ");
    Serial.print(label);
    Serial.print(": ");
    Serial.println(value);
}

void statusBlink(int count)
{
    for (int i = 0; i < count; i++)
    {
        digitalWrite(STATUS_LED, HIGH);
        delay(80);
        digitalWrite(STATUS_LED, LOW);
        delay(80);
    }
}

void resetDevice()
{
    sendStatus("Resetting device...");
    setBothChannels(0);
    timeoutEnabled = true;
    lastCommandTime = millis();
    statusBlink(5);
    sendStatus("Device reset complete");
}

void disconnectDevice()
{
    // Python is shutting down — setPower(0) stops TRIAC firing immediately.
    // setState() is intentionally not called (see setup() comment).
    dimmer1.setPower(0);
    dimmer2.setPower(0);

    currentBrightness_CH1 = 0;
    currentBrightness_CH2 = 0;
    targetBrightness_CH1 = 0;
    targetBrightness_CH2 = 0;
    fadeAccum_CH1 = 0;
    fadeAccum_CH2 = 0;

    piConnected = false;
    blinkUntil = millis() + 160;
    sendStatus("DISCONNECT - Lights off");
}

// =============================================================================
// EMERGENCY HANDLERS  (unchanged)
// =============================================================================

void setupWatchdog()
{
#ifdef ENABLE_WATCHDOG
    wdt_enable(WDTO_2S);
#endif
}

void resetWatchdog()
{
#ifdef ENABLE_WATCHDOG
    wdt_reset();
#endif
}
