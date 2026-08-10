# 🤝 Contributing to Tailgating Detection System

Thank you for your interest in contributing to the **Edge AI Tailgating Detection & 2FA Access System**! We welcome bug fixes, feature enhancements, documentation improvements, and architectural security updates.

---

## 📜 Code of Conduct
- Be respectful and collaborative.
- Ensure all security features (JWT signatures, rate limiting, anti-spoofing liveness checks, and GDPR face blurring) remain intact and fully functional.

---

## 🛠️ How to Contribute

### 1. Fork & Clone
Fork the repository on GitHub and clone your fork locally:
```bash
git clone https://github.com/YOUR-USERNAME/Tailgating-Detection.git
cd Tailgating-Detection
```

### 2. Create a Feature Branch
```bash
git checkout -b feature/my-new-feature
```

### 3. Local Environment Setup
Set up a Python virtual environment and install all required development packages:
```bash
python -m venv venv

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Code Standards & Architecture Guidelines
- **No Blocking Operations on Main OpenCV Thread**: Always execute long-running operations (audio alerts, web servers, network API requests) in non-blocking background daemon threads.
- **Maintain Modular Architecture**:
  - [`src/auth_pipeline.py`](file:///C:/Tailgatingdetection/src/auth_pipeline.py): 2FA Engine, 128D Face Encodings, EAR Liveness Detection.
  - [`src/access_system.py`](file:///C:/Tailgatingdetection/src/access_system.py): Flask Access Controller, Rate Limiting, Admin Portal & Dynamic QR Generator.
  - [`src/live_capture.py`](file:///C:/Tailgatingdetection/src/live_capture.py): OpenCV Camera Processing, Bounding Box Overlays, Non-blocking Audio Alarms.
  - [`src/detector.py`](file:///C:/Tailgatingdetection/src/detector.py): YOLOv8 + ByteTrack Multi-Object Tracking.
  - [`src/database.py`](file:///C:/Tailgatingdetection/src/database.py): SQLite Database & Audit Event Logging.
  - [`config.py`](file:///C:/Tailgatingdetection/config.py): System Constants & Configuration Parameters.

### 5. Running Tests & Verification
Before submitting a Pull Request, ensure that all unit tests pass without errors:
```bash
python -m unittest discover -s tests -p "test_*.py"
```

Also check Python code syntax:
```bash
python -m py_compile main.py src/*.py
```

### 6. Submitting a Pull Request (PR)
1. Push your branch to GitHub:
   ```bash
   git push origin feature/my-new-feature
   ```
2. Navigate to the main repository and click **New Pull Request**.
3. Provide a detailed summary of your changes, what was tested, and any relevant test outputs.

---

## ❓ Questions or Support?
If you have questions or encounter bugs, please open an **Issue** on GitHub!
