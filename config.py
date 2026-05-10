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

# ---------------------------------------------------------------------------
# IES-Based Lux Control (replaces fixed DIMMER_BRIGHTNESS)
# ---------------------------------------------------------------------------
# Target illuminance ranges per activity, sourced from Illuminating Engineering
# Society (IES) recommendations (Table 3.1).
# The closed-loop controller steps brightness up/down to keep the
# camera-estimated lux within these bands.
ACTIVITY_LUX_RANGE: dict = {
    "Reading Book/s":  (300, 500),   # IES: sufficient brightness for concentration
    "Writing":         (300, 500),   # IES: same as reading
    "Using Laptop":    (300, 500),   # IES: reduces glare and eye strain
    "Using Cellphone": (200, 300),   # IES: balanced lighting for screens
    "Idle":            (100, 150),   # IES: dimming lighting for comfort
}

LUX_STEP_SIZE: int = 3              # Brightness % points to nudge per control tick
LUX_CONTROL_INTERVAL: float = 0.5  # Seconds between control ticks

# Calibration factor: multiply raw camera-estimated lux by this value to
# approximate real photometric lux.  To calibrate, hold a real lux meter next
# to the camera, read both values, then set:
#   LUX_CALIBRATION_SCALE = <meter reading> / <_estimate_lux() output>
# Default 1.0 means no correction (relative control only).
LUX_CALIBRATION_SCALE: float = 1.0

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
