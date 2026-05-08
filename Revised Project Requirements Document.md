# Project Requirements Document  
## Focused AI-Assisted Human Activity Recognition System using Raspberry Pi + Camera + OpenAI Vision API

---

# 1. Project Overview

## Project Title
Focused AI-Assisted Human Activity Recognition System

## Project Goal
Create an intelligent monitoring system using a Raspberry Pi with a camera that can recognize only specific human activities with high accuracy while minimizing latency and API usage.

The system must focus ONLY on the following activities:
- Reading Book/s
- Using Cellphone
- Using Laptop
- Idle

The purpose of narrowing the activity scope is to:
- Improve AI focus
- Reduce unnecessary classifications
- Increase detection accuracy
- Reduce OpenAI API processing complexity
- Lower latency
- Lower API cost
- Improve system stability

---

# 2. Core Concept

The system should NOT continuously send every frame to the OpenAI API.

Instead, the system should:
- Detect whether meaningful activity changes occurred
- Reuse previous AI results when frames are visually similar
- Only send important frames to OpenAI Vision API

The system should use a hybrid pipeline:

```text
Camera Feed
    ↓
Frame Capture
    ↓
Motion Detection
    ↓
ROI Extraction (Person Area)
    ↓
Image Similarity Comparison
    ↓
Decision Engine
    ↓
If significant change detected:
    Send frame to OpenAI
Else:
    Reuse previous result
```

---

# 3. Focused Human Activities

The AI system must ONLY classify the following activities:

| Activity | Description |
|---|---|
| Reading Book/s | Person is reading a physical book, notebook, paper, or printed material |
| Using Cellphone | Person is actively interacting with a phone |
| Using Laptop | Person is actively interacting with a laptop/computer |
| Idle | Person is present but not performing the target activities |

The system must avoid:
- Overclassifying unrelated actions
- Detecting unnecessary activities
- Producing unsupported labels

The AI should ONLY return one of the allowed activity labels.

---

# 4. Accuracy Prioritization

The system must prioritize:
- Accurate activity recognition
- Stable detection
- Reduced false positives

Latency optimization should be achieved through:
- Activity limitation
- Smart frame caching
- Local similarity analysis
- Selective API calls

---

# 5. Hardware Requirements

## Minimum Hardware
- Raspberry Pi 5 preferred
- Raspberry Pi Camera Module
- Stable internet connection
- Active cooling system

## Optional Hardware
- Coral TPU
- Hailo AI Accelerator
- External SSD
- IR camera

---

# 6. Software Stack

## Programming Language
Python 3.x

## Suggested Libraries

### Computer Vision
- OpenCV
- NumPy

### AI / Vision
- OpenAI API SDK
- MediaPipe Pose
- Ultralytics YOLO (optional local detection)

### Optimization
- AsyncIO
- ONNX Runtime (optional)

---

# 7. System Workflow

# Phase 1 — Camera Capture

The system continuously captures frames from the camera.

Requirements:
- Adjustable FPS
- Adjustable resolution
- Efficient memory usage
- Stable frame buffering

---

# Phase 2 — Local Preprocessing

Before sending images to OpenAI API, the system performs local analysis.

## A. Motion Detection

Determine whether significant movement occurred.

Possible methods:
- Frame differencing
- Background subtraction
- Optical flow

---

## B. ROI (Region of Interest) Detection

The system should:
- Detect the human/person region
- Crop only relevant regions
- Ignore unnecessary background areas

This improves:
- Accuracy
- API efficiency
- Reduced image size

---

## C. Image Similarity Comparison

Compare:
- Current ROI frame
- Previous AI-analyzed ROI frame

Possible techniques:
- SSIM (Structural Similarity Index)
- Histogram comparison
- Feature matching

---

# Phase 3 — Decision Engine

The system decides whether to:
- Reuse previous AI result
- Send new frame to OpenAI

Example logic:

```python
IF motion_detected == False:
    reuse_previous_result

ELIF similarity_score > threshold:
    reuse_previous_result

ELSE:
    send_frame_to_openai
```

---

# Phase 4 — OpenAI Vision Analysis

When significant activity change is detected:
- Send image to OpenAI Vision API
- Receive activity classification
- Cache latest activity result

The API should only classify among:
- Reading Book/s
- Using Cellphone
- Using Laptop
- Idle

---

# 8. AI Prompt Engineering Requirements

The AI prompt must strongly constrain the model to only classify the allowed activities.

## Example Prompt

```text
Analyze the human activity in this image.

You MUST ONLY classify the activity as one of the following:
- Reading Book/s
- Using Cellphone
- Using Laptop
- Idle

Do NOT invent new activities.

Only classify based on clearly observable actions.

Return JSON format only:

{
  "activity": "",
  "confidence": 0-100,
  "reasoning": ""
}
```

---

# 9. Activity Stability System

The system must avoid rapid activity switching.

Implement:
- Temporal smoothing
- Confidence averaging
- Multi-frame confirmation

Example:
- A single uncertain frame should not immediately change activity labels.

---

# 10. Frame Caching System

The system should cache:
- Last analyzed frame
- Last activity result
- Similarity score
- Timestamp

Goal:
- Reduce API requests
- Reduce latency
- Improve responsiveness
- Reduce costs

---

# 11. Expected Latency

## Local Processing
Expected:
- 10ms–100ms

## OpenAI Vision API
Expected:
- 2–8+ seconds depending on:
  - Internet speed
  - API response time
  - Image size

Because activities are limited to only four labels, the AI response may become more focused and efficient.

---

# 12. Performance Optimization Requirements

The system should:
- Resize frames before API upload
- Compress images efficiently
- Use ROI cropping
- Limit API call frequency
- Use cooldown timers
- Skip duplicate frames

---

# 13. Required Configurability

The following should be configurable:

```text
FPS
Resolution
Similarity threshold
Motion threshold
API cooldown duration
Confidence threshold
ROI size
Frame compression quality
```

---

# 14. Error Handling Requirements

The system must handle:
- Internet disconnection
- API timeout
- Camera failure
- Invalid AI responses
- Memory overflow
- Raspberry Pi overheating

---

# 15. Logging Requirements

The system should log:
- Detected activity
- Confidence score
- Similarity score
- API requests
- Errors
- Processing time

---

# 16. Security Requirements

The OpenAI API key must:
- Never be hardcoded
- Use environment variables
- Be excluded from Git repositories

---

# 17. Future Expansion Requirements

The architecture should allow future support for:
- Multiple cameras
- Local AI models
- Edge AI accelerators
- Classroom analytics
- Cloud dashboards
- Mobile notifications

Future activities may be added later, but the current implementation must remain focused only on the four target activities.

---

# 18. Recommended Project Structure

```text
project/
│
├── main.py
├── config.py
├── requirements.txt
│
├── camera/
├── preprocessing/
├── similarity/
├── decision_engine/
├── ai/
├── logging/
├── cache/
├── storage/
├── utils/
│
├── prompts/
├── outputs/
└── models/
```

---

# 19. Non-Functional Requirements

## Maintainability
Code must be:
- Modular
- Scalable
- Well-documented

## Efficiency
The system should:
- Minimize API usage
- Avoid unnecessary AI calls

## Reliability
The system should:
- Recover gracefully from failures
- Maintain stable operation

---

# 20. Deliverables

The AI Agent/Planner should create:

- Full system architecture
- Modular Python implementation
- OpenAI Vision integration
- Similarity comparison system
- Frame caching system
- Activity stability system
- Logging system
- Configuration system
- Documentation

---

# 21. Final Development Instructions for AI Agent

The AI Agent/Planner must:
- Keep the activity scope LIMITED to:
  - Reading Book/s
  - Using Cellphone
  - Using Laptop
  - Idle
- Prioritize accuracy over latency
- Minimize unnecessary API calls
- Use intelligent caching
- Focus on stable classifications
- Optimize for Raspberry Pi limitations
- Use modular architecture
- Ensure future scalability

The implementation should be production-oriented rather than prototype-only.
