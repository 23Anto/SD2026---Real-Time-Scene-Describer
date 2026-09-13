import os
import cv2
from ultralytics import YOLO

from video_source import open_video_source

# Same diagnostic convention as live_preview.py (EfficientDet-Lite2), so the
# two models can be compared side by side under identical color-coding rules.
DIAGNOSTIC_FLOOR = 0.15
PRODUCTION_THRESHOLD = 0.7

model = YOLO(os.environ.get('YOLO_WEIGHTS', 'yolov8n.pt'))


def tier_color(score):
    if score >= PRODUCTION_THRESHOLD:
        return (0, 255, 0)      # green: would fire in production
    if score >= 0.3:
        return (0, 255, 255)    # yellow: detected, below production cutoff
    return (0, 0, 255)          # red: very low confidence, near-noise


def draw_detections(frame, result):
    for box in result.boxes:
        score = float(box.conf[0])
        cls_id = int(box.cls[0])
        label = model.names[cls_id]
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        color = tier_color(score)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{label}: {score:.2f}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        text_y = y1 - 8 if y1 - 8 > th else y1 + th + 8
        cv2.rectangle(frame, (x1, text_y - th - 6), (x1 + tw + 4, text_y + 4), color, -1)
        cv2.putText(frame, text, (x1 + 2, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)

    legend = f"YOLOv8n | green >= {PRODUCTION_THRESHOLD}  |  yellow 0.3-{PRODUCTION_THRESHOLD}  |  red < 0.3"
    cv2.putText(frame, legend, (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def main():
    cap = open_video_source()
    if not cap.isOpened():
        print("Could not open video source.")
        return

    print("Live YOLOv8n detection preview — press 'q' in the window to quit.")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Ignoring empty camera frame.")
            continue

        results = model(frame, verbose=False, conf=DIAGNOSTIC_FLOOR)
        annotated = draw_detections(frame, results[0])

        cv2.imshow('Live YOLOv8n Detection (q to quit)', annotated)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
