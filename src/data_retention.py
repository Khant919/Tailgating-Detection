"""
Module 8: GDPR & Privacy Compliance — Data Retention Engine
===========================================================
Defines the policy and clean-up execution to delete historical audit records
and biometric screenshots older than 30 days. Reclaims local storage using SQLite VACUUM.

Run:
    python src/data_retention.py
"""

import os
import sys
import io
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

# Force stdout/stderr to use UTF-8 on Windows to safely print emojis
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Path configurations matching project structure
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "tailgate_events.db")
DEFAULT_SCREENSHOTS_DIR = os.path.join(PROJECT_ROOT, "screenshots")


def enforce_data_retention(db_path: str = DEFAULT_DB_PATH, screenshots_dir: str = DEFAULT_SCREENSHOTS_DIR, retention_days: int = 30) -> None:
    """
    Deletes database rows and their associated evidence screenshots older than retention_days.
    
    Args:
        db_path: Path to the SQLite database file.
        screenshots_dir: Path to the screenshots folder.
        retention_days: Number of days to retain data before deletion.
    """
    print("=" * 70)
    print(f"📅 Running Data Retention Cleanup (Policy: {retention_days} days)")
    print("=" * 70)

    # Verify database existence
    if not os.path.exists(db_path):
        print(f"[DataRetention] ❌ Database not found at: {db_path}. Skipping.")
        return

    # Calculate threshold date
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    # SQLite uses ISO-8601 formatting for lexicographical sorting
    cutoff_str = cutoff_date.isoformat()
    print(f"[DataRetention] Cut-off threshold: {cutoff_str} (Records older than this will be purged)")

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Fetch images to delete
        select_query = "SELECT id, image_path FROM events WHERE timestamp < ?;"
        cursor.execute(select_query, (cutoff_str,))
        expired_records = cursor.fetchall()

        if not expired_records:
            print("[DataRetention] ✓ No expired records found. Storage usage is compliant.")
            return

        print(f"[DataRetention] Found {len(expired_records)} expired record(s) to remove.")

        deleted_files_count = 0
        for record_id, image_path in expired_records:
            # Skip if image path is empty (like authorized entries)
            if not image_path:
                continue

            # Check if path is already absolute, otherwise build absolute path
            if not os.path.isabs(image_path):
                # The image_path in db is stored as e.g. "screenshots/1723000000.jpg"
                # Strip the directory name if it starts with screenshots/
                filename = os.path.basename(image_path)
                abs_image_path = os.path.join(screenshots_dir, filename)
            else:
                abs_image_path = image_path

            # Remove screenshot file from disk
            if os.path.exists(abs_image_path):
                try:
                    os.remove(abs_image_path)
                    deleted_files_count += 1
                except OSError as err:
                    print(f"[DataRetention] ⚠️ Failed to delete file on disk '{abs_image_path}': {err}")
            else:
                print(f"[DataRetention] ⚠️ File not found on disk: '{abs_image_path}'")

        # 2. Purge database records
        delete_query = "DELETE FROM events WHERE timestamp < ?;"
        cursor.execute(delete_query, (cutoff_str,))
        deleted_rows = cursor.rowcount
        conn.commit()

        print(f"[DataRetention] Purged {deleted_rows} database row(s) and deleted {deleted_files_count} file(s) from disk.")

        # 3. Compact database to reclaim unused sectors
        print("[DataRetention] Compacting database file...")
        cursor.execute("VACUUM;")
        conn.commit()
        print("[DataRetention] ✓ Retention execution complete.")

    except sqlite3.Error as e:
        print(f"[DataRetention] ❌ Database error: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    # Execute the default 30-day policy
    enforce_data_retention()
