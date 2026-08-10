"""
Module 10: Multi-Threaded Camera & RTSP StreamReader
=====================================================
Uses a background thread to continually pull frames from the webcam/RTSP source
into a thread-safe LIFO queue. Avoids buffering lag and latency built-up
common in raw cv2.VideoCapture loops. Includes reconnection logic.
"""

import time
import threading
import queue
import sys
import io
import cv2

# Force stdout/stderr to use UTF-8 and line-buffering on Windows to safely print emojis
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(line_buffering=True, encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(line_buffering=True, encoding='utf-8', errors='replace')


class ThreadedCamera:
    """
    Thread-safe camera frame grabber. Drops old frames when the queue is full
    to ensure real-time latency (LIFO). Reconnects automatically on signal drop.
    """

    def __init__(self, source, reconnect_delay: float = 3.0):
        """
        Args:
            source: Camera index (int) or RTSP URL stream (str).
            reconnect_delay: Seconds to wait before attempting to reopen connection.
        """
        self.source = source
        self.reconnect_delay = reconnect_delay

        self.cap = None
        self.queue = queue.Queue(maxsize=1)
        self.running = False
        self.thread = None
        
        # Connect to source
        self._connect()

    def _connect(self) -> bool:
        """Attempts to connect or reconnect to the video source."""
        print(f"[ThreadedCamera] Connecting to source: '{self.source}'...")
        try:
            self.cap = cv2.VideoCapture(self.source)
            if self.cap.isOpened():
                print("[ThreadedCamera] [Connection] Connected successfully.")
                return True
            else:
                print("[ThreadedCamera] [Connection] Failed to open source.")
                return False
        except Exception as e:
            print(f"[ThreadedCamera] [Connection] Error opening source: {e}")
            return False

    def start(self):
        """Starts the background frame capture thread."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True, name="ThreadedCameraGrabber")
        self.thread.start()
        print("[ThreadedCamera] Background grabber thread started.")

    def _update(self):
        """Continually reads frames in a background thread."""
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                print(f"[ThreadedCamera] Stream disconnected. Retrying in {self.reconnect_delay}s...")
                time.sleep(self.reconnect_delay)
                self._connect()
                continue

            grabbed, frame = self.cap.read()
            if not grabbed:
                print("[ThreadedCamera] Frame read failed. Releasing device for reconnect...")
                self.cap.release()
                continue

            # Keep only the latest frame in queue (LIFO behavior)
            if self.queue.full():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass

            self.queue.put(frame)
            # Sleep briefly to yield thread control (prevents CPU core pinning)
            time.sleep(0.005)

    def read(self) -> tuple[bool, cv2.typing.MatLike | None]:
        """
        Retrieves the latest frame from the queue.
        Matches cv2.VideoCapture.read() signature.
        """
        try:
            # Wait up to 2 seconds for camera warmup/exposure on startup
            frame = self.queue.get(timeout=2.0)
            return True, frame
        except queue.Empty:
            return False, None

    def isOpened(self) -> bool:
        """Checks if the camera stream connection is active."""
        return self.cap is not None and self.cap.isOpened()

    def get(self, propId: int) -> float:
        """Redirects parameter queries to underlying VideoCapture object."""
        if self.cap is not None:
            return self.cap.get(propId)
        return 0.0

    def set(self, propId: int, value: float) -> bool:
        """Redirects parameter configurations to underlying VideoCapture object."""
        if self.cap is not None:
            return self.cap.set(propId, value)
        return False

    def release(self):
        """Stops the reader thread and releases the webcam device."""
        print("[ThreadedCamera] Releasing capture resource...")
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
        print("[ThreadedCamera] Resource released cleanly.")
