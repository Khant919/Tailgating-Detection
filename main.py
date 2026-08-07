"""
Entry point — Tailgating Detection System (Modules 1 - 5)
=========================================================
Modules active:
    Module 1   : Live webcam capture, FPS, Door ROI, counting line.
    Module 2+3 : PersonDetector — YOLOv8 detection + ByteTrack tracking.
    Module 4   : TripwireCounter — directional virtual tripwire counting.
    Module 5   : AccessController — simulated card-reader Flask API, host
                 accountability, and webhook alerts on tailgate events.

Run:
    python main.py

Simulate a card swipe (while main.py is running):
    # PowerShell:
    Invoke-WebRequest -Method POST http://127.0.0.1:5000/swipe `
      -ContentType "application/json" `
      -Body '{"employee_id":"EMP001","name":"Alice Smith"}'
"""

from src.access_system import AccessController
from src.counter import TripwireCounter
from src.detector import PersonDetector
from src.live_capture import WebcamCapture


if __name__ == "__main__":
    print("=" * 65)
    print("      TAILGATING DETECTION SYSTEM (Modules 1 - 5)")
    print("=" * 65)

    # 1. PersonDetector (Module 2+3)
    try:
        detector = PersonDetector()
    except RuntimeError as exc:
        print(f"[main] Fatal — could not load model: {exc}")
        raise SystemExit(1)

    # 2. TripwireCounter (Module 4)
    counter = TripwireCounter()

    # 3. AccessController (Module 5)
    controller = AccessController()
    controller.start_server()

    # 4. WebcamCapture (Module 1 loop)
    WebcamCapture(
        detector=detector,
        counter=counter,
        controller=controller,
    ).start()
