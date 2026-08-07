# --- YOLO Detector Settings (Module 2 & 3) ---
YOLO_MODEL = 'yolov8n.pt'
CONFIDENCE_THRESHOLD = 0.5
PERSON_CLASS_ID = 0

# --- Virtual Tripwire Settings (Module 4) ---
# Adjust these coordinates based on your camera feed's resolution (x, y)
TRIPWIRE_START = (50, 300)
TRIPWIRE_END = (600, 300)

# --- Region of Interest (ROI) Settings (Module 1) ---
# Polygon (x, y) points defining the entrance/doorway area to monitor.
# Only people whose feet fall inside this polygon are considered.
# NOTE: this file is currently NOT imported anywhere (detector.py and
# counter.py both do `from config import ...`, which resolves to the
# ROOT config.py, not this one). Kept in sync here to avoid drift until
# that duplication is fixed.
ROI_POINTS = [
    (50, 200),
    (600, 200),
    (600, 400),
    (50, 400),
]

# --- Access System Settings (Module 5) ---
FLASK_PORT = 5000
SWIPE_TIMEOUT_SECONDS = 5