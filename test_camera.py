import warnings
# 1. Suppress the PyTorch deprecation warnings immediately
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

import cv2
import easyocr
import numpy as np
import pyttsx3
import requests
import threading

# --- CONFIGURATION ---
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

print(f"Connecting to ESP32 stream via Web Requests: {ESP32_STREAM_URL}")

try:
    stream = requests.get(ESP32_STREAM_URL, stream=True, timeout=5)
    if stream.status_code != 200:
        print(f"[Error] Server responded with status code: {stream.status_code}")
        exit()
except Exception as e:
    print(f"\n[Fatal Error] Could not connect to {ESP32_STREAM_URL}\nDetails: {e}")
    exit()

print("\n[Success] Connected to ESP32 Network Stream!")
print("Live Scene Describer Active! Press 'q' on the image window to quit.")

bytes_buffer = bytearray()
frame_count = 0

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

        # --- FRAME THROTTLING ---
        if frame_count % 15 == 0:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = reader.readtext(rgb_frame)

            print("\033[H\033[J", end="") 
            print("=== Real-time Scene Content ===")
            
            detected_words = []

            for (bbox, text, prob) in results:
                if prob > 0.4:  
                    print(f" Detected: {text} ({int(prob*100)}% confidence)")
                    detected_words.append(text)

                    # FIXED: Extract explicit integer tuple coordinates from EasyOCR box layout
                    top_left = tuple(map(int, bbox[0]))
                    bottom_right = tuple(map(int, bbox[2]))
                    
                    cv2.rectangle(frame, top_left, bottom_right, (0, 255, 0), 2)
                    
                    # FIXED: Corrected text offset rendering vector placement
                    text_y = top_left[1] - 10 if top_left[1] - 10 > 10 else top_left[1] + 20
                    cv2.putText(frame, text, (top_left[0], text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

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

cv2.destroyAllWindows()
print("Disconnected.")