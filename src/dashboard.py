"""
Module 6: Security Dashboard UI
===============================
Provides a lightweight Flask server on port 5001.
Renders a premium, dark-mode security console for real-time guard review.
Features responsive layouts, incident telemetry, and interactive evidence viewing.
"""

import os
import threading
from datetime import datetime
from flask import Flask, render_template_string, send_from_directory, jsonify
from src.database import DatabaseManager

# Setup screenshot directory relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOTS_DIR = os.path.join(PROJECT_ROOT, "screenshots")

# Create Flask app instance
app = Flask(__name__)
db_manager = DatabaseManager()

# HTML template with premium dark-mode, glassmorphism, responsive grid, and custom JS features.
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Evidence Dashboard - SecureAccess</title>
    <!-- Modern Font Family -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(30, 41, 59, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-red: #ef4444;
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 2rem;
            line-height: 1.5;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(59, 130, 246, 0.05) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(239, 68, 68, 0.05) 0%, transparent 40%);
            background-attachment: fixed;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        /* Header Console Styling */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--card-border);
        }

        .brand h1 {
            font-size: 1.75rem;
            font-weight: 700;
            letter-spacing: -0.025em;
            background: linear-gradient(to right, #3b82f6, #60a5fa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .brand p {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }

        .system-status {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            background: var(--card-bg);
            padding: 0.5rem 1rem;
            border-radius: 9999px;
            border: 1px solid var(--card-border);
            font-size: 0.875rem;
            font-weight: 500;
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            background-color: var(--accent-green);
            border-radius: 50%;
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% {
                transform: scale(0.95);
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
            }
            70% {
                transform: scale(1);
                box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
            }
            100% {
                transform: scale(0.95);
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
            }
        }

        /* Telemetry Cards Grid */
        .telemetry-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2.5rem;
        }

        .telemetry-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 1.5rem;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            position: relative;
            overflow: hidden;
        }

        .telemetry-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--accent-blue);
        }

        .telemetry-card.danger::before {
            background: var(--accent-red);
        }

        .telemetry-card.success::before {
            background: var(--accent-green);
        }

        .telemetry-label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            font-weight: 600;
        }

        .telemetry-value {
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.03em;
        }

        /* Evidence Feed Section */
        .evidence-section {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 20px;
            padding: 1.5rem;
            backdrop-filter: blur(12px);
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }

        .section-title {
            font-size: 1.25rem;
            font-weight: 600;
        }

        .refresh-status {
            font-size: 0.825rem;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .refresh-status span {
            font-weight: 600;
        }

        /* Modern Custom Table Design */
        .table-container {
            width: 100%;
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }

        th {
            padding: 1rem;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            font-weight: 600;
            border-bottom: 1px solid var(--card-border);
        }

        td {
            padding: 1.25rem 1rem;
            font-size: 0.95rem;
            border-bottom: 1px solid var(--card-border);
            vertical-align: middle;
        }

        tr {
            transition: var(--transition);
        }

        tr:hover {
            background: rgba(255, 255, 255, 0.02);
        }

        /* Beautiful Badge Styles */
        .badge {
            display: inline-flex;
            align-items: center;
            gap: 0.375rem;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }

        .badge-danger {
            background-color: rgba(239, 110, 110, 0.12);
            color: #f87171;
            border: 1px solid rgba(239, 110, 110, 0.2);
        }

        .badge-info {
            background-color: rgba(59, 130, 246, 0.12);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.2);
        }

        /* Evidence Image Styling */
        .evidence-thumbnail {
            width: 110px;
            height: 65px;
            object-fit: cover;
            border-radius: 8px;
            border: 1px solid var(--card-border);
            cursor: zoom-in;
            transition: var(--transition);
        }

        .evidence-thumbnail:hover {
            transform: scale(1.08);
            border-color: rgba(59, 130, 246, 0.5);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-secondary);
        }

        .empty-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            opacity: 0.5;
        }

        /* Modal Lightbox for Images */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(11, 15, 25, 0.95);
            backdrop-filter: blur(10px);
            justify-content: center;
            align-items: center;
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .modal.active {
            display: flex;
            opacity: 1;
        }

        .modal-content {
            position: relative;
            max-width: 90%;
            max-height: 80%;
        }

        .modal-image {
            width: 100%;
            height: auto;
            max-height: 80vh;
            border-radius: 12px;
            border: 1px solid var(--card-border);
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }

        .modal-close {
            position: absolute;
            top: -40px;
            right: 0;
            background: none;
            border: none;
            color: var(--text-primary);
            font-size: 1.5rem;
            cursor: pointer;
            font-family: inherit;
        }

        .modal-caption {
            margin-top: 1rem;
            text-align: center;
            font-size: 0.95rem;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="brand">
                <h1>🛡️ SecureAccess</h1>
                <p>Evidence Dashboard & Infraction Log</p>
            </div>
            <div class="system-status">
                <div class="pulse-dot"></div>
                System Active: Monitoring Tripwire
            </div>
        </header>

        <!-- Telemetry Cards -->
        <div class="telemetry-grid">
            <div class="telemetry-card">
                <span class="telemetry-label">Monitoring Port</span>
                <span class="telemetry-value" style="color: var(--accent-blue);">5001</span>
            </div>
            <div class="telemetry-card danger">
                <span class="telemetry-label">Total Infractions</span>
                <span class="telemetry-value" id="incidents-count" style="color: var(--accent-red);">{{ events|length }}</span>
            </div>
            <div class="telemetry-card success">
                <span class="telemetry-label">Audit Engine</span>
                <span class="telemetry-value" style="color: var(--accent-green);">SQLite3</span>
            </div>
        </div>

        <!-- Evidence Feed -->
        <div class="evidence-section">
            <div class="section-header">
                <h2 class="section-title">Audit Trail & Incident Log</h2>
                <div class="refresh-status">
                    Auto-refreshing in <span id="countdown">5</span>s
                </div>
            </div>

            <div class="table-container">
                {% if events %}
                <table>
                    <thead>
                        <tr>
                            <th>Incident ID</th>
                            <th>Timestamp</th>
                            <th>Status Badge</th>
                            <th>Evidence Capture</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for event in events %}
                        <tr>
                            <td style="font-weight: 600; color: var(--accent-blue);">#{{ event.id }}</td>
                            <td>{{ event.timestamp }}</td>
                            <td>
                                {% if 'Tailgate' in event.status %}
                                <span class="badge badge-danger">⚠️ {{ event.status }}</span>
                                {% else %}
                                <span class="badge badge-info">{{ event.status }}</span>
                                {% endif %}
                            </td>
                            <td>
                                {% if event.image_path %}
                                <img src="/{{ event.image_path }}" 
                                     alt="Tailgating Evidence" 
                                     class="evidence-thumbnail"
                                     onclick="openLightbox('/{{ event.image_path }}', 'Incident #{{ event.id }} - {{ event.timestamp }}')"
                                     onerror="this.src='https://placehold.co/110x65/1e293b/ef4444?text=Missing+Img'">
                                {% else %}
                                <span style="font-size: 0.875rem; color: var(--text-secondary); font-style: italic;">No Image Captured</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% else %}
                <div class="empty-state">
                    <div class="empty-icon">🛡️</div>
                    <h3>No Infractions Logged</h3>
                    <p style="margin-top: 0.5rem; font-size: 0.875rem;">The system has not logged any tailgating events. All crossings are verified.</p>
                </div>
                {% endif %}
            </div>
        </div>
    </div>

    <!-- Lightbox Modal -->
    <div id="lightbox" class="modal" onclick="closeLightbox()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <button class="modal-close" onclick="closeLightbox()">&times; Close</button>
            <img id="lightbox-img" class="modal-image" src="" alt="Enlarged Evidence">
            <div id="lightbox-caption" class="modal-caption"></div>
        </div>
    </div>

    <script>
        // Auto-refresh script
        let countdownSec = 5;
        const countdownEl = document.getElementById('countdown');
        
        if (countdownEl) {
            setInterval(() => {
                countdownSec--;
                if (countdownSec <= 0) {
                    window.location.reload();
                } else {
                    countdownEl.textContent = countdownSec;
                }
            }, 1000);
        }

        // Lightbox functionality
        const lightbox = document.getElementById('lightbox');
        const lightboxImg = document.getElementById('lightbox-img');
        const lightboxCaption = document.getElementById('lightbox-caption');

        function openLightbox(imgSrc, captionText) {
            lightboxImg.src = imgSrc;
            lightboxCaption.textContent = captionText;
            lightbox.classList.add('active');
        }

        function closeLightbox() {
            lightbox.classList.remove('active');
        }

        // Close modal on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeLightbox();
            }
        });
    </script>
</body>
</html>
"""

@app.route("/")
def dashboard_home():
    """Fetches the latest 50 logged events and renders the dashboard UI."""
    events = db_manager.get_recent_events(limit=50)
    # Format timestamps slightly for display if needed
    formatted_events = []
    for ev in events:
        # Reformat ISO timestamp to make it more human readable in the UI
        try:
            dt = datetime.fromisoformat(ev["timestamp"])
            display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            display_time = ev["timestamp"]
            
        formatted_events.append({
            "id": ev["id"],
            "timestamp": display_time,
            "status": ev["status"],
            "image_path": ev["image_path"]
        })
    return render_template_string(DASHBOARD_HTML, events=formatted_events)

@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    """
    Serves the screenshot image files from the screenshots/ directory.
    Supports directories nested inside screenshots if required.
    """
    # Extricates base filename to ensure safe retrieval and route consistency
    base_name = os.path.basename(filename)
    return send_from_directory(SCREENSHOTS_DIR, base_name)

def run_dashboard_server():
    """Starts the Flask app on port 5001. Suppresses default terminal logging."""
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    print("[Dashboard] Starting Flask server on port 5001...")
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False, threaded=True)

if __name__ == "__main__":
    # Test execution
    run_dashboard_server()
