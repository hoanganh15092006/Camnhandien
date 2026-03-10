import cv2
import easyocr
import imutils
import numpy as np
import re
import os

def fix_chars(text, is_letters=False, is_digits=False):
    # Maps commonly confused chars on Vietnamese license plates
    dict_char_to_int = {'O': '0', 'I': '1', 'J': '3', 'A': '4', 'G': '6', 'S': '5', 'B': '8', 'Z': '2', 'Q': '0', 'T': '7'}
    dict_int_to_char = {'0': 'O', '1': 'I', '3': 'J', '4': 'A', '6': 'G', '5': 'S', '8': 'B', '2': 'Z', '7': 'T'}

    res = ""
    for char in text:
        if is_digits and char.upper() in dict_char_to_int:
            res += dict_char_to_int[char.upper()]
        elif is_letters and char.upper() in dict_int_to_char:
            res += dict_int_to_char[char.upper()]
        else:
            res += char.upper()
    return res


def process_plate(res):
    if not res:
        return None

    # Sort boxes top-to-bottom
    res = sorted(res, key=lambda r: r[0][0][1])
    formatted_text = ""

    if len(res) >= 2:
        line1 = re.sub(r'[^a-zA-Z0-9]', '', res[0][1])
        line2 = re.sub(r'[^a-zA-Z0-9]', '', res[1][1])

        prov_code = fix_chars(line1[:2], is_digits=True)
        series = line1[2:]

        if len(series) == 2:
            dict_int_to_char_local = {'0': 'O', '1': 'I', '3': 'J', '4': 'A', '6': 'G', '5': 'S', '8': 'B', '2': 'Z'}
            if series[1].isalpha() or series[1] in list(dict_int_to_char_local.values()):
                if series[1] in '0123456789' and series[1] not in dict_int_to_char_local:
                    series = fix_chars(series[0], is_letters=True) + fix_chars(series[1], is_digits=True)
                else:
                    c0 = fix_chars(series[0], is_letters=True)
                    c1 = fix_chars(series[1], is_letters=True) if series[1].isalpha() else fix_chars(series[1], is_digits=True)
                    series = c0 + c1
        elif len(series) == 1:
            series = fix_chars(series[0], is_letters=True)

        line1_fixed = f"{prov_code}-{series}" if series else prov_code

        line2_fixed = fix_chars(line2, is_digits=True)
        # Vietnamese plates have at most 5 digits on line 2. Trim any stray OCR char.
        line2_fixed = line2_fixed[:5]
        if len(line2_fixed) == 5:
            line2_fixed = f"{line2_fixed[:3]}.{line2_fixed[3:]}"
        elif len(line2_fixed) == 4:
            line2_fixed = f"{line2_fixed[:2]}.{line2_fixed[2:]}"

        formatted_text = f"{line1_fixed} {line2_fixed}"

    elif len(res) == 1:
        text = re.sub(r'[^a-zA-Z0-9]', '', res[0][1])
        if len(text) >= 5:
            prov_code = fix_chars(text[:2], is_digits=True)
            first_letter_idx = -1
            for i, c in enumerate(text[2:]):
                if c.isalpha():
                    first_letter_idx = i + 2
                    break
            if first_letter_idx != -1:
                series = fix_chars(text[first_letter_idx:first_letter_idx+1], is_letters=True)
                rest = fix_chars(text[first_letter_idx+1:], is_digits=True)
                if len(rest) == 5:
                    rest = f"{rest[:3]}.{rest[3:]}"
                formatted_text = f"{prov_code}{series}-{rest}"
            else:
                formatted_text = fix_chars(text, is_digits=True)
        else:
            formatted_text = text

    return formatted_text


def detect_plate_location(gray, edged):
    """Find the best license plate rectangle in the frame."""
    keypoints = cv2.findContours(edged.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = imutils.grab_contours(keypoints)
    if not contours:
        return None
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    # Try to find a 4-corner rectangle
    for contour in contours:
        approx = cv2.approxPolyDP(contour, 10, True)
        if len(approx) == 4:
            return approx

    # Fallback: bounding box of any large plate-shaped blob
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = w / float(h)
        area = cv2.contourArea(contour)
        rect_area = w * h
        solidity = float(area) / rect_area if rect_area > 0 else 0
        if 0.5 < aspect_ratio < 5.0 and area > 1000 and solidity > 0.5:
            return np.array([[[x, y]], [[x+w, y]], [[x+w, y+h]], [[x, y+h]]])

    return None


def preprocess_crop(img):
    """Upscale and sharpen a grayscale plate crop for better OCR accuracy."""
    # 1. Upscale 3x — EasyOCR works much better on larger images
    h, w = img.shape
    img = cv2.resize(img, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
    
    # 2. Adaptive histogram equalization for better contrast on dirty/dark plates
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    img = clahe.apply(img)
    
    # 3. Mild sharpening kernel
    kernel = np.array([[0, -1, 0],
                        [-1, 5, -1],
                        [0, -1, 0]])
    img = cv2.filter2D(img, -1, kernel)
    
    return img


def main():
    print("Initializing OCR (this may download models on first run)...")
    reader = easyocr.Reader(['en'], gpu=False)

    # Create output folder for saved plates
    output_dir = "plates"
    os.makedirs(output_dir, exist_ok=True)
    print(f"Plate images will be saved to: {os.path.abspath(output_dir)}")

    print("Opening video capture...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open video capture.")
        return

    # ─── Stabilization state ───────────────────────────────────────────
    # We only commit a plate after seeing the SAME text for VOTE_THRESHOLD
    # frames in a row. This prevents one-frame flukes from being logged.
    VOTE_THRESHOLD = 5

    vote_text      = None   # The plate text being voted on
    vote_count     = 0      # How many consecutive frames agreed
    vote_best_conf = 0.0    # Best confidence seen so far for this candidate
    vote_best_crop = None   # Best cropped plate image (grayscale)
    vote_best_frame = None  # Best full annotated frame (BGR)

    committed_plates = set()  # Keys of plates already saved this session
    # ────────────────────────────────────────────────────────────────────

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        display_frame = frame.copy()

        small_frame = imutils.resize(frame, width=640)
        gray   = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
        bfilt  = cv2.bilateralFilter(gray, 11, 17, 17)
        edged  = cv2.Canny(bfilt, 30, 200)

        location = detect_plate_location(gray, edged)

        this_text  = None
        this_conf  = 0.0
        this_crop  = None

        if location is not None:
            mask = np.zeros(gray.shape, np.uint8)
            cv2.drawContours(mask, [location], 0, 255, -1)

            xs, ys = np.where(mask == 255)
            if len(xs) > 0:
                x1, y1 = int(np.min(xs)), int(np.min(ys))
                x2, y2 = int(np.max(xs)), int(np.max(ys))
                crop = gray[x1:x2+1, y1:y2+1]

                # Show debug window
                cv2.imshow('Cropped Plate', imutils.resize(crop, width=220))

                try:
                    # Preprocess crop before OCR
                    proc_crop = preprocess_crop(crop)

                    res = reader.readtext(
                        proc_crop,
                        allowlist='0123456789ABCDEFGHJKLMNPRSTUVWXYZ.- ',
                        paragraph=False,
                        width_ths=0.5,
                        height_ths=0.5,
                        min_size=10,
                        text_threshold=0.5,
                        low_text=0.3,
                    )
                    text = process_plate(res)

                    if text and len(text) >= 5:
                        conf = sum(r[2] for r in res) / len(res)

                        # Live overlay (always shown, even if not yet stable)
                        cv2.polylines(display_frame, [location], True, (0, 255, 0), 3)
                        cv2.putText(display_frame, text,
                                    (location[0][0][0], location[0][0][1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                    (0, 255, 0), 2, cv2.LINE_AA)

                        if conf >= 0.5:
                            this_text = text
                            this_conf = conf
                            this_crop = crop

                except Exception:
                    pass

        # ─── Vote / stabilize ──────────────────────────────────────────
        if this_text is not None:
            if this_text == vote_text:
                vote_count += 1
                if this_conf > vote_best_conf:
                    vote_best_conf  = this_conf
                    vote_best_crop  = this_crop
                    vote_best_frame = display_frame.copy()
            else:
                # New candidate — restart vote
                vote_text       = this_text
                vote_count      = 1
                vote_best_conf  = this_conf
                vote_best_crop  = this_crop
                vote_best_frame = display_frame.copy()

            # Commit once stable
            if vote_count >= VOTE_THRESHOLD and vote_text not in committed_plates:
                committed_plates.add(vote_text)
                key = vote_text.replace(" ", "_").replace("-", "").replace(".", "")

                if vote_best_crop is not None:
                    cv2.imwrite(os.path.join(output_dir, f'plate_{key}_crop.png'), vote_best_crop)
                if vote_best_frame is not None:
                    cv2.imwrite(os.path.join(output_dir, f'plate_{key}_full.png'), vote_best_frame)

                print(f"[DA LUU] {vote_text}  (do chinh xac: {vote_best_conf:.0%})  -> plates/plate_{key}_crop.png & plates/plate_{key}_full.png")
        else:
            # Nothing detected → reset vote
            vote_text       = None
            vote_count      = 0
            vote_best_conf  = 0.0
            vote_best_crop  = None
            vote_best_frame = None
        # ──────────────────────────────────────────────────────────────

        cv2.imshow('License Plate Detection', display_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
