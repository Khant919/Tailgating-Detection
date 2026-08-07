"""
Module 8: Telemetry & Portfolio Analytics — Metrics Report Generator
=====================================================================
Queries the persistent SQLite database audit log to evaluate system performance.
Calculates key statistics including total entries, authorized swipes, tailgates,
and the bypass/security breach ratios.

Run:
    python generate_metrics_report.py
"""

import os
import sys
import io
import sqlite3
from typing import List, Dict, Any

# Force stdout/stderr to use UTF-8 on Windows to safely print emojis
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Root database path config
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "tailgate_events.db")


def query_all_events(db_path: str) -> List[Dict[str, Any]]:
    """Helper to retrieve all rows from the database events table."""
    if not os.path.exists(db_path):
        print(f"[MetricsReport] ❌ Error: Database not found at '{db_path}'.")
        print("Please run the main system or QA runner to log entries first.")
        return []

    conn = None
    events = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, status, image_path FROM events ORDER BY id ASC;")
        rows = cursor.fetchall()
        for row in rows:
            events.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "status": row["status"],
                "image_path": row["image_path"]
            })
    except sqlite3.Error as e:
        print(f"[MetricsReport] ❌ Database error occurred: {e}")
    finally:
        if conn:
            conn.close()
    return events


def generate_report():
    """Compiles statistics from SQLite database events and prints a formatted CLI report."""
    events = query_all_events(DB_PATH)
    if not events:
        return

    total_events = len(events)
    authorized_count = 0
    tailgate_count = 0

    # Classify database events
    for event in events:
        status = event["status"].lower()
        if "authorized" in status:
            authorized_count += 1
        elif "tailgate" in status:
            tailgate_count += 1

    # Ratio Calculations
    authorized_ratio = (authorized_count / total_events * 100) if total_events > 0 else 0.0
    tailgate_ratio = (tailgate_count / total_events * 100) if total_events > 0 else 0.0
    breach_index = (tailgate_count / authorized_count) if authorized_count > 0 else float('inf')

    # Print ASCII Report
    print("\n" + "=" * 65)
    print("           🛡️  SECUREACCESS AUDIT & PERFORMANCE TELEMETRY REPORT")
    print("=" * 65)
    print(f" Database Path   : {DB_PATH}")
    print(f" Report Generated: {os.path.basename(__file__)}")
    print(f" Active Policy   : Face Blurring Enabled | 30-Day Retention")
    print("-" * 65)
    print(" INCIDENT LOG METRICS:")
    print(f"  • Total Events Audited       : {total_events}")
    print(f"  • Authorised Swipes Recorded : {authorized_count} ({authorized_ratio:.1f}%)")
    print(f"  • Tailgating Violations      : {tailgate_count} ({tailgate_ratio:.1f}%)")
    print("-" * 65)
    print(" SYSTEM SECURITY PERFORMANCE RATIOS:")
    
    if total_events == 0:
        print("  [No data logs on record. Telemetry cannot calculate ratios.]")
    else:
        print(f"  • Authorised-to-Tailgate Ratio: {authorized_count}:{tailgate_count}")
        
        if breach_index == float('inf'):
            print("  • Breach Co-efficient         : N/A (No authorized swipes logged)")
        else:
            print(f"  • Breach Co-efficient         : {breach_index:.3f}")
            print("    (Reflects tailgates per single authorized card swipe.)")
            
        print("\n  • Analytics Evaluation:")
        if tailgate_ratio > 30.0:
            print("    🚨 WARNING: High breach co-efficient. Review guard deployment.")
        elif tailgate_ratio > 10.0:
            print("    ⚠️ ATTENTION: Moderate tailgating levels. Monitor peak hours.")
        else:
            print("    ✅ SECURITY RATING: Strong. Compliant with access directives.")
            
    print("=" * 65)
    print("             END OF SECURITY COMPLIANCE SUMMARY REPORT")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    generate_report()
