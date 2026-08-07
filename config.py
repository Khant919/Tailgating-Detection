"""
Project configuration values for Tailgating Detection System (Modules 1 - 5).
All tunable constants live here — never hardcode values in other modules.
"""

# ---------------------------------------------------------------------------
# Module 1: Webcam Capture & Display
# ---------------------------------------------------------------------------

# Default camera index for the webcam. Use 0 for the built-in webcam.
DEFAULT_CAMERA_INDEX = 0

# Default position of the vertical counting line as a fraction of frame width.
COUNTING_LINE_POSITION = 0.5
COUNTING_LINE_COLOR     = (0, 0, 255)   # Red (BGR)
COUNTING_LINE_THICKNESS = 2

# Door Region of Interest (ROI) in relative frame coordinates (x_left, y_top).
DOOR_ROI_TOP_LEFT = (0.3, 0.15)
DOOR_ROI_SIZE     = (0.4, 0.7)
DOOR_ROI_COLOR         = (0, 255, 0)       # Green (BGR)
DOOR_ROI_THICKNESS     = 2
DOOR_LABEL_TEXT        = "Door"
DOOR_LABEL_FONT_SCALE  = 0.8
DOOR_LABEL_COLOR       = (255, 255, 255)   # White text
DOOR_LABEL_THICKNESS   = 2

# Screenshot output directory
SCREENSHOT_DIR             = "screenshots"
SCREENSHOT_FILENAME_FORMAT = "screenshot_%Y%m%d_%H%M%S_%f.png"

# Optional Polygon ROI coordinates (x, y) defining the active monitoring zone
ROI_POINTS = [
    (50, 200),
    (600, 200),
    (600, 400),
    (50, 400),
]

# ---------------------------------------------------------------------------
# Module 2: YOLOv8 Person Detection
# ---------------------------------------------------------------------------

# YOLOv8 model weights
YOLO_MODEL = "yolov8n.pt"

# Minimum detection confidence score (0.0 – 1.0)
CONFIDENCE_THRESHOLD = 0.5

# COCO dataset class ID for 'person'
PERSON_CLASS_ID = 0

# Bounding box visual styling
DETECTION_BOX_COLOR         = (0, 165, 255)   # Orange (BGR)
DETECTION_BOX_THICKNESS     = 2
DETECTION_LABEL_FONT_SCALE  = 0.6
DETECTION_LABEL_COLOR       = (255, 255, 255) # White text
DETECTION_LABEL_THICKNESS   = 2

# ---------------------------------------------------------------------------
# Module 3: Multi-Object Tracking (ByteTrack via Ultralytics)
# ---------------------------------------------------------------------------

# Tracking algorithm YAML file
TRACKER_CONFIG = "bytetrack.yaml"

# Frames a lost track is kept alive before deletion
TRACK_BUFFER = 30

# Distinct color palette for tracked person bounding boxes
TRACK_COLORS = [
    (255, 100,   0),   # blue
    (255,   0, 180),   # magenta
    (  0, 200, 255),   # yellow
    (  0, 255, 128),   # lime green
    (200,   0, 255),   # purple
    (  0, 180, 255),   # gold
    (255, 200,   0),   # cyan-blue
    (128, 255,   0),   # spring green
]

TRACK_BOX_THICKNESS      = 2
TRACK_LABEL_FONT_SCALE   = 0.65
TRACK_LABEL_COLOR        = (255, 255, 255)
TRACK_LABEL_THICKNESS    = 2

# ---------------------------------------------------------------------------
# Module 4: Directional Counting — Virtual Tripwire
# ---------------------------------------------------------------------------

# Coordinates for the horizontal virtual line (x, y)
TRIPWIRE_START = (50, 300)
TRIPWIRE_END   = (600, 300)

# Line colors (BGR)
TRIPWIRE_COLOR_DEFAULT = (255, 100, 0)   # Blue (idle)
TRIPWIRE_COLOR_ENTRY   = (0, 200, 0)     # Green (entry flash)
TRIPWIRE_COLOR_EXIT    = (0, 0, 220)     # Red (exit flash)

# Flash duration in frames
TRIPWIRE_FLASH_FRAMES = 10
TRIPWIRE_THICKNESS    = 3

# Top-right counter overlay styling
COUNTER_LINE_SPACING   = 35
COUNTER_PADDING_RIGHT  = 10
COUNTER_PADDING_TOP    = 30
COUNTER_FONT_SCALE     = 0.85
COUNTER_FONT_THICKNESS = 2
COUNTER_ENTRY_COLOR    = (0, 200, 0)    # Green
COUNTER_EXIT_COLOR     = (0, 0, 220)    # Red

# ---------------------------------------------------------------------------
# Module 5: Access System Simulation & Core Logic (The Brain)
# ---------------------------------------------------------------------------

# How long (in seconds) a card swipe remains valid after it is registered
SWIPE_TIMEOUT_SECONDS = 5

# Port for local Flask HTTP API
FLASK_PORT = 5000

# Webhook URL for external alert notifications (Slack / Teams / webhook.site)
WEBHOOK_URL = "https://webhook.site/your-unique-id-here"

# ---------------------------------------------------------------------------
# Module 7: Optimization & QA Testing
# ---------------------------------------------------------------------------

# Disable all cv2.imshow and cv2.waitKey calls to save CPU.
HEADLESS_MODE = False

# Process only every N-th frame to halve CPU load; reuse previous tracking data for skipped frames.
PROCESS_EVERY_N_FRAMES = 2

# Maximum expected bounding box area for a single person. Exceeding this flags potential occlusion (merged boxes).
MAX_SINGLE_PERSON_AREA = 100000
