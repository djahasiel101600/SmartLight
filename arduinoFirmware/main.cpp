/*
  RobotDyn 2-Channel AC Light Dimmer Control - RPi4 Optimized

  Controls RobotDyn 2-Channel AC Light Dimmer Module via PWM signals.
  Optimized for reliable communication with Raspberry Pi 4.

  Communication Protocol (same as original):
  - Format: "BEHAVIOR:BRIGHTNESS\n"
  - Example: "idle:30\n" → 30% brightness
  - Response: "OK: behavior @ brightness%" or "ERROR: ..."

  Hardware:
  - Arduino UNO R3
  - RobotDyn 2-Channel AC Light Dimmer Module
  - Connections:
    * Dimmer CH1 (PWM) → Pin 9
    * Dimmer CH2 (PWM) → Pin 10
    * GND → GND

  RPi4 Integration Features:
  - Enhanced error recovery
  - Command queue protection
  - Non-blocking operations
  - Detailed status reporting

  Author: Optimized for Ambient Lighting Project
  Date: 2026-05-08
*/

// =============================================================================
// CONFIGURATION
// =============================================================================

// PWM Pins
const int PWM_PIN_CH1 = 9;
const int PWM_PIN_CH2 = 10;

// Status LED
const int STATUS_LED = 13;

// Serial communication
const int SERIAL_BAUD = 9600;
const int BUFFER_SIZE = 64; // Increased for longer behavior names

// Brightness mapping (0-100% → 0-255 PWM)
const int PWM_MAX = 255;
const int PWM_MIN = 0;

// Timing configuration
const unsigned long COMMAND_TIMEOUT = 60000;   // 60 seconds timeout (activity can be stable for a long time)
const unsigned long HEARTBEAT_INTERVAL = 1000; // Send heartbeat every 1 second
const unsigned long SERIAL_TIMEOUT = 100;      // Serial read timeout (ms)

// Fade configuration
const bool ENABLE_FADING = true; // Enable smooth transitions
const int FADE_STEPS = 20;       // Number of fade steps
const int FADE_DELAY_MS = 15;    // Delay between steps (ms)

// Debug mode (disable for production)
const bool DEBUG_MODE = false;

// =============================================================================
// GLOBAL VARIABLES
// =============================================================================

char serialBuffer[BUFFER_SIZE];
int bufferIndex = 0;

int currentBrightness_CH1 = 0;
int currentBrightness_CH2 = 0;
int targetBrightness_CH1 = 0;
int targetBrightness_CH2 = 0;

unsigned long lastCommandTime = 0;
unsigned long lastHeartbeatTime = 0;
bool timeoutEnabled = true; // Can be disabled by RPi

// Command queue protection
bool processingCommand = false;
unsigned long lastResponseTime = 0;

// =============================================================================
// SETUP
// =============================================================================

void setup()
{
    // Initialize serial with timeout protection
    Serial.begin(SERIAL_BAUD);
    Serial.setTimeout(SERIAL_TIMEOUT);

    // Configure pins
    pinMode(PWM_PIN_CH1, OUTPUT);
    pinMode(PWM_PIN_CH2, OUTPUT);
    pinMode(STATUS_LED, OUTPUT);

    // Initialize to safe state
    analogWrite(PWM_PIN_CH1, 0);
    analogWrite(PWM_PIN_CH2, 0);

    // Send ready signal with device info
    delay(100); // Allow Serial to stabilize
    sendReadySignal();

    // Startup blink sequence
    statusBlink(3);
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

    // Apply brightness
    int pwmValue = map(brightness, 0, 100, PWM_MIN, PWM_MAX);

    if (ENABLE_FADING)
    {
        // Set target for smooth fading
        targetBrightness_CH1 = pwmValue;
        targetBrightness_CH2 = pwmValue;
    }
    else
    {
        // Immediate change
        setBothChannels(pwmValue);
    }

    // Send success response
    sendCommandAck(behavior, brightness);

    // Log behavior change
    if (DEBUG_MODE)
    {
        logBrightnessChange(behavior, brightness, pwmValue);
    }

    statusBlink(1);
    processingCommand = false;
}

// =============================================================================
// BRIGHTNESS CONTROL
// =============================================================================

void setBothChannels(int pwmValue)
{
    analogWrite(PWM_PIN_CH1, pwmValue);
    analogWrite(PWM_PIN_CH2, pwmValue);

    currentBrightness_CH1 = pwmValue;
    currentBrightness_CH2 = pwmValue;
    targetBrightness_CH1 = pwmValue;
    targetBrightness_CH2 = pwmValue;
}

void setChannel(int channel, int pwmValue)
{
    if (channel == 1)
    {
        analogWrite(PWM_PIN_CH1, pwmValue);
        currentBrightness_CH1 = pwmValue;
        targetBrightness_CH1 = pwmValue;
    }
    else if (channel == 2)
    {
        analogWrite(PWM_PIN_CH2, pwmValue);
        currentBrightness_CH2 = pwmValue;
        targetBrightness_CH2 = pwmValue;
    }
}

void updateFading()
{
    static unsigned long lastFadeUpdate = 0;

    if (millis() - lastFadeUpdate < FADE_DELAY_MS)
    {
        return;
    }

    lastFadeUpdate = millis();
    bool updated = false;

    // Update channel 1
    if (currentBrightness_CH1 != targetBrightness_CH1)
    {
        int step = (targetBrightness_CH1 > currentBrightness_CH1) ? max(1, (targetBrightness_CH1 - currentBrightness_CH1) / FADE_STEPS) : min(-1, (targetBrightness_CH1 - currentBrightness_CH1) / FADE_STEPS);

        currentBrightness_CH1 += step;

        // Clamp to target
        if ((step > 0 && currentBrightness_CH1 >= targetBrightness_CH1) ||
            (step < 0 && currentBrightness_CH1 <= targetBrightness_CH1))
        {
            currentBrightness_CH1 = targetBrightness_CH1;
        }

        analogWrite(PWM_PIN_CH1, currentBrightness_CH1);
        updated = true;
    }

    // Update channel 2
    if (currentBrightness_CH2 != targetBrightness_CH2)
    {
        int step = (targetBrightness_CH2 > currentBrightness_CH2) ? max(1, (targetBrightness_CH2 - currentBrightness_CH2) / FADE_STEPS) : min(-1, (targetBrightness_CH2 - currentBrightness_CH2) / FADE_STEPS);

        currentBrightness_CH2 += step;

        if ((step > 0 && currentBrightness_CH2 >= targetBrightness_CH2) ||
            (step < 0 && currentBrightness_CH2 <= targetBrightness_CH2))
        {
            currentBrightness_CH2 = targetBrightness_CH2;
        }

        analogWrite(PWM_PIN_CH2, currentBrightness_CH2);
        updated = true;
    }

    if (updated && DEBUG_MODE)
    {
        printDebug("Fading", currentBrightness_CH1);
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
            Serial.print("[HEARTBEAT] ");
            Serial.print("CH1:");
            Serial.print(map(currentBrightness_CH1, PWM_MIN, PWM_MAX, 0, 100));
            Serial.print("% CH2:");
            Serial.print(map(currentBrightness_CH2, PWM_MIN, PWM_MAX, 0, 100));
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
    Serial.println("READY: RobotDyn Dimmer Controller v2.0");
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
    Serial.print(map(currentBrightness_CH1, PWM_MIN, PWM_MAX, 0, 100));
    Serial.print(",CH2=");
    Serial.print(map(currentBrightness_CH2, PWM_MIN, PWM_MAX, 0, 100));
    Serial.print(",TIMEOUT=");
    Serial.print(timeoutEnabled ? "ON" : "OFF");
    Serial.println();
}

void logBrightnessChange(char *behavior, int brightness, int pwmValue)
{
    printDebug("Behavior", behavior);
    printDebug("Brightness%", brightness);
    printDebug("PWM_Value", pwmValue);
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