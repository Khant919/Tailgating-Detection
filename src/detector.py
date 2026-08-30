"""
Module 2 + 3: YOLOv8 Person Detector with Built-in ByteTrack Tracking & Visual Re-ID
======================================================================================
Wraps Ultralytics YOLOv8 and uses ByteTrack tracking to detect and track people.
Includes a visual Re-identification (Re-ID) algorithm:
    1. Extracts spatial color embeddings (Hue-Saturation histograms across vertical zones).
    2. Stores embeddings of lost tracks in a buffer.
    3. Remaps new ByteTrack IDs back to lost IDs using Cosine Similarity if it exceeds 0.8.
"""

import math
from collections import namedtuple

import cv2
import numpy as np
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
    """Detects and tracks people in video frames using YOLOv8, ByteTrack, and Visual Re-ID."""

    def __init__(
        self,
        model_path:     str = YOLO_MODEL,
        tracker_config: str = TRACKER_CONFIG,
    ):
        import os
        # Dynamically resolve optimized model formats if default PyTorch model is requested
        optimized_model_path = model_path
        if model_path == "yolov8n.pt":
            # Search order: 1. OpenVINO folder (best for Intel CPUs), 2. ONNX file
            openvino_folder = "yolov8n_openvino_model"
            if os.path.exists(openvino_folder):
                optimized_model_path = openvino_folder
                print(f"[PersonDetector] 🚀 Auto-detected OpenVINO optimized model! Loading: '{openvino_folder}'")
            elif os.path.exists("yolov8n.onnx"):
                optimized_model_path = "yolov8n.onnx"
                print(f"[PersonDetector] 🚀 Auto-detected ONNX optimized model! Loading: 'yolov8n.onnx'")

        print(f"[PersonDetector] Loading model: '{optimized_model_path}'")
        try:
            self.model = YOLO(optimized_model_path, verbose=False)
            print("[PersonDetector] Model loaded successfully ✓")
        except Exception as exc:
            raise RuntimeError(
                f"[PersonDetector] Cannot load '{optimized_model_path}': {exc}"
            ) from exc

        self.tracker_config       = tracker_config
        self.confidence_threshold = CONFIDENCE_THRESHOLD
        self.person_class_id      = PERSON_CLASS_ID

        # Module 9 Re-ID tracking variables
        self.active_tracks: dict[int, tuple[np.ndarray, tuple[int, int, int, int]]] = {} # id -> (frame, bbox)
        self.lost_tracks: dict[int, list[float]] = {} # id -> color_histogram_vector
        self.id_remapping: dict[int, int] = {} # current_track_id -> original_lost_id

    def _extract_color_embedding(self, frame: np.ndarray, bbox: tuple[int, int, int, int]) -> list[float]:
        """
        Creates a lightweight visual embedding of a person inside the bounding box.
        Divides the box into 3 vertical zones (Upper torso, Mid body, Lower legs)
        and extracts Hue-Saturation (HSV) color histograms for each zone.
        """
        h_f, w_f = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        
        # Clamp coordinates to frame boundaries
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w_f, x2), min(h_f, y2)
        
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []
            
        # Convert to HSV color space
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        h, w = hsv.shape[:2]
        
        # Divide into 3 vertical zones (capturing shirt, mid, and pants colors)
        z1, z2 = h // 3, (2 * h) // 3
        zones = [hsv[0:z1, :], hsv[z1:z2, :], hsv[z2:h, :]]
        
        hist_parts = []
        for zone in zones:
            if zone.size == 0:
                continue
            # Calculate H-S 2D histogram (8 bins for H, 8 bins for S = 64 dimensions per zone)
            hist = cv2.calcHist([zone], [0, 1], None, [8, 8], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            hist_parts.extend(hist.flatten().tolist())
            
        return hist_parts

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculates the cosine similarity between two feature vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
            
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        
        if magnitude1 * magnitude2 == 0:
            return 0.0
            
        return dot_product / (magnitude1 * magnitude2)

    def _filter_detections(self, detections: list[Detection], frame_shape: tuple) -> list[Detection]:
        """
        Filters out degenerate boxes and suppresses overlapping container/phantom boxes.
        """
        if not detections:
            return []

        frame_h, frame_w = frame_shape[:2]
        valid: list[Detection] = []

        for det in detections:
            x1, y1, x2, y2 = det.bbox
            w = x2 - x1
            h = y2 - y1
            if w < 25 or h < 35:
                continue
            if w > 0.95 * frame_w and h > 0.95 * frame_h:
                continue
            valid.append(det)

        if len(valid) <= 1:
            return valid

        # Suppress heavily overlapping / container boxes (e.g. background clothing enclosing a person)
        keep = [True] * len(valid)
        for i in range(len(valid)):
            if not keep[i]:
                continue
            x1_i, y1_i, x2_i, y2_i = valid[i].bbox
            area_i = (x2_i - x1_i) * (y2_i - y1_i)

            for j in range(i + 1, len(valid)):
                if not keep[j]:
                    continue
                x1_j, y1_j, x2_j, y2_j = valid[j].bbox
                area_j = (x2_j - x1_j) * (y2_j - y1_j)

                inter_x1 = max(x1_i, x1_j)
                inter_y1 = max(y1_i, y1_j)
                inter_x2 = min(x2_i, x2_j)
                inter_y2 = min(y2_i, y2_j)

                inter_w = max(0, inter_x2 - inter_x1)
                inter_h = max(0, inter_y2 - inter_y1)
                inter_area = inter_w * inter_h

                min_area = min(area_i, area_j)
                if min_area > 0 and (inter_area / min_area) > 0.65:
                    # One box heavily encloses or overlaps the other -> keep the cleaner/higher-confidence box
                    if area_i > area_j * 1.2:
                        keep[i] = False
                        break
                    elif area_j > area_i * 1.2:
                        keep[j] = False
                    elif valid[i].confidence < valid[j].confidence:
                        keep[i] = False
                        break
                    else:
                        keep[j] = False

        return [valid[k] for k in range(len(valid)) if keep[k]]

    def detect(self, frame) -> list[Detection]:
        """
        Run YOLOv8 + ByteTrack on one frame. Return tracked person detections with Re-ID mappings.
        """
        raw_detections: list[Detection] = []

        if frame is None or frame.size == 0:
            return raw_detections

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

            # 1. Parse boxes and establish preliminary raw detections
            for box, track_id in zip(result.boxes, track_id_list):
                confidence = float(box.conf.item())
                class_id   = int(box.cls.item())

                if class_id != self.person_class_id:
                    continue
                if confidence < self.confidence_threshold:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                bbox = (int(x1), int(y1), int(x2), int(y2))

                raw_detections.append(
                    Detection(
                        track_id=int(track_id),
                        bbox=bbox,
                        confidence=confidence,
                    )
                )

            # Filter out degenerate boxes and suppress overlapping background phantom boxes
            raw_detections = self._filter_detections(raw_detections, frame.shape)

            # 2. Run Visual Re-ID Fallback Engine
            current_ids = {det.track_id for det in raw_detections if det.track_id >= 0}
            prev_active_ids = set(self.active_tracks.keys())

            # Find lost IDs (active in previous frame, absent in current frame)
            lost_ids = prev_active_ids - current_ids
            for lid in lost_ids:
                last_frame, last_bbox = self.active_tracks[lid]
                emb = self._extract_color_embedding(last_frame, last_bbox)
                if emb:
                    # Save the last known embedding in the buffer
                    self.lost_tracks[lid] = emb

            # Find newly assigned IDs that are not already remapped
            new_ids = (current_ids - prev_active_ids) - set(self.id_remapping.keys())
            for nid in new_ids:
                nid_bbox = next((det.bbox for det in raw_detections if det.track_id == nid), None)
                if nid_bbox:
                    emb = self._extract_color_embedding(frame, nid_bbox)
                    if emb and self.lost_tracks:
                        # Compare against all lost track embeddings
                        best_similarity = 0.0
                        best_match_id = -1
                        for lost_id, lost_emb in list(self.lost_tracks.items()):
                            sim = self._cosine_similarity(emb, lost_emb)
                            if sim > best_similarity:
                                best_similarity = sim
                                best_match_id = lost_id
                        
                        # Remap new ID to old ID if it meets similarity threshold (0.8)
                        if best_similarity >= 0.8:
                            if best_match_id != nid:
                                print(
                                    f"[PersonDetector] 🔗 Re-ID Match: Remapped Track ID {nid} "
                                    f"to reclaimed ID {best_match_id} (Similarity: {best_similarity:.2f})"
                                )
                                self.id_remapping[nid] = best_match_id
                            # Remove the matched ID from the lost buffer
                            self.lost_tracks.pop(best_match_id, None)

            # 3. Apply Remapping & Build final list of detections
            remapped_detections = []
            for det in raw_detections:
                tid = det.track_id
                if tid >= 0:
                    # Resolve mapping iteratively to handle multiple remappings, preventing cycles
                    visited = {tid}
                    mapped_id = self.id_remapping.get(tid, tid)
                    while mapped_id in self.id_remapping and mapped_id not in visited:
                        visited.add(mapped_id)
                        mapped_id = self.id_remapping[mapped_id]
                else:
                    mapped_id = -1

                remapped_detections.append(
                    Detection(
                        track_id=mapped_id,
                        bbox=det.bbox,
                        confidence=det.confidence
                    )
                )

            # 4. Save active tracks for the next frame
            self.active_tracks = {}
            for det in remapped_detections:
                if det.track_id >= 0:
                    # Store a copy of the frame crop bounds
                    self.active_tracks[det.track_id] = (frame.copy(), det.bbox)

            # Prune old lost tracks if buffer grows too large (keep latest 50)
            if len(self.lost_tracks) > 50:
                oldest_keys = list(self.lost_tracks.keys())[:-50]
                for k in oldest_keys:
                    self.lost_tracks.pop(k, None)

        except Exception as exc:
            print(f"[PersonDetector] Warning: inference error — {exc}")

        return remapped_detections

    def detect_and_track(self, frame) -> list[Detection]:
        """Alias for detect() for backward compatibility."""
        return self.detect(frame)

    def draw_boxes(self, frame, detections: list[Detection]) -> None:
        """Draw bounding boxes and ID labels on frame in-place."""
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
