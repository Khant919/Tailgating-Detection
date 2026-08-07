"""
Module 6: sqlite3 Database Manager for Alert Auditing.
======================================================
Handles the persistent storage of tailgating and access control events.
Uses a connection-per-call architecture with explicit close operations
to ensure thread-safety and prevent file locking issues on Windows.
"""

import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Any

# Default database file path (located in the project root)
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tailgate_events.db")

class DatabaseManager:
    """Manages SQLite database connections, initialization, and CRUD operations for events."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        Initializes the DatabaseManager.
        
        Args:
            db_path: Absolute or relative path to the SQLite database file.
        """
        self.db_path = os.path.abspath(db_path)
        # Ensure parent directories exist
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # Initialize the database table
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Helper to open a connection to the SQLite database."""
        return sqlite3.connect(self.db_path)

    def init_db(self) -> None:
        """Creates the events table if it does not already exist."""
        query = """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            image_path TEXT
        );
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query)
            conn.commit()
            print(f"[DatabaseManager] Database initialized successfully at: {self.db_path}")
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error initializing database: {e}")
        finally:
            if conn:
                conn.close()

    def log_event(self, status: str, image_path: str) -> None:
        """
        Logs a new event record into the database.
        
        Args:
            status: Description of the event (e.g., 'Tailgate Detected').
            image_path: Relative or absolute path to the saved screenshot.
        """
        # Save timestamp in standard ISO format for easy sorting and displaying
        timestamp = datetime.now().isoformat()
        query = "INSERT INTO events (timestamp, status, image_path) VALUES (?, ?, ?);"
        
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, (timestamp, status, image_path))
            conn.commit()
            print(f"[DatabaseManager] Logged event: '{status}' with image: {image_path}")
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error logging event: {e}")
        finally:
            if conn:
                conn.close()

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves the latest event records from the database.
        
        Args:
            limit: Maximum number of records to return.
            
        Returns:
            A list of dictionaries representing each event.
        """
        query = "SELECT id, timestamp, status, image_path FROM events ORDER BY id DESC LIMIT ?;"
        events = []
        
        conn = None
        try:
            conn = self._get_connection()
            # Use sqlite3.Row to easily convert database rows into dictionaries
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            
            for row in rows:
                events.append({
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "status": row["status"],
                    "image_path": row["image_path"]
                })
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error fetching events: {e}")
        finally:
            if conn:
                conn.close()
            
        return events
