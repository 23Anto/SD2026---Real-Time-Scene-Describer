import warnings
# 1. Suppress the PyTorch deprecation warnings immediately
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

import cv2
import easyocr
import numpy as np
import pyttsx3
import threading
import time

# --- STEP 2: CONFIGURATION ---
# Replace with your ESP32-S3 Sense IP address.
# Note: For the standard Espressif CameraWebServer sketch, the stream path is usually :81/stream
ESP32_STREAM_URL = "http://172.20.10.4/stream"  

print("Initializing EasyOCR and TTS Engine (Please wait)...")
engine = pyttsx3.init()
last_spoken_text = ""

# Set gpu=False since CUDA is not available on this laptop environment
reader = easyocr.Reader(['en'], gpu=False) 

def speak_async(text):
    global last_spoken_text
    if text.strip() and text != last_spoken_text:
        last_spoken_text = text
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass

# Initialize the network video stream capture
print(f"Connecting to ESP32 stream at: {ESP32_STREAM_URL}")
cap = cv2.VideoCapture(ESP32_STREAM_URL)

if not cap.isOpened():
    print("\n[Error] Could not open the video stream. Please check:")
    print(" 1. Is your ESP32 turned on and connected to Wi-Fi?")
    print(" 2. Is your laptop on the exact same Wi-Fi network?")
    print(f" 3. Can you open {ESP32_STREAM_URL} directly in your web browser?")
    exit()

print("\n[Success] Connected to ESP32 Wi-Fi Stream!")
print("Live Scene Describer Active! Press 'q' on the image window to quit.")

frame_count = 0

while True:
    ret, frame = cap.read()
    if not ret:
        print("[Warning] Failed to grab frame from network stream. Reconnecting...")
        time.sleep(1)
        cap = cv2.VideoCapture(ESP32_STREAM_URL)
        continue

    frame_count += 1

    # --- STEP 3: FRAME THROTTLING ---
    # Processing on CPU takes time; throttling keeps the network stream from backing up
    if frame_count % 15 == 0:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = reader.readtext(rgb_frame)

        # Clear console screen for clean updates
        print("\033[H\033[J", end="") 
        print("=== Real-time Scene Content ===")
        
        detected_words = []

        for (bbox, text, prob) in results:
            if prob > 0.4:  
                print(f" Detected: {text} ({int(prob*100)}% confidence)")
                detected_words.append(text)

                # Draw boundaries
                (top_left, top_right, bottom_right, bottom_left) = bbox
                tl = (int(top_left[0]), int(top_left[1]))
                br = (int(bottom_right[0]), int(bottom_right[1]))
                cv2.rectangle(frame, tl, br, (0, 255, 0), 2)
                cv2.putText(frame, text, tl, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        if detected_words:
            full_sentence = " ".join(detected_words)
            if threading.active_count() <= 2: 
                tts_thread = threading.Thread(target=speak_async, args=(full_sentence,))
                tts_thread.daemon = True
                tts_thread.start()

    # Display the live feed window
    cv2.imshow('Scene Describer (Wi-Fi Stream)', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Disconnected.")
