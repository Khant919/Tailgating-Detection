"""
src/auth_pipeline.py
====================
Optimized 2FA Pipeline: Mathematical Face Recognition + QR Code Scanning.
Designed for high efficiency on Intel i7 11th Gen CPUs.

Key Features:
    1. Pre-encodes employee face embeddings during startup.
    2. Uses tight YOLO ROI cropping to minimize face_recognition CPU overhead.
    3. Maintains active sessions with a 5-second automatic expiration timeout.
    4. Executes pyzbar QR scanning ONLY when active sessions exist (CPU saving).
"""

import os
import sys
import time
from typing import Dict, Optional, Tuple, List
import cv2
import numpy as np

# Reconfigure stdout for Windows console unicode safety
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Third-party computer vision libraries
# These optional dependencies fail in more ways than ImportError: face_recognition
# needs a compiled dlib, and pyzbar loads libzbar-64.dll at import time (raising
# OSError/FileNotFoundError when the VC++ runtime is absent). Catch broadly so a
# missing optional dependency degrades the 2FA stage instead of killing the app.
try:
    import face_recognition
except Exception as exc:
    print(f"[2FA] face_recognition unavailable ({exc.__class__.__name__}) — face matching disabled.")
    face_recognition = None

try:
    from pyzbar import pyzbar
except Exception as exc:
    print(f"[2FA] pyzbar unavailable ({exc.__class__.__name__}) — camera QR scanning disabled.")
    pyzbar = None

from src.database import DatabaseManager


class TwoFactorAuthenticator:
    """
    Two-Factor Authentication (2FA) Engine combining face recognition
    with QR code verification.
    """

    def __init__(
        self,
        known_faces_dir: str = "known_faces",
        expiration_seconds: float = 5.0,
        tolerance: float = 0.6,
        db: Optional[DatabaseManager] = None,
    ):
        """
        Initializes the 2FA engine and enrolls known employee faces.

        Args:
            known_faces_dir: Directory containing employee reference photos (.jpg, .jpeg, .png).
            expiration_seconds: Time limit (in seconds) for completing QR scan after face match.
            tolerance: Distance threshold for face_recognition matching (lower = stricter).
            db: Optional DatabaseManager instance.
        """
        self.known_faces_dir = known_faces_dir
        self.expiration_seconds = expiration_seconds
        self.tolerance = tolerance
        self.db = db or DatabaseManager()

        # Dictionary storing enrolled employee embeddings: {"employee_name": np.ndarray}
        self.known_employees: Dict[str, np.ndarray] = {}

        # Active session state management: {"employee_name": timestamp_matched}
        self.active_sessions: Dict[str, float] = {}

        # Sliding window history of Eye Aspect Ratios (EAR) for anti-spoofing liveness check: {"employee_name": [ear1, ear2, ...]}
        self.ear_history: Dict[str, List[float]] = {}

        # Perform enrollment scanning on startup
        self._enroll_known_faces()

    def _calculate_ear(self, eye_points: List[Tuple[int, int]]) -> float:
        """
        Calculates Eye Aspect Ratio (EAR) for a single eye using 6 2D facial landmark points.
        Formula: EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)
        """
        if len(eye_points) < 6:
            return 0.0
        
        pts = np.array(eye_points, dtype=np.float32)
        # Vertical landmark distances
        v1 = np.linalg.norm(pts[1] - pts[5])
        v2 = np.linalg.norm(pts[2] - pts[4])
        # Horizontal landmark distance
        h = np.linalg.norm(pts[0] - pts[3])

        if h == 0:
            return 0.0

        return float((v1 + v2) / (2.0 * h))

    def check_liveness(self, face_landmarks: dict) -> Tuple[bool, float]:
        """
        Calculates average Eye Aspect Ratio (EAR) for left and right eyes.

        Args:
            face_landmarks: Dictionary containing 'left_eye' and 'right_eye' 2D point lists.

        Returns:
            Tuple (is_eyes_open: bool, average_ear: float)
        """
        left_eye = face_landmarks.get("left_eye", [])
        right_eye = face_landmarks.get("right_eye", [])

        left_ear = self._calculate_ear(left_eye)
        right_ear = self._calculate_ear(right_eye)

        avg_ear = (left_ear + right_ear) / 2.0
        # EAR threshold > 0.12 indicates open/naturally functioning eyes
        return (avg_ear > 0.12), avg_ear

    def _enroll_known_faces(self) -> None:
        """
        Scans local directory for employee photos and pre-computes 128D face encodings.
        """
        if face_recognition is None:
            print("[2FA Engine] [WARNING] 'face_recognition' library is not installed. Face verification disabled.")
            return

        if not os.path.exists(self.known_faces_dir):
            os.makedirs(self.known_faces_dir, exist_ok=True)
            print(f"[2FA Engine] Created directory '{self.known_faces_dir}'. Place employee photos here (.png, .jpg, .jpeg, .webp, .bmp).")
            return

        valid_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}
        enrolled_count = 0

        print(f"[2FA Engine] Enrolling employee faces from '{self.known_faces_dir}'...")

        for filename in os.listdir(self.known_faces_dir):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in valid_extensions:
                continue

            employee_name = os.path.splitext(filename)[0]
            file_path = os.path.join(self.known_faces_dir, filename)

            try:
                # Load image file
                image = face_recognition.load_image_file(file_path)

                # Extract 128-dimensional embedding
                encodings = face_recognition.face_encodings(image)

                if len(encodings) > 0:
                    self.known_employees[employee_name] = encodings[0]
                    enrolled_count += 1
                    emp_rec = self.db.get_or_create_employee(employee_name)
                    emp_id = emp_rec.get("employee_id", "UNKNOWN")
                    emp_key = emp_rec.get("unique_key", "")
                    print(f"[2FA Engine]   [OK] Enrolled: '{employee_name}' (ID: {emp_id}, Key: {emp_key[:8]}...)")
                else:
                    print(f"[2FA Engine] [WARNING] No face detected in '{filename}'. Skipping.")
            except Exception as e:
                print(f"[2FA Engine] [ERROR] Processing '{filename}': {e}")

        print(f"[2FA Engine] Startup Complete: {enrolled_count} employee face(s) enrolled.\n")

    def _cleanup_expired_sessions(self) -> None:
        """
        Purges active 2FA sessions that have exceeded the 5-second timeout window.
        """
        current_time = time.time()
        expired_users = [
            user for user, timestamp in self.active_sessions.items()
            if (current_time - timestamp) > self.expiration_seconds
        ]
        for user in expired_users:
            del self.active_sessions[user]
            print(f"[2FA Engine] [TIMEOUT] Session Expired for user: '{user}' (5s limit reached)")

    def verify_face(self, frame: np.ndarray, bounding_box: Tuple[int, int, int, int]) -> Tuple[bool, Optional[str]]:
        """
        Method 1: Verifies face identity inside the YOLO bounding box.

        Args:
            frame: Full BGR frame from webcam/camera stream.
            bounding_box: YOLO bounding box (x1, y1, x2, y2).

        Returns:
            Tuple (is_matched: bool, employee_name: Optional[str])
        """
        if face_recognition is None or not self.known_employees:
            return False, None

        # Clean up any expired active sessions first
        self._cleanup_expired_sessions()

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bounding_box

        # Safety clip bounding box coordinates to frame boundaries
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(w, int(x2)), min(h, int(y2))

        if x2 <= x1 or y2 <= y1:
            return False, None

        # Crop frame to person ROI to minimize CPU work
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return False, None

        # Resolution Guard: Prevent processing small crops when subject is too far from camera
        crop_h, crop_w = crop.shape[:2]
        if crop_h < 60 or crop_w < 60:
            print(f"[Auth] Face crop too small ({crop_w}x{crop_h} px). Waiting for subject to move closer.")
            return False, None

        # Convert BGR crop to RGB for dlib / face_recognition
        rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

        # Extract 128D face encoding from the cropped region
        # On Intel i7 11th gen, encoding a small crop takes ~10-15ms
        live_encodings = face_recognition.face_encodings(rgb_crop)

        if not live_encodings:
            return False, None

        live_encoding = live_encodings[0]

        # Extract known employee names and vectors
        known_names = list(self.known_employees.keys())
        known_vectors = list(self.known_employees.values())

        # Mathematical face distance calculation (Euclidean distance)
        face_distances = face_recognition.face_distance(known_vectors, live_encoding)

        if len(face_distances) == 0:
            return False, None

        best_match_index = int(np.argmin(face_distances))
        best_distance = face_distances[best_match_index]

        if best_distance <= self.tolerance:
            matched_name = known_names[best_match_index]

            # ------------------------------------------------------------------
            # PASSIVE LIVENESS CHECK: EAR & Static Photo Variance Detection
            # ------------------------------------------------------------------
            landmarks_list = face_recognition.face_landmarks(rgb_crop)
            if landmarks_list:
                landmarks = landmarks_list[0]
                has_valid_eyes, current_ear = self.check_liveness(landmarks)

                if matched_name not in self.ear_history:
                    self.ear_history[matched_name] = []
                self.ear_history[matched_name].append(current_ear)

                # Maintain 5-frame sliding window
                if len(self.ear_history[matched_name]) > 5:
                    self.ear_history[matched_name].pop(0)

                # Detect static photo spoof attempt across 5 consecutive frames
                if len(self.ear_history[matched_name]) >= 5:
                    ear_variance = float(np.var(self.ear_history[matched_name]))
                    # Near-zero EAR variance (< 0.00002) indicates a static photo held in front of camera
                    if ear_variance < 0.00002:
                        print(f"[Auth] ⚠️ SPOOF ATTEMPT DETECTED: Static photo detected for '{matched_name}'!")
                        return False, None

            # State Management: Add/Update user in active sessions with current timestamp
            self.active_sessions[matched_name] = time.time()
            print(f"[2FA Engine] [MATCH] FACE MATCHED: '{matched_name}' (Distance: {best_distance:.3f})")
            return True, matched_name

        return False, None

    def scan_qr(self, frame: np.ndarray) -> Tuple[bool, Optional[str]]:
        """
        Method 2: Scans frame for QR code payload and validates against active 2FA sessions.

        CPU Optimization: Only executes scanning if active_sessions is non-empty.

        Args:
            frame: Full BGR frame from webcam/camera stream.

        Returns:
            Tuple (is_granted: bool, employee_name: Optional[str])
        """
        if pyzbar is None:
            return False, None

        # CPU Guard: Only execute pyzbar if there is an active face session pending QR verification
        if not self.active_sessions:
            return False, None

        # Maintain session timeouts
        self._cleanup_expired_sessions()
        if not self.active_sessions:
            return False, None

        # CPU Optimization for Intel i7: Convert to grayscale for fast pyzbar QR decoding
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Decode QR codes in the frame
        decoded_objects = pyzbar.decode(gray_frame)

        for obj in decoded_objects:
            try:
                qr_payload = obj.data.decode("utf-8").strip()
            except Exception:
                continue

            # Check if QR payload matches any employee currently awaiting QR verification
            if qr_payload in self.active_sessions:
                print(f"[2FA Engine] [SUCCESS] 2FA ACCESS GRANTED for '{qr_payload}'!")
                
                # Clear session upon successful authentication
                del self.active_sessions[qr_payload]
                return True, qr_payload

        return False, None
