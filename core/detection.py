import numpy as np
import os
from ultralytics import YOLO

# Load the YOLO model once
model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "best.pt")
try:
    model = YOLO(model_path)
except Exception as e:
    print(f"Error loading {model_path}: {e}")
    model = None

def detect_plate_location(frame):
    """
    Find the license plate using YOLOv8 (best.pt).
    Returns the bounding box coordinates as a 4-point array.
    """
    if frame is None or model is None:
        return None

    # Run inference
    results = model.predict(frame, conf=0.5, verbose=False)
    
    if not results or len(results[0].boxes) == 0:
        return None
        
    # Get the box with highest confidence
    box = results[0].boxes[0]
    # x1, y1, x2, y2 coordinates
    coords = box.xyxy[0].cpu().numpy()
    x1, y1, x2, y2 = coords
    
    # Format as a 4-point polygon: [[[x1, y1]], [[x2, y1]], [[x2, y2]], [[x1, y2]]]
    res = np.array([[[int(x1), int(y1)]], [[int(x2), int(y1)]], [[int(x2), int(y2)]], [[int(x1), int(y2)]]])
    return res
