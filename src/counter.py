"""
Module 4 + 7 + 9: Directional Counting — Virtual Tripwire & Optical Flow Occlusion Recovery
=============================================================================================
Provides TripwireCounter which draws a horizontal virtual line across the
frame and counts people as their box-centre crosses it in either direction.
Includes Lucas-Kanade optical flow tracking to detect independent velocity vectors
indicative of overlapping tailgaters (occlusion resolution).
"""

from collections import deque

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
    TRIPWIRE_X_END_RATIO,
    TRIPWIRE_X_START_RATIO,
    TRIPWIRE_Y_RATIO,
    MAX_SINGLE_PERSON_AREA,
    MAX_SINGLE_PERSON_AREA_RATIO,
    MAX_OCCUPANCY_PER_BOX,
    MIN_OCCLUSION_FRAMES,
    OCCLUSION_ASPECT_MULTIPLIER,
    OCCLUSION_MEMORY_FRAMES,
    OPTICAL_FLOW_SPLIT_THRESHOLD,
    SINGLE_PERSON_ASPECT_RATIO,
)


class TripwireCounter:
    """
    Counts people crossing a horizontal virtual tripwire and uses
    optical flow to detect hidden tailgating occlusions inside overlapping boxes.
    """

    def __init__(
        self,
        tripwire_start: tuple[int, int] | None = None,
        tripwire_end:   tuple[int, int] | None = None,
    ):
        """
        Args:
            tripwire_start: Explicit (x, y) start of the line. When omitted the
                line is positioned from frame-relative ratios on the first frame,
                so the same config works on 480p, 720p and 1080p cameras.
            tripwire_end: Explicit (x, y) end of the line.

        Passing either argument pins the line to those exact pixels and disables
        the automatic rescaling.
        """
        self._auto_scale: bool = tripwire_start is None and tripwire_end is None
        self._frame_size: tuple[int, int] | None = None

        tripwire_start = tripwire_start or TRIPWIRE_START
        tripwire_end   = tripwire_end   or TRIPWIRE_END

        self.tripwire_start: tuple[int, int] = tripwire_start
        self.tripwire_end:   tuple[int, int] = tripwire_end
        self.tripwire_y:     int             = tripwire_start[1]

        # Occlusion threshold in pixels; rescaled once the frame size is known.
        self.max_person_area: int = MAX_SINGLE_PERSON_AREA

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

        # Rolling per-track occupancy estimates: track_id -> deque of ints.
        self._occupancy_history: dict[int, deque] = {}

        # Tracks that were flagged as carrying a hidden second person.
        self.occluded_entries: int = 0

    def configure_for_frame(self, width: int, height: int) -> None:
        """
        Rescale the tripwire and the occlusion threshold to the real frame size.

        Called automatically on the first frame (and again if the resolution
        changes). No-op when explicit pixel coordinates were supplied.
        """
        if self._frame_size == (width, height):
            return
        self._frame_size = (width, height)

        # The occlusion threshold is always frame-relative, even with a pinned line.
        self.max_person_area = int(width * height * MAX_SINGLE_PERSON_AREA_RATIO)

        if not self._auto_scale:
            return

        y = int(height * TRIPWIRE_Y_RATIO)
        self.tripwire_start = (int(width * TRIPWIRE_X_START_RATIO), y)
        self.tripwire_end   = (int(width * TRIPWIRE_X_END_RATIO), y)
        self.tripwire_y     = y

        print(
            f"[TripwireCounter] Calibrated for {width}x{height} | "
            f"line y={y} | occlusion threshold={self.max_person_area} px"
        )

    def estimate_box_occupancy(self, bbox: tuple[int, int, int, int], flow_split: bool = False) -> int:
        """
        Estimate how many people are inside a single bounding box.

        Two people walking shoulder-to-shoulder are frequently detected as one
        box. Counting that box as one entry is the classic way a tailgater slips
        through, so the box shape is inspected for evidence of a merge.

        Width-to-height ratio is the primary signal because it is scale
        invariant — someone standing twice as close grows in both dimensions, so
        the ratio is unchanged, whereas raw pixel area is not comparable between
        near and far people. Area and optical-flow divergence act as supporting
        evidence only; neither can raise the estimate on its own beyond two.

        Args:
            bbox: (x1, y1, x2, y2) of the detection.
            flow_split: True when optical flow found two diverging motion
                clusters inside this box.

        Returns:
            Estimated number of people, at least 1.
        """
        x1, y1, x2, y2 = bbox
        width  = max(0, x2 - x1)
        height = max(0, y2 - y1)

        if width == 0 or height == 0:
            return 1

        aspect = width / height
        merge_aspect = SINGLE_PERSON_ASPECT_RATIO * OCCLUSION_ASPECT_MULTIPLIER

        occupancy = 1
        # In upper-body/webcam framing (box extends to bottom of frame), a single person's
        # head+shoulders naturally has aspect ratio ~0.8-1.2. Two people abreast will have aspect >= 1.6.
        is_upper_body_crop = bool(self._frame_size and y2 >= int(self._frame_size[1] * 0.85))
        if is_upper_body_crop:
            if aspect >= 1.6:
                occupancy = round(aspect / 0.9)
        else:
            if aspect >= merge_aspect:
                # How many single-person widths fit across this box for full-body view
                occupancy = round(aspect / SINGLE_PERSON_ASPECT_RATIO)

        # Supporting evidence: optical flow split confirms two independent diverging bodies
        if flow_split:
            occupancy = max(occupancy, 2)

        return max(1, min(occupancy, MAX_OCCUPANCY_PER_BOX))

    def _record_occupancy(self, track_id: int, occupancy: int) -> None:
        """Append this frame's estimate to the track's rolling window."""
        history = self._occupancy_history.get(track_id)
        if history is None:
            history = deque(maxlen=OCCLUSION_MEMORY_FRAMES)
            self._occupancy_history[track_id] = history
        history.append(occupancy)

    def _settled_occupancy(self, track_id: int) -> int:
        """
        Resolve the rolling window into the occupancy used for counting.

        A merge must be visible in several frames before it inflates the count,
        so a single noisy detection cannot manufacture a phantom person.
        """
        history = self._occupancy_history.get(track_id)
        if not history:
            return 1

        merged_frames = sum(1 for value in history if value >= 2)
        if merged_frames < MIN_OCCLUSION_FRAMES:
            return 1

        return max(history)

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

    def process_crossing(self, detections, frame=None) -> list[dict]:
        """
        Analyse tracked detections, check for crossings, and run optical flow
        occlusion recovery if overlaps are detected.

        Returns:
            A list of crossing events in the order they occurred, each shaped
            {"track_id": int, "direction": "entry" | "exit"}. Callers need the
            track_id — not just a count — to tell *which* tracked person crossed,
            so an entry can be matched against that person's own authentication.
        """
        events: list[dict] = []

        # Rescale the line to this camera's resolution before evaluating crossings.
        if frame is not None:
            h, w = frame.shape[:2]
            self.configure_for_frame(w, h)

        # Occlusion analysis must run BEFORE the crossing loop: a merged box that
        # crosses this frame has to be resolved into a headcount now, otherwise
        # the hidden person is already through the door uncounted.
        flow_splits = self._process_optical_flow(frame, detections) if frame is not None else {}

        for det in detections:
            if det.track_id >= 0:
                self._record_occupancy(
                    det.track_id,
                    self.estimate_box_occupancy(det.bbox, flow_splits.get(det.track_id, False)),
                )

        # Run crossing updates
        for det in detections:
            track_id = det.track_id

            if track_id < 0:
                continue

            x1, y1, x2, y2 = det.bbox
            curr_cx: int = (x1 + x2) // 2
            curr_cy: int = (y1 + y2) // 2   # True centre

            if track_id not in self.track_history:
                self.track_history[track_id] = (curr_cx, curr_cy, y1, y2)
                continue

            prev_entry = self.track_history[track_id]
            # REFERENCE POINTS FOR CROSSING:
            # Evaluates upper torso / head level (y1 + 0.25 * height) and body centroid (cy)
            # This ensures both full-body walking and sitting webcam head down/up trigger reliably.
            prev_cx, prev_cy, prev_y1, prev_y2 = prev_entry if len(prev_entry) == 4 else (prev_entry[0], prev_entry[1], prev_entry[1], prev_entry[1])
            
            curr_upper = y1 + int(0.25 * (y2 - y1))
            prev_upper = prev_y1 + int(0.25 * (prev_y2 - prev_y1))
            
            curr_center = curr_cy
            prev_center = prev_cy

            deadband = 10
            upper_limit = self.tripwire_y - deadband
            lower_limit = self.tripwire_y + deadband

            # Downward Crossing (ENTRY / IN):
            # 1. Head/upper body lowers past tripwire line
            head_down = (prev_upper < self.tripwire_y and curr_upper >= self.tripwire_y)
            # 2. Body traversal crossing completely from upper zone to lower zone past deadband
            center_down = (prev_center < upper_limit and curr_center >= lower_limit)
            is_entry = head_down or center_down

            # Upward Crossing (EXIT / OUT):
            # 1. Head/upper body rises above tripwire line
            head_up = (prev_upper > self.tripwire_y and curr_upper <= self.tripwire_y)
            # 2. Body traversal crossing completely from lower zone to upper zone past deadband
            center_up = (prev_center > lower_limit and curr_center <= upper_limit)
            is_exit = head_up or center_up

            # ENTRY: crossed downward
            if is_entry and self.crossed_ids.get(track_id) != "entry":
                occupancy = self._settled_occupancy(track_id)

                self.entry_count += occupancy
                self.crossed_ids[track_id] = "entry"
                self._trigger_flash("entry")

                events.append({
                    "track_id": track_id,
                    "direction": "entry",
                    "occluded": False,
                })
                print(
                    f"[TripwireCounter] ENTRY  | ID {track_id:>3} | "
                    f"crossing (center: {prev_center} → {curr_center}, upper: {prev_upper} → {curr_upper}) | "
                    f"IN={self.entry_count}  OUT={self.exit_count}"
                )

                for _ in range(occupancy - 1):
                    self.occluded_entries += 1
                    events.append({
                        "track_id": track_id,
                        "direction": "entry",
                        "occluded": True,
                    })
                    print(
                        f"[TripwireCounter] 🚨 OCCLUDED ENTRY | hidden person inside "
                        f"box of ID {track_id} | IN={self.entry_count}"
                    )

            # EXIT: crossed upward
            elif is_exit and self.crossed_ids.get(track_id) != "exit":
                self.exit_count += 1
                self.crossed_ids[track_id] = "exit"
                self._trigger_flash("exit")
                events.append({
                    "track_id": track_id,
                    "direction": "exit",
                    "occluded": False,
                })
                print(
                    f"[TripwireCounter] EXIT   | ID {track_id:>3} | "
                    f"crossing (center: {prev_center} → {curr_center}, upper: {prev_upper} → {curr_upper}) | "
                    f"IN={self.entry_count}  OUT={self.exit_count}"
                )

            self.track_history[track_id] = (curr_cx, curr_cy, y1, y2)

        return events

    @staticmethod
    def _has_velocity_split(dx: np.ndarray) -> bool:
        """
        Decide whether horizontal point velocities form two diverging clusters.

        Points are sorted and split at their single largest gap rather than at
        zero. Splitting at zero would classify ordinary measurement noise around
        a stationary mean as "two people moving apart"; splitting at the widest
        gap only separates genuinely bimodal motion.
        """
        if len(dx) < 6:
            return False

        ordered = np.sort(dx)
        gaps = np.diff(ordered)
        if len(gaps) == 0:
            return False

        split_at = int(np.argmax(gaps)) + 1
        left, right = ordered[:split_at], ordered[split_at:]

        if len(left) < 3 or len(right) < 3:
            return False

        return abs(float(np.mean(right)) - float(np.mean(left))) > OPTICAL_FLOW_SPLIT_THRESHOLD

    def _process_optical_flow(self, frame: np.ndarray, detections) -> dict[int, bool]:
        """
        Run Lucas-Kanade optical flow inside merge-candidate boxes.

        Returns:
            {track_id: True} for every box whose interior motion splits into two
            diverging clusters — evidence of two people inside one detection.
        """
        splits: dict[int, bool] = {}
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Candidate boxes: heavily overlapping pairs, or a single oversized box.
        candidates: dict[int, tuple[int, int, int, int]] = {}
        for i in range(len(detections)):
            for j in range(i + 1, len(detections)):
                if self._calculate_iou(detections[i].bbox, detections[j].bbox) > 0.5:
                    for det in (detections[i], detections[j]):
                        if det.track_id >= 0:
                            candidates[det.track_id] = det.bbox

        for det in detections:
            if det.track_id < 0:
                continue
            x1, y1, x2, y2 = det.bbox
            if (x2 - x1) * (y2 - y1) > self.max_person_area:
                candidates[det.track_id] = det.bbox

        if not candidates:
            self._flow_pts = None
            self._prev_gray = gray.copy()
            return splits

        if self._flow_pts is not None and self._prev_gray is not None:
            p1, st, _err = cv2.calcOpticalFlowPyrLK(
                self._prev_gray, gray, self._flow_pts, None,
                winSize=(15, 15), maxLevel=2,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
            )

            if p1 is not None:
                st = st.reshape(-1)
                good_new = p1.reshape(-1, 2)[st == 1]
                good_old = self._flow_pts.reshape(-1, 2)[st == 1]

                # Evaluate each candidate box using only the points inside it, so
                # one box's motion cannot be blamed on another's.
                for track_id, (bx1, by1, bx2, by2) in candidates.items():
                    inside = (
                        (good_new[:, 0] >= bx1) & (good_new[:, 0] <= bx2)
                        & (good_new[:, 1] >= by1) & (good_new[:, 1] <= by2)
                    )
                    if inside.sum() < 6:
                        continue

                    dx = good_new[inside][:, 0] - good_old[inside][:, 0]
                    if self._has_velocity_split(dx):
                        splits[track_id] = True
                        print(
                            f"[TripwireCounter] ⚠️ Optical flow: two motion clusters inside "
                            f"box of ID {track_id} — probable hidden tailgater."
                        )

                self._flow_pts = good_new.reshape(-1, 1, 2) if len(good_new) else None
            else:
                self._flow_pts = None

        # Reseed whenever the point set has thinned out, so the tracker keeps
        # working for as long as the boxes stay merged.
        if self._flow_pts is None or len(self._flow_pts) < 8:
            mask = np.zeros_like(gray)
            for (ox1, oy1, ox2, oy2) in candidates.values():
                margin_x = int((ox2 - ox1) * 0.1)
                margin_y = int((oy2 - oy1) * 0.1)
                cv2.rectangle(
                    mask,
                    (ox1 + margin_x, oy1 + margin_y),
                    (ox2 - margin_x, oy2 - margin_y),
                    255, -1
                )

            p0 = cv2.goodFeaturesToTrack(
                gray, maxCorners=30, qualityLevel=0.01, minDistance=5, mask=mask
            )
            if p0 is not None:
                self._flow_pts = p0

        self._prev_gray = gray.copy()
        return splits

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
