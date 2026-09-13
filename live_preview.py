import os
import cv2
import mediapipe as mp

from video_source import open_video_source

MODEL_PATH = os.environ.get(
    'MODEL_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'efficientdet_lite2.tflite'),
)

BaseOptions = mp.tasks.BaseOptions
ObjectDetector = mp.tasks.vision.ObjectDetector
ObjectDetectorOptions = mp.tasks.vision.ObjectDetectorOptions
VisionRunningMode = mp.tasks.vision.RunningMode

# Diagnostic mode: run detection at a much lower floor than the production
# score_threshold (0.7) so faint/occluded detections still show up on screen,
# color-coded by confidence tier instead of being silently filtered out.
DIAGNOSTIC_FLOOR = 0.15
PRODUCTION_THRESHOLD = 0.7

options = ObjectDetectorOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.IMAGE,
    score_threshold=DIAGNOSTIC_FLOOR,
    max_results=15,
)


def tier_color(score):
    if score >= PRODUCTION_THRESHOLD:
        return (0, 255, 0)      # green: would actually fire in production
    if score >= 0.3:
        return (0, 255, 255)    # yellow: detected, but below production cutoff
    return (0, 0, 255)          # red: very low confidence, near-noise


def draw_detections(frame, detection_result):
    for detection in detection_result.detections:
        if not detection.categories:
            continue
        category = detection.categories[0]
        label = category.category_name
        score = category.score
        color = tier_color(score)

        bbox = detection.bounding_box
        x1, y1 = int(bbox.origin_x), int(bbox.origin_y)
        x2, y2 = x1 + int(bbox.width), y1 + int(bbox.height)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{label}: {score:.2f}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        text_y = y1 - 8 if y1 - 8 > th else y1 + th + 8
        cv2.rectangle(frame, (x1, text_y - th - 6), (x1 + tw + 4, text_y + 4), color, -1)
        cv2.putText(frame, text, (x1 + 2, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)

    legend = f"green >= {PRODUCTION_THRESHOLD}  |  yellow 0.3-{PRODUCTION_THRESHOLD}  |  red < 0.3"
    cv2.putText(frame, legend, (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def main():
    cap = open_video_source()
    if not cap.isOpened():
        print("Could not open video source.")
        return

    print("Live object detection preview — press 'q' in the window to quit.")
    with ObjectDetector.create_from_options(options) as detector:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Ignoring empty camera frame.")
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            detection_result = detector.detect(mp_image)
            annotated = draw_detections(frame, detection_result)

            cv2.imshow('Live Object Detection (q to quit)', annotated)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
