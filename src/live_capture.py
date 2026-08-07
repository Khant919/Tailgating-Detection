"""
Module 1 + 2 + 3 + 4 + 5 + 6 + 7: Optimized Live Webcam Capture & Security UI loop.
==================================================================================
Per-frame pipeline order:
    read frame
        → draw Door ROI                          (Module 1, skipped if headless)
        → draw counting line                     (Module 1, skipped if headless)
        → detector.detect(frame)                 (Module 2+3, run every N frames)
        → detector.draw_boxes(frame, dets)       (Module 2+3, skipped if headless)
        → counter.process_crossing(detections)   (Module 4)
        → [entry_count increased?]               (Module 5)
          controller.check_for_tailgate()        (Module 5)
            → save frame as Unix timestamp.jpg   (Module 6)
            → log to SQLite database             (Module 6)
        → counter.draw_tripwire(frame)           (Module 4, skipped if headless)
        → draw FPS overlay                       (Module 1, skipped if headless)
        → imshow/waitKey                         (Module 1, skipped if headless)
"""

import os
import time
from datetime import datetime
import threading

import cv2

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
)

from src.database import DatabaseManager
from src.dashboard import run_dashboard_server


class WebcamCapture:
    """A clean object-oriented wrapper for webcam capture and display."""

    def __init__(
        self,
        camera_index: int = DEFAULT_CAMERA_INDEX,
        detector=None,
        counter=None,
        controller=None,
    ):
        """
        Args:
            camera_index: Webcam index (default 0).
            detector:     Optional PersonDetector (Module 2+3).
            counter:      Optional TripwireCounter (Module 4).
            controller:   Optional AccessController (Module 5).
                          Requires counter to also be set.
        """
        self.camera_index = camera_index
        self.detector     = detector
        self.counter      = counter
        self.controller   = controller

        # Tracks previous entry_count so we detect new entries each frame.
        self._prev_entry_count: int = 0

        # Module 7: Performance optimization variables
        self.frame_count: int = 0
        self._last_detections = []

        # Window title reflects active modules.
        if detector and counter and controller:
            self.window_title = "Tailgating Detection - Module 1-7 (Press 'q' to quit)"
        elif detector and counter:
            self.window_title = "Tailgating Detection - Module 1-4 (Press 'q' to quit)"
        elif detector:
            self.window_title = "Tailgating Detection - Module 1-3 (Press 'q' to quit)"
        else:
            self.window_title = "Tailgating Detection - Module 1 only (Press 'q' to quit)"

        self.video_capture      = None
        self.previous_timestamp = None
        self.fps                = 0.0
        self.screenshot_dir     = SCREENSHOT_DIR
        os.makedirs(self.screenshot_dir, exist_ok=True)

        # Module 6: Persistent Audit Trail Database Manager
        self.db = DatabaseManager()

        self.dashboard_thread = None

    # ──────────────────────────────────────────────────────────────────────────
    def start(self):
        """Open the webcam and run the main frame loop."""
        self.video_capture = cv2.VideoCapture(self.camera_index)

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

                # Module 2+3+7: Detection + tracking.
                # Runs YOLO detector on every N-th frame to save CPU load.
                detections = []
                if self.detector is not None:
                    if self.frame_count % PROCESS_EVERY_N_FRAMES == 0 or not self._last_detections:
                        detections = self.detector.detect(frame)
                        self._last_detections = detections
                    else:
                        detections = self._last_detections

                    if not HEADLESS_MODE:
                        self.detector.draw_boxes(frame, detections)

                # Module 4: Tripwire crossing.
                if self.counter is not None:
                    self.counter.process_crossing(detections)

                    # Module 5: Tailgate check — fires once per new entry.
                    if self.controller is not None:
                        new_entries = (
                            self.counter.entry_count - self._prev_entry_count
                        )
                        for _ in range(new_entries):
                            # Returns dict: {"status":"authorized"|"tailgate", ...}
                            result = self.controller.check_for_tailgate()

                            if result["status"] == "tailgate":
                                host = result.get("host_employee")
                                if host:
                                    print(
                                        f"🚨 TAILGATE DETECTED 🚨 | "
                                        f"Probable host: {host['name']} "
                                        f"({host['employee_id']})"
                                    )
                                else:
                                    print(
                                        "🚨 TAILGATE DETECTED 🚨 | "
                                        "No prior swipe on record"
                                    )

                                # Module 6: Capture and log the tailgate event
                                os.makedirs(self.screenshot_dir, exist_ok=True)
                                timestamp_filename = f"{int(time.time())}.jpg"
                                saved_image_path = os.path.join(self.screenshot_dir, timestamp_filename)

                                if cv2.imwrite(saved_image_path, frame):
                                    print(f"[WebcamCapture] Saved evidence screenshot: {saved_image_path}")
                                else:
                                    print(f"[WebcamCapture] Error saving screenshot to: {saved_image_path}")

                                # Log event to database
                                # Store image_path relative to workspace root (e.g., 'screenshots/1723000000.jpg')
                                db_image_path = f"screenshots/{timestamp_filename}"
                                self.db.log_event('Tailgate Detected', db_image_path)
                            else:
                                emp = result.get("employee", {})
                                print(
                                    f"✅ Authorised Entry | "
                                    f"{emp.get('name', 'Unknown')} "
                                    f"({emp.get('employee_id', 'N/A')})"
                                )

                    # Keep entry count in sync.
                    self._prev_entry_count = self.counter.entry_count

                    # Draw tripwire line + IN/OUT overlay (skipped if headless)
                    if not HEADLESS_MODE:
                        self.counter.draw_tripwire(frame)

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
                    # In headless mode, waitKey is not used. Sleep briefly to yield CPU time.
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
