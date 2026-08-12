"""
Module 5 (Enhanced): Access System Simulation — Host Accountability & Webhooks
================================================================================
Simulates a physical card reader / access control system using a lightweight
Flask HTTP server running in a background daemon thread.

Features:
  1. Rich swipe records — POST /swipe accepts JSON {employee_id, name}.
  2. Host accountability — self.last_valid_swipe tracks who last swiped;
     named in tailgate alerts as the probable door-holder.
  3. Webhook integration — tailgate alerts POSTed to WEBHOOK_URL in a
     fire-and-forget daemon thread (never blocks the OpenCV loop).

Thread-safety:
  Thread A — Flask server       (writes _valid_swipes)
  Thread B — Main/OpenCV loop   (reads + writes _valid_swipes, last_valid_swipe)
  Thread C — Webhook thread     (reads immutable event_data dict — no lock needed)
"""

import os
import threading
import time
from collections import deque
from functools import wraps
from typing import Optional
import socket
import jwt
import qrcode
import io
import base64

import requests
from flask import Flask, jsonify, request

from config import FLASK_PORT, SWIPE_TIMEOUT_SECONDS, WEBHOOK_URL, JWT_SECRET

SwipeRecord = dict   # type alias for readability


def _get_local_ip(request_host: Optional[str] = None) -> str:
    """Get the most appropriate local Wi-Fi/LAN IP address of the laptop."""
    # 1. If the admin portal was accessed via a specific IP, prioritize using that IP directly
    if request_host:
        host_ip = request_host.split(":")[0]
        if host_ip not in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
            import re
            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", host_ip):
                return host_ip

    # 2. Otherwise, query all active network adapter IPs and choose the physical LAN adapter
    try:
        hostname = socket.gethostname()
        ips = socket.gethostbyname_ex(hostname)[2]
        
        # Prioritize 192.168.100.x subnet (user's active LAN subnet)
        for ip in ips:
            if ip.startswith("192.168.100."):
                return ip
                
        # Fallback to other 192.168.x.x subnets
        for ip in ips:
            if ip.startswith("192.168."):
                return ip
                
        # Fallback to other private classes (excluding common hypervisor switches)
        for ip in ips:
            if ip.startswith("172.") or ip.startswith("10."):
                if not ip.startswith("172.17.") and not ip.startswith("172.18.") and not ip.startswith("172.31."):
                    return ip

        # Fallback to standard connection route test
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def require_api_key(f):
    """Decorator to verify that requests include a valid API key in the x-api-key header."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Fetch the system key from the environment, using a secure fallback for local dev
        secret_key = os.environ.get("TAILGATE_API_KEY", "dev-secret-api-key-12345")
        
        # Retrieve the key provided by the client
        provided_key = request.headers.get("x-api-key")
        
        if not provided_key or provided_key != secret_key:
            print(f"[AccessController] 🔐 Blocked Unauthorized Access: x-api-key='{provided_key}'")
            return jsonify({
                "status": "error",
                "message": "Unauthorized. Missing or invalid x-api-key header."
            }), 401
            
        return f(*args, **kwargs)
    return decorated_function


class AccessController:
    """
    Enhanced card-reader simulation with host accountability and webhook alerts.
    """

    def __init__(
        self,
        port:          int   = FLASK_PORT,
        swipe_timeout: float = SWIPE_TIMEOUT_SECONDS,
        webhook_url:   str   = WEBHOOK_URL,
    ):
        self.port:          int           = port
        self.swipe_timeout: float         = swipe_timeout
        self.webhook_url:   Optional[str] = webhook_url or None

        self._valid_swipes: deque[SwipeRecord] = deque()
        self.last_valid_swipe: Optional[SwipeRecord] = None
        self._pending_face_match: Optional[str] = None
        self._lock: threading.Lock = threading.Lock()

        self._app: Flask = Flask(__name__)
        self._app.logger.disabled = True
        self._register_routes()

        print(
            f"[AccessController] Initialised | port={self.port} | "
            f"timeout={self.swipe_timeout}s | "
            f"webhook={'enabled' if self.webhook_url else 'disabled'}"
        )

    def _register_routes(self) -> None:
        """Register Flask URL routes."""

        @self._app.route("/swipe", methods=["POST"])
        def swipe():
            auth_header = request.headers.get("Authorization")
            provided_api_key = request.headers.get("x-api-key")
            
            record = None
            
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                try:
                    payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                    record = {
                        "employee_id": payload.get("employee_id", "UNKNOWN"),
                        "name":        payload.get("name",        "Unknown Employee"),
                        "timestamp":   time.time(),
                    }
                except jwt.ExpiredSignatureError:
                    return jsonify({"status": "error", "message": "Badge registration has expired."}), 401
                except jwt.InvalidTokenError:
                    return jsonify({"status": "error", "message": "Invalid security badge credentials."}), 401
            elif provided_api_key:
                # Fallback support for existing API key tests
                secret_key = os.environ.get("TAILGATE_API_KEY", "dev-secret-api-key-12345")
                if provided_api_key != secret_key:
                    return jsonify({"status": "error", "message": "Unauthorized. Invalid x-api-key header."}), 401
                
                body = {}
                if request.is_json:
                    body = request.get_json(silent=True) or {}
                record = {
                    "employee_id": body.get("employee_id", "UNKNOWN"),
                    "name":        body.get("name",        "Unknown Employee"),
                    "timestamp":   time.time(),
                }
            else:
                return jsonify({"status": "error", "message": "Unauthorized. Missing authentication credentials."}), 401

            with self._lock:
                self._valid_swipes.append(record)

            print(
                f"[AccessController] 💳 Swipe | {record['name']} "
                f"({record['employee_id']}) | queue={len(self._valid_swipes)}"
            )

            return jsonify({
                "status":   "ok",
                "message":  f"Swipe recorded. Entry window open for {self.swipe_timeout}s.",
                "employee": record,
            }), 200

        @self._app.route("/status", methods=["GET"])
        def status():
            now = time.time()
            with self._lock:
                active = sum(
                    1 for r in self._valid_swipes
                    if now - r["timestamp"] <= self.swipe_timeout
                )
                last = dict(self.last_valid_swipe) if self.last_valid_swipe else None

            return jsonify({
                "status":           "ok",
                "active_swipes":    active,
                "last_valid_swipe": last,
            }), 200

        @self._app.route("/admin", methods=["GET"])
        def admin():
            from flask import render_template_string
            
            with self._lock:
                name = self._pending_face_match or "Alice Smith"
            
            if name == "Alice Smith":
                employee_id = "EMP001"
            else:
                clean_name = "".join(c for c in name if c.isalnum()).upper()
                employee_id = f"EMP-{clean_name}"
            
            # Generate JWT signed with JWT_SECRET containing employee's badge details
            payload = {
                "employee_id": employee_id,
                "name":        name,
                "iat":         int(time.time()),
            }
            token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
            
            # Construct Wi-Fi URL for the mobile badge reader dynamically
            local_ip = _get_local_ip(request_host=request.host)
            onboarding_url = f"http://{local_ip}:{self.port}/keycard?token={token}"
            
            # Generate QR Code in memory as a base64 Data URI
            qr = qrcode.QRCode(version=1, box_size=8, border=4)
            qr.add_data(onboarding_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            qr_data_uri = f"data:image/png;base64,{qr_base64}"
            
            html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SecureAccess Onboarding Admin Portal</title>
    <style>
        body {
            background-color: #121212;
            color: #ffffff;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
            box-sizing: border-box;
        }
        .card {
            background-color: #1e1e1e;
            border: 1px solid #333333;
            border-radius: 12px;
            padding: 30px;
            text-align: center;
            max-width: 450px;
            box-shadow: 0 15px 35px rgba(0,0,0,0.6);
        }
        h1 {
            color: #00ff66;
            margin-top: 0;
            font-size: 22px;
            letter-spacing: 0.5px;
        }
        p {
            color: #aaaaaa;
            font-size: 14px;
            line-height: 1.5;
            margin-bottom: 25px;
        }
        .qr-container {
            background-color: white;
            padding: 15px;
            border-radius: 8px;
            display: inline-block;
            margin-bottom: 25px;
        }
        .qr-image {
            display: block;
            max-width: 100%;
            height: auto;
        }
        .url-box {
            background-color: #121212;
            border: 1px solid #333333;
            border-radius: 6px;
            padding: 10px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 12px;
            word-break: break-all;
            color: #00ff66;
            text-align: left;
            margin-bottom: 10px;
        }
        .label {
            font-size: 11px;
            color: #777777;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 5px;
            text-align: left;
            display: block;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>SecureAccess Admin Onboarding</h1>
        <p>Scan this QR code with your smartphone connected to local Wi-Fi to register the mobile keycard badge credentials: <strong>{{ name }} ({{ employee_id }})</strong>.</p>
        
        <div class="qr-container">
            <img class="qr-image" src="{{ qr_data_uri }}" alt="Onboarding QR Code">
        </div>
        
        <span class="label">Local Activation Link:</span>
        <div class="url-box">
            <a href="{{ onboarding_url }}" style="color: #00ff66; text-decoration: none;">{{ onboarding_url }}</a>
        </div>
    </div>
</body>
</html>
            """
            return render_template_string(
                html,
                qr_data_uri=qr_data_uri,
                onboarding_url=onboarding_url,
                name=name,
                employee_id=employee_id
            )

        @self._app.route("/mobile-keycard", methods=["GET"])
        @self._app.route("/keycard", methods=["GET"])
        def mobile_keycard():
            from flask import render_template_string
            
            html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SecureAccess Mobile Keycard</title>
    <style>
        body {
            background-color: #121212;
            color: #ffffff;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            text-align: center;
            box-sizing: border-box;
            padding: 20px;
        }
        h1 {
            font-size: 24px;
            margin-bottom: 5px;
            color: #00ff66;
            letter-spacing: 1px;
        }
        p {
            font-size: 14px;
            color: #aaaaaa;
            margin-bottom: 30px;
        }
        .container {
            display: flex;
            flex-direction: column;
            align-items: center;
            width: 100%;
            max-width: 320px;
        }
        .keycard-btn {
            background: radial-gradient(circle, #2a2a2a 0%, #1e1e1e 100%);
            border: 3px solid #333333;
            border-radius: 50%;
            width: 180px;
            height: 180px;
            display: none; /* Hidden until badge registered */
            flex-direction: column;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            outline: none;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            position: relative;
        }
        .keycard-btn:active {
            transform: scale(0.92);
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3);
        }
        .keycard-btn.granted {
            border-color: #00ff66;
            background: radial-gradient(circle, #0c3e1e 0%, #061c0e 100%);
            box-shadow: 0 0 25px rgba(0, 255, 102, 0.3);
        }
        .keycard-btn.error {
            border-color: #ff3333;
            background: radial-gradient(circle, #3e0c0c 0%, #1c0606 100%);
            box-shadow: 0 0 25px rgba(255, 51, 51, 0.3);
        }
        .icon {
            font-size: 32px;
            margin-bottom: 8px;
            transition: transform 0.2s;
        }
        .btn-text {
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 0.5px;
            color: #dddddd;
            transition: color 0.2s;
        }
        .keycard-btn.granted .btn-text {
            color: #00ff66;
        }
        .keycard-btn.error .btn-text {
            color: #ff3333;
        }
        .status-msg {
            margin-top: 25px;
            font-size: 14px;
            min-height: 20px;
            color: #888888;
            transition: color 0.2s;
        }
        .unauthorized-card {
            border: 2px dashed #ff3333;
            background-color: rgba(255, 51, 51, 0.05);
            border-radius: 12px;
            padding: 30px 20px;
            width: 100%;
            box-sizing: border-box;
        }
        .unauthorized-card h2 {
            color: #ff3333;
            margin-top: 0;
            font-size: 18px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>SecureAccess</h1>
        <p>Virtual Mobile Keycard Badge</p>
        
        <div id="unauthorized-view" class="unauthorized-card">
            <h2>⚠️ Access Blocked</h2>
            <p style="margin-bottom: 0;">No security badge found on this device. Please scan your administrator's onboarding QR code to register credentials.</p>
        </div>
        
        <button id="unlock-btn" class="keycard-btn">
            <span class="icon" id="btn-icon">💳</span>
            <span class="btn-text" id="btn-label">TAP TO UNLOCK</span>
        </button>
        
        <div id="status-display" class="status-msg"></div>
    </div>

    <script>
        const unlockBtn = document.getElementById('unlock-btn');
        const unauthorizedView = document.getElementById('unauthorized-view');
        const statusDisplay = document.getElementById('status-display');
        const btnIcon = document.getElementById('btn-icon');
        const btnLabel = document.getElementById('btn-label');

        // Helper to parse JWT payload on client side
        function parseJwt(token) {
            try {
                return JSON.parse(atob(token.split('.')[1]));
            } catch (e) {
                return null;
            }
        }

        // On Page Load: Handle dynamic token check & registration
        const urlParams = new URLSearchParams(window.location.search);
        const urlToken = urlParams.get('token');

        if (urlToken) {
            // Save the incoming token to local storage
            localStorage.setItem('auth_token', urlToken);
            // Clean up the URL query parameters so the token is hidden from view
            window.history.replaceState({}, document.title, window.location.pathname);
        }

        const storedToken = localStorage.getItem('auth_token');
        const userPayload = storedToken ? parseJwt(storedToken) : null;

        if (userPayload) {
            // Setup active view
            unauthorizedView.style.display = 'none';
            unlockBtn.style.display = 'flex';
            statusDisplay.textContent = `Badge Active: ${userPayload.name} (${userPayload.employee_id})`;
            statusDisplay.style.color = '#00ff66';
        } else {
            // Setup inactive view
            unauthorizedView.style.display = 'block';
            unlockBtn.style.display = 'none';
        }

        let isTransacting = false;

        unlockBtn.addEventListener('click', async () => {
            if (isTransacting || !storedToken) return;
            
            isTransacting = true;
            statusDisplay.textContent = 'Transmitting badge credentials...';
            statusDisplay.style.color = '#aaaaaa';
            
            try {
                const response = await fetch('/swipe', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${storedToken}`
                    }
                });

                const data = await response.json();

                if (response.ok) {
                    unlockBtn.classList.add('granted');
                    btnIcon.textContent = '✅';
                    btnLabel.textContent = 'ACCESS GRANTED';
                    statusDisplay.textContent = 'Badge verified. Entry window open!';
                    statusDisplay.style.color = '#00ff66';
                    
                    // Consume the onboarding badge token immediately on successful swipe
                    localStorage.removeItem('auth_token');
                } else {
                    unlockBtn.classList.add('error');
                    btnIcon.textContent = '❌';
                    btnLabel.textContent = 'ACCESS DENIED';
                    statusDisplay.textContent = data.message || 'Verification failed.';
                    statusDisplay.style.color = '#ff3333';
                    
                    if (response.status === 401) {
                        // Clear invalid/expired token
                        localStorage.removeItem('auth_token');
                        setTimeout(() => { window.location.reload(); }, 2500);
                    }
                }
            } catch (err) {
                unlockBtn.classList.add('error');
                btnIcon.textContent = '⚠️';
                btnLabel.textContent = 'CONNECT ERROR';
                statusDisplay.textContent = 'Network error: Cannot reach Flask server.';
                statusDisplay.style.color = '#ff3333';
            }

            // Reset button feedback state after 10 seconds
            setTimeout(() => {
                const currentToken = localStorage.getItem('auth_token');
                if (currentToken) {
                    // Reset to active/unlock state if token is still present
                    unlockBtn.className = 'keycard-btn';
                    btnIcon.textContent = '💳';
                    btnLabel.textContent = 'TAP TO UNLOCK';
                    if (userPayload) {
                        statusDisplay.textContent = `Badge Active: ${userPayload.name} (${userPayload.employee_id})`;
                        statusDisplay.style.color = '#00ff66';
                    }
                    isTransacting = false;
                } else {
                    // Revert to unauthorized view (token was consumed/cleared)
                    unauthorizedView.style.display = 'block';
                    unlockBtn.style.display = 'none';
                    statusDisplay.textContent = '';
                    isTransacting = false;
                }
            }, 3000);
        });
    </script>
</body>
</html>
            """
            return render_template_string(html_template)

    def start_server(self) -> None:
        """
        Launch Flask in a background daemon thread. Returns immediately.
        """
        self.server_thread = threading.Thread(
            target=self._app.run,
            kwargs={
                "host":         "0.0.0.0",
                "port":         self.port,
                "debug":        False,
                "use_reloader": False,
                "threaded":     True,
            },
            daemon=True,
            name="FlaskAccessServer",
        )
        self.server_thread.start()

        print(
            f"[AccessController] 🚀 Flask server started on "
            f"http://127.0.0.1:{self.port}  (daemon thread)"
        )

    def check_for_tailgate(self) -> dict:
        """
        Determine whether a new entry crossing was authorised or a tailgate.
        """
        now = time.time()

        with self._lock:
            # Prune expired records
            while self._valid_swipes:
                oldest = self._valid_swipes[0]
                age    = now - oldest["timestamp"]
                if age > self.swipe_timeout:
                    self._valid_swipes.popleft()
                    print(
                        f"[AccessController] ⏰ Expired | "
                        f"{oldest['name']} ({oldest['employee_id']}) | age={age:.1f}s"
                    )
                else:
                    break

            # Authorised entry
            if self._valid_swipes:
                record = self._valid_swipes.popleft()
                age    = now - record["timestamp"]
                self.last_valid_swipe = record
                print(
                    f"[AccessController] ✅ Authorised | "
                    f"{record['name']} ({record['employee_id']}) | "
                    f"age={age:.2f}s | remaining={len(self._valid_swipes)}"
                )
                return {"status": "authorized", "employee": record}

            # Tailgate
            host = dict(self.last_valid_swipe) if self.last_valid_swipe else None

        host_name = host["name"]        if host else "Unknown"
        host_id   = host["employee_id"] if host else "N/A"

        print(
            f"[AccessController] 🚨 TAILGATE | "
            f"Probable host: {host_name} ({host_id})"
        )

        event_data = {
            "status":        "tailgate",
            "host_employee": host,
            "detected_at":   now,
            "alert_text":    (
                f"🚨 Tailgate Detected! "
                f"Host responsible: {host_name} ({host_id})"
            ),
        }

        self._fire_webhook_async(event_data)

        return {"status": "tailgate", "host_employee": host}

    def send_webhook_alert(self, event_data: dict) -> None:
        """
        POST a formatted tailgate alert to WEBHOOK_URL synchronously.
        """
        if not self.webhook_url or "webhook.site/your-unique-id-here" in self.webhook_url:
            return

        host      = event_data.get("host_employee") or {}
        host_name = host.get("name",        "Unknown")
        host_id   = host.get("employee_id", "N/A")

        payload: dict = {
            "text": event_data.get(
                "alert_text",
                f"🚨 Tailgate Detected! Host responsible: {host_name} ({host_id})"
            ),
            "details": {
                "host_employee_id":   host_id,
                "host_employee_name": host_name,
                "detected_at_epoch":  event_data.get("detected_at"),
            },
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=5,
            )
            print(
                f"[AccessController] 📡 Webhook sent | "
                f"status={response.status_code}"
            )
        except requests.exceptions.RequestException as exc:
            print(f"[AccessController] ⚠️  Webhook error — {exc}")

    def _fire_webhook_async(self, event_data: dict) -> None:
        """Launch send_webhook_alert() in a short-lived daemon thread."""
        threading.Thread(
            target=self.send_webhook_alert,
            args=(event_data,),
            daemon=True,
            name="WebhookAlertThread",
        ).start()

    def pending_swipe_count(self) -> int:
        """Return number of un-expired swipes in the queue."""
        now = time.time()
        with self._lock:
            return sum(
                1 for r in self._valid_swipes
                if now - r["timestamp"] <= self.swipe_timeout
            )

    def set_pending_face_match(self, name: str) -> None:
        """Update the pending face match name so the /admin portal can generate a QR code for them."""
        with self._lock:
            self._pending_face_match = name
