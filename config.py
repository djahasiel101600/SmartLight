"""
Central configuration for the Activity Recognition System.
All tunable parameters live here.
"""

# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
CAMERA_INDEX: int = 0          # cv2.VideoCapture index (0 = default webcam)
FPS: int = 30                  # Target capture FPS (display loop runs freely between captures)
FRAME_WIDTH: int = 640
FRAME_HEIGHT: int = 480

CAMERA_BACKEND: int = 0        # 0 = auto-detect, or cv2.CAP_V4L2 (200) for Pi
CAMERA_WARMUP_SECONDS: float = 2.0  # Seconds to let the camera warm up after open
CAMERA_USE_PICAMERA2: bool = True  # True for Pi CSI camera module, False for USB webcam / Windows dev
HEADLESS: bool = False         # Set True on Raspberry Pi (no display)

# Camera lock (for stable lux estimation)
# When enabled, startup applies fixed exposure/gain controls to reduce
# frame-to-frame brightness drift from automatic camera behavior.

# Tweaking these values changes how the camera sensor collects and processes light per frame, which directly changes your lux estimate behavior.
# CAMERA_LOCK_ENABLED decides whether the camera runs in fixed mode or adaptive mode. When fixed, the sensor stops “helping” automatically, so measurements become repeatable. When adaptive (auto), the camera may brighten/darken frames on its own, which looks good visually but causes lux drift for the same real scene.
# CAMERA_LOCK_EXPOSURE_US controls shutter time. Increasing it makes frames brighter (more photons captured), but can add motion blur and can saturate bright scenes. Decreasing it darkens frames, improves motion sharpness, and may increase noise in low light. For lux estimation, this is one of the strongest levers.
# CAMERA_LOCK_ANALOG_GAIN (or CAMERA_LOCK_ISO on some backends) amplifies sensor signal. Higher gain/ISO makes the image brighter without longer exposure, but also amplifies noise and can make lux estimates less stable in dim scenes. Lower gain gives cleaner data but may underexpose.
# CAMERA_LOCK_AWB_ENABLED and CAMERA_LOCK_AWB_MODE affect color-channel balancing. AWB can shift channel scaling frame-to-frame as scene color changes, which can slightly move grayscale/luma-based lux estimates. Disabling AWB generally improves trend consistency; forcing AWB mode only helps if you use a valid numeric mode for your camera stack.
# CAMERA_LOCK_EV adds brightness bias on top of exposure logic (where supported). Positive EV pushes brighter, negative EV darker. In measurement workflows, EV is usually kept at 0.0 to avoid hidden bias.
# In practice: exposure + gain/ISO set the sensor’s raw brightness response, AWB/EV can add processing-side variation, and locking all of them trades visual adaptability for stable, comparable lux readings.

CAMERA_LOCK_ENABLED: bool = True
CAMERA_LOCK_EXPOSURE_US: int = 33000    # Exposure time in microseconds (increased for daylight)
CAMERA_LOCK_ANALOG_GAIN: float = 3.0    # Picamera2 AnalogueGain target (increased for brightness)
CAMERA_LOCK_ISO: int = 100              # Best-effort fallback for backends supporting ISO
CAMERA_LOCK_AWB_ENABLED: bool = False   # False keeps color processing stable for lux trends
CAMERA_LOCK_AWB_MODE = None             # Picamera2 expects int enum; None means do not force mode
CAMERA_LOCK_EV: float = 0.0             # Exposure compensation / EV (if supported)

# ---------------------------------------------------------------------------
# Motion Detection
# ---------------------------------------------------------------------------
MOTION_THRESHOLD: float = 25.0   # Pixel intensity diff threshold (0-255)
MOTION_MIN_AREA: int = 600      # Minimum contour area to count as motion

# ---------------------------------------------------------------------------
# ROI Extraction
# ---------------------------------------------------------------------------
ROI_PADDING: float = 0.10        # Fractional padding around detected body bbox

# ---------------------------------------------------------------------------
# Image Similarity
# ---------------------------------------------------------------------------
SIMILARITY_THRESHOLD: float = 0.92   # SSIM score above which frames are "same"
SIMILARITY_RESIZE: tuple = (160, 120) # Resize before SSIM to speed up comparison

# ---------------------------------------------------------------------------
# API / Cache
# ---------------------------------------------------------------------------
API_COOLDOWN_SECONDS: float = 3.0    # Minimum seconds between consecutive API calls
CONFIDENCE_THRESHOLD: int = 50       # Minimum confidence (0-100) to accept a result

# ---------------------------------------------------------------------------
# Image Encoding (sent to OpenAI)
# ---------------------------------------------------------------------------
ENCODE_WIDTH: int = 640
ENCODE_HEIGHT: int = 480
JPEG_QUALITY: int = 75               # JPEG quality 1-100 for base64 payload

# ---------------------------------------------------------------------------
# Activity Stability (temporal smoothing)
# ---------------------------------------------------------------------------
STABILITY_WINDOW: int = 12           # Number of recent results to consider (~0.8s at 15fps)
STABILITY_MAJORITY: float = 0.70     # Fraction of window that must agree

# ---------------------------------------------------------------------------
# Allowed Activities
# ---------------------------------------------------------------------------
ALLOWED_ACTIVITIES: list = [
    "Reading Book/s",
    "Using Cellphone",
    "Using Laptop",
    "Writing",
    "Idle",
]
DEFAULT_ACTIVITY: str = "Idle"

# ---------------------------------------------------------------------------
# Dimmer Controller (Arduino via Serial)
# ---------------------------------------------------------------------------
DIMMER_ENABLED: bool = True          # Set False to disable without changing code
DIMMER_PORT: str = "/dev/ttyACM0"   # Already working per your output
DIMMER_BAUD: int = 9600
DIMMER_COMMIT_DELAY: float = 1.5    # Seconds a new activity must persist before dimmer changes

# Test-mode defaults for CLI flags (--test-dimm, --test-full-brightness)
DIMMER_TEST_BEHAVIOR: str = "writing"
DIMMER_TEST_STEP: int = 10
DIMMER_TEST_DWELL_SECONDS: float = 0.4

# ---------------------------------------------------------------------------
# Photoresistor Sensor (Arduino ADC via Serial)
# ---------------------------------------------------------------------------
# When enabled, use hardware photoresistor readings instead of camera-based lux.
# Photoresistor is connected to Arduino A2 with 10k ohm resistor divider.
# Supply voltage: 3.3 V (NOT 5 V).  Circuit: 3.3V → LDR → A2 → 10kΩ → GND.
# The Arduino AREF pin must be tied to the same 3.3 V rail, and the firmware
# calls analogReference(EXTERNAL) so the ADC full-scale (1023) = 3.3 V.
# The Arduino responds to "PHOTOLUX?" command with raw ADC reading (0-1023).
PHOTORESISTOR_ENABLED: bool = True
PHOTORESISTOR_POLL_INTERVAL: float = 0.5  # Seconds between ADC polls
PHOTORESISTOR_SMOOTHING_ALPHA: float = 0.15
# EMA smoothing factor for lux readings (0.01 = very smooth/slow, 1.0 = no smoothing/raw).
# 0.15 averages ~6 recent samples — stable for slow-changing ambient light.
PHOTORESISTOR_SETTLE_DELAY: float = 2
# Seconds to wait after a brightness change before reading the photoresistor.
# Gives the bulb and LDR time to physically settle at the new level.
# Increase if readings still lag after steps; 0.5–1.5s is typical for AC dimmers.

# Photoresistor ADC-to-lux calibration data.
# Format: { raw_adc_reading: lux_value, ... }
# Calibrate by measuring with a real lux meter at different light levels,
# recording both the Arduino ADC raw value (0-1023) and the meter reading.
# Example: If meter reads 50 lux when Arduino ADC = 100, and 500 lux when ADC = 800,
# then set PHOTORESISTOR_CALIBRATION_POINTS = { 100: 50, 800: 500 }
# The system will interpolate between these points.
#
# To calibrate:
# 1. Run the script with photoresistor enabled
# 2. In different light conditions, note the ADC raw value and meter reading
# 3. Update this dict with at least 2 calibration pairs
# 4. System will use linear interpolation between calibration points
# format: [raw adc]: [lux from meter]
PHOTORESISTOR_CALIBRATION_POINTS: dict = {
    115:22.9,
    215:110,
    408:160,
    591:1026
}

# ---------------------------------------------------------------------------
# IES-Based Lux Control (replaces fixed DIMMER_BRIGHTNESS)
# ---------------------------------------------------------------------------
# Target illuminance ranges per activity, sourced from Illuminating Engineering
# Society (IES) recommendations (Table 3.1).
# The closed-loop controller steps brightness up/down to keep the
# camera-estimated lux within these bands.
ACTIVITY_LUX_RANGE: dict = {
    "Reading Book/s":  (500, 750),   # IES: sufficient brightness for concentration
    "Writing":         (500, 750),   # IES: same as reading
    "Using Laptop":    (150, 500),   # IES: reduces glare and eye strain
    "Using Cellphone": (100, 200),   # IES: balanced lighting for screens
    "Idle":            (50, 100),   # IES: dimming lighting for comfort
}

LUX_STEP_SIZE: int = 3              # Brightness % points to nudge per control tick
LUX_CONTROL_INTERVAL: float = 0.5  # Seconds between control ticks

# Lux-to-brightness lookup table derived from reference hardware measurements.
# Each row: (lux_min, lux_max, brightness_min%, brightness_max%)
# Used to seed the initial brightness on activity commit and to clamp the
# controller output so the displayed brightness % always stays within the
# range that physically produces the target illuminance.
LUX_BRIGHTNESS_TABLE: list = [
    ( 50,  100, 10, 20),   #  50–100 lux  → 10–20%
    (100,  200, 20, 40),   # 100–200 lux  → 20–40%
    (150,  300, 30, 50),   # 150–300 lux  → 30–50%
    (500,  750, 80, 100),  # 500–750 lux  → 80–100%
]

# Calibration factor: multiply raw camera-estimated lux by this value to
# approximate real photometric lux.  To calibrate, hold a real lux meter next
# to the camera, read both values, then set:
#   LUX_CALIBRATION_SCALE = <meter reading> / <_estimate_lux() output>
# Default 1.0 means no correction (relative control only).
LUX_CALIBRATION_SCALE: float = 1

# Calibration offset: adds a fixed lux bias after scaling.
# This is useful when the room has steady ambient light that causes the
# camera estimate to have a consistent baseline error.
LUX_CALIBRATION_OFFSET: float = 0

# 16 lx & 17.4 meter

# Behavior label sent to the Arduino (must match your Arduino firmware).
DIMMER_BEHAVIOR: dict = {
    "Reading Book/s": "reading_book",
    "Using Laptop":   "using_laptop",
    "Using Cellphone": "using_cellphone",
    "Writing":          "writing",
    "Idle":           "idle",
}

# ---------------------------------------------------------------------------
# Idle Auto-Off
# ---------------------------------------------------------------------------
# When the stable activity has been "Idle" for this many continuous seconds,
# the light is turned off completely (brightness → 0 via the Arduino fader).
# The light comes back on automatically as soon as a non-idle activity is detected.
IDLE_AUTO_OFF_ENABLED: bool = True
IDLE_AUTO_OFF_SECONDS: float = 90.0   # 2 minutes — adjust as needed

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_TO_FILE: bool = True
LOG_DIR: str = "outputs"           # Relative to project root (version3/)
LOG_LEVEL: str = "INFO"            # DEBUG | INFO | WARNING | ERROR
