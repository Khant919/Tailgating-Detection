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

import threading
import time
from collections import deque
from typing import Optional

import requests
from flask import Flask, jsonify, request

from config import FLASK_PORT, SWIPE_TIMEOUT_SECONDS, WEBHOOK_URL

SwipeRecord = dict   # type alias for readability


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
