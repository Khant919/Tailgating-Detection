"""
Module 7: Automated QA Test Runner
==================================
Runs the tailgating detection pipeline against a local test video file.
Simulates a card swipe at frame 50 via the local Access API to verify authorized
vs. unauthorized entry logic and SQLite logging.
Prints a final telemetry report of entries and tailgates.

Run:
    python qa_test_runner.py [path/to/test_video.mp4]
"""

import os
import sys
import time
import cv2
import numpy as np
import requests

from config import (
    HEADLESS_MODE,
    PROCESS_EVERY_N_FRAMES,
    SCREENSHOT_DIR,
    TRACK_COLORS,
)
from src.access_system import AccessController
from src.counter import TripwireCounter
from src.detector import PersonDetector
from src.database import DatabaseManager


def draw_radar_map_overlay(frame: np.ndarray, detections, counter) -> None:
    """Helper to render a bird's-eye view radar map overlay in the QA output."""
    h, w = frame.shape[:2]
    src_pts = np.float32([
        [int(0.35 * w), int(0.4 * h)],
        [int(0.65 * w), int(0.4 * h)],
        [int(0.9 * w),  int(0.95 * h)],
        [int(0.1 * w),  int(0.95 * h)]
    ])
    dst_pts = np.float32([
        [10, 10],
        [140, 10],
        [140, 190],
        [10, 190]
    ])
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    
    overlay = frame.copy()
    x_offset, y_offset = 10, h - 210
    
    # Semi-transparent map backing
    cv2.rectangle(overlay, (x_offset, y_offset), (x_offset + 150, y_offset + 200), (20, 20, 20), -1)
    cv2.rectangle(overlay, (x_offset, y_offset), (x_offset + 150, y_offset + 200), (0, 255, 0), 1)
    cv2.rectangle(overlay, (x_offset + 10, y_offset + 10), (x_offset + 140, y_offset + 190), (80, 80, 80), 1)
    
    # Draw perspective tripwire
    trip_y = counter.tripwire_y
    trip_x_left, trip_x_right = 50, 600
    denom_l = (M[2, 0] * trip_x_left + M[2, 1] * trip_y + M[2, 2])
    denom_r = (M[2, 0] * trip_x_right + M[2, 1] * trip_y + M[2, 2])
    if denom_l != 0 and denom_r != 0:
        plx = int((M[0, 0] * trip_x_left + M[0, 1] * trip_y + M[0, 2]) / denom_l)
        ply = int((M[1, 0] * trip_x_left + M[1, 1] * trip_y + M[1, 2]) / denom_l)
        prx = int((M[0, 0] * trip_x_right + M[0, 1] * trip_y + M[0, 2]) / denom_r)
        pry = int((M[1, 0] * trip_x_right + M[1, 1] * trip_y + M[1, 2]) / denom_r)
        cv2.line(overlay, (x_offset + plx, y_offset + ply), (x_offset + prx, y_offset + pry), (0, 0, 255), 2)
        cv2.putText(overlay, "TRIPWIRE", (x_offset + plx + 5, y_offset + ply - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)

    cv2.putText(overlay, "RADAR MINI-MAP", (x_offset + 15, y_offset + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)

    # Plot tracks
    for det in detections:
        track_id = det.track_id
        if track_id < 0:
            continue
        x1, y1, x2, y2 = det.bbox
        cx = (x1 + x2) // 2
        cy = y2
        
        denom = (M[2, 0] * cx + M[2, 1] * cy + M[2, 2])
        if denom != 0:
            px = int((M[0, 0] * cx + M[0, 1] * cy + M[0, 2]) / denom)
            py = int((M[1, 0] * cx + M[1, 1] * cy + M[1, 2]) / denom)
            if 0 <= px <= 150 and 0 <= py <= 200:
                color = TRACK_COLORS[abs(track_id) % len(TRACK_COLORS)]
                cv2.circle(overlay, (x_offset + px, y_offset + py), 5, color, -1)
                cv2.putText(overlay, f"ID {track_id}", (x_offset + px + 6, y_offset + py + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)


def run_qa_test(video_path: str):
    """
    Executes the automated QA process on the specified video file.
    
    Args:
        video_path: Path to the test video MP4 file.
    """
    print("=" * 70)
    print(f"🚀 Starting Automated QA Runner | Video: {video_path}")
    print("=" * 70)

    # 1. Error Handling: Verify file existence
    if not os.path.exists(video_path):
        print(f"[QA Runner] ❌ Error: Video file not found at: {video_path}")
        print("Please place a test video in the directory and try again.")
        sys.exit(1)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[QA Runner] ❌ Error: Failed to open video file at: {video_path}")
        sys.exit(1)

    # Get video details
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_video = cap.get(cv2.CAP_PROP_FPS)
    print(f"[QA Runner] Video properties: {total_frames} frames | {fps_video:.2f} FPS")

    # 2. Initialize Core Components (matching main.py setup)
    print("[QA Runner] Initializing PersonDetector...")
    try:
        detector = PersonDetector()
    except Exception as exc:
        print(f"[QA Runner] ❌ Fatal: Could not initialize PersonDetector: {exc}")
        cap.release()
        sys.exit(1)

    print("[QA Runner] Initializing TripwireCounter...")
    counter = TripwireCounter()

    print("[QA Runner] Initializing AccessController...")
    controller = AccessController()
    controller.start_server()

    # Wait a moment for Flask server thread to bind and start
    time.sleep(1.0)

    print("[QA Runner] Initializing DatabaseManager...")
    db = DatabaseManager()

    # Track entry counts and loop state
    prev_entry_count = 0
    frame_count = 0
    last_detections = []
    
    # Store initial tailgates count in database to count delta
    initial_events = db.get_recent_events(limit=1000)
    initial_tailgates = sum(1 for e in initial_events if "Tailgate" in e["status"])

    print("[QA Runner] Processing video stream...")
    
    try:
        while True:
            success, frame = cap.read()
            if not success:
                # Video file finished
                break

            frame_count += 1

            # 3. Simulated Swipe Logic at frame 50
            if frame_count == 50:
                print(f"\n[QA Runner] 💳 Frame {frame_count}: Simulating valid card swipe API call...")
                try:
                    # Send swipe POST request to local AccessController Flask port
                    url = f"http://127.0.0.1:{controller.port}/swipe"
                    payload = {"employee_id": "EMP-QA-999", "name": "QA Automated Tester"}
                    api_key = os.environ.get("TAILGATE_API_KEY", "dev-secret-api-key-12345")
                    headers = {"x-api-key": api_key}
                    response = requests.post(url, json=payload, headers=headers, timeout=3)
                    
                    if response.status_code == 200:
                        print(f"[QA Runner] Swipe registered: {response.json().get('message')}")
                    else:
                        print(f"[QA Runner] ⚠️ Swipe API returned status code {response.status_code}")
                except requests.exceptions.RequestException as e:
                    print(f"[QA Runner] ⚠️ Failed to make swipe API request: {e}")

            # 4. Process Frame with optimization skipping
            detections = []
            if frame_count % PROCESS_EVERY_N_FRAMES == 0 or not last_detections:
                detections = detector.detect(frame)
                last_detections = detections
            else:
                detections = last_detections

            # Run counting logic
            counter.process_crossing(detections, frame)

            # Check for new entry crossing
            new_entries = counter.entry_count - prev_entry_count
            for _ in range(new_entries):
                result = controller.check_for_tailgate()

                if result["status"] == "tailgate":
                    print(f"[QA Runner] 🚨 Tailgate detected at frame {frame_count}!")
                    
                    # Capture screenshot
                    screenshot_dir = SCREENSHOT_DIR
                    os.makedirs(screenshot_dir, exist_ok=True)
                    timestamp_filename = f"qa_tailgate_{int(time.time())}_{frame_count}.jpg"
                    saved_image_path = os.path.join(screenshot_dir, timestamp_filename)
                    
                    if cv2.imwrite(saved_image_path, frame):
                        print(f"[QA Runner] Saved QA evidence to: {saved_image_path}")
                    
                    # Log event to database
                    db_image_path = f"screenshots/{timestamp_filename}"
                    db.log_event("Tailgate Detected (QA)", db_image_path)
                else:
                    emp = result.get("employee", {})
                    print(f"[QA Runner] ✅ Authorised entry at frame {frame_count}: {emp.get('name')}")

            prev_entry_count = counter.entry_count

            # 5. Visual Display (if not headless)
            if not HEADLESS_MODE:
                # Draw visual annotations
                h, w = frame.shape[:2]
                line_x = int(w * 0.5)
                cv2.line(frame, (line_x, 0), (line_x, h), (0, 0, 255), 2) # Tripwire
                detector.draw_boxes(frame, detections)
                counter.draw_tripwire(frame)
                
                # Draw the homography radar mini-map overlay
                draw_radar_map_overlay(frame, detections, counter)
                
                # Show video window
                cv2.imshow("QA Test Runner - Processing (Press 'q' to stop)", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("[QA Runner] Stop requested by user.")
                    break
            else:
                # Visuals disabled, small sleep to emulate standard processing rate if running fast
                time.sleep(0.002)

    except KeyboardInterrupt:
        print("\n[QA Runner] 🛑 Interrupted by user.")
    finally:
        # Cleanup video resource
        cap.release()
        if not HEADLESS_MODE:
            cv2.destroyAllWindows()
            
        # Clean up background controller Flask thread
        print("[QA Runner] Cleaning up access server background threads...")
        if hasattr(controller, 'server_thread') and controller.server_thread:
            controller.server_thread.join(timeout=0.5)

    # 6. QA Report Summary
    print("\n" + "=" * 70)
    print("                      QA TEST RUNNER REPORT")
    print("=" * 70)
    
    # Query database to count tailgates logged during this run
    final_events = db.get_recent_events(limit=1000)
    final_tailgates = sum(1 for e in final_events if "Tailgate" in e["status"])
    tailgates_logged_this_run = max(0, final_tailgates - initial_tailgates)
    
    print(f"QA Test Complete: {counter.entry_count} Entries Counted, {tailgates_logged_this_run} Tailgates Logged in Database.")
    print("=" * 70)


if __name__ == "__main__":
    # Retrieve video path from arguments or use a default test_video.mp4
    input_video = sys.argv[1] if len(sys.argv) > 1 else "test_video.mp4"
    run_qa_test(input_video)
