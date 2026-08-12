"""
Module 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9: Fully Optimized & Privacy-Hardened Live Pipeline.
==========================================================================================
Includes:
    1. Visual Re-ID fallback tracking (inside PersonDetector).
    2. Lucas-Kanade optical flow occlusion warning (inside TripwireCounter).
    3. Homography perspective warping displaying a "Radar Mini-Map" in the video window.
    4. Custom API swipe validation and face-blurred BGR screenshot logging.
"""

import os
import time
from datetime import datetime
import threading
import webbrowser

import cv2
import numpy as np

from config import (
    COUNTING_LINE_COLOR,
    COUNTING_LINE_POSITION,
    COUNTING_LINE_THICKNESS,
    DEFAULT_CAMERA_INDEX,
    DOOR_LABEL_COLOR,
    DOOR_LABEL_FONT_SCALE,
    DOOR_LABEL_TEXT,
    DOOR_LABEL_THICKNESS,
    DOOR_ROI_COLOR,
    DOOR_ROI_SIZE,
    DOOR_ROI_THICKNESS,
    DOOR_ROI_TOP_LEFT,
    SCREENSHOT_DIR,
    SCREENSHOT_FILENAME_FORMAT,
    HEADLESS_MODE,
    PROCESS_EVERY_N_FRAMES,
    TRACK_COLORS,
)

import sys

# Audio alarm imports (Windows winsound support)
try:
    import winsound
except ImportError:
    winsound = None


def play_alarm_sound() -> None:
    """
    Plays an audible breach alarm chime safely without blocking the video pipeline.
    Uses winsound.Beep on Windows, with a terminal bell fallback for non-Windows platforms.
    """
    try:
        if sys.platform == "win32" and winsound is not None:
            # Play a 2000Hz frequency beep for 500ms
            winsound.Beep(2000, 500)
        else:
            # Fallback for Linux / macOS: Terminal bell ASCII character \a
            print("\a", end="", flush=True)
    except Exception as err:
        print(f"[Alarm] Could not play alarm sound: {err}")


def trigger_breach_alarm() -> None:
    """
    Spawns a non-blocking daemon thread to play the breach alarm sound.
    Ensures zero impact on OpenCV video frame rate (prevents video freezing).
    """
    threading.Thread(target=play_alarm_sound, daemon=True, name="BreachAlarmThread").start()


from src.database import DatabaseManager
from src.dashboard import run_dashboard_server
from src.auth_pipeline import TwoFactorAuthenticator


class WebcamCapture:
    """A clean object-oriented wrapper for webcam capture, displaying a Bird's-Eye radar map."""

    def __init__(
        self,
        camera_index: int = DEFAULT_CAMERA_INDEX,
        detector=None,
        counter=None,
        controller=None,
        authenticator=None,
    ):
        """
        Args:
            camera_index: Webcam index (default 0).
            detector:     Optional PersonDetector (Module 2+3).
            counter:      Optional TripwireCounter (Module 4).
            controller:   Optional AccessController (Module 5).
            authenticator: Optional TwoFactorAuthenticator (2FA Pipeline).
        """
        self.camera_index  = camera_index
        self.detector      = detector
        self.counter       = counter
        self.controller    = controller
        self.authenticator = authenticator or TwoFactorAuthenticator()
        self.auth_states   = {} # track_id -> {"status": str, "name": str, "timestamp": float}


        # Module 7: Performance variables
        self.frame_count: int = 0
        self._last_detections = []

        # Window title reflects active modules.
        if detector and counter and controller:
            self.window_title = "Tailgating Detection - Module 1-9 (Press 'q' to quit)"
        else:
            self.window_title = "Tailgating Detection (Press 'q' to quit)"

        self.video_capture      = None
        self.previous_timestamp = None
        self.fps                = 0.0
        self.screenshot_dir     = SCREENSHOT_DIR
        os.makedirs(self.screenshot_dir, exist_ok=True)

        # Module 6: Persistent Audit Trail Database Manager
        self.db = DatabaseManager()

        self.dashboard_thread = None

        # Module 9: Perspective transform matrix
        self.M = None

        # Module 8: Haar Cascade for GDPR face blurring — loaded lazily on first breach.
        self._face_cascade = None

    def _get_homography_matrix(self, w: int, h: int) -> np.ndarray:
        """
        Computes the perspective transform matrix between the walk-path on the floor
        (trapezoid in 2D camera coordinates) and a top-down radar view (150x200 rectangle).
        """
        src_pts = np.float32([
            [int(0.35 * w), int(0.4 * h)],   # Top-left of walking zone
            [int(0.65 * w), int(0.4 * h)],   # Top-right
            [int(0.9 * w),  int(0.95 * h)],  # Bottom-right
            [int(0.1 * w),  int(0.95 * h)]   # Bottom-left
        ])
        
        dst_pts = np.float32([
            [10, 10],   # Top-left in radar coordinates
            [140, 10],  # Top-right
            [140, 190], # Bottom-right
            [10, 190]   # Bottom-left
        ])
        return cv2.getPerspectiveTransform(src_pts, dst_pts)

    def _ensure_cascade_file(self) -> str:
        """
        Ensures the Haar Cascade file exists locally. If the pip-installed OpenCV
        distribution does not bundle it, this downloads it from the official OpenCV repository.
        """
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "haarcascade_frontalface_default.xml")
        if not os.path.exists(local_path):
            print("[WebcamCapture] [Download] Haar Cascade XML not found locally. Downloading from OpenCV GitHub...")
            import urllib.request
            url = "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml"
            try:
                # Set user-agent to avoid GitHub downloads being blocked
                req = urllib.request.Request(
                    url, 
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    with open(local_path, 'wb') as out_file:
                        out_file.write(response.read())
                print("[WebcamCapture] [Download] Downloaded Haar Cascade XML successfully.")
            except Exception as e:
                print(f"[WebcamCapture] [Download] Error: Failed to download Haar Cascade: {e}")
        return local_path.replace("\\", "/")

    def _get_face_cascade(self) -> cv2.CascadeClassifier | None:
        """
        Lazily loads the Haar Cascade face classifier used for GDPR blurring.
        Returns None if the cascade could not be loaded, so blurring degrades
        gracefully into a skipped screenshot rather than crashing the loop.
        """
        if self._face_cascade is None:
            cascade_path = self._ensure_cascade_file()
            cascade = cv2.CascadeClassifier(cascade_path)
            if cascade.empty():
                print(f"[WebcamCapture] Error: Could not load Haar Cascade from {cascade_path}.")
                return None
            self._face_cascade = cascade
        return self._face_cascade

    def _blur_faces(self, frame: np.ndarray) -> np.ndarray:
        """
        Module 8: GDPR compliance — applies a 51x51 Gaussian blur over every
        detected face before the frame is written to disk as breach evidence.

        Operates on a copy so the live display frame keeps unblurred faces for
        the on-screen guard view.

        Args:
            frame: BGR frame to anonymise.

        Returns:
            A new frame with all detected face regions blurred.
        """
        cascade = self._get_face_cascade()
        if cascade is None:
            # Fail closed: without a working cascade we cannot guarantee
            # anonymisation, so return a fully blurred frame rather than
            # writing identifiable faces to disk.
            print("[WebcamCapture] Warning: Cascade unavailable — blurring entire frame.")
            return cv2.GaussianBlur(frame, (51, 51), 0)

        anonymised = frame.copy()
        gray = cv2.cvtColor(anonymised, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        for (x, y, w, h) in faces:
            roi = anonymised[y:y + h, x:x + w]
            if roi.size == 0:
                continue
            anonymised[y:y + h, x:x + w] = cv2.GaussianBlur(roi, (51, 51), 0)

        print(f"[WebcamCapture] GDPR: Blurred {len(faces)} face(s) in evidence screenshot.")
        return anonymised

    def _draw_radar_map(self, frame: np.ndarray, detections) -> None:
        """Plots tracked people onto a bird's-eye 2D view displayed as a radar map."""
        h, w = frame.shape[:2]
        if self.M is None:
            self.M = self._get_homography_matrix(w, h)

        # Create overlay canvas
        overlay = frame.copy()
        
        # Draw semi-transparent dark map container in the bottom-left corner
        x_offset, y_offset = 10, h - 210
        cv2.rectangle(overlay, (x_offset, y_offset), (x_offset + 150, y_offset + 200), (20, 20, 20), -1)
        # Draw green border
        cv2.rectangle(overlay, (x_offset, y_offset), (x_offset + 150, y_offset + 200), (0, 255, 0), 1)
        
        # Draw pedestrian walking path boundaries (perspective-warped rectangle)
        cv2.rectangle(overlay, (x_offset + 10, y_offset + 10), (x_offset + 140, y_offset + 190), (80, 80, 80), 1)
        
        # Draw Perspective Tripwire line onto the map
        trip_y = self.counter.tripwire_y
        trip_x_left, trip_x_right = 50, 600
        
        denom_l = (self.M[2, 0] * trip_x_left + self.M[2, 1] * trip_y + self.M[2, 2])
        denom_r = (self.M[2, 0] * trip_x_right + self.M[2, 1] * trip_y + self.M[2, 2])
        
        if denom_l != 0 and denom_r != 0:
            plx = int((self.M[0, 0] * trip_x_left + self.M[0, 1] * trip_y + self.M[0, 2]) / denom_l)
            ply = int((self.M[1, 0] * trip_x_left + self.M[1, 1] * trip_y + self.M[1, 2]) / denom_l)
            prx = int((self.M[0, 0] * trip_x_right + self.M[0, 1] * trip_y + self.M[0, 2]) / denom_r)
            pry = int((self.M[1, 0] * trip_x_right + self.M[1, 1] * trip_y + self.M[1, 2]) / denom_r)
            
            cv2.line(overlay, (x_offset + plx, y_offset + ply), (x_offset + prx, y_offset + pry), (0, 0, 255), 2)
            cv2.putText(overlay, "TRIPWIRE", (x_offset + plx + 5, y_offset + ply - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)

        # Draw Title
        cv2.putText(overlay, "RADAR MINI-MAP", (x_offset + 15, y_offset + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)

        # Plot projected track points
        for det in detections:
            track_id = det.track_id
            if track_id < 0:
                continue
                
            x1, y1, x2, y2 = det.bbox
            cx = (x1 + x2) // 2
            cy = y2  # Bottom center (foot contact point representing floor position)
            
            denom = (self.M[2, 0] * cx + self.M[2, 1] * cy + self.M[2, 2])
            if denom != 0:
                px = int((self.M[0, 0] * cx + self.M[0, 1] * cy + self.M[0, 2]) / denom)
                py = int((self.M[1, 0] * cx + self.M[1, 1] * cy + self.M[1, 2]) / denom)
                
                # Check boundaries inside map limits
                if 0 <= px <= 150 and 0 <= py <= 200:
                    color = TRACK_COLORS[abs(track_id) % len(TRACK_COLORS)]
                    cv2.circle(overlay, (x_offset + px, y_offset + py), 5, color, -1)
                    cv2.putText(overlay, f"ID {track_id}", (x_offset + px + 6, y_offset + py + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)
                    
        # Apply semi-transparency blending
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    # ──────────────────────────────────────────────────────────────────────────
    def start(self):
        """Open the webcam and run the main frame loop."""
        from src.stream_reader import ThreadedCamera
        self.video_capture = ThreadedCamera(self.camera_index)
        self.video_capture.start()

        if not self.video_capture.isOpened():
            print(f"Error: Could not open webcam at index {self.camera_index}.")
            print("Please check that your camera is connected and try again.")
            return

        # Module 6: Start Dashboard Flask app in a background daemon thread
        self.dashboard_thread = threading.Thread(
            target=run_dashboard_server,
            daemon=True,
            name="FlaskDashboardServer"
        )
        self.dashboard_thread.start()

        self.previous_timestamp = time.time()
        
        if not HEADLESS_MODE:
            print("Press 'q' to quit and 's' to save the current frame.")
        else:
            print("[WebcamCapture] Headless Mode Enabled. Visual displays disabled.")
            print("[WebcamCapture] Press Ctrl+C in terminal to exit gracefully.")

        # State flag to prevent opening multiple browser tabs per face recognition event
        admin_portal_opened = False

        try:
            while True:
                # Read frame.
                success, frame = self.video_capture.read()
                if not success:
                    print("Warning: Could not read frame from webcam.")
                    break

                # Increment frame count
                self.frame_count += 1

                # FPS calculation.
                self._update_fps()

                # Module 1: Draw ROI and counting line (skipped if headless)
                if not HEADLESS_MODE:
                    self._draw_door_roi(frame)
                    self._draw_counting_line(frame)

                # Module 2+3+7+9: Detection + tracking + Re-ID.
                detections = []
                if self.detector is not None:
                    if self.frame_count % PROCESS_EVERY_N_FRAMES == 0 or not self._last_detections:
                        detections = self.detector.detect(frame)
                        self._last_detections = detections
                    else:
                        detections = self._last_detections

                    if not HEADLESS_MODE:
                        self.detector.draw_boxes(frame, detections)

                # Module 10: 2FA Authentication Engine (Face Recognition + QR Scan & Keycard)
                if self.authenticator is not None and detections:
                    # 1. Pass frame and bounding box of tracked people to verify_face()
                    for det in detections:
                        is_matched, emp_name = self.authenticator.verify_face(frame, det.bbox)
                        if is_matched:
                            self.auth_states[det.track_id] = {
                                "status": "matched",
                                "name": emp_name,
                                "timestamp": time.time()
                            }
                            # Update controller so /admin portal generates QR code for this matched employee
                            if self.controller is not None:
                                self.controller.set_pending_face_match(emp_name)

                            # Auto-open Admin Portal in web browser (EXACTLY ONCE per face match event)
                            if not admin_portal_opened:
                                port = self.controller.port if self.controller else 5005
                                admin_url = f"http://localhost:{port}/admin"
                                print(f"[2FA Engine] 🌐 Face Matched ({emp_name})! Opening Admin Portal: {admin_url}")
                                webbrowser.open(admin_url)
                                admin_portal_opened = True

                    # Reset state flag when active 2FA sessions clear (timeout or QR verified)
                    if len(self.authenticator.active_sessions) == 0:
                        admin_portal_opened = False

                    # 2. Check for QR Code scan OR mobile keycard swipe from admin route
                    if self.authenticator.active_sessions:
                        # Option A: Direct QR code scan from camera stream
                        is_granted, qr_name = self.authenticator.scan_qr(frame)
                        
                        # Option B: Keycard swipe via Mobile Page (from Admin QR code)
                        if not is_granted and self.controller is not None:
                            with self.controller._lock:
                                for swipe_rec in list(self.controller._valid_swipes):
                                    swiped_name = swipe_rec.get("name")
                                    if swiped_name in self.authenticator.active_sessions:
                                        is_granted = True
                                        qr_name = swiped_name
                                        # Clear active session
                                        del self.authenticator.active_sessions[swiped_name]
                                        break

                        if is_granted:
                            # Update auth state for the corresponding employee
                            for tid, info in list(self.auth_states.items()):
                                if info.get("name") == qr_name:
                                    info["status"] = "granted"
                                    info["granted_time"] = time.time()
                                    break
                            else:
                                for tid, info in list(self.auth_states.items()):
                                    if info.get("status") == "matched":
                                        info["status"] = "granted"
                                        info["name"] = qr_name
                                        info["granted_time"] = time.time()
                                        break

                    # 3. Draw 2FA bounding box overlays (Yellow for Face Match, Green for QR Grant)
                    if not HEADLESS_MODE:
                        now = time.time()
                        for det in detections:
                            info = self.auth_states.get(det.track_id)
                            if info:
                                x1, y1, x2, y2 = map(int, det.bbox)
                                status = info.get("status")
                                name = info.get("name", "")

                                if status == "matched":
                                    if (now - info.get("timestamp", 0)) <= 5.0:
                                        # Yellow Bounding Box: FACE MATCHED: AWAITING QR...
                                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 3)
                                        cv2.putText(
                                            frame,
                                            f"FACE MATCHED: AWAITING QR... ({name})",
                                            (x1, max(25, y1 - 10)),
                                            cv2.FONT_HERSHEY_SIMPLEX,
                                            0.55,
                                            (0, 255, 255),
                                            2
                                        )
                                elif status == "granted":
                                    if (now - info.get("granted_time", now)) <= 3.0:
                                        # Green Bounding Box: 2FA ACCESS GRANTED
                                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
                                        cv2.putText(
                                            frame,
                                            f"ACCESS GRANTED: {name}",
                                            (x1, max(25, y1 - 10)),
                                            cv2.FONT_HERSHEY_SIMPLEX,
                                            0.55,
                                            (0, 255, 0),
                                            2
                                        )
                                    else:
                                        # Reset state for track_id so process starts from beginning (Face Scan)
                                        self.auth_states.pop(det.track_id, None)

                # Module 4+9: Tripwire crossing & Optical Flow
                if self.counter is not None:
                    crossing_events = self.counter.process_crossing(detections, frame)

                    # Module 5: Tailgate check — fires once per entry crossing.
                    if self.controller is not None:
                        entry_events = [
                            ev for ev in crossing_events if ev["direction"] == "entry"
                        ]
                        for event in entry_events:
                            # Identity binding: authorise using the 2FA session of the
                            # specific track that crossed, so one person's swipe cannot
                            # authorise somebody else walking through.
                            crossing_track = event["track_id"]
                            is_occluded = event.get("occluded", False)

                            if is_occluded:
                                # A person found hidden inside another's bounding
                                # box: no track, no face match, and they must not
                                # be able to consume the host's swipe.
                                authenticated_name = None
                            else:
                                auth_info = self.auth_states.get(crossing_track) or {}
                                authenticated_name = (
                                    auth_info.get("name")
                                    if auth_info.get("status") == "granted"
                                    else None
                                )

                            # Returns dict: {"status":"authorized"|"tailgate", ...}
                            result = self.controller.check_for_tailgate(
                                authenticated_name=authenticated_name,
                                allow_card_only=not is_occluded,
                            )

                            if result["status"] == "tailgate":
                                # Trigger non-blocking audio alarm chime
                                trigger_breach_alarm()

                                cause = (
                                    f"Hidden person inside box of ID {crossing_track}"
                                    if is_occluded
                                    else f"Track ID {crossing_track} unverified"
                                )
                                host = result.get("host_employee")
                                if host:
                                    print(
                                        f"🚨 TAILGATE DETECTED 🚨 | {cause} | "
                                        f"Probable host: {host['name']} "
                                        f"({host['employee_id']})"
                                    )
                                else:
                                    print(
                                        f"🚨 TAILGATE DETECTED 🚨 | {cause} | "
                                        f"No prior swipe on record"
                                    )

                                # Module 6+8: Capture and log the tailgate event
                                os.makedirs(self.screenshot_dir, exist_ok=True)
                                timestamp_filename = f"{int(time.time())}.jpg"
                                saved_image_path = os.path.join(self.screenshot_dir, timestamp_filename)

                                # Module 8: Anonymise faces before persisting evidence
                                evidence_frame = self._blur_faces(frame)

                                if cv2.imwrite(saved_image_path, evidence_frame):
                                    print(f"[WebcamCapture] Saved evidence screenshot: {saved_image_path}")
                                else:
                                    print(f"[WebcamCapture] Error saving screenshot to: {saved_image_path}")

                                # Log event to database
                                # Store image_path relative to workspace root (e.g., 'screenshots/1723000000.jpg')
                                db_image_path = f"screenshots/{timestamp_filename}"
                                self.db.log_event(
                                    'Tailgate Detected (Occluded)' if is_occluded
                                    else 'Tailgate Detected',
                                    db_image_path,
                                )
                            else:
                                emp = result.get("employee", {})
                                print(
                                    f"✅ Authorised Entry | "
                                    f"{emp.get('name', 'Unknown')} "
                                    f"({emp.get('employee_id', 'N/A')})"
                                )
                                # Log authorized entry in SQLite database for reporting
                                self.db.log_event(f"Authorized Entry: {emp.get('name', 'Unknown')}", "")

                    # Draw tripwire line + IN/OUT overlay (skipped if headless)
                    if not HEADLESS_MODE:
                        self.counter.draw_tripwire(frame)

                # Module 9: Draw homography top-down mini-radar overlay (skipped if headless)
                if not HEADLESS_MODE:
                    self._draw_radar_map(frame, detections)

                # Module 1: FPS overlay (drawn last — always on top, skipped if headless)
                if not HEADLESS_MODE:
                    self._draw_fps(frame)

                # Display frame (skipped if headless)
                if not HEADLESS_MODE:
                    cv2.imshow(self.window_title, frame)

                # Keyboard controls & loop pacing
                if not HEADLESS_MODE:
                    key = cv2.waitKey(1) & 0xFF
                    if key in {ord("q"), ord("Q")}:
                        break
                    if key in {ord("s"), ord("S")}:
                        self._save_screenshot(frame)
                else:
                    time.sleep(0.005)

        except KeyboardInterrupt:
            print("\n[WebcamCapture] 🛑 Keyboard interrupt received. Shutting down system gracefully...")
        finally:
            self._cleanup()

    # ──────────────────────────────────────────────────────────────────────────
    def _update_fps(self):
        current = time.time()
        elapsed = current - self.previous_timestamp
        self.fps = 1.0 / elapsed if elapsed > 0 else 0.0
        self.previous_timestamp = current

    # ──────────────────────────────────────────────────────────────────────────
    def _draw_counting_line(self, frame):
        """Draw the vertical counting line at COUNTING_LINE_POSITION."""
        h, w     = frame.shape[:2]
        line_x   = max(0, min(int(w * COUNTING_LINE_POSITION), w - 1))
        cv2.line(
            frame, (line_x, 0), (line_x, h),
            COUNTING_LINE_COLOR, COUNTING_LINE_THICKNESS, lineType=cv2.LINE_AA,
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _draw_door_roi(self, frame):
        """Draw a labelled rectangular door region of interest."""
        h, w = frame.shape[:2]
        x1 = max(0, min(int(w * DOOR_ROI_TOP_LEFT[0]), w - 1))
        y1 = max(0, min(int(h * DOOR_ROI_TOP_LEFT[1]), h - 1))
        x2 = max(0, min(x1 + int(w * DOOR_ROI_SIZE[0]), w - 1))
        y2 = max(0, min(y1 + int(h * DOOR_ROI_SIZE[1]), h - 1))

        cv2.rectangle(
            frame, (x1, y1), (x2, y2),
            DOOR_ROI_COLOR, DOOR_ROI_THICKNESS, lineType=cv2.LINE_AA,
        )
        cv2.putText(
            frame, DOOR_LABEL_TEXT,
            (x1, max(y1 - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            DOOR_LABEL_FONT_SCALE,
            DOOR_LABEL_COLOR,
            DOOR_LABEL_THICKNESS,
            lineType=cv2.LINE_AA,
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _draw_fps(self, frame):
        """Draw FPS counter in the top-left corner."""
        text = f"FPS: {self.fps:.1f}"
        cv2.putText(
            frame, text, (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3, cv2.LINE_AA,
        )
        cv2.putText(
            frame, text, (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA,
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _save_screenshot(self, frame):
        """Save the current frame as a timestamped PNG."""
        filename = datetime.now().strftime(SCREENSHOT_FILENAME_FORMAT)
        path     = os.path.join(self.screenshot_dir, filename)
        if cv2.imwrite(path, frame):
            print(f"Saved screenshot: {path}")
        else:
            print(f"Failed to save screenshot: {path}")

    # ──────────────────────────────────────────────────────────────────────────
    def _cleanup(self):
        """Release the webcam, close display windows, and join daemon threads."""
        print("[WebcamCapture] Initiating resource cleanup...")
        if self.video_capture is not None:
            self.video_capture.release()
        if not HEADLESS_MODE:
            cv2.destroyAllWindows()

        # Join Flask threads with a short timeout to prevent application hang
        if self.dashboard_thread is not None:
            print("[WebcamCapture] Joining dashboard server thread...")
            self.dashboard_thread.join(timeout=0.5)

        if self.controller is not None and hasattr(self.controller, 'server_thread') and self.controller.server_thread:
            print("[WebcamCapture] Joining access controller server thread...")
            self.controller.server_thread.join(timeout=0.5)

        print("[WebcamCapture] Cleanup completed successfully.")
