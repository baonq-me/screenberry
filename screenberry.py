import hashlib
import json
import logging
import socket
import traceback
from io import BytesIO

import boto3
import cv2
import numpy as np
import pytesseract
import requests
from PIL import Image, ImageEnhance, ImageFilter
from dotenv import load_dotenv
from flask import Response
from flask import g
from flask_openapi3 import Info, Server, OpenAPI, Tag
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.remote.remote_connection import LOGGER
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait
import time
import uuid
from models import scan_request
from utils.utils import *

LOGGER.setLevel(logging.INFO)

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(".env")

logging.basicConfig(  # filename="/dev/stdout",
    filemode='a',
    format='[%(asctime)s,%(msecs)d] [%(threadName)s] [%(filename)s:%(lineno)d] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=os.environ.get('LOGLEVEL', 'INFO').upper())

logging.warning("This should be run inside a container with root permission to ensure its correctness")

MAX_WORKER_COUNT = int(os.environ.get("MAX_WORKER_COUNT", str(os.cpu_count() * 2)))
logging.info(f"Setting MAX_WORKER_COUNT = {MAX_WORKER_COUNT}")

S3_WRITE_ENDPOINT = get_env("S3_WRITE_ENDPOINT")
S3_READ_ENDPOINT = get_env("S3_READ_ENDPOINT")
S3_BUCKET_NAME = get_env("S3_BUCKET_NAME")
S3_ACCESS_KEY = get_env("S3_ACCESS_KEY")
S3_PRIVATE_KEY = get_env("S3_PRIVATE_KEY")

SELENIUM_REMOTE_API = os.environ.get("SELENIUM_REMOTE_SERVER", "http://localhost:4444") + "/wd/hub"


def create_app():
    flask_app = OpenAPI(
        __name__,
        info=Info(title="screenberry API", version="1.0.0"),
        servers=[
            Server(url="http://127.0.0.1:8082"),
            Server(url="http://127.0.0.1:8080"),
            Server(url="https://screenberry.baonq.me")
        ],
    )
    return flask_app


screenberry = create_app()

@screenberry.get('/v1/screenshot/domain/<string:domain>')
def scan_domain(path: scan_request.DomainRequest, query: scan_request.DomainRequestParams):

    url = "https://" + path.domain
    request_id = uuid.uuid4()

    logging.info(f"Request id {request_id}: {url}")


    timeout = int(query.timeout)

    time_start = time.time()

    firefox_options = Options()
    # firefox_options.add_argument("--width=3456")
    # firefox_options.add_argument("--height=2234")
    firefox_options.add_argument("--width=1920")
    firefox_options.add_argument("--height=1080")
    firefox_options.set_preference("layout.css.devPixelsPerPx", "2.0")
    # firefox_options.set_preference("layout.css.devPixelsPerPx", "2.0")  # Change "2.0" to the desired scaling factor

    # Create a remote WebDriver session
    driver = webdriver.Remote(
        command_executor=SELENIUM_REMOTE_API,
        options=firefox_options
    )

    try:
        # Set the window size to 1280x768
        #driver.set_window_size(1920, 1080)
        #driver.set_window_size(3456, 2234)

        # Navigate to the desired URL
        driver.get(url)  # Change this to the URL you want to capture

        WebDriverWait(driver, timeout).until(expected_conditions.presence_of_element_located((By.TAG_NAME, "body")))

        # Wait 5 seconds to load page
        time.sleep(5)

        # Get page title
        site_title = driver.title
        logging.info(f"Screenshot taken for site: {site_title}")
        current_url = driver.current_url
        logging.info(f"Current url: {current_url}")

        # Extract script
        script_tags = driver.find_elements(By.TAG_NAME, "script")
        scripts = []
        for script in script_tags:
            src = script.get_attribute('src')
            if src:
                logging.info(f"src: {src}")
                content = requests.get(src).text
                content_f64 = content[:64]
                content_sha256 = hashlib.sha256(content.encode('utf-8')).hexdigest()
                scripts.append({"type": "external", "src": src, "content_f64": content_f64, "content_sha256": content_sha256})
            else:
                content = script.get_attribute('innerHTML')
                content_f64 = content[:64]
                content_sha256 = hashlib.sha256(content.encode('utf-8')).hexdigest()
                scripts.append({"type": "inline", "content_f64": content_f64, "content_sha256": content_sha256})

        # Get page source html
        page_html = driver.page_source
        page_html_presigned_url = upload_s3(f"html_{request_id}.html", BytesIO(bytes(page_html, 'utf-8')), "text/html", link_expire_seconds=7 * 24 * 60 * 60)
        logging.info(page_html_presigned_url)


        # Capture screenshot in PNG format directly into memory
        screenshot_png = driver.get_screenshot_as_png()

        # Convert the screenshot to a PIL image
        screenshot_image = Image.open(BytesIO(screenshot_png))

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
        extracted_text = ''
        for psm in range(1,14):

            if predict_login_page:
                break

            try:
                extracted_text = pytesseract.image_to_string(Image.fromarray(refined_image), lang="eng+vie", config=f"--oem 3 --psm {psm}")
            except Exception as ex:
                logging.error(f"Error with psm = {psm}: {ex}")
                continue

            extracted_text = remove_vietnamese_diacritics(extracted_text.lower()).replace('  ', ' ').replace("\n", " ").encode('ascii', errors='ignore').decode()
            # logging.info(f"[psm={psm}] OCR output text: {extracted_text}")

            for keyword in ["login", "log in", "sign in", "single sign", "dang nhap", "password", "mat khau"]:
                if keyword in extracted_text:
                    logging.warning(f"[psm={psm}] Possible login form detected in OCR output text with keyword: {keyword}")
                    predict_login_page = True
                    break

                if keyword in remove_vietnamese_diacritics(site_title.lower()):
                    logging.warning(f"[psm={psm}] Possible login form detected in page title text with keyword: {keyword}")
                    predict_login_page = True
                    break

        logging.info(f"OCR extracted text: {extracted_text}")

        # Convert PNG to JPG in memory
        img = Image.open(BytesIO(screenshot_png)).convert("RGB")
        img_bytes = BytesIO()
        img.save(img_bytes, format="JPEG", quality=70)
        img_bytes.seek(0)  # Reset pointer to the beginning

        # Generate pre-signed URL (7 days)
        screenshot_presigned_url = upload_s3(f"screenshot_{request_id}.jpg", img_bytes, "image/jpeg", link_expire_seconds=7 * 24 * 60 * 60)
        logging.info(screenshot_presigned_url)

        return {
            "status": "success",
            "time_total_ms": round((time.time() - time_start) * 1000),
            "domain": path.domain,
            "result": {
                "screenshot_presigned_url": screenshot_presigned_url,
                "page_html_presigned_url": page_html_presigned_url,
                "site_title": site_title,
                "predict_login_page": predict_login_page,
                "predict_login_page_text": "" if not predict_login_page else extracted_text,
                "scripts": scripts
            }
        }

    except Exception as ex:
        logging.error(ex)
        traceback.print_exc()

        return {
            "status": "error",
            "exception": ex
        }

    finally:
        # Quit the driver
        logging.info("Shutting down driver ...")
        driver.quit()


def upload_s3(filename, data, content_type, link_expire_seconds=24 * 60 * 60):

    # Initialize S3 client with custom endpoint and disable SSL verification if provided
    s3_write_client = boto3.client(
        's3',
        endpoint_url=S3_WRITE_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_PRIVATE_KEY,
        region_name="vn",
        verify=False
    )

    # Upload JPG to S3
    s3_write_client.upload_fileobj(data, S3_BUCKET_NAME, filename, ExtraArgs={'ContentType': content_type})
    logging.info(f"Uploaded to s3://{S3_BUCKET_NAME}/{filename}")

    s3_read_client = boto3.client(
        's3',
        endpoint_url=S3_READ_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_PRIVATE_KEY,
        region_name="vn",
        verify=False
    )

    # Generate pre-signed URL (7 days)
    return s3_read_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': S3_BUCKET_NAME, 'Key': filename},
        ExpiresIn=link_expire_seconds # 7 * 24 * 60 * 60  # 7 days in seconds
    )

@screenberry.before_request
def before_request():
    g.time_start = time.time()


@screenberry.after_request
def after_request(response):
    if 'time_start' not in g:
        return response

    time_end = time.time()
    response.headers['X-Execution-Time-Ms'] = round((time_end - g.time_start)*1000, 2)
    response.headers['X-Time-Start'] = int(g.time_start)
    response.headers['X-Time-End'] = int(time_end)
    return response


def remove_vietnamese_diacritics(text):
    """
    Converts a string to a slug by:
    - Removing accents and replacing special characters.
    - Converting to lowercase.
    - Replacing spaces and non-alphanumeric characters with '-'.
    - Removing extra dashes.

    Args:
        s (str): The input string.

    Returns:
        str: The slugified version of the string.
    """
    # Define the mapping for removing accents
    from_chars = "àáãảạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệđùúủũụưừứửữựòóỏõọôồốổỗộơờớởỡợìíỉĩịäëïîöüûñçýỳỹỵỷ"
    to_chars = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeduuuuuuuuuuuoooooooooooooooooiiiiiaeiiouuncyyyyy"
    translation_table = str.maketrans(from_chars, to_chars)

    # Remove accents
    return text.translate(translation_table)


@screenberry.get('/', summary="Home", tags=[Tag(name="Index", description="Index page")])
def index():
    r = {
        "service_name": "screenberry",
        "description": "Screenshot web page and extract text",
        "api_doc": "/openapi/swagger",
        "production_endpoint": "http://127.0.0.1",
        "production_ip": "127.0.0.1",
        "links": {
            "doc": "...",
        },
        "backend": socket.gethostname(),
        "version": "1.0"
    }

    return Response(json.dumps(r), mimetype='application/json')


if __name__ == '__main__':
    screenberry.run(host='0.0.0.0', port=8082, debug=False)
