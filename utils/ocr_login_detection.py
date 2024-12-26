import time

import cv2
from PIL import Image, ImageEnhance, ImageFilter
from PIL.ImageFile import ImageFile
import pytesseract

from utils.utils import remove_vietnamese_diacritics
import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed


def extract_text_using_pytesseract(img, psm, time_start):

    try:
        text = pytesseract.image_to_string(Image.fromarray(img), lang="eng+vie", config=f"--oem 3 --psm {psm}")
        time_taken_ms = round((time.time() - time_start)*1000)

        return text, "", psm, time_taken_ms

    except Exception as e:
        logging.error(e)
        return "", str(e), 0, round((time.time() - time_start)*1000)


def ocr_login_detection(screenshot_image: ImageFile, keywords: list[str]):

    # Preprocess the image
    # Convert to grayscale
    gray_image = screenshot_image.convert("L")

    # Enhance the image contrast
    enhancer = ImageEnhance.Contrast(gray_image)
    enhanced_image = enhancer.enhance(2.0)

    # Apply a slight blur to remove noise
    blurred_image = enhanced_image.filter(ImageFilter.MedianFilter(size=3))

    # Convert the image to OpenCV format for additional processing
    open_cv_image = np.array(blurred_image)

    # Apply thresholding to binarize the image
    _, refined_image = cv2.threshold(open_cv_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Extract text using pytesseract
    # https://stackoverflow.com/questions/44619077/pytesseract-ocr-multiple-config-options
    # Automatic page segmentation with Orientation and script detection, use Long short-term memory engine.
    # psm = 1,3,4,9 should work

    predict_login_page = False
    list_extracted_text = []

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(extract_text_using_pytesseract, refined_image, psm, time.time()): psm for psm in range(1, 14)}
        for future in as_completed(futures):
            extracted_text, error, psm, time_taken_ms = future.result()

            if error != "":
                list_extracted_text.append({
                    "method": f"osm=3,psm={psm}",
                    "error": error
                })

                continue

            extracted_text = extracted_text.replace('  ', ' ').replace("\n", " ")
            extracted_text = extracted_text.encode('ascii', errors='ignore').decode()
            extracted_text = remove_vietnamese_diacritics(extracted_text.lower())
            logging.info(f"OCR extracted text in {time_taken_ms} ms -> {extracted_text}")

            list_extracted_text.append({
                "method": f"osm=3,psm={psm}",
                "text": extracted_text
            })

            for keyword in keywords:
                if keyword in extracted_text:
                    logging.warning(f"[psm={psm}] Possible login form detected in OCR output text with keyword: {keyword}")
                    predict_login_page = True
                    break

    return predict_login_page, list_extracted_text
