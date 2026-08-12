"""
Project configuration values for Tailgating Detection System (Modules 1 - 5).
All tunable constants live here — never hardcode values in other modules.

Secrets (JWT signing key, API key, webhook URL) are read from environment
variables; see the Module 5 section below.
"""

import os

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

# Coordinates for the horizontal virtual line (x, y).
# These are the 640x480 fallbacks used only until the first frame arrives; the
# counter rescales itself to the real frame size using the ratios below, so the
# line lands in the same relative place on a 720p or 1080p camera.
TRIPWIRE_START = (50, 300)
TRIPWIRE_END   = (600, 300)

# Tripwire position as a fraction of frame height/width (derived from the
# 640x480 pixel values above: 300/480, 50/640, 600/640).
TRIPWIRE_Y_RATIO       = 0.625
TRIPWIRE_X_START_RATIO = 0.078
TRIPWIRE_X_END_RATIO   = 0.9375

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
SWIPE_TIMEOUT_SECONDS = 10

# Port for local Flask HTTP API
FLASK_PORT = 5005

# Lifetime of a dynamic QR badge token. Short by design: the QR is rendered on a
# screen, so anyone who photographs it holds a valid credential until it expires.
BADGE_TOKEN_TTL_SECONDS = 60

# Rate limits protecting the access API from brute-force and replay floods.
RATE_LIMIT_SWIPE   = "5 per second"
RATE_LIMIT_ADMIN   = "10 per minute"
RATE_LIMIT_DEFAULT = ["200 per day", "50 per hour"]

# Webhook URL for external alert notifications (Slack / Teams / webhook.site).
# Set TAILGATE_WEBHOOK_URL to enable; alerts are skipped while it is unset.
WEBHOOK_URL = os.environ.get("TAILGATE_WEBHOOK_URL", "")

# Secrets are read from the environment. The development fallbacks below let the
# demo run out of the box, but they are published in this repository and are
# therefore public — anyone can forge a badge token with them. Set both
# TAILGATE_JWT_SECRET and TAILGATE_API_KEY before running this anywhere real.
#
#   PowerShell:  $env:TAILGATE_JWT_SECRET = "<random 32+ char string>"
#   bash:        export TAILGATE_JWT_SECRET="<random 32+ char string>"
#
# Generate one with:  python -c "import secrets; print(secrets.token_urlsafe(48))"
DEV_JWT_SECRET = "insecure-development-only-jwt-secret-do-not-use-in-production"
DEV_API_KEY    = "insecure-development-only-api-key"

DEV_DASHBOARD_PASSWORD = "insecure-development-only-dashboard-password"

JWT_SECRET = os.environ.get("TAILGATE_JWT_SECRET", DEV_JWT_SECRET)
API_KEY    = os.environ.get("TAILGATE_API_KEY", DEV_API_KEY)

# Credentials guarding the evidence dashboard (HTTP Basic Auth). The dashboard
# serves breach screenshots containing people's faces, so it must not be open.
DASHBOARD_USER     = os.environ.get("TAILGATE_DASHBOARD_USER", "guard")
DASHBOARD_PASSWORD = os.environ.get("TAILGATE_DASHBOARD_PASSWORD", DEV_DASHBOARD_PASSWORD)

# Port for the evidence dashboard
DASHBOARD_PORT = int(os.environ.get("TAILGATE_DASHBOARD_PORT", "5001"))

# Bind address for the Flask servers. Defaults to loopback so the access API and
# the evidence dashboard are not exposed to the local network. Override with
# TAILGATE_BIND_HOST="0.0.0.0" only behind a trusted network or reverse proxy.
BIND_HOST = os.environ.get("TAILGATE_BIND_HOST", "127.0.0.1")


def warn_on_insecure_secrets() -> None:
    """Print a loud startup warning when the public development secrets are active."""
    insecure = []
    if JWT_SECRET == DEV_JWT_SECRET:
        insecure.append("TAILGATE_JWT_SECRET")
    if API_KEY == DEV_API_KEY:
        insecure.append("TAILGATE_API_KEY")
    if DASHBOARD_PASSWORD == DEV_DASHBOARD_PASSWORD:
        insecure.append("TAILGATE_DASHBOARD_PASSWORD")

    if insecure:
        print("=" * 70)
        print("⚠️  SECURITY WARNING: using public development secrets for:")
        for name in insecure:
            print(f"      - {name}")
        print("   These values are committed to the repository and are not secret.")
        print("   Set them in the environment before any real deployment.")
        print("=" * 70)

# ---------------------------------------------------------------------------
# Module 7: Optimization & QA Testing
# ---------------------------------------------------------------------------

# Disable all cv2.imshow and cv2.waitKey calls to save CPU.
HEADLESS_MODE = False

# Process only every N-th frame to halve CPU load; reuse previous tracking data for skipped frames.
PROCESS_EVERY_N_FRAMES = 2

# Maximum expected bounding box area for a single person, as a fraction of the
# frame area. Exceeding it flags potential occlusion (two people merged into one
# box). Expressed as a ratio because a fixed pixel value is meaningless across
# resolutions — the previous absolute 350000 px exceeded an entire 640x480 frame
# (307200 px), so the check could never fire.
MAX_SINGLE_PERSON_AREA_RATIO = 0.45

# Absolute fallback used only until the first frame is seen.
MAX_SINGLE_PERSON_AREA = int(640 * 480 * MAX_SINGLE_PERSON_AREA_RATIO)

# Minimum optical flow velocity split divergence threshold (pixels/frame) to flag tailgating occlusion.
OPTICAL_FLOW_SPLIT_THRESHOLD = 12.0
