/*
  RobotDyn 2-Channel AC Light Dimmer Control - RPi4 Optimized

  Controls RobotDyn 2-Channel AC Light Dimmer Module using zero-crossing
  synchronized TRIAC triggering via the RBDimmer library.
  Simple analogWrite() cannot produce smooth AC dimming — the TRIAC must be
  fired at a precise delay after each AC zero-crossing.

  *** REQUIRES: RBDimmer library ***
  Arduino IDE → Sketch → Include Library → Manage Libraries → search "RBDimmer"

  Communication Protocol (unchanged):
  - Format: "BEHAVIOR:BRIGHTNESS\n"
  - Example: "idle:30\n" → 30% brightness
  - Response: "OK:behavior:brightness" or "ERROR:..."

  Hardware:
  - Arduino UNO R3
  - RobotDyn 2-Channel AC Light Dimmer Module
  - Connections:
    * Dimmer Z-C  → Pin 2  (interrupt pin — REQUIRED for smooth ZC-sync dimming)
    * Dimmer CH1  → Pin 9
    * Dimmer CH2  → Pin 10
    * GND         → GND

  Author: Optimized for Ambient Lighting Project
  Date: 2026-05-08
*/

#include <RBDdimmer.h>

// =============================================================================
// CONFIGURATION
// =============================================================================

// Pins
const int ZC_PIN = 2; // Zero-cross detection — must be interrupt-capable (pin 2 or 3 on UNO)
const int PWM_PIN_CH1 = 9;
const int PWM_PIN_CH2 = 10;
const int STATUS_LED = 13;

// Serial communication
const int SERIAL_BAUD = 9600;
const int BUFFER_SIZE = 64;

// Timing configuration
const unsigned long COMMAND_TIMEOUT = 60000;   // 60 s — activity can be stable for a long time
const unsigned long HEARTBEAT_INTERVAL = 1000; // heartbeat interval (ms)
const unsigned long SERIAL_TIMEOUT_MS = 100;   // serial read timeout (ms)

// Fade configuration (operates in 0-100 % space)
const bool ENABLE_FADING = true;
const int FADE_STEP_SIZE = 2; // % per tick — increase to fade faster
const int FADE_DELAY_MS = 20; // ms per tick → 50 ticks × 2% = 0→100% in ~1 s

// Debug mode (disable for production)
const bool DEBUG_MODE = false;

// =============================================================================
// DIMMER OBJECTS
// =============================================================================

// dimmerLamp constructor takes only the PWM pin.
// The ZC pin is set globally by the library via the first begin() call.
dimmerLamp dimmer1(PWM_PIN_CH1);
dimmerLamp dimmer2(PWM_PIN_CH2);

// =============================================================================
// GLOBAL VARIABLES
// =============================================================================

char serialBuffer[BUFFER_SIZE];
int bufferIndex = 0;

// Brightness in percentage (0–100) — no raw PWM values used
int currentBrightness_CH1 = 0;
int currentBrightness_CH2 = 0;
int targetBrightness_CH1 = 0;
int targetBrightness_CH2 = 0;

unsigned long lastCommandTime = 0;
unsigned long lastHeartbeatTime = 0;
bool timeoutEnabled = true;
bool processingCommand = false;

// Pi connection state — lights stay OFF until Pi sends its first command
bool piConnected = false;

// =============================================================================
// FORWARD DECLARATIONS
// (PlatformIO does not auto-generate these unlike Arduino IDE)
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
void printDebug(const char *label, int value);
void printDebug(const char *label, const char *value);

// =============================================================================
// SETUP
// =============================================================================

void setup()
{
    Serial.begin(SERIAL_BAUD);
    Serial.setTimeout(SERIAL_TIMEOUT_MS);

    pinMode(STATUS_LED, OUTPUT);

    // Initialize dimmers — library attaches ZC interrupt on ZC_PIN internally
    dimmer1.begin(NORMAL_MODE, ON);
    dimmer2.begin(NORMAL_MODE, ON);
    dimmer1.setPower(0);
    dimmer2.setPower(0);

    currentBrightness_CH1 = 0;
    currentBrightness_CH2 = 0;
    targetBrightness_CH1 = 0;
    targetBrightness_CH2 = 0;

    delay(100); // Allow Serial to stabilize
    sendReadySignal();

    // Do NOT run the POST light ramp here.
    // Lights stay OFF until the Raspberry Pi connects and sends its first command.
    // The POST ramp runs automatically on first Pi command (see processCommand).

    // Startup blink sequence (STATUS LED only, no light output)
    statusBlink(3);
}

// =============================================================================
// POST (POWER-ON SELF-TEST)
// =============================================================================

/**
 * Smooth ramp 0% → 100% → 0% using ZC-synchronized dimmer library.
 * 1% step every POST_STEP_MS ms → ramp-up ~1.5 s, hold 0.5 s, ramp-down ~1.5 s.
 * With ZC-sync this produces a perfectly smooth analogue-looking fade.
 */
void runLightPOST()
{
    const int POST_STEP_MS = 15; // ms per 1% step — tune for desired speed

    Serial.println("POST: Light ramp test started");

    // Ramp up: 0% → 100%
    for (int pct = 0; pct <= 100; pct++)
    {
        dimmer1.setPower(pct);
        dimmer2.setPower(pct);
        currentBrightness_CH1 = pct;
        currentBrightness_CH2 = pct;
        delay(POST_STEP_MS);
    }

    // Brief hold at full brightness
    delay(500);

    // Ramp down: 100% → 0%
    for (int pct = 100; pct >= 0; pct--)
    {
        dimmer1.setPower(pct);
        dimmer2.setPower(pct);
        currentBrightness_CH1 = pct;
        currentBrightness_CH2 = pct;
        delay(POST_STEP_MS);
    }

    // Sync target state
    targetBrightness_CH1 = 0;
    targetBrightness_CH2 = 0;

    Serial.println("POST: Light ramp test complete");
}

// =============================================================================
// MAIN LOOP
// =============================================================================

void loop()
{
    // Process incoming serial commands
    processSerialInput();

    // Handle fading (non-blocking)
    if (ENABLE_FADING)
    {
        updateFading();
    }

    // Safety timeout check
    if (timeoutEnabled)
    {
        checkSafetyTimeout();
    }

    // Optional heartbeat for connection monitoring
    sendHeartbeat();

    // Small delay to prevent overwhelming the system
    delay(5);
}

// =============================================================================
// SERIAL COMMUNICATION
// =============================================================================

void processSerialInput()
{
    if (Serial.available() > 0)
    {
        char inChar = Serial.read();

        if (inChar == '\n' || inChar == '\r')
        { // Handle both newline types
            if (bufferIndex > 0)
            {
                serialBuffer[bufferIndex] = '\0';
                processCommand(serialBuffer);
                bufferIndex = 0;
            }
        }
        else if (bufferIndex < BUFFER_SIZE - 1)
        {
            serialBuffer[bufferIndex] = inChar;
            bufferIndex++;
        }
        else
        {
            // Buffer overflow - clear and report error
            bufferIndex = 0;
            sendError("Command too long");
        }

        lastCommandTime = millis();
    }
}

void processCommand(char *command)
{
    processingCommand = true;

    // Handle special commands first
    if (strcmp(command, "PING") == 0)
    {
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

    // Parse behavior:brightness format
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

    // Validate brightness
    int brightness = validateBrightness(brightnessStr);
    if (brightness < 0)
    {
        processingCommand = false;
        return;
    }

    // Apply brightness directly in % — no map() needed with ZC-sync library
    //
    // First valid command from Pi: run the POST ramp now so the light confirms
    // connection, then immediately set the requested brightness level.
    if (!piConnected)
    {
        piConnected = true;
        Serial.println("STATUS: Pi connected — light active");
        runLightPOST();
    }

    if (ENABLE_FADING)
    {
        // Set target for smooth fading
        targetBrightness_CH1 = brightness;
        targetBrightness_CH2 = brightness;
    }
    else
    {
        // Immediate change
        setBothChannels(brightness);
    }

    // Send success response
    sendCommandAck(behavior, brightness);

    // Log behavior change
    if (DEBUG_MODE)
    {
        logBrightnessChange(behavior, brightness);
    }

    statusBlink(1);
    processingCommand = false;
}

// =============================================================================
// BRIGHTNESS CONTROL (0–100 %)
// =============================================================================

void setBothChannels(int pct)
{
    dimmer1.setPower(pct);
    dimmer2.setPower(pct);
    currentBrightness_CH1 = pct;
    currentBrightness_CH2 = pct;
    targetBrightness_CH1 = pct;
    targetBrightness_CH2 = pct;
}

void setChannel(int channel, int pct)
{
    if (channel == 1)
    {
        dimmer1.setPower(pct);
        currentBrightness_CH1 = pct;
        targetBrightness_CH1 = pct;
    }
    else if (channel == 2)
    {
        dimmer2.setPower(pct);
        currentBrightness_CH2 = pct;
        targetBrightness_CH2 = pct;
    }
}

void updateFading()
{
    static unsigned long lastFadeUpdate = 0;

    if (millis() - lastFadeUpdate < (unsigned long)FADE_DELAY_MS)
    {
        return;
    }

    lastFadeUpdate = millis();

    // Channel 1
    if (currentBrightness_CH1 != targetBrightness_CH1)
    {
        int step = (targetBrightness_CH1 > currentBrightness_CH1) ? FADE_STEP_SIZE : -FADE_STEP_SIZE;
        currentBrightness_CH1 += step;

        // Clamp to target
        if ((step > 0 && currentBrightness_CH1 > targetBrightness_CH1) ||
            (step < 0 && currentBrightness_CH1 < targetBrightness_CH1))
        {
            currentBrightness_CH1 = targetBrightness_CH1;
        }

        dimmer1.setPower(currentBrightness_CH1);
    }

    // Channel 2
    if (currentBrightness_CH2 != targetBrightness_CH2)
    {
        int step = (targetBrightness_CH2 > currentBrightness_CH2) ? FADE_STEP_SIZE : -FADE_STEP_SIZE;
        currentBrightness_CH2 += step;

        if ((step > 0 && currentBrightness_CH2 > targetBrightness_CH2) ||
            (step < 0 && currentBrightness_CH2 < targetBrightness_CH2))
        {
            currentBrightness_CH2 = targetBrightness_CH2;
        }

        dimmer2.setPower(currentBrightness_CH2);
    }

    if (DEBUG_MODE && (currentBrightness_CH1 != targetBrightness_CH1 ||
                       currentBrightness_CH2 != targetBrightness_CH2))
    {
        printDebug("Fading CH1", currentBrightness_CH1);
    }
}

// =============================================================================
// VALIDATION & HELPERS
// =============================================================================

int validateBrightness(char *brightnessStr)
{
    // Check if string contains only digits
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
        setBothChannels(0);
        sendStatus("TIMEOUT - Lights OFF");
        lastCommandTime = millis(); // Reset to prevent continuous triggers
        statusBlink(2);
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
// RESPONSE FUNCTIONS
// =============================================================================

void sendReadySignal()
{
    // Single line only — Python reads exactly one line in check_ready()
    Serial.println("READY: RobotDyn Dimmer Controller v3.0 (ZC-Sync)");
}

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

// =============================================================================
// EMERGENCY HANDLERS
// =============================================================================

// Watchdog timer for critical failures (optional)
void setupWatchdog()
{
// For Arduino UNO, watchdog timer can be enabled
// This requires including <avr/wdt.h>
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