import cv2
import os
from dotenv import load_dotenv
from ultralytics import YOLO
import easyocr
import Levenshtein
import threading

def setup_paths():
    load_dotenv()
    HOME_DIR = os.environ["HOME_DIR"]
    PATH = os.path.join(HOME_DIR, "yolo_fine_tuning/runs/detect/train14/weights/best.pt")
    video_path = os.path.join(HOME_DIR, "yolo_fine_tuning/src/testVideo/tra-pa_motion_test_multi.mp4")
    camera_path = 0
    return PATH, camera_path

def initialize_model(PATH):
    return YOLO(PATH)

def preprocess_frame(frame, before_prosess):
    if before_prosess:
        denoised_frame = cv2.medianBlur(frame, 1)
        g_frame = cv2.cvtColor(denoised_frame, cv2.COLOR_BGR2GRAY)
        ch_frame = cv2.cvtColor(g_frame, cv2.COLOR_GRAY2BGR)
        return ch_frame
    return frame

def process_results_frame(results_frame, model):
    return model.track(results_frame, persist=True)

def crop_and_process_plate(x1, y1, x2, y2, frame, division, before_prosess):
    t_cropped_frame = frame[y1:int(y1 + (y2 - y1) * division), x1:x2]
    b_cropped_frame = frame[int(y1 + (y2 - y1) * division):y2, x1:x2]

    if not before_prosess:
        t_g_cropped_frame = cv2.cvtColor(t_cropped_frame, cv2.COLOR_BGR2GRAY)
        b_g_cropped_frame = cv2.cvtColor(b_cropped_frame, cv2.COLOR_BGR2GRAY)
        _, t_binary_cropped_frame = cv2.threshold(t_g_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, b_binary_cropped_frame = cv2.threshold(b_g_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return t_binary_cropped_frame, b_binary_cropped_frame
    else:
        t_resized_frame = cv2.resize(t_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        b_resized_frame = cv2.resize(b_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        return t_resized_frame, b_resized_frame

def ocr_process(t_result_frame, b_result_frame, reader):
    t_result_text = reader.readtext(t_result_frame, detail=0)
    b_result_text = reader.readtext(b_result_frame, detail=0)
    result_list = t_result_text + b_result_text
    return " ".join(result_list)

def update_id_and_ocr_results(result_text, ocr_results, id_list, new_ids):
    found_similar = False
    count = 0
    for parked in ocr_results:
        similarity = Levenshtein.ratio(result_text, parked)
        if similarity >= 0.8:
            found_similar = True
            break
        count += 1
    if found_similar:
        del ocr_results[count]
    else:
        ocr_results.append(result_text)
        id_list.extend(new_ids)
    return found_similar

def main():
    PATH, camera_path = setup_paths()
    model = initialize_model(PATH)
    cap = cv2.VideoCapture(camera_path)
    cap.set(cv2.CAP_PROP_FPS, 60)

    reader = easyocr.Reader(["ja", "en"])
    id_list = []
    ocr_results = []
    division = 5 / 12
    before_prosess = True

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        results_frame = preprocess_frame(frame, before_prosess)
        results = process_results_frame(results_frame, model)
        annotated_frame = results[0].plot()
        detected_ids = list(map(int, results[0].boxes.id)) if results[0].boxes.id is not None else []

        new_ids = [i for i in detected_ids if i not in id_list and results[0].boxes.xyxy.tolist()]
        for i in new_ids:
            x1, y1, x2, y2 = map(int, results[0].boxes.xyxy[0].tolist())
            t_result_frame, b_result_frame = crop_and_process_plate(x1, y1, x2, y2, results_frame, division, before_prosess)

            if t_result_frame.size > 0 and b_result_frame.size > 0:
                cv2.imshow('Processed Top Frame', t_result_frame)
                cv2.imshow('Processed Bottom Frame', b_result_frame)

                result_text = ocr_process(t_result_frame, b_result_frame, reader)
                print("OCR:", result_text)

                found_similar = update_id_and_ocr_results(result_text, ocr_results, id_list, new_ids)

        print("id:", id_list)
        print("parked", len(ocr_results))

        cv2.imshow('Frame', annotated_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
