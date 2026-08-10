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

import requests
from flask import Flask, jsonify, request

from config import FLASK_PORT, SWIPE_TIMEOUT_SECONDS, WEBHOOK_URL

SwipeRecord = dict   # type alias for readability


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
        @require_api_key
        def swipe():
            body: dict = {}
            if request.is_json:
                body = request.get_json(silent=True) or {}

            record: SwipeRecord = {
                "employee_id": body.get("employee_id", "UNKNOWN"),
                "name":        body.get("name",        "Unknown Employee"),
                "timestamp":   time.time(),
            }

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

        @self._app.route("/mobile-keycard", methods=["GET"])
        @self._app.route("/keycard", methods=["GET"])
        def mobile_keycard():
            from flask import render_template_string
            
            # Retrieve the API key to supply to our front-end client
            api_key = os.environ.get("TAILGATE_API_KEY", "dev-secret-api-key-12345")
            
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
        select {
            background-color: #1e1e1e;
            color: #ffffff;
            border: 1px solid #333333;
            border-radius: 8px;
            padding: 12px;
            font-size: 16px;
            width: 100%;
            margin-bottom: 40px;
            outline: none;
            cursor: pointer;
            transition: border-color 0.2s;
        }
        select:focus {
            border-color: #00ff66;
        }
        .keycard-btn {
            background: radial-gradient(circle, #2a2a2a 0%, #1e1e1e 100%);
            border: 3px solid #333333;
            border-radius: 50%;
            width: 180px;
            height: 180px;
            display: flex;
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
    </style>
</head>
<body>
    <div class="container">
        <h1>SecureAccess</h1>
        <p>Virtual Mobile Keycard Badge</p>
        
        <select id="employee-select">
            <option value="EMP001|Alice Smith">EMP001 - Alice Smith</option>
            <option value="EMP002|Bob Jones">EMP002 - Bob Jones</option>
        </select>
        
        <button id="unlock-btn" class="keycard-btn">
            <span class="icon" id="btn-icon">💳</span>
            <span class="btn-text" id="btn-label">TAP TO UNLOCK</span>
        </button>
        
        <div id="status-display" class="status-msg">Select credentials and tap reader.</div>
    </div>

    <script>
        const unlockBtn = document.getElementById('unlock-btn');
        const empSelect = document.getElementById('employee-select');
        const statusDisplay = document.getElementById('status-display');
        const btnIcon = document.getElementById('btn-icon');
        const btnLabel = document.getElementById('btn-label');

        let isTransacting = false;

        unlockBtn.addEventListener('click', async () => {
            if (isTransacting) return;
            
            isTransacting = true;
            statusDisplay.textContent = 'Transmitting credentials...';
            statusDisplay.style.color = '#aaaaaa';
            
            // Extract credentials from select element
            const [empId, empName] = empSelect.value.split('|');
            
            try {
                const response = await fetch('/swipe', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'x-api-key': '{{ api_key }}'
                    },
                    body: JSON.stringify({
                        employee_id: empId,
                        name: empName
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    // Success UI Feedback
                    unlockBtn.classList.add('granted');
                    btnIcon.textContent = '✅';
                    btnLabel.textContent = 'ACCESS GRANTED';
                    statusDisplay.textContent = 'Credentials verified. Entry window open!';
                    statusDisplay.style.color = '#00ff66';
                } else {
                    // Fail UI Feedback
                    unlockBtn.classList.add('error');
                    btnIcon.textContent = '❌';
                    btnLabel.textContent = 'ACCESS DENIED';
                    statusDisplay.textContent = data.message || 'Verification failed.';
                    statusDisplay.style.color = '#ff3333';
                }
            } catch (err) {
                // Connection Error UI Feedback
                unlockBtn.classList.add('error');
                btnIcon.textContent = '⚠️';
                btnLabel.textContent = 'CONNECT ERROR';
                statusDisplay.textContent = 'Network error: Cannot reach Flask server.';
                statusDisplay.style.color = '#ff3333';
            }

            // Reset button feedback state after 3 seconds
            setTimeout(() => {
                unlockBtn.className = 'keycard-btn';
                btnIcon.textContent = '💳';
                btnLabel.textContent = 'TAP TO UNLOCK';
                statusDisplay.textContent = 'Select credentials and tap reader.';
                statusDisplay.style.color = '#888888';
                isTransacting = false;
            }, 3000);
        });
    </script>
</body>
</html>
            """
            return render_template_string(html_template, api_key=api_key)

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
