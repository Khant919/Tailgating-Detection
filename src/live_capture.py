"""
Module 1 + 2 + 3 + 4 + 5: Live webcam capture wrapper and display loop.

Per-frame pipeline order:
    read frame
        → draw Door ROI                          (Module 1)
        → draw counting line                     (Module 1)
        → detector.detect(frame)                 (Module 2+3)
        → detector.draw_boxes(frame, dets)       (Module 2+3)
        → counter.process_crossing(detections)   (Module 4)
        → [entry_count increased?]               (Module 5)
          controller.check_for_tailgate()        (Module 5)
        → counter.draw_tripwire(frame)           (Module 4)
        → draw FPS overlay                       (Module 1)
        → imshow
"""

import os
import time
from datetime import datetime

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
)


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

        # Window title reflects active modules.
        if detector and counter and controller:
            self.window_title = "Tailgating Detection - Module 1+2+3+4+5 (Press 'q' to quit)"
        elif detector and counter:
            self.window_title = "Tailgating Detection - Module 1+2+3+4 (Press 'q' to quit)"
        elif detector:
            self.window_title = "Tailgating Detection - Module 1+2+3 (Press 'q' to quit)"
        else:
            self.window_title = "Tailgating Detection - Module 1 only (Press 'q' to quit)"

        self.video_capture      = None
        self.previous_timestamp = None
        self.fps                = 0.0
        self.screenshot_dir     = SCREENSHOT_DIR
        os.makedirs(self.screenshot_dir, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    def start(self):
        """Open the webcam and run the main frame loop."""
        self.video_capture = cv2.VideoCapture(self.camera_index)

        if not self.video_capture.isOpened():
            print(f"Error: Could not open webcam at index {self.camera_index}.")
            print("Please check that your camera is connected and try again.")
            return

        self.previous_timestamp = time.time()
        print("Press 'q' to quit and 's' to save the current frame.")

        try:
            while True:
                # Read frame.
                success, frame = self.video_capture.read()
                if not success:
                    print("Warning: Could not read frame from webcam.")
                    break

                # FPS calculation.
                self._update_fps()

                # Module 1: Draw ROI and counting line.
                self._draw_door_roi(frame)
                self._draw_counting_line(frame)

                # Module 2+3: Detection + tracking.
                detections = []
                if self.detector is not None:
                    detections = self.detector.detect(frame)
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
                            else:
                                emp = result.get("employee", {})
                                print(
                                    f"✅ Authorised Entry | "
                                    f"{emp.get('name', 'Unknown')} "
                                    f"({emp.get('employee_id', 'N/A')})"
                                )

                    # Keep entry count in sync.
                    self._prev_entry_count = self.counter.entry_count

                    # Draw tripwire line + IN/OUT overlay.
                    self.counter.draw_tripwire(frame)

                # Module 1: FPS overlay (drawn last — always on top).
                self._draw_fps(frame)

                # Display frame.
                cv2.imshow(self.window_title, frame)

                # Keyboard controls.
                key = cv2.waitKey(1) & 0xFF
                if key in {ord("q"), ord("Q")}:
                    break
                if key in {ord("s"), ord("S")}:
                    self._save_screenshot(frame)

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
        """Release the webcam and close display windows."""
        if self.video_capture is not None:
            self.video_capture.release()
        cv2.destroyAllWindows()
