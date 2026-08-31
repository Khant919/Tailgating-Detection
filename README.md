# 🛡️ Edge AI Tailgating Detection & 2FA Access System

An enterprise-grade, edge-computed Computer Vision system designed to detect and log physical tailgating infractions (unauthorized entry events) in real-time. 

By combining **YOLOv8 Object Detection**, **ByteTrack Multi-Object Tracking**, a **Directional Virtual Tripwire**, a **2FA Biometric & QR Verification Engine**, **Passive Liveness Detection (EAR)**, and an **Interactive Evidence Dashboard**, this system provides a complete software-defined alternative to expensive physical security turnstiles.

---

## 🏗️ System Architecture & Workflow

```mermaid
flowchart TD
    A[Webcam / IP Camera Feed] --> B[YOLOv8 Person Detection]
    B --> C[ByteTrack Multi-Object Tracking]
    C --> D[Face Recognition & 128D Embedding Lookup]
    D --> E{Resolution & Liveness Check}
    E -- Failed / Photo Spoof --> F[Reject Verification / Log Warning]
    E -- Passed (Face Matched) --> G[Auto-Open Admin Portal & Dynamic QR Code]
    G --> H[Employee Scans QR / Mobile Keycard Swipe]
    H --> I[2FA Access Granted & Auto-Close Portal]
    C --> J[Directional Virtual Tripwire Crossing]
    J --> K{Authorized Access Recorded?}
    K -- Yes --> L[Log 'Authorized Entry' to SQLite]
    K -- No (Tailgate) --> M[🚨 TAILGATE BREACH ALERT]
    M --> N[Trigger Non-Blocking Audio Alarm Chime]
    M --> O[Haar Cascade Face Blur & Screenshot Logging]
    O --> P[Interactive Guard Dashboard - Port 5001]
```

---

## 🌟 Key Features

### 1. 🔑 2-Factor Authentication (2FA) Pipeline (`src/auth_pipeline.py`)
- **Biometric Face Enrollment**: Pre-computes 128D face encodings from images in `known_faces/` (supports `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tiff`).
- **Resolution Guard**: Enforces a minimum `60x60` px face crop dimension before encoding to eliminate false positives when subjects are too far away.
- **Throttled Recognition**: The dlib face encoding (~10-15ms per person on CPU) only re-runs for a given track every `FACE_RECOGNITION_INTERVAL_FRAMES` detection passes (default `5`, override with `TAILGATE_FACE_RECOGNITION_INTERVAL`) instead of every frame — the biggest single FPS cost with multiple people in view.
- **Passive Liveness Detection (EAR)**: Computes Eye Aspect Ratio (EAR) and monitors EAR variance across 5 consecutive frames. Rejects static photos or phone screen spoofing attempts with a `⚠️ SPOOF ATTEMPT DETECTED` alert.
- **Session Expiration**: Active face matches automatically time out (default **20s**, configurable via `TAILGATE_2FA_TIMEOUT_SECONDS`) if no QR code scan or mobile keycard swipe occurs — completing the QR scan/swipe after the window closes still resolves as a tailgate breach even though the face matched, since face match alone is only the first factor.
- **Swipe Validity Window**: Once the QR scan/keycard swipe itself succeeds, it stays queued for **30s** (configurable via `TAILGATE_SWIPE_TIMEOUT_SECONDS`) waiting to be matched to that person's tripwire crossing — a separate timer from session expiration above, covering the walk from phone-tap to actually passing through the door.

### 2. 📱 Admin Portal & Dynamic QR Badge Generator (`src/access_system.py`)
- **Auto-Browser Launch**: When a face match occurs, the system automatically launches the Admin Portal (`http://localhost:5005/admin`) in a single browser window.
- **Expiring JWT Tokens**: Dynamic QR codes embed 60-second expiring JWT badge tokens (`exp` claim) to prevent replay attacks.
- **Mobile Keycard Swipe**: Employees can scan the QR code using any smartphone on local Wi-Fi to load `/keycard` and authorize their entry.
- **Auto-Disappearing Page**: Upon entry verification, the Admin Portal displays `✅ ACCESS GRANTED` and automatically closes the browser tab.

### 3. 🔒 Cyber Security & Rate Limiting (`Flask-Limiter`)
- **DDoS & Brute-Force Shield**: Enforces rate limiting on Flask routes:
  - `POST /swipe`: Restricted to **5 requests per second** per IP.
  - `GET /admin`: Restricted to **10 requests per minute** per IP.
- **API Key Security**: Validates requests via `x-api-key` headers or JWT bearer tokens, compared in constant time.
- **Secrets from the environment**: the JWT signing key, API key and dashboard password are read from environment variables (see `.env.example`). The committed development fallbacks are public and the app prints a loud warning while they are in use.
- **Loopback by default**: both servers bind `127.0.0.1`. Set `TAILGATE_BIND_HOST=0.0.0.0` only on a trusted network — this is required for the phone QR flow.
- **Production WSGI server**: both the access API and the evidence dashboard run under `waitress` (not the Flask development server), so there is no "do not use in production" warning and no single-threaded request bottleneck.
- **Headless mode**: set `TAILGATE_HEADLESS=true` to disable all `cv2.imshow`/`cv2.waitKey` calls, for running on a machine with no attached display (e.g. an on-site server). Stop the process with Ctrl+C in this mode, since the `q` keyboard shortcut needs the video window.

### 3b. 🪪 Identity-Bound Entry Authorisation
A swipe only authorises the person it belongs to. Each tripwire crossing reports the
`track_id` that crossed, and that track's own 2FA session is matched against the queued
swipes — so if Alice swipes and Bob walks through, Bob is flagged as a **tailgate** and
Alice's swipe is left in the queue for her. Without this binding any swipe would
authorise any body, which is precisely the attack this system exists to catch.

When no face match exists for the crossing person, the system falls back to card-only
mode and logs the entry as unverified.

### 3c. 📨 Telegram Breach Alerts (`src/access_system.py`)
Every tailgate breach — including hidden/occluded entries — fires an optional Telegram
message via the Bot API, in the same fire-and-forget daemon thread as the generic
webhook, so it never blocks the OpenCV loop. Enable it by setting both
`TAILGATE_TELEGRAM_BOT_TOKEN` and `TAILGATE_TELEGRAM_CHAT_ID` (see `.env.example`);
leave either unset to disable it.

### 4. 🔊 Non-Blocking Audio Breach Alarm (`src/live_capture.py`)
- Spawns a dedicated background daemon thread (`BreachAlarmThread`) running `winsound.Beep(2000, 500)` (Windows) or `\a` terminal bell (Linux/macOS) whenever a tailgate breach occurs, ensuring zero OpenCV video frame stuttering.

### 5. 👥 Privacy Compliance (GDPR Face Blurring & Data Retention)
- **Biometric Face Blurring**: Automatically applies a `51x51` Gaussian blur ROI over faces in breach screenshots. The live guard view keeps faces unblurred; only the frame written to disk is anonymised. If the cascade cannot load, the whole frame is blurred rather than persisting identifiable faces.
- **Authenticated Evidence Dashboard**: breach screenshots are served only behind HTTP Basic Auth (`TAILGATE_DASHBOARD_USER` / `TAILGATE_DASHBOARD_PASSWORD`).
- **Data Retention Purge**: `src/data_retention.py` scrubs database records and screenshot evidence older than 30 days, and now runs automatically at every startup as well as standalone.
- **No biometric data in version control**: `known_faces/` and `screenshots/` are gitignored. Never commit photographs of real people.

### 5b. 👥 Occlusion-Aware Counting
Two people walking shoulder-to-shoulder are often detected as a **single** bounding box —
the classic way a tailgater slips through a people counter. Each box is therefore resolved
into a headcount before its crossing is counted:

- **Width-to-height ratio** is the primary signal, because it is scale invariant: someone
  standing twice as close grows in both dimensions, so the ratio is unchanged, while raw
  pixel area is not comparable between near and far people.
- **Optical flow** inside the box confirms a merge when the point velocities separate into
  two diverging clusters (split at the largest gap, not at zero, so noise around a
  stationary mean is not mistaken for two people).
- **Box area** relative to the frame acts as a third check.

A merge must be visible in several frames before it inflates the count, so one noisy
detection cannot manufacture a phantom person. When a merged box crosses, the tracked
person gets a normal entry event and **each hidden person gets their own entry event
flagged as occluded**. An occluded entry has no track and no authentication, and is barred
from consuming anyone else's swipe — so it always resolves to a tailgate, logged as
`Tailgate Detected (Occluded)`.

If a single person's own arm/leg motion is being misread as a second, hidden person
(spurious `Tailgate Detected (Occluded)` events), loosen the detector via
`TAILGATE_MIN_OCCLUSION_FRAMES` (default 4 of the last `TAILGATE_OCCLUSION_MEMORY_FRAMES`,
default 6) and `TAILGATE_OPTICAL_FLOW_SPLIT_THRESHOLD` (default 20.0 px/frame) — raising
either reduces false positives at some cost to how quickly a real hidden tailgater is caught.

### 6. 📐 Resolution-Independent Tripwire
The counting line and the occlusion threshold are derived from frame-relative ratios and
calibrated on the first frame, so the same config works on 480p, 720p and 1080p cameras.
Passing explicit pixel coordinates to `TripwireCounter` pins the line and disables rescaling.

---

## 💼 Business ROI vs. Physical Turnstiles

| Expense Category | Physical Hardware Turnstile | SecureAccess Software System |
| :--- | :--- | :--- |
| **Capital Expenditure (CapEx)** | **$15,000 – $25,000** per lane | **$0** (Runs on existing workstations) |
| **Installation & Masonry** | **$5,000 – $10,000** (Floor bolting, power lines) | **$100** (Mounting standard 1080p webcam) |
| **Spatial Footprint** | Obstructs floor space / fire exits | **Zero footprint** (Mounted overhead) |
| **Maintenance** | **$1,500 – $3,000** annual mechanical upkeep | **$0** (No moving parts) |
| **Biometric Auditing** | Requires extra hardware | **Built-in** (2FA + Face Blur Evidence Logs) |
| **TOTAL INITIAL COST** | **$20,000 – $35,000** per lane | **~$100 – $300** (Standard webcam) |

---

## 🛠️ Installation & Setup

### 1. Clone Repository & Create Virtual Environment
```bash
git clone https://github.com/Khant919/Tailgating-Detection.git
cd Tailgating-Detection

# Create virtual environment
python -m venv venv

# Activate on Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Activate on Linux/macOS:
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

**Python version:** use **CPython 3.10 – 3.13**. The `face_recognition` stage needs `dlib`, and
precompiled `dlib-bin` wheels are only published up to 3.13 — on 3.14 there is no wheel and the
source build requires CMake + Visual Studio Build Tools.

On Windows, install the precompiled dlib wheel *before* the rest, then install
`face_recognition` without its dependencies (its metadata pins the `dlib` sdist,
which would otherwise shadow `dlib-bin` and trigger a source build):

```bash
py -3.12 -m venv venv312
venv312\Scripts\pip install dlib-bin
venv312\Scripts\pip install --no-deps face_recognition face_recognition_models
venv312\Scripts\pip install Pillow "setuptools<81"
venv312\Scripts\pip install -r requirements.txt
```

Two gotchas found in practice, both silent failures rather than install errors:

- `--no-deps` also skips **Pillow**, which `face_recognition` imports directly — install it
  separately or `face_recognition` raises `ModuleNotFoundError: No module named 'PIL'` on first use.
- `face_recognition_models` looks up its model files via `pkg_resources`, which **setuptools ≥ 81
  removed**. A fresh venv's default setuptools is new enough to break this with
  `ModuleNotFoundError: No module named 'pkg_resources'` even though `face_recognition_models`
  itself installed successfully. Pin `setuptools<81`.

Verify enrollment actually works before relying on it — it fails silently into "0 employees
enrolled" if `known_faces/` is empty or a photo has no detectable face:

```bash
venv312\Scripts\python -c "from src.auth_pipeline import TwoFactorAuthenticator; a = TwoFactorAuthenticator(); print(list(a.known_employees))"
```

If `face_recognition` or `pyzbar` are unavailable, the app still runs: YOLO detection,
tracking, tripwire counting, tailgate alerting, evidence capture and the dashboard all work,
and only the face-matching / camera-QR stages of 2FA are skipped.

`pyzbar` additionally needs the [Visual C++ 2013 Redistributable](https://www.microsoft.com/en-US/download/details.aspx?id=40784)
on Windows, otherwise `libzbar-64.dll` fails to load.

### 3. Add Employee Photos for Face Enrollment
Place employee reference photos inside the `known_faces/` folder:
```
known_faces/
├── Alice.png
├── Khant.png
└── Bob.webp
```

---

## 🚀 Running the Project

### 0. Configure secrets (do this first)
Copy `.env.example` and set real values, or export them in your shell. The app runs
without this, but prints a security warning because the fallback secrets are published
in this repository:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```powershell
$env:TAILGATE_JWT_SECRET = "<generated value>"
$env:TAILGATE_API_KEY = "<generated value>"
$env:TAILGATE_DASHBOARD_PASSWORD = "<your password>"
```

### 1. Launch the Main Application
```bash
python main.py
```
This warns about insecure secrets, runs the data-retention sweep, initializes YOLOv8
detection, enrolls employee faces from `known_faces/`, starts the Flask Access Server on
`http://127.0.0.1:5005`, starts the evidence dashboard on `http://127.0.0.1:5001`, and
opens the OpenCV live webcam stream.

Both servers live inside `main.py`. **Closing the video window (`q`) stops the dashboard
too** — it is a daemon thread, not a separate service.

### 1b. Open the Evidence Dashboard
Visit `http://localhost:5001` **while `main.py` is running** and sign in with
`TAILGATE_DASHBOARD_USER` / `TAILGATE_DASHBOARD_PASSWORD`.

### 1c. Simulate a card swipe
```bash
curl -X POST http://127.0.0.1:5005/swipe -H "x-api-key: $TAILGATE_API_KEY" -H "Content-Type: application/json" -d "{\"employee_id\":\"EMP001\",\"name\":\"Alice Smith\"}"
```

### 2. Testing 2FA Authentication Flow
1. **Approach Camera**: Step in front of the camera.
2. **Face Match**: Bounding box turns **Yellow** (`FACE MATCHED: AWAITING QR...`).
3. **Admin Portal Auto-Opens**: `http://localhost:5005/admin` opens in your browser with a dynamic QR code.
4. **Scan QR or Keycard**: Scan the QR code or tap `/keycard` swipe.
5. **Access Granted**: Bounding box turns **Green** (`ACCESS GRANTED`), the Admin Portal page displays success and auto-closes.

### 3. Running Unit Test Suite
```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 🏢 Deployment: On-Site PC, LAN-Only

This is not a cloud-hostable web app — it reads a live camera feed and runs an OpenCV
loop, so it is *installed* on a machine at the door rather than *hosted*. The supported
deployment is a dedicated on-site PC (a mini-PC or laptop; a Raspberry Pi is too weak for
YOLOv8 + dlib) with the webcam mounted overhead, kept on the local network only.

**Nothing is exposed to the internet.** Remote visibility comes from Telegram alerts
(§3c), which the on-site PC sends *outbound* — so breach notifications reach a phone
anywhere without any inbound port, tunnel, or public URL. The dashboard stays on the LAN
because its screenshots contain people's faces; the fewer places that is reachable from,
the better.

### Operating model

| Concern | How it is served |
| :--- | :--- |
| Breach notifications, from anywhere | **Telegram alerts** (outbound only) |
| Evidence dashboard, guard review | `http://<pc-lan-ip>:5001` — same Wi-Fi/LAN only |
| Phone QR / mobile keycard | `http://<pc-lan-ip>:5005` — same Wi-Fi/LAN only |
| Public internet access | **Not configured, by design** |

### Configuring it for an always-on install

Per-terminal `$env:` assignments only last for that one session, which is no good for a
machine meant to run unattended. Use **a `.env` file in the project root** — `config.py`
loads it at import time via `python-dotenv`, so no terminal setup is needed at all:

```ini
TAILGATE_JWT_SECRET=<generated>
TAILGATE_API_KEY=<generated>
TAILGATE_DASHBOARD_USER=guard
TAILGATE_DASHBOARD_PASSWORD=<your password>
TAILGATE_BIND_HOST=0.0.0.0
TAILGATE_TELEGRAM_BOT_TOKEN=<bot token>
TAILGATE_TELEGRAM_CHAT_ID=<chat id>
```

`.env` is gitignored — never commit it. Copy `.env.example` as the starting point.

Machine-level environment variables (Windows: `[Environment]::SetEnvironmentVariable(name,
value, "Machine")`, needs admin) work too and take precedence over `.env`, since
`load_dotenv()` does not override values that are already set. Be aware of one Windows
gotcha: a newly set machine variable is **not** visible to any already-running process,
including terminal host apps like Windows Terminal or VS Code — opening a new tab is not
enough, because the tab inherits the host's stale environment. Only processes started
after a reboot (or after fully restarting the terminal application) see it. `.env` has no
such delay, which is why it is the recommended option here.

Then just run:

```powershell
cd I:\Tailgating_Detection
venv312\Scripts\python main.py
```

Confirm the startup banner shows `telegram=enabled` and no `SECURITY WARNING` block — if
it still warns about development secrets, the configuration is not being picked up.

`TAILGATE_BIND_HOST=0.0.0.0` binds both servers to every interface on that machine. On a
trusted private LAN behind a router that is exactly what the phone flow needs; it is
**not** the same as exposing them to the internet, which would additionally require port
forwarding on the router (do not add it).

If the PC has no monitor attached, set `TAILGATE_HEADLESS=true` and stop the process with
Ctrl+C, since the `q` shortcut needs the video window.

### If remote dashboard access is genuinely needed later

Use **Tailscale** (a private WireGuard mesh — only your own signed-in devices can reach
the machine, no public URL) or a **Cloudflare Tunnel** with Cloudflare Access in front of
it. Note that both are blocked on some ISPs by deep packet inspection, which shows up as
a TCP connection that succeeds while the request itself silently times out; a mobile
hotspot is the quickest way to confirm that is what you are seeing. Never substitute
plain router port forwarding for these — that publishes the face-evidence dashboard to
the whole internet behind a single Basic Auth password.

---

## 🤝 Contributing

Contributions are welcome! Follow these steps to contribute:
1. **Fork the Repository**
2. **Create a Feature Branch**: `git checkout -b feature/amazing-feature`
3. **Commit your changes**: `git commit -m "Add amazing feature"`
4. **Push to branch**: `git push origin feature/amazing-feature`
5. **Open a Pull Request**

---

## 📜 License
Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
