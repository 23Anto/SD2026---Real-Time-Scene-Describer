import cv2
import numpy as np
import time
import mediapipe as mp


ESP32_STREAM_URL = "http://172.20.10.4/stream"


print(f"Connecting to ESP32 stream via Web Requests: {ESP32_STREAM_URL}")

try:
    stream = requests.get(ESP32_STREAM_URL, stream=True, timeout=5)
    if stream.status_code != 200:
        print(f"[Error] Server responded with status code: {stream.status_code}")
        exit()
except Exception as e:
    print(f"\n[Fatal Error] Could not connect to {ESP32_STREAM_URL}\nDetails: {e}")
    exit()

for chunk in stream.iter_content(chunk_size=1024):
    bytes_buffer.extend(chunk)
    
    start_idx = bytes_buffer.find(b'\xff\xd8')
    end_idx = bytes_buffer.find(b'\xff\xd9')
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        jpg_data = bytes_buffer[start_idx:end_idx + 2]
        del bytes_buffer[:end_idx + 2] 
        
        frame = cv2.imdecode(np.frombuffer(jpg_data, dtype=np.uint8), cv2.IMREAD_COLOR)
        
        if frame is None:
            continue
            
        frame_count += 1



# Switch to standard sequential image evaluation 
VisionRunningMode = mp.tasks.vision.RunningMode

# Paths and options setup
model_path = r'C:\Users\anton\Desktop\Twenty20\SD2026---Real-Time-Scene-Describer\efficientdet_lite2.tflite'

BaseOptions = mp.tasks.BaseOptions
ObjectDetector = mp.tasks.vision.ObjectDetector
ObjectDetectorOptions = mp.tasks.vision.ObjectDetectorOptions


def describe_and_draw(frame, detection_result):
    """
    Parses structural details, outputs description to console, 
    and draws permanent bounding frames over the captured image.
    """
    if not detection_result or not detection_result.detections:
        print("\n[Image Snapshot] Content Summary: No clear objects recognized.")
        return frame

    print("\n=== Image Snapshot Content Description ===")
    
    for idx, detection in enumerate(detection_result.detections):
        # 1. Extract label attributes
        if not detection.categories:
            continue
        category = detection.categories[0]
        label = category.category_name
        score = category.score

        # Log item to your console window
        print(f" -> Object {idx + 1}: Detected a {label} ({int(score * 100)}% certainty)")

        # 2. Extract and scale visual border boxes
        bbox = detection.bounding_box
        start_x = int(bbox.origin_x)
        start_y = int(bbox.origin_y)
        box_width = int(bbox.width)
        box_height = int(bbox.height)
        
        end_x = start_x + box_width
        end_y = start_y + box_height

        # 3. Draw visuals directly onto captured matrix
        cv2.rectangle(frame, (start_x, start_y), (end_x, end_y), (0, 255, 0), 2)
        text_str = f"{label}: {score:.2f}"
        (text_w, text_h), _ = cv2.getTextSize(text_str, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        text_end_y = start_y - 5 if start_y - 5 > 0 else start_y + 15
        
        cv2.rectangle(frame, (start_x, start_y - 20), (start_x + text_w, start_y), (0, 255, 0), -1)
        cv2.putText(frame, text_str, (start_x, text_end_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    print("==========================================")
    return frame


# Configure options explicitly for standalone IMAGE handling
options = ObjectDetectorOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.IMAGE,
    score_threshold=0.7,
    max_results=5
)

# Open local hardware video feed
cap = cv2.VideoCapture(0)

print("--------------------------------------------------")
print("Image Describer Initialized!")
print(" -> Press [SPACEBAR] to take a picture and describe it.")
print(" -> Press [Q] to quit application.")
print("--------------------------------------------------")

with ObjectDetector.create_from_options(options) as detector:
    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            print("Ignoring empty camera frame.")
            continue
        
        # Display clear runtime instructions over the moving video sequence
        preview_frame = frame.copy()
        cv2.putText(preview_frame, "Press SPACE to Describe | Q to Quit", (15, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        
        cv2.imshow('Camera Live Preview', preview_frame)
        
        key = cv2.waitKey(1) & 0xFF
        
        # SPACEBAR pressed: Lock image snapshot, process it, and showcase findings
        if key == ord(' '):
            print("\nCapturing frame...")
            
            # Format transformation (BGR to RGB format conversion)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            
            # Perform blocking execution analysis
            detection_result = detector.detect(mp_image)
            
            # Generate static summary visual output layout overlay
            described_snapshot = describe_and_draw(frame, detection_result)
            
            # Display target frame evaluation output screen window 
            cv2.imshow('Captured Scene Description', described_snapshot)
            print("Snapshot analyzed. Press any key on the image window to resume live preview.")
            
            # Pause view indefinitely until user presses an interactive key to close the popup
            cv2.waitKey(0)
            cv2.destroyWindow('Captured Scene Description')
            
        # Q pressed: Terminate live frame processing loop execution
        elif key == ord('q'):
            break

        else:
            # Continue live feed without processing
            continue

cap.release()
cv2.destroyAllWindows()
