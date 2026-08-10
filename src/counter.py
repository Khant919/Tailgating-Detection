"""
Module 4 + 7 + 9: Directional Counting — Virtual Tripwire & Optical Flow Occlusion Recovery
=============================================================================================
Provides TripwireCounter which draws a horizontal virtual line across the
frame and counts people as their box-centre crosses it in either direction.
Includes Lucas-Kanade optical flow tracking to detect independent velocity vectors
indicative of overlapping tailgaters (occlusion resolution).
"""

import cv2
import numpy as np

from config import (
    COUNTER_ENTRY_COLOR,
    COUNTER_EXIT_COLOR,
    COUNTER_FONT_SCALE,
    COUNTER_FONT_THICKNESS,
    COUNTER_LINE_SPACING,
    COUNTER_PADDING_RIGHT,
    COUNTER_PADDING_TOP,
    TRIPWIRE_COLOR_DEFAULT,
    TRIPWIRE_COLOR_ENTRY,
    TRIPWIRE_COLOR_EXIT,
    TRIPWIRE_END,
    TRIPWIRE_FLASH_FRAMES,
    TRIPWIRE_START,
    TRIPWIRE_THICKNESS,
    MAX_SINGLE_PERSON_AREA,
    OPTICAL_FLOW_SPLIT_THRESHOLD,
)


class TripwireCounter:
    """
    Counts people crossing a horizontal virtual tripwire and uses
    optical flow to detect hidden tailgating occlusions inside overlapping boxes.
    """

    def __init__(
        self,
        tripwire_start: tuple[int, int] = TRIPWIRE_START,
        tripwire_end:   tuple[int, int] = TRIPWIRE_END,
    ):
        self.tripwire_start: tuple[int, int] = tripwire_start
        self.tripwire_end:   tuple[int, int] = tripwire_end
        self.tripwire_y:     int             = tripwire_start[1]

        # Counters
        self.entry_count: int = 0
        self.exit_count:  int = 0

        # Per-track state
        self.track_history: dict[int, tuple[int, int]] = {}
        self.crossed_ids: dict[int, str] = {}

        # Flash state
        self._flash_event:       str | None = None
        self._flash_frames_left: int        = 0

        # Module 9: Optical Flow tracking state
        self._prev_gray = None
        self._flow_pts = None

    def _calculate_iou(self, box1: tuple[int, int, int, int], box2: tuple[int, int, int, int]) -> float:
        """Helper to calculate the Intersection over Union (IoU) of two boxes."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        x_left = max(x1_1, x1_2)
        y_top = max(y1_1, y1_2)
        x_right = min(x2_1, x2_2)
        y_bottom = min(y2_1, y2_2)
        
        if x_right < x_left or y_bottom < y_top:
            return 0.0
            
        intersection_area = (x_right - x_left) * (y_bottom - y_top)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = float(area1 + area2 - intersection_area)
        
        if union_area == 0:
            return 0.0
            
        return intersection_area / union_area

    def process_crossing(self, detections, frame=None) -> None:
        """
        Analyse tracked detections, check for crossings, and run optical flow
        occlusion recovery if overlaps are detected.
        """
        # Run crossing updates
        for det in detections:
            track_id = det.track_id

            if track_id < 0:
                continue

            x1, y1, x2, y2 = det.bbox
            curr_cx: int = (x1 + x2) // 2
            curr_cy: int = (y1 + y2) // 2   # True centre

            # Occlusion Check: Flag if bounding box area suddenly exceeds a normal single-person area
            box_area = (x2 - x1) * (y2 - y1)
            if box_area > MAX_SINGLE_PERSON_AREA:
                print(
                    f"[TripwireCounter] ⚠️ WARNING: Potential Merged Box / Occlusion Detected! "
                    f"ID: {track_id} | Area: {box_area} px (Threshold: {MAX_SINGLE_PERSON_AREA} px)"
                )

            if track_id not in self.track_history:
                self.track_history[track_id] = (curr_cx, curr_cy)
                continue

            _, prev_cy = self.track_history[track_id]

            prev_above = prev_cy  < self.tripwire_y
            curr_below = curr_cy >= self.tripwire_y
            prev_below = prev_cy  > self.tripwire_y
            curr_above = curr_cy <= self.tripwire_y

            # ENTRY: centre crossed downward
            if prev_above and curr_below:
                if self.crossed_ids.get(track_id) != "entry":
                    self.entry_count += 1
                    self.crossed_ids[track_id] = "entry"
                    self._trigger_flash("entry")
                    print(
                        f"[TripwireCounter] ENTRY  | ID {track_id:>3} | "
                        f"center_y {prev_cy} → {curr_cy} | "
                        f"IN={self.entry_count}  OUT={self.exit_count}"
                    )

            # EXIT: centre crossed upward
            elif prev_below and curr_above:
                if self.crossed_ids.get(track_id) != "exit":
                    self.exit_count += 1
                    self.crossed_ids[track_id] = "exit"
                    self._trigger_flash("exit")
                    print(
                        f"[TripwireCounter] EXIT   | ID {track_id:>3} | "
                        f"center_y {prev_cy} → {curr_cy} | "
                        f"IN={self.entry_count}  OUT={self.exit_count}"
                    )

            else:
                last = self.crossed_ids.get(track_id)
                if last == "entry" and prev_above:
                    del self.crossed_ids[track_id]
                elif last == "exit" and prev_below:
                    del self.crossed_ids[track_id]

            self.track_history[track_id] = (curr_cx, curr_cy)

        # Module 9: Optical Flow Occlusion Recovery
        if frame is not None:
            self._process_optical_flow(frame, detections)

    def _process_optical_flow(self, frame: np.ndarray, detections) -> None:
        """Runs Lucas-Kanade optical flow inside highly overlapping bounding boxes."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Identify overlapping box regions (IoU > 0.5)
        overlap_regions = []
        for i in range(len(detections)):
            for j in range(i + 1, len(detections)):
                box1 = detections[i].bbox
                box2 = detections[j].bbox
                if self._calculate_iou(box1, box2) > 0.5:
                    # Capture overlap box dimensions
                    ox1 = max(box1[0], box2[0])
                    oy1 = max(box1[1], box2[1])
                    ox2 = min(box1[2], box2[2])
                    oy2 = min(box1[3], box2[3])
                    if ox2 > ox1 and oy2 > oy1:
                        overlap_regions.append((ox1, oy1, ox2, oy2))

        # Check for large single boxes as backup
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            if (x2 - x1) * (y2 - y1) > MAX_SINGLE_PERSON_AREA:
                overlap_regions.append((x1, y1, x2, y2))

        # If no overlapping/occluded zones, clear points and update frame state
        if not overlap_regions:
            self._flow_pts = None
            self._prev_gray = gray.copy()
            return

        # 2. Track points if we have active points from previous frame
        if self._flow_pts is not None and self._prev_gray is not None:
            p1, st, err = cv2.calcOpticalFlowPyrLK(
                self._prev_gray, gray, self._flow_pts, None,
                winSize=(15, 15), maxLevel=2,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
            )
            
            # Filter successfully tracked points
            if p1 is not None:
                good_new = p1[st == 1]
                good_old = self._flow_pts[st == 1]
                
                if len(good_new) >= 6:
                    # Calculate vector displacements
                    dx = good_new[:, 0] - good_old[:, 0]
                    
                    # Split points into two groups based on direction of movement (dx)
                    group1_dx = dx[dx > 0]
                    group2_dx = dx[dx <= 0]
                    
                    if len(group1_dx) >= 3 and len(group2_dx) >= 3:
                        mean_g1 = np.mean(group1_dx)
                        mean_g2 = np.mean(group2_dx)
                        # If velocities diverge by more than the threshold, it indicates multiple people moving independently
                        if abs(mean_g1 - mean_g2) > OPTICAL_FLOW_SPLIT_THRESHOLD:
                            print(
                                f"[TripwireCounter] ⚠️ WARNING: Optical Flow indicates active tailgating "
                                f"occlusion inside bounding box! (Velocity Split: {abs(mean_g1 - mean_g2):.2f} px/f)"
                            )
                
                self._flow_pts = good_new.reshape(-1, 1, 2)
            else:
                self._flow_pts = None
        else:
            # 3. Initialize points inside the occluded region (Shi-Tomasi corner detection)
            mask = np.zeros_like(gray)
            for (ox1, oy1, ox2, oy2) in overlap_regions:
                # Add margin inside
                margin_x = int((ox2 - ox1) * 0.1)
                margin_y = int((oy2 - oy1) * 0.1)
                cv2.rectangle(
                    mask, 
                    (ox1 + margin_x, oy1 + margin_y), 
                    (ox2 - margin_x, oy2 - margin_y), 
                    255, -1
                )
                
            p0 = cv2.goodFeaturesToTrack(gray, maxCorners=30, qualityLevel=0.01, minDistance=5, mask=mask)
            if p0 is not None:
                self._flow_pts = p0
                
        self._prev_gray = gray.copy()

    def draw_tripwire(self, frame) -> None:
        """Draw the tripwire line and IN/OUT counter overlay onto frame in-place."""
        if self._flash_frames_left > 0:
            line_color = (
                TRIPWIRE_COLOR_ENTRY if self._flash_event == "entry"
                else TRIPWIRE_COLOR_EXIT
            )
            self._flash_frames_left -= 1
        else:
            line_color = TRIPWIRE_COLOR_DEFAULT

        cv2.line(
            frame,
            self.tripwire_start,
            self.tripwire_end,
            line_color,
            TRIPWIRE_THICKNESS,
            lineType=cv2.LINE_AA,
        )

        label_y = max(self.tripwire_start[1] - 8, 15)
        cv2.putText(
            frame, "TRIPWIRE",
            (self.tripwire_start[0], label_y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, line_color, 1, cv2.LINE_AA,
        )

        self._draw_counter_overlay(frame)

    def _draw_counter_overlay(self, frame) -> None:
        """Render right-aligned IN / OUT counters in the top-right corner."""
        _, frame_w = frame.shape[:2]

        lines = [
            (f"IN:  {self.entry_count}", COUNTER_ENTRY_COLOR),
            (f"OUT: {self.exit_count}",  COUNTER_EXIT_COLOR),
        ]

        for i, (text, color) in enumerate(lines):
            (text_w, _), _ = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX,
                COUNTER_FONT_SCALE, COUNTER_FONT_THICKNESS,
            )
            x = frame_w - text_w - COUNTER_PADDING_RIGHT
            y = COUNTER_PADDING_TOP + i * COUNTER_LINE_SPACING

            cv2.putText(
                frame, text, (x + 1, y + 1),
                cv2.FONT_HERSHEY_SIMPLEX, COUNTER_FONT_SCALE,
                (0, 0, 0), COUNTER_FONT_THICKNESS + 1, cv2.LINE_AA,
            )
            cv2.putText(
                frame, text, (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, COUNTER_FONT_SCALE,
                color, COUNTER_FONT_THICKNESS, cv2.LINE_AA,
            )

    def _trigger_flash(self, event: str) -> None:
        self._flash_event       = event
        self._flash_frames_left = TRIPWIRE_FLASH_FRAMES

    def reset(self) -> None:
        self.entry_count        = 0
        self.exit_count         = 0
        self.track_history.clear()
        self.crossed_ids.clear()
        self._flash_event       = None
        self._flash_frames_left = 0
        self._flow_pts          = None
        self._prev_gray         = None
