# Project Requirements Document

## SmartLight — AI-Assisted Human Activity Recognition & Adaptive Lighting System

---

# 1. Project Overview

## Project Title

SmartLight: AI-Assisted Human Activity Recognition & Adaptive Lighting System

## Project Goal

Create an intelligent adaptive lighting system using a Raspberry Pi with a camera that:

1. Recognizes specific human activities with high accuracy using AI vision.
2. Automatically adjusts room illuminance to IES-recommended levels for each activity.
3. Minimizes API usage through intelligent local preprocessing and caching.
4. Provides closed-loop photoresistor feedback to maintain accurate lux levels.

The system focuses on the following activities:

- Reading Book/s
- Using Cellphone
- Using Laptop
- Writing
- Idle

Narrowing the activity scope achieves:

- Higher AI classification accuracy
- Reduced OpenAI API processing complexity and cost
- Lower latency
- Improved system stability

---

# 2. Core Concept

The system does **not** continuously send every frame to the OpenAI API.

Instead it:

- Detects whether meaningful activity changes occurred using local preprocessing.
- Reuses previous AI results when frames are visually similar.
- Only sends important frames to OpenAI Vision API.
- Adjusts lighting continuously using a closed-loop photoresistor controller.

**System pipeline:**

```text
Camera Feed
    ↓
Frame Capture
    ↓
ROI Extraction (Person Area via MediaPipe Pose)
    ↓
Motion Detection
    ↓
Image Similarity Comparison (SSIM)
    ↓
Decision Engine (3-gate: motion / similarity / cooldown)
    ↓
If significant change detected → Send frame to OpenAI Vision API
Else → Reuse previous cached result
    ↓
Activity Smoother (temporal majority voting)
    ↓
Dimmer Manager
    ↓
Photoresistor Lux Feedback → IES Closed-Loop Controller → Arduino → RBDimmer → Lamp
```

---

# 3. Focused Human Activities

The AI system classifies **only** the following five activities:

| Activity        | Description                                                             |
| --------------- | ----------------------------------------------------------------------- |
| Reading Book/s  | Person is reading a physical book, notebook, paper, or printed material |
| Using Cellphone | Person is actively interacting with a phone                             |
| Using Laptop    | Person is actively interacting with a laptop or desktop computer        |
| Writing         | Person is writing with a pen or pencil on paper or a notebook           |
| Idle            | Person is present but not performing any of the target activities       |

The system must:

- Avoid overclassifying unrelated actions.
- Never produce labels outside the allowed set.
- Return only one label per classification.

---

# 4. IES-Based Illuminance Targets

The system must adjust lighting to maintain the following IES-recommended illuminance levels per activity:

| Activity        | Target Lux Range | Rationale                                        |
| --------------- | :--------------: | ------------------------------------------------ |
| Reading Book/s  |  500 – 750 lux   | IES: sufficient brightness for sustained reading |
| Writing         |  500 – 750 lux   | IES: same as reading                             |
| Using Laptop    |  150 – 500 lux   | IES: reduces glare and eye strain on screens     |
| Using Cellphone |  100 – 200 lux   | IES: balanced lighting for handheld screens      |
| Idle            |   50 – 100 lux   | IES: comfortable ambient lighting at rest        |

Brightness is **not a fixed value**. It is continuously adjusted by the closed-loop controller until the photoresistor-measured lux falls within the target band.

---

# 5. Accuracy Prioritization

The system must prioritize:

- Accurate activity recognition.
- Stable activity detection (temporal smoothing before acting on results).
- Reduced false positives.

Latency optimization is achieved through:

- Smart frame caching.
- Local preprocessing (motion + SSIM) to gate API calls.
- Selective, rate-limited API calls.

---

# 6. Hardware Requirements

## Minimum Hardware

| Component           | Specification                                  |
| ------------------- | ---------------------------------------------- |
| Raspberry Pi        | Pi 5 preferred, Pi 4 acceptable                |
| Camera              | Raspberry Pi Camera Module (CSI) or USB webcam |
| Arduino             | Uno or compatible (Serial communication)       |
| Dimmer Module       | RBDimmer (AC phase-angle control)              |
| Photoresistor (LDR) | 5 kΩ–10 kΩ typical resistance range            |
| Resistor            | 10 kΩ (voltage divider for LDR)                |
| Power               | Stable internet connection, active cooling     |

## Photoresistor Circuit

```
3.3 V → LDR → Arduino A2 → 10 kΩ → GND
                    ↑
              AREF tied to 3.3 V
              analogReference(EXTERNAL)
```

## Optional Hardware

- Coral TPU / Hailo AI Accelerator (for local inference)
- External SSD
- IR camera

---

# 7. Software Stack

## Programming Language

Python 3.x

## Libraries

### Computer Vision

- OpenCV (`cv2`)
- NumPy
- scikit-image (SSIM)

### AI / Vision

- OpenAI Python SDK (`openai`)
- MediaPipe Pose (ROI extraction)

### Hardware Control

- pyserial (Arduino serial communication)

### Optimization

- Threading (background API worker, serial worker)

---

# 8. System Workflow

## Phase 1 — Camera Capture

The system continuously captures frames from the camera at configurable FPS and resolution.

Requirements:

- Adjustable FPS (default 30).
- 640×480 resolution.
- Support for both picamera2 (Pi CSI) and cv2.VideoCapture (USB / Windows).
- Optional camera lock (fixed exposure, gain, AWB) for stable lux trend measurement.
- 2-second warmup period on startup.

---

## Phase 2 — Local Preprocessing

### A. ROI Extraction

The system detects the person using **MediaPipe Pose** and crops a bounding box around all visible body landmarks with 10% padding. This reduces API payload size and focuses classification on the person.

**Fallback:** Use the full frame if no pose is detected.

### B. Motion Detection

Determines whether significant movement occurred using:

- Grayscale conversion + Gaussian blur (21×21)
- Frame differencing (`cv2.absdiff`)
- Binary threshold at 25 intensity units
- Dilation + contour area filtering (min area: 600 px²)

### C. Image Similarity Comparison

Compares the current ROI to the last API-classified frame using **SSIM** at 160×120 resolution. Falls back to histogram correlation if scikit-image is unavailable.

Threshold: `0.92` (92% structural similarity = no meaningful change).

---

## Phase 3 — Decision Engine (3-Gate Logic)

```
Gate 1: No motion       → reuse cache (reason: no_motion)
Gate 2: SSIM ≥ 0.92     → reuse cache (reason: similar_frame)
Gate 3: Cooldown < 3.0s → reuse cache (reason: cooldown)
All gates pass          → CALL_API
```

---

## Phase 4 — OpenAI Vision Classification

When a significant change is detected:

1. Resize ROI to 640×480, JPEG encode at quality 75, base64 encode.
2. Send to GPT-4o Vision with a constrained system prompt (5 allowed labels only).
3. Parse JSON response: `{ "activity": "...", "confidence": 0-100, "reasoning": "..." }`.
4. Reject results with confidence < 50; retain cached result.
5. Run in a background daemon thread — camera loop is never blocked.

---

## Phase 5 — Activity Stability

Apply **temporal majority voting** over a rolling window of 12 results:

- Require 70% agreement before committing a new stable label.
- Average confidence across matching results in the window.
- Retain previous label if no majority is reached.

---

## Phase 6 — Dimmer Control & IES Lux Loop

### 6a. Activity Commit

A new activity must persist for `DIMMER_COMMIT_DELAY = 1.5 s` before any dimmer command is sent (debounce).

### 6b. Photoresistor Lux Sensing

Poll Arduino ADC every `0.5 s` via `PHOTOLUX?` serial command:

- Convert raw ADC (0–1023) to lux using **log-linear interpolation** of `PHOTORESISTOR_CALIBRATION_POINTS`.
- Apply EMA smoothing (`α = 0.15`, ~6 sample effective window).

### 6c. Initial Brightness Seed

On activity commit, seed brightness to the value corresponding to the midpoint lux of the IES target range, using `LUX_BRIGHTNESS_TABLE` piecewise interpolation:

|  Lux Range  | Brightness |
| :---------: | :--------: |
| 50–100 lux  |   10–20%   |
| 100–200 lux |   20–40%   |
| 150–300 lux |   30–50%   |
| 500–750 lux |  80–100%   |

### 6d. Dead-Band Step Controller

Every `LUX_CONTROL_INTERVAL = 2.0 s`:

```
if lux < target_min  →  brightness += 2%   (too dark)
if lux > target_max  →  brightness -= 2%   (too bright)
else                 →  hold               (in band)
```

Hard-clamped to [1%, 100%].

### 6e. Display Percentage

The "Light: X%" value in the camera feed overlay is derived from the **current lux reading** mapped through `LUX_BRIGHTNESS_TABLE` — not from the last serial command sent.

### 6f. Idle Auto-Off

If the activity remains "Idle" for 90 continuous seconds, send `off:0` to the Arduino. Light resumes automatically on any non-idle detection.

### 6g. Arduino Serial Protocol

Commands are sent as `behavior:brightness\n` (e.g., `reading_book:88`). All serial I/O runs in a background `_SerialWorker` daemon thread to avoid blocking the camera loop. A keepalive PING is sent every 30 seconds.

---

# 9. Required Configurability

The following must be configurable in `config.py`:

```
FPS, Resolution
Similarity threshold
Motion threshold, min area
API cooldown duration
Confidence threshold
ROI padding
Frame compression quality
Dimmer port, baud rate, commit delay
Activity lux ranges (ACTIVITY_LUX_RANGE)
LUX_STEP_SIZE, LUX_CONTROL_INTERVAL
LUX_BRIGHTNESS_TABLE (seed table)
LUX_CALIBRATION_SCALE, LUX_CALIBRATION_OFFSET
Photoresistor enabled, poll interval, smoothing alpha
PHOTORESISTOR_CALIBRATION_POINTS
IDLE_AUTO_OFF_ENABLED, IDLE_AUTO_OFF_SECONDS
Stability window, majority fraction
```

---

# 10. Frame Caching System

The system caches:

- Last analyzed frame
- Last activity result + confidence + reasoning
- Timestamp of last API call

Goals:

- Reduce API requests and cost.
- Reduce latency.
- Maintain responsiveness between API calls.

---

# 11. Expected Latency

| Component                           | Expected Latency           |
| ----------------------------------- | -------------------------- |
| Local preprocessing (motion + SSIM) | 5–30 ms                    |
| OpenAI GPT-4o Vision API            | 2–8+ s (network dependent) |
| Serial command (Arduino)            | < 50 ms                    |
| Photoresistor poll                  | < 50 ms                    |

API calls run in a background thread so they do not block the camera display loop.

---

# 12. Error Handling Requirements

The system must handle:

- Internet disconnection (retry / cache reuse)
- API timeout or invalid JSON response (retain cached activity)
- Camera failure (graceful exit with error message)
- Arduino not connected (log warning, run without dimmer)
- Invalid AI response labels (reject, retain cache)
- Low confidence responses (reject, retain cache)

---

# 13. Logging Requirements

The system must log:

- Detected stable activity + confidence
- Classification source (API vs cache) and reason
- Similarity score per frame
- API call latency (ms)
- Photoresistor lux readings
- Dimmer brightness commands
- Processing time per frame
- Errors and warnings

Logs are written to the `outputs/` directory when `LOG_TO_FILE = True`.

---

# 14. Security Requirements

- The OpenAI API key must **never be hardcoded**.
- Use environment variables (`OPENAI_API_KEY`).
- Exclude from version control via `.gitignore`.

---

# 15. Non-Functional Requirements

## Maintainability

- Modular, single-responsibility package structure.
- All tunable parameters centralised in `config.py`.
- Well-documented modules with clear docstrings.

## Efficiency

- Minimize API usage via 3-gate decision engine.
- Serial I/O and API calls run in daemon threads.
- EMA smoothing prevents unnecessary brightness steps.

## Reliability

- Graceful degradation if Arduino or internet is unavailable.
- Temporal smoothing prevents flickering on borderline classifications.
- Keepalive prevents Arduino firmware safety timeout.

---

# 16. Current Project Structure

```text
SmartLight/
│
├── main.py                    # Entry point, main loop, overlay drawing
├── config.py                  # All tunable parameters
├── requirements.txt
│
├── ai/
│   └── openai_client.py       # GPT-4o Vision classification
├── applog/
│   └── logger.py              # Structured logging
├── arduinoFirmware/
│   ├── platformio.ini
│   └── src/main.cpp           # Arduino firmware (RBDimmer + serial protocol)
├── cache/
│   └── frame_cache.py         # API result cache + cooldown
├── camera/
│   └── capture.py             # Camera abstraction (picamera2 / cv2)
├── decision_engine/
│   └── engine.py              # 3-gate decision logic
├── dimmer_controller/
│   ├── controller.py          # Serial communication with Arduino
│   ├── dimmer_manager.py      # Activity→dimmer orchestration + photoresistor
│   └── lux_controller.py      # IES dead-band step controller
├── outputs/                   # Log files
├── preprocessing/
│   ├── motion_detector.py
│   └── roi_extractor.py
├── similarity/
│   └── comparator.py          # SSIM / histogram comparison
├── stability/
│   └── activity_smoother.py   # Temporal majority voting
└── Doc/
    ├── SYSTEM_OVERVIEW.md
    ├── PHOTORESISTOR_CALIBRATION.md
    └── Revised Project Requirements Document.md
```

---

# 17. Future Expansion

The architecture allows future support for:

- Multiple cameras or zones
- Local AI models (YOLO, ONNX) to reduce API dependency
- Edge AI accelerators (Coral TPU, Hailo)
- Multi-activity scene detection
- Cloud dashboards and mobile notifications
- Classroom or office analytics
- Additional activities (e.g., Eating, Exercising)
