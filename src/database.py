"""
Module 6: sqlite3 Database Manager for Alert Auditing.
======================================================
Handles the persistent storage of tailgating and access control events.
Uses a connection-per-call architecture with explicit close operations
to ensure thread-safety and prevent file locking issues on Windows.
"""

import os
import secrets
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional

# Default database file path (located in the project root)
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tailgate_events.db")

class DatabaseManager:
    """Manages SQLite database connections, initialization, and CRUD operations for events and employees."""

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
        """Creates the events and employees tables if they do not already exist."""
        events_query = """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            image_path TEXT
        );
        """
        employees_query = """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE NOT NULL,
            name TEXT UNIQUE NOT NULL,
            unique_key TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        );
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(events_query)
            cursor.execute(employees_query)
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

    def get_or_create_employee(
        self,
        name: str,
        employee_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieves an employee by name, or creates a new persistent record with a unique key.

        Args:
            name: Full name or photo identifier of the employee.
            employee_id: Optional custom employee ID. If None, generated from name.

        Returns:
            Dict containing id, employee_id, name, unique_key, and created_at.
        """
        existing = self.get_employee_by_name(name)
        if existing:
            return existing

        # Generate a clean employee ID if none provided
        if not employee_id:
            clean_name = "".join(c for c in name if c.isalnum()).upper()
            employee_id = f"EMP-{clean_name}" if clean_name else f"EMP-{secrets.token_hex(4).upper()}"

        # Generate cryptographically secure unique key
        unique_key = secrets.token_hex(16)
        created_at = datetime.now().isoformat()

        insert_query = """
        INSERT INTO employees (employee_id, name, unique_key, created_at)
        VALUES (?, ?, ?, ?);
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(insert_query, (employee_id, name, unique_key, created_at))
            conn.commit()
            emp_id = cursor.lastrowid
            print(f"[DatabaseManager] Registered employee: '{name}' (ID: {employee_id}, Key: {unique_key[:8]}...)")
            return {
                "id": emp_id,
                "employee_id": employee_id,
                "name": name,
                "unique_key": unique_key,
                "created_at": created_at,
            }
        except sqlite3.IntegrityError:
            # Handle potential race condition if registered concurrently
            return self.get_employee_by_name(name) or {}
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error creating employee '{name}': {e}")
            return {
                "id": None,
                "employee_id": employee_id,
                "name": name,
                "unique_key": unique_key,
                "created_at": created_at,
            }
        finally:
            if conn:
                conn.close()

    def get_employee_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Finds an employee by name."""
        query = "SELECT id, employee_id, name, unique_key, created_at FROM employees WHERE name = ? LIMIT 1;"
        conn = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, (name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error fetching employee by name: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_employee_by_key(self, unique_key: str) -> Optional[Dict[str, Any]]:
        """Finds an employee by their unique security key."""
        query = "SELECT id, employee_id, name, unique_key, created_at FROM employees WHERE unique_key = ? LIMIT 1;"
        conn = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, (unique_key,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error fetching employee by key: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_employee_by_id(self, employee_id: str) -> Optional[Dict[str, Any]]:
        """Finds an employee by their employee_id."""
        query = "SELECT id, employee_id, name, unique_key, created_at FROM employees WHERE employee_id = ? LIMIT 1;"
        conn = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, (employee_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error fetching employee by ID: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def list_employees(self) -> List[Dict[str, Any]]:
        """Lists all registered employees in the database."""
        query = "SELECT id, employee_id, name, unique_key, created_at FROM employees ORDER BY id ASC;"
        conn = None
        employees = []
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            for row in rows:
                employees.append(dict(row))
            return employees
        except sqlite3.Error as e:
            print(f"[DatabaseManager] Error listing employees: {e}")
            return []
        finally:
            if conn:
                conn.close()
