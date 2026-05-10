/*
  RobotDyn Dimmer Range Tester
  ============================================================
  PURPOSE
    Sweep through every raw setPower(n) value (0-99) and let you
    observe the bulb. After each scan the firmware prints a full
    annotated list you can copy-paste and label in your notes.

  HOW TO USE
    1. Flash this sketch via PlatformIO.
    2. Open the serial monitor at 9600 baud.
    3. Choose a mode:

       SCAN          — step through 0..99 one at a time,
                       holding each value for DWELL_MS.
                       Prints the value + a blank label slot.
       SCAN:<step>   — same but skips in <step> increments.
                       E.g.  SCAN:5  tests 0,5,10,15,...,95,99.
                       Use this first to find dead zones fast,
                       then SCAN:1 to narrow down boundaries.
       HOLD:<n>      — lock the bulb at setPower(n) indefinitely.
                       Good for staring at a single level.
       NEXT          — advance one step (wraps 99 -> 0).
       PREV          — go back one step (wraps 0 -> 99).
       OFF           — setState(OFF): fully disarm the TRIAC.
       PAUSE         — freeze an auto-scan at the current value.
       RESUME        — continue a paused scan.
       REPORT        — print the full 0-99 result table with your
                       labels inserted (edit LABELS[] below first).

  LABELING RESULTS
    After running SCAN, copy the printed table from the serial
    monitor into the LABELS array below (one string per index).
    Suggested label strings:
      "OK"        — bulb lit, brightness looks correct
      "DIM"       — bulb lit but unexpectedly faint
      "FLICKER"   — bulb flickers or is unstable
      "DEAD"      — bulb completely off (dead zone)
      "BRIGHT"    — unexpectedly bright (e.g. 60 Hz overflow)
      ""          — not yet tested
    Reflash after editing LABELS[] and send REPORT to see the
    annotated table ready to paste into config.h.

  WIRING  (same as production firmware)
    ZC  pin 2   (hardware INT0 — fixed by RBDDimmer library)
    CH1 pin 9
    CH2 pin 10  (mirrors CH1 in this tester)
    LED pin 13
*/

#include <RBDdimmer.h>

// =============================================================================
// HARDWARE
// =============================================================================

const int PWM_PIN_CH1 = 9;
const int PWM_PIN_CH2 = 10;
const int STATUS_LED = 13;
const int SERIAL_BAUD = 9600;

// =============================================================================
// SCAN SETTINGS  — adjust before flashing if needed
// =============================================================================

// How long (ms) to hold each value during an auto-scan.
// Increase if you need more time to observe each step.
const int DWELL_MS = 2000;

// Default step size when SCAN (no argument) is sent.
const int DEFAULT_STEP = 1;

// =============================================================================
// LABEL TABLE
// ============================================================== ==============
// After your first scan, fill in the label for each index 0-99.
// Leave "" for values you haven't tested yet.
// Send REPORT over serial to print the full annotated table.
//
// IMPORTANT: array must stay exactly 100 entries.
//
const char *LABELS[100] = {
    /* 0  */ "",
    /* 1  */ "",
    /* 2  */ "",
    /* 3  */ "",
    /* 4  */ "",
    /* 5  */ "",
    /* 6  */ "",
    /* 7  */ "",
    /* 8  */ "",
    /* 9  */ "",
    /* 10 */ "",
    /* 11 */ "",
    /* 12 */ "",
    /* 13 */ "",
    /* 14 */ "",
    /* 15 */ "",
    /* 16 */ "",
    /* 17 */ "",
    /* 18 */ "",
    /* 19 */ "",
    /* 20 */ "",
    /* 21 */ "",
    /* 22 */ "",
    /* 23 */ "",
    /* 24 */ "",
    /* 25 */ "",
    /* 26 */ "",
    /* 27 */ "",
    /* 28 */ "",
    /* 29 */ "",
    /* 30 */ "",
    /* 31 */ "",
    /* 32 */ "",
    /* 33 */ "",
    /* 34 */ "",
    /* 35 */ "",
    /* 36 */ "",
    /* 37 */ "",
    /* 38 */ "",
    /* 39 */ "",
    /* 40 */ "",
    /* 41 */ "",
    /* 42 */ "",
    /* 43 */ "",
    /* 44 */ "",
    /* 45 */ "",
    /* 46 */ "",
    /* 47 */ "",
    /* 48 */ "",
    /* 49 */ "",
    /* 50 */ "",
    /* 51 */ "",
    /* 52 */ "",
    /* 53 */ "",
    /* 54 */ "",
    /* 55 */ "",
    /* 56 */ "",
    /* 57 */ "",
    /* 58 */ "",
    /* 59 */ "",
    /* 60 */ "",
    /* 61 */ "",
    /* 62 */ "",
    /* 63 */ "",
    /* 64 */ "",
    /* 65 */ "",
    /* 66 */ "",
    /* 67 */ "",
    /* 68 */ "",
    /* 69 */ "",
    /* 70 */ "",
    /* 71 */ "",
    /* 72 */ "",
    /* 73 */ "",
    /* 74 */ "",
    /* 75 */ "",
    /* 76 */ "",
    /* 77 */ "",
    /* 78 */ "",
    /* 79 */ "",
    /* 80 */ "",
    /* 81 */ "",
    /* 82 */ "",
    /* 83 */ "",
    /* 84 */ "",
    /* 85 */ "",
    /* 86 */ "",
    /* 87 */ "",
    /* 88 */ "",
    /* 89 */ "",
    /* 90 */ "",
    /* 91 */ "",
    /* 92 */ "",
    /* 93 */ "",
    /* 94 */ "",
    /* 95 */ "",
    /* 96 */ "",
    /* 97 */ "",
    /* 98 */ "",
    /* 99 */ "",
};

// =============================================================================
// DIMMER OBJECTS
// =============================================================================

dimmerLamp dimmer1(PWM_PIN_CH1);
dimmerLamp dimmer2(PWM_PIN_CH2);

// =============================================================================
// RUNTIME STATE
// =============================================================================

char serialBuffer[64];
int bufferIndex = 0;

int currentValue = 0; // last value passed to setPower()
int scanValue = 0;    // current position during auto-scan
int scanStep = DEFAULT_STEP;
bool scanning = false;
bool paused = false;
unsigned long lastDwellTime = 0;

// =============================================================================
// HELPERS
// =============================================================================

// Apply a raw setPower(n) value to both channels.
// n == -1 means setState(OFF) — the only safe "fully off" at 60 Hz.
void applyRaw(int n)
{
    if (n < 0)
    {
        dimmer1.setState(OFF);
        dimmer2.setState(OFF);
        currentValue = -1;
        Serial.println("[OFF] setState(OFF) applied");
        return;
    }
    if (n > 99)
        n = 99;

    dimmer1.setState(ON);
    dimmer2.setState(ON);
    dimmer1.setPower((uint8_t)n);
    dimmer2.setPower((uint8_t)n);
    currentValue = n;
}

// Print one scan row: "  setPower(42) | ???"
void printRow(int n, bool isCurrent)
{
    Serial.print(isCurrent ? " >> " : "    ");
    Serial.print("setPower(");
    if (n < 10)
        Serial.print("  ");
    else if (n < 100)
        Serial.print(" ");
    Serial.print(n);
    Serial.print(") | ");
    if (LABELS[n][0] != '\0')
        Serial.print(LABELS[n]);
    else
        Serial.print("???");
    Serial.println();
}

void printSeparator()
{
    Serial.println(F("------------------------------------"));
}

void printReport()
{
    printSeparator();
    Serial.println(F("DIMMER RANGE REPORT  (copy-paste to config.h)"));
    printSeparator();
    for (int i = 0; i < 100; i++)
        printRow(i, false);
    printSeparator();
}

// =============================================================================
// COMMAND PROCESSOR
// =============================================================================

void processCommand(char *cmd)
{
    // OFF
    if (strcmp(cmd, "OFF") == 0)
    {
        scanning = false;
        paused = false;
        applyRaw(-1);
        return;
    }

    // PAUSE
    if (strcmp(cmd, "PAUSE") == 0)
    {
        if (scanning)
        {
            paused = true;
            Serial.println(F("[PAUSED]"));
        }
        else
        {
            Serial.println(F("[INFO] Not scanning"));
        }
        return;
    }

    // RESUME
    if (strcmp(cmd, "RESUME") == 0)
    {
        if (scanning && paused)
        {
            paused = false;
            lastDwellTime = millis();
            Serial.println(F("[RESUMED]"));
        }
        else
        {
            Serial.println(F("[INFO] Nothing to resume"));
        }
        return;
    }

    // NEXT
    if (strcmp(cmd, "NEXT") == 0)
    {
        scanning = false;
        paused = false;
        int next = (currentValue < 0) ? 0 : (currentValue + 1) % 100;
        applyRaw(next);
        printRow(next, true);
        return;
    }

    // PREV
    if (strcmp(cmd, "PREV") == 0)
    {
        scanning = false;
        paused = false;
        int prev = (currentValue <= 0) ? 99 : currentValue - 1;
        applyRaw(prev);
        printRow(prev, true);
        return;
    }

    // REPORT
    if (strcmp(cmd, "REPORT") == 0)
    {
        printReport();
        return;
    }

    // HOLD:<n>
    if (strncmp(cmd, "HOLD:", 5) == 0)
    {
        scanning = false;
        paused = false;
        int n = atoi(cmd + 5);
        if (n < 0 || n > 99)
        {
            Serial.println(F("[ERROR] Range: 0-99"));
            return;
        }
        applyRaw(n);
        Serial.print(F("[HOLD] Locked at setPower("));
        Serial.print(n);
        Serial.println(F(")"));
        return;
    }

    // SCAN  or  SCAN:<step>
    if (strcmp(cmd, "SCAN") == 0 || strncmp(cmd, "SCAN:", 5) == 0)
    {
        if (strncmp(cmd, "SCAN:", 5) == 0)
        {
            int s = atoi(cmd + 5);
            scanStep = (s >= 1 && s <= 99) ? s : DEFAULT_STEP;
        }
        else
        {
            scanStep = DEFAULT_STEP;
        }

        scanValue = 0;
        scanning = true;
        paused = false;
        lastDwellTime = millis();
        applyRaw(scanValue);

        Serial.print(F("[SCAN] Starting scan, step="));
        Serial.print(scanStep);
        Serial.print(F(", dwell="));
        Serial.print(DWELL_MS);
        Serial.println(F("ms"));
        Serial.println(F("Send PAUSE to freeze, RESUME to continue."));
        printSeparator();
        printRow(scanValue, true);
        return;
    }

    Serial.println(F("[ERROR] Unknown command. Valid: SCAN, SCAN:<step>, HOLD:<n>, NEXT, PREV, OFF, PAUSE, RESUME, REPORT"));
}

// =============================================================================
// SERIAL INPUT
// =============================================================================

void processSerialInput()
{
    while (Serial.available() > 0)
    {
        char c = Serial.read();
        if (c == '\n' || c == '\r')
        {
            if (bufferIndex > 0)
            {
                serialBuffer[bufferIndex] = '\0';
                processCommand(serialBuffer);
                bufferIndex = 0;
            }
        }
        else if (bufferIndex < 63)
        {
            serialBuffer[bufferIndex++] = c;
        }
        else
        {
            bufferIndex = 0;
        }
    }
}

// =============================================================================
// SCAN ENGINE
// =============================================================================

void updateScan()
{
    if (!scanning || paused)
        return;
    if ((millis() - lastDwellTime) < (unsigned long)DWELL_MS)
        return;

    // Advance to next value
    int next = scanValue + scanStep;

    // Make sure we always land on exactly 99 at the end
    if (next >= 100)
    {
        if (scanValue != 99)
        {
            // one final step to 99 if we haven't hit it exactly
            next = 99;
        }
        else
        {
            // scan complete
            scanning = false;
            applyRaw(-1);
            printSeparator();
            Serial.println(F("[SCAN COMPLETE] Sending REPORT..."));
            printReport();
            return;
        }
    }

    scanValue = next;
    lastDwellTime = millis();
    applyRaw(scanValue);
    printRow(scanValue, true);
}

// =============================================================================
// SETUP & LOOP
// =============================================================================

void setup()
{
    Serial.begin(SERIAL_BAUD);
    pinMode(STATUS_LED, OUTPUT);

    dimmer1.begin(NORMAL_MODE, ON);
    dimmer2.begin(NORMAL_MODE, ON);
    // setState(OFF) is the only reliable off at 60 Hz.
    // setPower(0) overflows the 60 Hz half-cycle timer and fires the TRIAC.
    dimmer1.setState(OFF);
    dimmer2.setState(OFF);

    delay(200);

    Serial.println();
    Serial.println(F("============================================"));
    Serial.println(F("  RobotDyn Dimmer Range Tester"));
    Serial.println(F("  60 Hz / dimmable LED bulb"));
    Serial.println(F("============================================"));
    Serial.println(F("Commands:"));
    Serial.println(F("  SCAN          step through 0-99, 1 at a time"));
    Serial.println(F("  SCAN:<step>   step with custom increment (e.g. SCAN:5)"));
    Serial.println(F("  HOLD:<n>      lock at one value  (e.g. HOLD:35)"));
    Serial.println(F("  NEXT / PREV   manual single step"));
    Serial.println(F("  PAUSE / RESUME"));
    Serial.println(F("  OFF           setState(OFF) — full off"));
    Serial.println(F("  REPORT        print annotated result table"));
    Serial.println(F("============================================"));
    Serial.println(F("Ready."));

    digitalWrite(STATUS_LED, HIGH);
    delay(200);
    digitalWrite(STATUS_LED, LOW);
}

void loop()
{
    processSerialInput();
    updateScan();

    // Blink LED while scan is running
    if (scanning && !paused)
        digitalWrite(STATUS_LED, (millis() % 500) < 100 ? HIGH : LOW);
    else
        digitalWrite(STATUS_LED, LOW);
}
