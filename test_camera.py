import cv2
import easyocr
import pyttsx3
import numpy as np

# Initialize text-to-speech engine
engine = pyttsx3.init()

# Initialize EasyOCR reader (load languages as needed, e.g., 'en')
reader = easyocr.Reader(['en'])

# Replace with your ESP32-CAM stream URL
url = 'http://192.168.1' 
cap = cv2.VideoCapture(url)

last_spoken_text = ""

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # Run EasyOCR on the current frame
    results = reader.readtext(frame)
    
    for (bbox, text, prob) in results:
        if prob > 0.5 and text != last_spoken_text:
            print(f"Detected: {text} ({prob:.2f})")
            engine.say(text)
            engine.runAndWait()
            last_spoken_text = text

    cv2.imshow("ESP32 Stream", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
