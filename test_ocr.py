import warnings
# 1. Suppress the PyTorch deprecation warnings immediately
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

import os

import cv2
import easyocr
import numpy as np
import pyttsx3
import requests
import threading

from video_source import DEFAULT_ESP_URL

# --- Global Control Flags ---
cancel_current_task = threading.Event()
active_thread = None

# --- CONFIGURATION ---
# Override with the VIDEO_SOURCE env var when the ESP32 gets a new IP, e.g.
#   VIDEO_SOURCE="http://192.168.1.223/stream" python test_camera.py
ESP32_STREAM_URL = os.environ.get("VIDEO_SOURCE", DEFAULT_ESP_URL)

engine = pyttsx3.init()
last_spoken_text = ""

# Set gpu=False since CUDA is not available on this laptop environment, connect to external GPU? Maybe..
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

def ocr_process(cancel_flag):

    frame_count = 0
    bytes_buffer = bytearray() # Initialized as mutable bytearray for extend/del performance

    try:
        stream = requests.get(ESP32_STREAM_URL, stream=True, timeout=5)
        if stream.status_code != 200:
            print(f"[Error] Server responded with status code: {stream.status_code}")
            exit()

        while not cancel_flag.is_set():

            for chunk in stream.iter_content(chunk_size=1024):
                if cancel_flag.is_set():
                    break # Breaks out of the chunk loop
                    
                bytes_buffer.extend(chunk)
                
                start_idx = bytes_buffer.find(b'\xff\xd8')
                end_idx = bytes_buffer.find(b'\xff\xd9')
                
                # READER
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    jpg_data = bytes_buffer[start_idx:end_idx + 2]
                    del bytes_buffer[:end_idx + 2] 
                    
                    frame = cv2.imdecode(np.frombuffer(jpg_data, dtype=np.uint8), cv2.IMREAD_COLOR)
                    
                    if frame is None:
                        continue
                        
                    frame_count += 1

                    # --- FRAME THROTTLING ---
                    if frame_count % 15 == 0:
                        # Double-check before running heavy AI inference
                        if cancel_flag.is_set():
                            break
                            
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        results = reader.readtext(rgb_frame)

                        print("\033[H\033[J", end="") 
                        print("=== Real-time Scene Content ===")
                        
                        detected_words = []

                        for (bbox, text, prob) in results:
                            if prob > 0.4:  
                                print(f" Detected: {text} ({int(prob*100)}% confidence)")
                                detected_words.append(text)
                                
                                top_left = tuple(map(int, bbox[0]))
                                bottom_right = tuple(map(int, bbox[2]))
                                
                                cv2.rectangle(frame, top_left, bottom_right, (0, 255, 0), 2)
                                
                                text_y = top_left[1] - 10 if top_left[1] - 10 > 10 else top_left[1] + 20
                                cv2.putText(frame, text, (top_left[0], text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                        if detected_words:
                            full_sentence = " ".join(detected_words)
                            if threading.active_count() <= 2: 
                                tts_thread = threading.Thread(target=speak_async, args=(full_sentence,))
                                tts_thread.daemon = True
                                tts_thread.start()

                    # Move cv2.imshow out of the if frame_count condition so the window stays active
                    cv2.imshow('Scene Describer (Wi-Fi Stream)', frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    cancel_flag.set() # Set flag locally if user presses 'q'
                    break
    
    except Exception as e:  
        print(f"[OCR Error]: {e}")
        
    finally:
        # 2. CRITICAL CLEANUP: Force close the connection so the ESP32 can accept a new request later
        try:
            stream.close()
            print("[OCR] Network stream closed.")
        except NameError:
            pass # Stream was never successfully opened
            
        cv2.destroyWindow('Scene Describer (Wi-Fi Stream)')
        print("[OCR] Thread fully cleaned up and ready for next command.")

        cv2.destroyAllWindows()
        print("Disconnected.")