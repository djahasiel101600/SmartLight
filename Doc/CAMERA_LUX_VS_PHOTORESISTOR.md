# Camera-Based Lux Estimation vs. Photoresistor: White Reference Method Analysis

## Overview

This document evaluates the **white paper / white object reference method** as a camera-based lux sensing approach, compares it in depth against the current photoresistor hardware implementation, and explains the practical limitations specific to this project's setup — particularly the constraint that the integrated camera is lower quality than a 720p webcam.

---

## 1. What the White Reference Method Is

The white reference method is inspired by a well-established technique in photometry and remote sensing called a **Lambertian reflectance standard**. It works on the following physical principle:

For a perfectly diffuse (Lambertian) white surface with known reflectance factor $\rho$, the relationship between the incident illuminance $E$ (lux) and the luminance $L$ the camera measures is:

$$E = \frac{\pi \cdot L}{\rho}$$

In practice this means: if you keep a white object (paper, card) in the camera frame at all times, and you measure how bright that white patch looks to the camera, you can estimate how much light is falling on it — and therefore on the scene — because a white surface reflects most incident light diffusely.

The idea the user is considering is:

- Designate a fixed white region in the camera frame (e.g., a piece of white A4 paper on the desk).
- Measure the average pixel brightness of just that region every frame.
- Map that brightness to a lux value via calibration (similar to what `_estimate_lux()` already does for the full frame, but focused on the reference patch).

The current `_estimate_lux()` function in `main.py` is essentially the simplest version of this concept applied to the whole frame:

```python
def _estimate_lux(frame) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg = float(gray.mean())
    return round((avg / 255.0) ** 1.8 * 1000.0, 1)
```

A white paper ROI would be a refinement — isolating only the reference patch instead of averaging the whole scene.

---

## 2. The Camera Processing Pipeline Problem

Before evaluating the method, it is critical to understand everything that happens between photons hitting the sensor and a pixel value appearing in memory. This pipeline is the root cause of most camera-based lux measurement unreliability.

```
Incident light (lux)
        ↓
  Lens (vignetting, chromatic aberration)
        ↓
  Image Sensor (quantum efficiency, noise, dark current)
        ↓
  Analog Gain Control (AGC) — auto-adjusts to exposure
        ↓
  Auto-Exposure Control (AEC) — auto-adjusts shutter time
        ↓
  Auto White Balance (AWB) — scales R/G/B channels per scene color
        ↓
  Gamma Correction (γ ≈ 2.2 or sRGB curve — non-linear compression)
        ↓
  Tone Mapping / Image Signal Processor (ISP)
        ↓
  JPEG compression
        ↓
  Pixel value (0–255) in memory
```

Every stage between the sensor and the final pixel value can change the relationship between true lux and pixel brightness — and most of them are **automatic, adaptive, and non-linear**. This is the fundamental problem with camera-based lux estimation.

---

## 3. Why the White Reference Method Faces Serious Obstacles

### 3.1 Auto-Exposure and Gain (AEC / AGC) — The Main Enemy

This is the single largest problem. Camera sensors automatically adjust their shutter time and gain to produce a "good-looking" image regardless of actual light level. This is called **automatic exposure compensation**.

If the room lights are at 100 lux and the camera exposes for 33 ms, the white paper might appear at pixel value ~180.  
If the lights increase to 500 lux, the camera **reduces** its exposure time to ~6 ms.  
The white paper might now appear at pixel value ~175 — **almost the same** — even though lux increased by 5×.

This means: **with auto-exposure active, pixel brightness is largely decoupled from real illuminance.** The camera is designed to make all scenes look equally well-lit, which is the opposite of what a lux meter should do.

The current project has `CAMERA_LOCK_ENABLED = False` by default. Unless this is set to `True` with fixed exposure and gain values, the white reference method will give highly unreliable results.

Even with `CAMERA_LOCK_ENABLED = True`, you must be careful: if the white paper saturates (goes to pure 255) at higher light levels, all information above that point is lost.

### 3.2 Non-Linear Gamma Curve

Camera output is **gamma-corrected** before you ever see a pixel value. The standard gamma is $\gamma \approx 2.2$:

$$\text{pixel} = \left(\frac{L}{L_\text{max}}\right)^{1/\gamma} \times 255$$

This means the relationship between real luminance $L$ and pixel value is a **power curve, not a line**. The existing `_estimate_lux()` function partially compensates for this with `(avg / 255.0) ** 1.8`, but this exponent is a rough approximation tuned manually — it is not derived from the actual camera's gamma profile.

For a white paper reference to work accurately, you would need to characterize your specific camera's gamma curve and invert it precisely — a complex per-device calibration process.

### 3.3 Auto White Balance (AWB)

The camera's AWB algorithm scales the red, green, and blue channels differently depending on the estimated color temperature of the scene. This is designed for natural-looking photos, but it means:

- Under a warm tungsten bulb: AWB boosts blue, reduces red → grayscale conversion changes.
- Under a cool LED: AWB boosts red → grayscale value of the same white paper changes.

Even converting to grayscale does not escape this, because `cv2.cvtColor(BGR → GRAY)` uses a fixed formula that weights the already-AWB-shifted R/G/B values. As the dimmer changes the bulb's effective color temperature (phase-cut dimmers shift color temperature at lower brightness levels), AWB will continuously adjust, causing lux drift in the measurement.

This is exactly why `CAMERA_LOCK_AWB_ENABLED = False` is the recommended setting when using camera-based lux estimation in this project.

### 3.4 Low Camera Quality — The Specific Problem Here

The user notes the integrated camera is lower quality than a 720p webcam. This matters for several compounding reasons:

| Issue                                         | How it Affects White Reference                                                                                                       |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **More aggressive ISP processing**            | Cheaper camera chips apply heavier image sharpening, noise reduction, and tone mapping, all of which alter pixel values non-linearly |
| **Lower bit depth / more quantization noise** | Fewer distinguishable pixel levels means smaller lux differences produce no change in pixel value at all                             |
| **Stronger lens vignetting**                  | Brightness of the white paper changes depending on where in the frame it is placed — center reads brighter than edges                |
| **Weaker low-light performance**              | At 50–100 lux (the Idle range), sensor noise becomes significant relative to signal — the white paper reading becomes noisy          |
| **Less controllable through API**             | Lower-end camera modules often expose fewer manual control parameters, making it harder to fully lock exposure and gain              |

A high-quality, well-characterized industrial camera with raw sensor output could make the white reference method work. A low-quality integrated camera with heavy ISP processing is the worst-case scenario for this technique.

### 3.5 Physical and Positional Constraints

- The white paper must be **always visible** to the camera and **never occluded** by the person (who may lean forward, move their arms, etc.).
- It must be **flat-on** to the light source — tilting the paper changes its effective illuminance by $E_\text{tilt} = E \cdot \cos\theta$.
- The paper's reflectance must be stable — dirt, yellowing, shadows, or glare (specular highlights from glossy surfaces) all change the reading.
- If the paper is too close to the lamp or the person, it may receive different illuminance than the area being measured for the activity target.

### 3.6 Conflict with the Activity Recognition Pipeline

The current ROI is cropped tightly around the person via MediaPipe Pose. The white paper would need to be:

- In a fixed, separate region of the frame.
- Never inside the person's ROI (or it could confuse the AI into misclassifying activity).
- Consistently lit by the same light source as the working area.

Managing two ROIs simultaneously (person ROI for classification, paper ROI for lux) adds implementation complexity to the pipeline.

---

## 4. When the White Reference Method Can Work

To make camera-based white reference lux estimation viable, **all** of the following would need to be true:

| Requirement                                           | Current Status    |
| ----------------------------------------------------- | ----------------- |
| Camera exposure locked (`CAMERA_LOCK_ENABLED = True`) | Off by default    |
| Camera gain locked (`CAMERA_LOCK_ANALOG_GAIN` fixed)  | Not set           |
| AWB disabled (`CAMERA_LOCK_AWB_ENABLED = False`)      | Already available |
| Camera gamma characterized and inverted               | Not implemented   |
| White paper always visible, flat, unoccluded          | Not guaranteed    |
| Paper reflectance known and stable                    | Not guaranteed    |
| Separate paper ROI defined in pipeline                | Not implemented   |

If all of these are satisfied, the method could achieve approximately **±20–40% lux accuracy** — still worse than a well-calibrated photoresistor (±5–15% with log-linear interpolation) and significantly harder to set up.

---

## 5. Direct Comparison: White Reference Camera vs. Photoresistor

| Criterion                                      |         White Reference (Camera)          |           Photoresistor (Current)           |
| ---------------------------------------------- | :---------------------------------------: | :-----------------------------------------: |
| **Measures true incident lux**                 |     No — measures reflected luminance     | Yes — directly converts illuminance to ADC  |
| **Affected by auto-exposure**                  |               Yes, severely               |                     No                      |
| **Affected by auto white balance**             |                    Yes                    |                     No                      |
| **Affected by gamma correction**               |                    Yes                    |                     No                      |
| **Affected by scene content**                  |         Yes (occlusion, shadows)          |                     No                      |
| **Additional hardware required**               |                    No                     |        Yes (LDR + resistor + wiring)        |
| **Calibration complexity**                     | High (camera pipeline has many variables) | Moderate (ADC → lux pairs + log-linear fit) |
| **Repeatable between sessions**                |   Low (camera re-adapts on every start)   |   High (fixed hardware, stable response)    |
| **Works with camera off / headless**           |                    No                     |                     Yes                     |
| **Accuracy (well-configured)**                 |                  ±20–40%                  |                   ±5–15%                    |
| **Works during activity recognition**          |     Requires separate ROI management      |              Fully independent              |
| **Affected by person occluding reference**     |                    Yes                    |                     No                      |
| **Affected by dimmer color temperature shift** |               Yes (via AWB)               |     Slightly (response is photometric)      |
| **Implementation effort**                      |                   High                    |          Low (already implemented)          |
| **Reliability on low-quality camera**          |                 Very low                  |                     N/A                     |

---

## 6. The Dual-Purpose Problem

The most fundamental difficulty is that this project asks the camera to serve **two incompatible goals simultaneously**:

1. **Activity recognition** — needs a natural-looking, well-exposed, sharp image so the AI can identify what the person is doing.
2. **Lux measurement** — needs a radiometrically stable, locked, uncorrected image so pixel brightness faithfully represents incident light.

These goals are in direct conflict. Auto-exposure and gamma correction exist specifically to make images look good for human viewing and AI recognition — and they do so precisely by _removing_ the information a lux meter needs. You cannot fully satisfy both requirements with a single camera stream without significant compromise in at least one.

The photoresistor separates these concerns completely: the camera handles activity recognition with full auto settings, while the photoresistor independently handles lux measurement.

---

## 7. Practical Testing and Calibration Difficulty

### White Reference Calibration Procedure

To calibrate the white paper method properly, you would need to:

1. Lock camera exposure and gain to fixed values (`CAMERA_LOCK_ENABLED = True`).
2. Disable AWB.
3. Define a fixed rectangular ROI in the frame covering the white paper.
4. For each light level: record the mean pixel brightness of the paper ROI and the simultaneous lux meter reading.
5. Build a calibration curve (at minimum a power-law fit: `lux = A × pixel^B`).
6. **Repeat the entire calibration if** the camera is repositioned, the paper is moved, the bulb type changes, or the exposure lock settings are changed.

Each recalibration requires holding a lux meter at a precise point while adjusting lighting across the full target range (50–1400 lux) — with the camera locked. This is similar effort to photoresistor calibration but with far more failure modes.

### Photoresistor Calibration Procedure (for comparison)

1. Run the system normally (no special settings required).
2. At each light level, record the `[Photoresistor] raw_adc=X` value from the terminal and the lux meter reading.
3. Add the ADC → lux pair to `PHOTORESISTOR_CALIBRATION_POINTS`.
4. The log-linear interpolator handles the rest automatically.

The photoresistor calibration is significantly simpler because the sensor response is stable, deterministic, and independent of the camera pipeline.

---

## 8. Summary and Recommendation

The white reference method is a **theoretically sound** photometric technique that works well with industrial cameras, spectroradiometers, and properly characterised imaging systems. In this project's context, it is **not a reliable substitute** for the photoresistor for the following compounding reasons:

1. The camera's auto-exposure and AWB pipelines are the primary tools for activity recognition quality, and disabling them for lux measurement degrades classification performance.
2. The lower-quality integrated camera has a less predictable, harder-to-invert ISP pipeline, making radiometric calibration significantly less reliable than with a high-quality webcam.
3. The white paper's lux reading is sensitive to its position, angle, occlusion by the person, and specular reflections — all of which vary during normal use.
4. The photoresistor is already implemented, well-calibrated with log-linear interpolation, and provides direct, camera-independent lux readings at ±5–15% accuracy.

**The photoresistor is the correct tool for this job.** It is simpler to calibrate, more accurate, fully independent of the camera and its pipeline, and unaffected by scene content or camera settings. The camera is best left dedicated to its primary purpose: providing clean, well-exposed frames for human activity recognition.

The only scenario where the white reference approach would be worth revisiting is if the photoresistor hardware fails and a temporary software-only fallback is needed — and even then, `CAMERA_LOCK_ENABLED = True` would be a hard prerequisite.
