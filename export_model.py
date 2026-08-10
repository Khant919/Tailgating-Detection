"""
Module 10: Model Compilation & Quantization Engine
===================================================
Loads the standard PyTorch YOLOv8 weights and exports them to:
    1. ONNX (FP16 optimized)
    2. OpenVINO (INT8 quantized for Intel CPU acceleration)

Run:
    python export_model.py
"""

import os
import sys
import io
from ultralytics import YOLO

# Force stdout/stderr to use UTF-8 on Windows to safely print emojis
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def export_yolo_models(model_name: str = "yolov8n.pt"):
    """Loads and compiles PyTorch YOLOv8 model to optimized CPU runtimes."""
    print("=" * 70)
    print("📦  YOLOv8 MODEL COMPILATION & QUANTIZATION UTILITY")
    print("=" * 70)
    print(f"Target Model Base: {model_name}")
    print("Export Formats   : ONNX (FP16) & OpenVINO (INT8)")
    print("-" * 70)

    # 1. Load PyTorch model
    if not os.path.exists(model_name):
        print(f"[ModelExport] Target weights file '{model_name}' not found locally.")
        print(f"[ModelExport] Downloading default PyTorch weights from Ultralytics...")
    
    try:
        model = YOLO(model_name)
        print("[ModelExport] PyTorch model loaded successfully.")
    except Exception as e:
        print(f"[ModelExport] Error loading PyTorch model: {e}")
        sys.exit(1)

    # 2. Export to ONNX (FP16 precision)
    print("\n[ModelExport] Starting ONNX compilation (FP16 half-precision)...")
    try:
        # half=True forces FP16 half-precision, reducing memory footprint on edge runtimes
        onnx_path = model.export(format="onnx", half=True, verbose=False)
        print(f"[ModelExport] ONNX export complete. Saved to: {onnx_path}")
    except Exception as e:
        print(f"[ModelExport] Warning: ONNX export failed: {e}")

    # 3. Export to OpenVINO (INT8 Quantization)
    print("\n[ModelExport] Starting OpenVINO compilation (INT8 quantized)...")
    try:
        # int8=True applies INT8 integer quantization calibration for Intel CPU acceleration
        openvino_path = model.export(format="openvino", int8=True, verbose=False)
        print(f"[ModelExport] OpenVINO export complete. Saved to folder: {openvino_path}")
    except Exception as e:
        print(f"[ModelExport] Warning: OpenVINO export failed: {e}")

    print("\n" + "=" * 70)
    print("✓ Model exports completed. Check project directory for output assets.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    export_yolo_models()
