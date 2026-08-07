"""
Region of Interest (ROI) setup for tailgating detection (Module 1).

Restricts detection/tracking/tailgating logic to a polygon region of the
frame (typically the doorway/entrance area), so that people walking past
in the background don't trigger false tripwire crossings or alerts.
"""

import cv2
import numpy as np


class RegionOfInterest:
    """Represents a polygon ROI and provides filtering/drawing helpers."""

    def __init__(self, points):
        """
        Args:
            points: list of (x, y) tuples defining the polygon, in order.
                    Must contain at least 3 points to form a valid region.

        Raises:
            ValueError: if fewer than 3 points are provided.
        """
        if points is None or len(points) < 3:
            raise ValueError(
                f'ROI requires at least 3 (x, y) points, got: {points!r}'
            )

        # Stored as an (N, 1, 2) int32 array — the shape OpenCV's polygon
        # functions (pointPolygonTest, fillPoly, polylines) expect.
        self.points = np.array(points, dtype=np.int32).reshape((-1, 1, 2))

    def contains_point(self, point) -> bool:
        """
        Check whether a single (x, y) point lies inside the ROI polygon.

        Uses cv2.pointPolygonTest, which returns:
            > 0  -> point is inside
            = 0  -> point is exactly on the boundary
            < 0  -> point is outside
        Points ON the boundary are treated as inside (>= 0) so people
        stepping right up to the edge of the doorway still count.
        """
        try:
            x, y = point
            result = cv2.pointPolygonTest(
                self.points, (float(x), float(y)), False
            )
            return result >= 0
        except Exception as exc:
            # Fail safe: if the check itself errors out (e.g. malformed
            # point), don't crash the whole detection loop — just treat
            # the point as outside the ROI and log it.
            print(f'[RegionOfInterest] contains_point error: {exc}')
            return False

    def filter_detections(self, detections):
        """
        Keep only the detections whose bottom-center point (feet position)
        falls inside the ROI polygon. Bottom-center is used rather than
        the box center because it's a much better proxy for where a
        person is actually standing on the floor.

        Args:
            detections: list of Detection namedtuples (see detector.py),
                        each with a .bbox of (x1, y1, x2, y2).

        Returns:
            A new list containing only the detections inside the ROI.
            Returns an empty list (never raises) if detections is empty
            or None.
        """
        if not detections:
            return []

        filtered = []
        for det in detections:
            try:
                x1, y1, x2, y2 = det.bbox
                foot_point = ((x1 + x2) / 2, y2)  # bottom-center of box
                if self.contains_point(foot_point):
                    filtered.append(det)
            except (AttributeError, ValueError, TypeError) as exc:
                # Skip malformed detections rather than crashing the loop.
                print(f'[RegionOfInterest] Skipping bad detection: {exc}')
                continue

        return filtered

    def draw(self, frame, color=(255, 0, 255), alpha=0.15, thickness=2):
        """
        Draw the ROI polygon on the frame: a translucent fill plus a
        solid outline, so the monitored area is visually obvious.

        Args:
            frame: the BGR frame to draw on (modified via blending, but
                   the outline is still drawn directly onto `frame`).
            color: BGR color tuple for the fill and outline.
            alpha: opacity of the fill (0 = invisible, 1 = solid).
            thickness: outline thickness in pixels.

        Returns:
            The frame with the ROI drawn on it.
        """
        if frame is None or frame.size == 0:
            return frame

        try:
            overlay = frame.copy()
            cv2.fillPoly(overlay, [self.points], color)
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)
            cv2.polylines(
                frame, [self.points], isClosed=True,
                color=color, thickness=thickness, lineType=cv2.LINE_AA,
            )
            cv2.putText(
                frame, 'ROI',
                (int(self.points[0][0][0]), int(self.points[0][0][1]) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA,
            )
        except Exception as exc:
            # Drawing failures should never take down the capture loop.
            print(f'[RegionOfInterest] draw error: {exc}')

        return frame
