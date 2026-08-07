"""
Module 4: Directional Counting — Virtual Tripwire
===================================================
Provides TripwireCounter which draws a horizontal virtual line across the
frame and counts people as their box-centre crosses it in either direction.

Crossing direction (image coordinates — y=0 is TOP):
    centre_y goes from < tripwire_y  to >= tripwire_y  → ENTRY  (moved DOWN)
    centre_y goes from > tripwire_y  to <= tripwire_y  → EXIT   (moved UP)

Edge-case handling:
    • IDs disappearing/reappearing: track_history is preserved between frames.
    • Hovering on line: crossed_ids prevents double-counting same event.
    • Unconfirmed tracks (track_id == -1): silently ignored.
    • Using box CENTRE ((y1+y2)//2) so close-to-camera subjects work reliably.
"""

import cv2

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
)


class TripwireCounter:
    """
    Counts people crossing a horizontal virtual tripwire in a video frame.
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

    def process_crossing(self, detections) -> None:
        """
        Analyse tracked detections and update entry/exit counts using bbox CENTRE.
        """
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

    def draw_tripwire(self, frame) -> None:
        """
        Draw the tripwire line and IN/OUT counter overlay onto frame in-place.
        """
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
