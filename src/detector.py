"""
Module 2 + 3: YOLOv8 Person Detector with Built-in ByteTrack Tracking
=======================================================================
Wraps Ultralytics YOLOv8 and uses ByteTrack tracking to detect AND track
people in a single model call.

Public API:
    detector = PersonDetector()
    detections = detector.detect(frame)
    detector.draw_boxes(frame, detections)
"""

from collections import namedtuple

import cv2
from ultralytics import YOLO

from config import (
    CONFIDENCE_THRESHOLD,
    DETECTION_BOX_THICKNESS,
    DETECTION_LABEL_COLOR,
    DETECTION_LABEL_FONT_SCALE,
    DETECTION_LABEL_THICKNESS,
    PERSON_CLASS_ID,
    TRACK_COLORS,
    TRACKER_CONFIG,
    YOLO_MODEL,
)

Detection = namedtuple("Detection", ["track_id", "bbox", "confidence"])


class PersonDetector:
    """
    Detects and tracks people in video frames using YOLOv8 + ByteTrack.
    """

    def __init__(
        self,
        model_path:     str = YOLO_MODEL,
        tracker_config: str = TRACKER_CONFIG,
    ):
        print(f"[PersonDetector] Loading model : '{model_path}'")
        try:
            self.model = YOLO(model_path, verbose=False)
            print("[PersonDetector] Model loaded successfully ✓")
        except Exception as exc:
            raise RuntimeError(
                f"[PersonDetector] Cannot load '{model_path}': {exc}"
            ) from exc

        self.tracker_config       = tracker_config
        self.confidence_threshold = CONFIDENCE_THRESHOLD
        self.person_class_id      = PERSON_CLASS_ID

    def detect(self, frame) -> list[Detection]:
        """
        Run YOLOv8 + ByteTrack on one frame. Return tracked person detections.
        """
        detections: list[Detection] = []

        if frame is None or frame.size == 0:
            return detections

        try:
            results = self.model.track(
                frame,
                tracker=self.tracker_config,
                persist=True,
                classes=[self.person_class_id],
                conf=self.confidence_threshold,
                verbose=False,
            )

            result = results[0]

            if result.boxes.id is not None:
                track_id_list = result.boxes.id.int().tolist()
            else:
                track_id_list = [-1] * len(result.boxes)

            for box, track_id in zip(result.boxes, track_id_list):
                confidence = float(box.conf.item())
                class_id   = int(box.cls.item())

                if class_id != self.person_class_id:
                    continue
                if confidence < self.confidence_threshold:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                bbox = (int(x1), int(y1), int(x2), int(y2))

                detections.append(
                    Detection(
                        track_id=int(track_id),
                        bbox=bbox,
                        confidence=confidence,
                    )
                )

        except Exception as exc:
            print(f"[PersonDetector] Warning: inference error — {exc}")

        return detections

    def detect_and_track(self, frame) -> list[Detection]:
        """Alias for detect() for backward compatibility."""
        return self.detect(frame)

    def draw_boxes(self, frame, detections: list[Detection]) -> None:
        """
        Draw bounding boxes and ID labels on frame in-place.
        """
        for det in detections:
            track_id        = det.track_id
            x1, y1, x2, y2 = det.bbox
            confidence      = det.confidence

            color = TRACK_COLORS[abs(track_id) % len(TRACK_COLORS)] if track_id >= 0 else (0, 165, 255)

            cv2.rectangle(
                frame, (x1, y1), (x2, y2), color,
                DETECTION_BOX_THICKNESS, lineType=cv2.LINE_AA,
            )

            id_str = str(track_id) if track_id != -1 else "?"
            label  = f"ID: {id_str} | {confidence:.2f}"

            (text_w, text_h), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX,
                DETECTION_LABEL_FONT_SCALE, DETECTION_LABEL_THICKNESS,
            )

            label_y         = max(y1 - 5, text_h + baseline)
            bg_top_left     = (x1,              label_y - text_h - baseline)
            bg_bottom_right = (x1 + text_w + 6, label_y + baseline)

            cv2.rectangle(frame, bg_top_left, bg_bottom_right, color, cv2.FILLED)
            cv2.putText(
                frame, label, (x1 + 3, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                DETECTION_LABEL_FONT_SCALE,
                DETECTION_LABEL_COLOR,
                DETECTION_LABEL_THICKNESS,
                lineType=cv2.LINE_AA,
            )
