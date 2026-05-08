"""
Central configuration for the Activity Recognition System.
All tunable parameters live here.
"""

# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
CAMERA_INDEX: int = 0          # cv2.VideoCapture index (0 = default webcam)
FPS: int = 15                  # Target capture FPS
FRAME_WIDTH: int = 640
FRAME_HEIGHT: int = 480

CAMERA_BACKEND: int = 0        # 0 = auto-detect, or cv2.CAP_V4L2 (200) for Pi
CAMERA_WARMUP_SECONDS: float = 2.0  # Seconds to let the camera warm up after open
CAMERA_USE_PICAMERA2: bool = False  # True for Pi CSI camera module, False for USB webcam / Windows dev
HEADLESS: bool = False         # Set True on Raspberry Pi (no display)

# ---------------------------------------------------------------------------
# Motion Detection
# ---------------------------------------------------------------------------
MOTION_THRESHOLD: float = 25.0   # Pixel intensity diff threshold (0-255)
MOTION_MIN_AREA: int = 1500      # Minimum contour area to count as motion

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
STABILITY_WINDOW: int = 5            # Number of recent results to consider
STABILITY_MAJORITY: float = 0.60     # Fraction of window that must agree

# ---------------------------------------------------------------------------
# Allowed Activities
# ---------------------------------------------------------------------------
ALLOWED_ACTIVITIES: list = [
    "Reading Book/s",
    "Using Cellphone",
    "Using Laptop",
    "Idle",
]
DEFAULT_ACTIVITY: str = "Idle"

# ---------------------------------------------------------------------------
# Dimmer Controller (Arduino via Serial)
# ---------------------------------------------------------------------------
DIMMER_ENABLED: bool = True          # Set False to disable without changing code
DIMMER_PORT: str = "/dev/ttyACM0"   # Already working per your output
DIMMER_BAUD: int = 9600

# Brightness level (0-100) sent to the Arduino per activity.
# Adjust these to suit your lighting environment.
DIMMER_BRIGHTNESS: dict = {
    "Reading Book/s": 90,
    "Using Laptop":   70,
    "Using Cellphone": 60,
    "Idle":           20,
}

# Behavior label sent to the Arduino (must match your Arduino firmware).
DIMMER_BEHAVIOR: dict = {
    "Reading Book/s": "reading_book",
    "Using Laptop":   "using_laptop",
    "Using Cellphone": "using_cellphone",
    "Idle":           "idle",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_TO_FILE: bool = True
LOG_DIR: str = "outputs"           # Relative to project root (version3/)
LOG_LEVEL: str = "INFO"            # DEBUG | INFO | WARNING | ERROR
