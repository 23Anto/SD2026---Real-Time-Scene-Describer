import cv2
import easyocr
import pyttsx3
import threading

# Initiate TTS
engine = pyttsx3.init()

# Track what was last spoken to prevent annoying audio loops
last_spoken_text = ""

def speak_async(text):
    """Worker function to handle speech in a background thread."""
    global last_spoken_text
    # Only speak if it's new text and not empty
    if text.strip() and text != last_spoken_text:
        last_spoken_text = text
        try:
            # engine.say and runAndWait must execute together in the thread
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            pass

# Initialize EasyOCR Reader ('en' for English)
reader = easyocr.Reader(['en'], gpu=True) 

cap = cv2.VideoCapture(0)
frame_count = 0

print("Live Scene Describer Active! Press 'q' to quit.")


#Frame Capturing Loop

while True:
    ret, frame = cap.read()
    if not ret: break

    frame_count += 1
    
    # --- STEP 2: FRAME THROTTLING ---
    # Run engine once every 15 frames (~0.5 seconds)
    if frame_count % 15 == 0:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = reader.readtext(rgb_frame)
        
        print("\033[H\033[J", end="") 
        print("=== Real-time Scene Content ===")
        
        detected_words = []
        
        for (bbox, text, prob) in results:
            if prob > 0.4:  # Filter out low-confidence guesses
                print(f" Detected: {text} ({int(prob*100)}% confidence)")
                detected_words.append(text)
                
                # Draw the bounding boxes on the live feed
                (top_left, top_right, bottom_right, bottom_left) = bbox
                tl = (int(top_left[0]), int(top_left[1]))
                br = (int(bottom_right[0]), int(bottom_right[1]))
                cv2.rectangle(frame, tl, br, (0, 255, 0), 2)
                cv2.putText(frame, text, tl, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # --- STEP 3: TRIGGER BACKGROUND AUDIO ---
        if detected_words:
            # Combine all detected strings into a single sentence
            full_sentence = " ".join(detected_words)
            
            # Check if the TTS engine is currently busy speaking
            # This prevents threads from stacking up if text is read faster than spoken
            if not threading.active_count() > 2: 
                tts_thread = threading.Thread(target=speak_async, args=(full_sentence,))
                tts_thread.daemon = True # Closes thread automatically when main script exits
                tts_thread.start()

    cv2.imshow('Scene Describer (Real-time)', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
