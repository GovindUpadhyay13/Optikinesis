import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import pyautogui
import numpy as np
import math
import threading
from flask import Flask, render_template, Response, request, jsonify
import webbrowser
import time
import urllib.parse
import sys
import os
from collections import deque
import logging
from dotenv import load_dotenv
load_dotenv()

# --- LOCAL SUBSYSTEMS ---
import database
import breathguard
import communication_service
import agent_reasoning
from fatigue_monitor import fatigue_monitor
from voice_commands import voice_executor
from computer_use_agent import jayu_agent, VoiceAgentMode

logger = logging.getLogger("optikinesis_main")
logging.basicConfig(level=logging.INFO)

# --- PyQt5 IMPORTS FOR CURSOR OVERLAY ---
try:
    from PyQt5 import QtWidgets, QtGui, QtCore  # type: ignore
    PYQT5_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    QtWidgets = QtGui = QtCore = None  # type: ignore
    PYQT5_AVAILABLE = False
    logger.warning("PyQt5 not installed. Cursor overlay will not be available.")

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# --- CONFIGURATION ---
pyautogui.FAILSAFE = False

# Screen settings
SCREEN_W, SCREEN_H = pyautogui.size()
CENTER_X = SCREEN_W // 2
CENTER_Y = SCREEN_H // 2

# Axis inversion flags
INVERT_X = False  # Natural mapping with mirrored camera
INVERT_Y = False

# Blink Settings
BLINK_THRESH = 0.22
BLINK_WINDOW = 1.5

# Configurable Settings (overlay & mouse control off by default to keep mouse freely clickable)
SETTINGS = {
    "emergency_contact": os.getenv("EMERGENCY_CONTACT", "+1234567890"),
    "cursor_scope": 1.0,
    "blink_sensitivity": BLINK_THRESH,
    "cursor_speed": 0.5,
    "overlay_enabled": False,
    "mouse_control_enabled": False,
    "gaze_sensitivity": 1.4,
    "smoothing": 0.25
}

# EMA smoothing for cursor position
prev_screen_x = CENTER_X
prev_screen_y = CENTER_Y

# Shared state
mouse_target = [CENTER_X, CENTER_Y]
mouse_lock = threading.Lock()

# Calibration state
calib_center_gaze = [0.5, 0.5]
calib_center_head = [0.0, 0.0]
is_calibrated = False
calibrate_requested = True  # Auto-calibrate on first detected face
calibration_feedback_until = 0
calibration_lock = threading.Lock()

# Camera frame sharing (thread-safe)
latest_jpeg_frame = None
camera_status = {
    "camera_online": False,
    "is_black": False,
    "face_detected": False,
    "calibrated": False,
    "yaw": 0.0,
    "pitch": 0.0,
    "gaze_x": 0.5,
    "gaze_y": 0.5
}
frame_lock = threading.Lock()


# --- CONNECT BREATHGUARD ALERT DISPATCHER ---
def on_breathguard_alert(alert_id, caregiver, rule, metric, val, severity):
    """Callback when BreathGuard detects an anomaly persisting past the validation window."""
    if not caregiver:
        caregiver = database.get_primary_caregiver()
    if not caregiver:
        return

    cg_phone = caregiver["phone_number"]
    cg_name = caregiver["name"]
    alert_text = agent_reasoning.compose_caregiver_alert(rule, metric, val, severity)

    # 1. Place automated voice call
    communication_service.place_caregiver_voice_call(
        to_phone=cg_phone,
        caregiver_name=cg_name,
        message_text=alert_text,
        is_emergency=(severity == "critical")
    )

    # 2. Send SMS alert
    communication_service.send_caregiver_sms(
        to_phone=cg_phone,
        caregiver_name=cg_name,
        message_text=alert_text
    )

breathguard.breathguard_engine.set_alert_dispatcher(on_breathguard_alert)


# --- CURSOR CIRCLE OVERLAY ---
if PYQT5_AVAILABLE:
    class CursorOverlay(QtWidgets.QWidget):
        def __init__(self, radius=60):
            super().__init__()
            self.radius = radius
            self.diameter = 2 * self.radius + 4
            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint |
                QtCore.Qt.WindowStaysOnTopHint |
                QtCore.Qt.Tool |
                QtCore.Qt.SubWindow |
                QtCore.Qt.WindowTransparentForInput
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
            self.setFixedSize(self.diameter, self.diameter)

            self.label = QtWidgets.QLabel(self)
            self.label.setGeometry(0, 0, self.diameter, self.diameter)
            self.label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

            # Ensure native Windows OS click-through via WS_EX_TRANSPARENT
            if sys.platform == "win32":
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    hwnd = int(self.winId())
                    GWL_EXSTYLE = -20
                    WS_EX_TRANSPARENT = 0x00000020
                    WS_EX_LAYERED = 0x00080000
                    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
                except Exception as e:
                    logger.warning("Could not set WS_EX_TRANSPARENT on CursorOverlay: %s", e)

            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self.update_position)
            self.timer.start(16)

        def update_position(self):
            if SETTINGS.get("overlay_enabled", True):
                x, y = pyautogui.position()
                self.move(x - self.radius, y - self.radius)
                self.draw_circle()
                if not self.isVisible():
                    self.show()
            else:
                if self.isVisible():
                    self.hide()

        def draw_circle(self):
            img = np.zeros((self.diameter, self.diameter, 4), dtype=np.uint8)
            cv2.circle(img, (self.radius + 2, self.radius + 2), self.radius - 5, (0, 255, 128, 200), 4)
            cv2.circle(img, (self.radius + 2, self.radius + 2), 4, (0, 255, 255, 255), -1)
            qimg = QtGui.QImage(img.data, self.diameter, self.diameter, QtGui.QImage.Format_RGBA8888)
            pixmap = QtGui.QPixmap.fromImage(qimg)
            self.label.setPixmap(pixmap)


# --- MOUSE MOVER THREAD ---
def mouse_mover():
    """Continuously move mouse to target position."""
    while True:
        if SETTINGS.get("mouse_control_enabled", True):
            with mouse_lock:
                x, y = mouse_target
            try:
                if not (math.isnan(x) or math.isnan(y)):
                    pyautogui.moveTo(int(x), int(y))
            except Exception:
                pass
        time.sleep(0.01)


# --- HELPERS ---
def get_blink_ratio(landmarks, eye_indices):
    """Calculate eye aspect ratio for blink detection."""
    top = landmarks[eye_indices[1]]
    bottom = landmarks[eye_indices[3]]
    left = landmarks[eye_indices[0]]
    right = landmarks[eye_indices[2]]
    
    ver_dist = math.hypot(top.x - bottom.x, top.y - bottom.y)
    hor_dist = math.hypot(left.x - right.x, left.y - right.y)
    
    return ver_dist / hor_dist if hor_dist != 0 else 0


def execute_type_external(text):
    time.sleep(5)
    pyautogui.write(text, interval=0.1)


# --- MEDIAPIPE FACE LANDMARKER SETUP ---
MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

if not os.path.exists(MODEL_PATH):
    logger.info(f"Downloading face landmarker model to {MODEL_PATH}...")
    import urllib.request
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    logger.info("Download complete!")

base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    output_face_blendshapes=False,
    output_facial_transformation_matrixes=False,
    num_faces=1,
    min_face_detection_confidence=0.5,
    min_face_presence_confidence=0.5,
    min_tracking_confidence=0.5
)
face_landmarker = vision.FaceLandmarker.create_from_options(options)


# --- CAMERA & EYE/HEAD TRACKING LOOP ---
def camera_tracking_loop():
    """Independent background worker for webcam capture, eye gaze, head pose & BreathGuard rPPG."""
    global latest_jpeg_frame, camera_status, prev_screen_x, prev_screen_y
    global calib_center_gaze, calib_center_head, is_calibrated, calibrate_requested, calibration_feedback_until

    logger.info("Opening webcam...")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(1)

    if not cap.isOpened():
        logger.error("Could not open any camera device!")
        with frame_lock:
            camera_status["camera_online"] = False
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    logger.info("Camera initialized successfully.")

    with frame_lock:
        camera_status["camera_online"] = True

    # Blink detection state
    blink_active = False
    LEFT_EYE_INDICES = [33, 159, 133, 145]

    while True:
        success, frame = cap.read()
        if not success:
            time.sleep(0.05)
            continue

        h, w, _ = frame.shape
        frame = cv2.flip(frame, 1)

        # Check if the camera feed is completely black / shutter closed
        frame_mean = float(np.mean(frame))
        is_black = bool(frame_mean < 5.0)

        with frame_lock:
            camera_status["is_black"] = is_black

        if is_black:
            cv2.rectangle(frame, (20, 20), (w - 20, h - 20), (0, 0, 255), 3)
            cv2.putText(frame, "CAMERA FEED BLOCKED / BLACK", (40, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
            cv2.putText(frame, "1. Open camera privacy shutter (slider on webcam)", (40, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)
            cv2.putText(frame, "2. Check Lenovo Vantage -> Camera Privacy", (40, 170),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)
            cv2.putText(frame, "3. Check camera hotkey (e.g., F8 or Fn+F8)", (40, 210),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)
            
            with frame_lock:
                camera_status["face_detected"] = False
                
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                with frame_lock:
                    latest_jpeg_frame = buffer.tobytes()
            time.sleep(0.08)
            continue

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        results = face_landmarker.detect(mp_image)

        face_detected = bool(results.face_landmarks and len(results.face_landmarks) > 0)
        with frame_lock:
            camera_status["face_detected"] = face_detected

        if face_detected:
            landmarks = results.face_landmarks[0]

            # -------------------------------------------------------------
            # BREATHGUARD rPPG PROCESSING (Only runs if user granted permission)
            # -------------------------------------------------------------
            breathguard.breathguard_engine.process_face_frame(rgb_frame, landmarks)

            # -------------------------------------------------------------
            # 1. EYE IRIS GAZE TRACKING (Landmarks 468 & 473)
            # -------------------------------------------------------------
            try:
                l_iris = landmarks[468]
                l_outer = landmarks[33]
                l_inner = landmarks[133]
                l_top = landmarks[159]
                l_bottom = landmarks[145]

                r_iris = landmarks[473]
                r_outer = landmarks[263]
                r_inner = landmarks[362]
                r_top = landmarks[386]
                r_bottom = landmarks[374]

                cv2.circle(frame, (int(l_iris.x * w), int(l_iris.y * h)), 3, (0, 255, 255), -1)
                cv2.circle(frame, (int(r_iris.x * w), int(r_iris.y * h)), 3, (0, 255, 255), -1)

                l_eye_w = max(abs(l_inner.x - l_outer.x), 1e-4)
                l_eye_h = max(abs(l_bottom.y - l_top.y), 1e-4)
                r_eye_w = max(abs(r_outer.x - r_inner.x), 1e-4)
                r_eye_h = max(abs(r_bottom.y - r_top.y), 1e-4)

                l_gaze_h = (l_iris.x - min(l_outer.x, l_inner.x)) / l_eye_w
                r_gaze_h = (r_iris.x - min(r_inner.x, r_outer.x)) / r_eye_w
                eye_gaze_x = float(np.clip((l_gaze_h + r_gaze_h) / 2.0, 0.1, 0.9))

                l_gaze_v = (l_iris.y - min(l_top.y, l_bottom.y)) / l_eye_h
                r_gaze_v = (r_iris.y - min(r_top.y, r_bottom.y)) / r_eye_h
                eye_gaze_y = float(np.clip((l_gaze_v + r_gaze_v) / 2.0, 0.1, 0.9))
            except Exception:
                eye_gaze_x, eye_gaze_y = 0.5, 0.5

            # -------------------------------------------------------------
            # 2. HEAD POSE TRACKING
            # -------------------------------------------------------------
            nose = landmarks[1]
            left_cheek = landmarks[234]
            right_cheek = landmarks[454]
            forehead = landmarks[10]
            chin = landmarks[152]

            face_width = max(abs(right_cheek.x - left_cheek.x), 1e-4)
            face_height = max(abs(chin.y - forehead.y), 1e-4)
            face_center_x = (left_cheek.x + right_cheek.x) / 2.0
            face_center_y = (forehead.y + chin.y) / 2.0

            head_yaw = (nose.x - face_center_x) / face_width
            head_pitch = (nose.y - face_center_y) / face_height

            # -------------------------------------------------------------
            # 3. CALIBRATION HANDLING
            # -------------------------------------------------------------
            with calibration_lock:
                if calibrate_requested:
                    calib_center_gaze = [eye_gaze_x, eye_gaze_y]
                    calib_center_head = [head_yaw, head_pitch]
                    is_calibrated = True
                    calibrate_requested = False
                    calibration_feedback_until = time.time() + 1.5
                    logger.info(f"[Calibration] Gaze center calibrated: ({eye_gaze_x:.3f}, {eye_gaze_y:.3f})")

            # -------------------------------------------------------------
            # 4. GAZE + HEAD TO SCREEN COORDINATE MAPPING
            # -------------------------------------------------------------
            delta_gaze_x = (eye_gaze_x - calib_center_gaze[0])
            delta_gaze_y = (eye_gaze_y - calib_center_gaze[1])

            delta_head_x = (head_yaw - calib_center_head[0])
            delta_head_y = (head_pitch - calib_center_head[1])

            sens = float(SETTINGS.get("gaze_sensitivity", 1.4))
            speed = float(SETTINGS.get("cursor_speed", 0.5))

            total_norm_x = (delta_gaze_x * 3.8 + delta_head_x * 2.8) * sens
            total_norm_y = (delta_gaze_y * 4.2 + delta_head_y * 3.2) * sens

            if INVERT_X:
                total_norm_x = -total_norm_x
            if INVERT_Y:
                total_norm_y = -total_norm_y

            scope = float(SETTINGS.get("cursor_scope", 1.0))
            raw_screen_x = CENTER_X + (total_norm_x * (SCREEN_W / 2) * scope)
            raw_screen_y = CENTER_Y + (total_norm_y * (SCREEN_H / 2) * scope)

            raw_screen_x = max(10, min(SCREEN_W - 10, raw_screen_x))
            raw_screen_y = max(10, min(SCREEN_H - 10, raw_screen_y))

            smoothing_alpha = max(0.08, min(0.60, 0.15 + speed * 0.35))
            screen_x = int(prev_screen_x + smoothing_alpha * (raw_screen_x - prev_screen_x))
            screen_y = int(prev_screen_y + smoothing_alpha * (raw_screen_y - prev_screen_y))
            prev_screen_x = screen_x
            prev_screen_y = screen_y

            if SETTINGS.get("mouse_control_enabled", True):
                with mouse_lock:
                    mouse_target[0] = screen_x
                    mouse_target[1] = screen_y

            # -------------------------------------------------------------
            # 5. BLINK DETECTION (CLICK AUTOMATION)
            # -------------------------------------------------------------
            ratio = get_blink_ratio(landmarks, LEFT_EYE_INDICES)
            base_thresh = SETTINGS.get("blink_sensitivity", BLINK_THRESH)
            thresh = fatigue_monitor.get_adjusted_sensitivity(base_thresh)

            if ratio < thresh:
                blink_active = True
            else:
                if blink_active:
                    fatigue_monitor.record_blink()
                    try:
                        pyautogui.click()
                    except Exception:
                        pass
                    blink_active = False

            # -------------------------------------------------------------
            # 6. VISUAL HUD ON CAMERA FEED
            # -------------------------------------------------------------
            disp_gaze_x = int(np.clip(CENTER_X + total_norm_x * (w / 2), 20, w - 20))
            disp_gaze_y = int(np.clip(CENTER_Y + total_norm_y * (h / 2), 20, h - 20))
            cv2.drawMarker(frame, (disp_gaze_x, disp_gaze_y), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)

            if time.time() < calibration_feedback_until:
                cv2.rectangle(frame, (10, 10), (w - 10, 50), (0, 200, 0), -1)
                cv2.putText(frame, "CENTER CALIBRATED SUCCESSFULLY!", (20, 38),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)
            else:
                cv2.putText(frame, "Tracking Active | Press 'C' to calibrate center", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)

            # BreathGuard Vitals Mini-HUD
            bg_summary = breathguard.breathguard_engine.get_vitals_summary()
            if bg_summary["permission_granted"] and bg_summary["breathing_rate"]:
                cv2.putText(frame, f"Resp: {bg_summary['breathing_rate']:.1f} BPM | Pulse: {bg_summary['pulse_rate']:.1f}",
                            (10, h - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 128), 1)
            else:
                cv2.putText(frame, "BreathGuard: Permission Required",
                            (10, h - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

            cv2.putText(frame, f"Gaze: ({eye_gaze_x:.2f}, {eye_gaze_y:.2f}) Blink: {ratio:.2f}",
                        (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

            with frame_lock:
                camera_status["calibrated"] = is_calibrated
                camera_status["gaze_x"] = round(eye_gaze_x, 3)
                camera_status["gaze_y"] = round(eye_gaze_y, 3)

        else:
            cv2.rectangle(frame, (10, 10), (w - 10, 60), (0, 0, 180), -1)
            cv2.putText(frame, "FACE NOT DETECTED", (20, 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            with frame_lock:
                latest_jpeg_frame = buffer.tobytes()

        time.sleep(0.02)


# =========================================================================
# FLASK HTTP ROUTES & REST APIS
# =========================================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/video_feed')
def video_feed():
    """Stream camera video feed continuously from background worker."""
    def frame_generator():
        while True:
            with frame_lock:
                frame_bytes = latest_jpeg_frame
            if frame_bytes is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.03)

    return Response(frame_generator(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/calibrate', methods=['POST'])
def calibrate():
    """Calibrate the gaze tracking to center on current gaze/head position."""
    global calibrate_requested
    with calibration_lock:
        calibrate_requested = True
    return jsonify({"status": "ok", "message": "Calibration requested. Looking at center..."})


@app.route('/tracking_status')
def tracking_status():
    """Status endpoint for the UI to show camera and tracking state."""
    with frame_lock:
        status_copy = {
            "camera_online": bool(camera_status.get("camera_online", False)),
            "is_black": bool(camera_status.get("is_black", False)),
            "face_detected": bool(camera_status.get("face_detected", False)),
            "calibrated": bool(camera_status.get("calibrated", False)),
            "yaw": float(camera_status.get("yaw", 0.0)),
            "pitch": float(camera_status.get("pitch", 0.0)),
            "gaze_x": float(camera_status.get("gaze_x", 0.5)),
            "gaze_y": float(camera_status.get("gaze_y", 0.5)),
            "mouse_control_enabled": bool(SETTINGS.get("mouse_control_enabled", False)),
            "overlay_enabled": bool(SETTINGS.get("overlay_enabled", False))
        }
    return jsonify(status_copy)


# --- PATIENT PROFILE APIS ---
@app.route('/api/profile', methods=['GET', 'POST'])
def api_profile():
    if request.method == 'POST':
        data = request.json or {}
        updated = database.update_patient_profile(data)
        return jsonify({"status": "success", "profile": updated})
    profile = database.get_patient_profile()
    return jsonify({"status": "success", "profile": profile})


# --- CAREGIVER & FRIEND CONTACT MANAGEMENT APIS ---
@app.route('/api/caregivers', methods=['GET', 'POST', 'PUT', 'DELETE'])
def api_caregivers():
    if request.method == 'GET':
        ctype = request.args.get("type")
        caregivers = database.get_all_caregivers(contact_type=ctype)
        return jsonify({"status": "success", "caregivers": caregivers})
    
    elif request.method == 'POST':
        data = request.json or {}
        name = data.get("name", "").strip()
        rel = data.get("relationship", "").strip()
        phone = data.get("phone_number", "").strip()
        ctype = data.get("contact_type", "caregiver")
        if not name or not phone:
            return jsonify({"status": "error", "message": "Name and phone number are required"}), 400
        
        new_id = database.add_caregiver(
            name=name,
            relationship=rel,
            phone_number=phone,
            email=data.get("email", ""),
            is_primary=data.get("is_primary", 0),
            preferred_channel=data.get("preferred_channel", "voice"),
            contact_type=ctype
        )
        return jsonify({"status": "success", "id": new_id, "message": "Contact added successfully"})

    elif request.method == 'PUT':
        data = request.json or {}
        cid = data.get("id")
        if not cid:
            return jsonify({"status": "error", "message": "Contact ID is required"}), 400
        database.update_caregiver(
            caregiver_id=cid,
            name=data.get("name", ""),
            relationship=data.get("relationship", ""),
            phone_number=data.get("phone_number", ""),
            is_primary=data.get("is_primary", 0),
            preferred_channel=data.get("preferred_channel", "voice")
        )
        return jsonify({"status": "success", "message": "Contact updated successfully"})

    elif request.method == 'DELETE':
        cid = request.args.get("id", type=int)
        if not cid:
            return jsonify({"status": "error", "message": "Contact ID is required"}), 400
        database.delete_caregiver(cid)
        return jsonify({"status": "success", "message": "Contact removed"})


@app.route('/api/friends', methods=['GET', 'POST', 'DELETE'])
def api_friends():
    """Dedicated endpoint for friend contacts selection and management."""
    if request.method == 'GET':
        friends = database.get_friends()
        return jsonify({"status": "success", "friends": friends})

    elif request.method == 'POST':
        data = request.json or {}
        name = data.get("name", "").strip()
        rel = data.get("relationship", "").strip() or "Friend"
        phone = data.get("phone_number", "").strip()
        if not name or not phone:
            return jsonify({"status": "error", "message": "Friend name and phone number are required"}), 400
        
        new_id = database.add_friend(name=name, phone_number=phone, relationship=rel)
        return jsonify({"status": "success", "id": new_id, "message": "Friend added successfully"})

    elif request.method == 'DELETE':
        fid = request.args.get("id", type=int)
        if not fid:
            return jsonify({"status": "error", "message": "Friend ID is required"}), 400
        database.delete_friend(fid)
        return jsonify({"status": "success", "message": "Friend contact removed"})


# --- EVERYDAY HELP REQUEST APIS ---
@app.route('/api/help_requests', methods=['GET', 'POST'])
def api_help_requests():
    if request.method == 'POST':
        data = request.json or {}
        category = data.get("category", "general")
        note = data.get("note", "")
        caregiver_id = data.get("caregiver_id")

        help_req = database.create_help_request(category=category, note=note, caregiver_id=caregiver_id)
        
        # Dispatch notification to caregiver via SMS
        if help_req.get("caregiver_phone"):
            msg_text = agent_reasoning.compose_assistance_message(category, note)
            communication_service.send_caregiver_sms(
                to_phone=help_req["caregiver_phone"],
                caregiver_name=help_req["caregiver_name"],
                message_text=msg_text
            )

        return jsonify({"status": "success", "request": help_req})

    limit = request.args.get("limit", default=20, type=int)
    requests_list = database.get_help_requests(limit=limit)
    return jsonify({"status": "success", "requests": requests_list})


@app.route('/api/help_requests/<int:req_id>/acknowledge', methods=['POST'])
def api_ack_help_request(req_id):
    data = request.json or {}
    new_status = data.get("status", "acknowledged")
    database.update_help_request_status(req_id, new_status)
    return jsonify({"status": "success", "request_id": req_id, "status": new_status})


# --- BREATHGUARD CONSENT SAFEGUARD APIS ---
@app.route('/api/breathguard/consent', methods=['GET', 'POST'])
def api_breathguard_consent():
    """
    STRICT SAFEGUARD: Vitals tracking is blocked until explicit consent is given.
    """
    if request.method == 'POST':
        data = request.json or {}
        granted = bool(data.get("consent", False))
        breathguard.breathguard_engine.request_permission(granted)
        return jsonify({
            "status": "success",
            "permission_granted": granted,
            "message": "Permission granted for vitals monitoring" if granted else "Vitals monitoring permission revoked"
        })

    has_perm = breathguard.breathguard_engine.has_permission()
    return jsonify({
        "status": "success",
        "permission_granted": has_perm
    })


# --- BREATHGUARD VITALS & ALERT APIS ---
@app.route('/api/breathguard/vitals', methods=['GET'])
def api_breathguard_vitals():
    """Get real-time breathing, pulse, waveforms, and signal validation."""
    summary = breathguard.breathguard_engine.get_vitals_summary()
    return jsonify(summary)


@app.route('/api/breathguard/test_scenario', methods=['POST'])
def api_breathguard_test_scenario():
    """Trigger or disable test safety drills (simulated data)."""
    data = request.json or {}
    scenario = data.get("scenario", "normal")  # 'normal', 'bradypnea', 'tachypnea', 'apnea', 'disable'
    if scenario == "disable":
        breathguard.breathguard_engine.set_test_mode(False)
        return jsonify({"status": "success", "message": "Test drill mode disabled. Returning to live mode."})
    else:
        breathguard.breathguard_engine.set_test_mode(True, scenario=scenario)
        return jsonify({"status": "success", "message": f"Simulated drill active: {scenario} (clearly labeled test data)"})


@app.route('/api/breathguard/alerts', methods=['GET'])
def api_breathguard_alerts():
    alerts = database.get_breathguard_alerts(limit=25)
    return jsonify({"status": "success", "alerts": alerts})


# --- DIRECT CAREGIVER OUTBOUND CALL & VIDEO CALL APIS ---
@app.route('/api/call/caregiver', methods=['POST'])
def api_call_caregiver():
    """
    STRICT SAFEGUARD: Places outbound call to caregiver with verified destination check.
    """
    data = request.json or {}
    phone = data.get("phone_number")
    name = data.get("caregiver_name")
    
    prof = database.get_patient_profile() or {}
    caller_name = prof.get("preferred_name") or prof.get("full_name") or "OptiKinesis user"
    is_emerg = data.get("is_emergency", False)
    default_msg = f"{caller_name} is requesting your immediate assistance via OptiKinesis." if is_emerg else f"{caller_name} is calling you via OptiKinesis."
    custom_message = data.get("message") or default_msg

    if not phone:
        # Default to primary caregiver
        primary = database.get_primary_caregiver()
        if primary:
            phone = primary["phone_number"]
            name = primary["name"]

    if not phone:
        return jsonify({"status": "error", "message": "No caregiver phone number available"}), 400

    result = communication_service.place_caregiver_voice_call(
        to_phone=phone,
        caregiver_name=name or "Caregiver",
        message_text=custom_message,
        is_emergency=is_emerg
    )
    return jsonify(result)


@app.route('/api/call/video/session', methods=['POST'])
def api_video_session():
    """Generate secure WebRTC video call room session."""
    data = request.json or {}
    cid = data.get("caregiver_id")
    session = communication_service.create_video_session(caregiver_id=cid)
    return jsonify({"status": "success", "session": session})


@app.route('/api/twilio/acknowledge', methods=['POST', 'GET'])
def api_twilio_acknowledge():
    """Webhook when caregiver presses 1 on keypad during automated phone alert."""
    digits = request.values.get("Digits", "")
    logger.info(f"[Twilio Webhook] Received keypad response: Digits={digits}")
    return """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say voice="Polly.Joanna">Thank you. Your acknowledgement has been recorded in OptiKinesis. Have a good day.</Say>
    </Response>"""


# --- ELEVENLABS TEXT-TO-SPEECH API ---
@app.route('/api/tts/synthesize', methods=['POST'])
def api_tts_synthesize():
    """
    Synthesizes natural speech using ElevenLabs API with user's key.
    Returns audio_base64 for immediate browser playback.
    """
    data = request.json or {}
    text = data.get("text", "").strip()
    voice_id = data.get("voice_id")
    if not text:
        return jsonify({"status": "error", "message": "Text is required"}), 400

    result = communication_service.synthesize_speech(text, voice_id=voice_id)
    return jsonify(result)


# --- AGENT REASONING API ---
@app.route('/api/ai/assist', methods=['POST'])
def api_ai_assist():
    data = request.json or {}
    query = data.get("query", "")
    res = agent_reasoning.process_agent_query(query)
    return jsonify(res)


# --- SETTINGS & ACTIONS ---
@app.route('/update_settings', methods=['POST'])
def update_settings():
    data = request.json or {}
    if 'emergency_contact' in data:
        SETTINGS['emergency_contact'] = data['emergency_contact']
    if 'cursor_scope' in data:
        try:
            SETTINGS['cursor_scope'] = float(data['cursor_scope'])
        except Exception:
            pass
    if 'blink_sensitivity' in data:
        try:
            SETTINGS['blink_sensitivity'] = float(data['blink_sensitivity'])
        except Exception:
            pass
    if 'cursor_speed' in data:
        try:
            speed = float(data['cursor_speed'])
            SETTINGS['cursor_speed'] = max(0.1, min(2.0, speed))
        except Exception:
            pass
    if 'gaze_sensitivity' in data:
        try:
            SETTINGS['gaze_sensitivity'] = float(data['gaze_sensitivity'])
        except Exception:
            pass
    if 'overlay_enabled' in data:
        SETTINGS['overlay_enabled'] = bool(data['overlay_enabled'])
    if 'mouse_control_enabled' in data:
        SETTINGS['mouse_control_enabled'] = bool(data['mouse_control_enabled'])
    return jsonify({"status": "updated", "settings": SETTINGS})


@app.route('/perform_action', methods=['POST'])
def perform_action():
    data = request.json or {}
    action = data.get('action')
    text = data.get('text', '')

    contact_num = SETTINGS["emergency_contact"]

    if action == 'google':
        webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(text)}")
    elif action == 'youtube':
        webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(text)}")
    elif action == 'type_external':
        threading.Thread(target=execute_type_external, args=(text,)).start()
        return jsonify({"status": "timer_started"})
    elif action == 'toggle_mouse':
        SETTINGS['mouse_control_enabled'] = not SETTINGS.get('mouse_control_enabled', False)
        return jsonify({"status": "toggled", "mouse_control_enabled": SETTINGS['mouse_control_enabled']})
    elif action == 'toggle_overlay':
        SETTINGS['overlay_enabled'] = not SETTINGS.get('overlay_enabled', False)
        return jsonify({"status": "toggled", "overlay_enabled": SETTINGS['overlay_enabled']})
    return jsonify({"status": "ok"})


# --- FATIGUE MONITORING ROUTES ---
@app.route('/fatigue_status')
def fatigue_status():
    status = fatigue_monitor.check_fatigue()
    return jsonify(status)


# --- JAYU COMPUTER USE & DUAL-MODE VOICE AGENT ROUTES ---
@app.route('/api/agent/voice', methods=['POST'])
def api_agent_voice():
    """
    Dual-mode voice assistant:
    1. 'type_speak': Dictates text into accessible keyboard and synthesizes speech.
    2. 'speak_navigation': Jayu Gemini Computer Use agent navigating the local computer.
    """
    data = request.json or {}
    text = data.get("text", "").strip()
    mode = data.get("mode", VoiceAgentMode.SPEAK_NAVIGATION)
    
    if not text:
        return jsonify({"status": "error", "message": "Voice text is required"}), 400
        
    result = jayu_agent.process_voice_command(text, mode=mode)
    return jsonify(result)


@app.route('/voice_command', methods=['POST'])
def voice_command():
    data = request.json or {}
    text = data.get('text', '').strip()
    mode = data.get('mode', VoiceAgentMode.SPEAK_NAVIGATION)
    if not text:
        return jsonify({'status': 'error', 'message': 'No command text provided'})
    result = jayu_agent.process_voice_command(text, mode=mode)
    return jsonify(result)


# --- KEYBOARD LISTENER FOR CALIBRATION ---
def keyboard_listener():
    """Listen for 'c' key press for calibration."""
    global calibrate_requested
    try:
        from pynput import keyboard
        def on_press(key):
            global calibrate_requested
            try:
                if hasattr(key, 'char') and key.char in ['c', 'C']:
                    logger.info("[Calibration] 'C' key detected - triggering calibration...")
                    with calibration_lock:
                        calibrate_requested = True
            except Exception:
                pass

        listener = keyboard.Listener(on_press=on_press)
        listener.start()
        listener.join()
    except Exception as e:
        logger.info(f"Keyboard listener status: {e}")


if __name__ == '__main__':
    # Start camera and tracking loop in background thread
    threading.Thread(target=camera_tracking_loop, daemon=True).start()

    # Start mouse mover thread
    threading.Thread(target=mouse_mover, daemon=True).start()
    
    # Start keyboard listener for calibration
    threading.Thread(target=keyboard_listener, daemon=True).start()
    
    # Run Flask in a background thread
    threading.Thread(target=lambda: app.run(port=5001, debug=False, use_reloader=False), daemon=True).start()
    
    time.sleep(1.5)
    
    if PYQT5_AVAILABLE and SETTINGS.get("overlay_enabled", False):
        qt_app = QtWidgets.QApplication(sys.argv)
        overlay = CursorOverlay(radius=60)
        overlay.show()
        qt_app.exec_()
    else:
        logger.info("Running clean web server without desktop cursor overlay. Press Ctrl+C to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
