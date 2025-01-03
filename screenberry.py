import json
import logging
import socket
import time
import traceback
import uuid
from io import BytesIO

import boto3
import requests
from PIL import Image
from dotenv import load_dotenv
from flask import Response
from flask import g
from flask import request
from flask_caching import Cache
from flask_openapi3 import Info, Server, OpenAPI, Tag
from pyinstrument import Profiler
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.remote.remote_connection import LOGGER
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from models import scan_request
from utils.ocr_login_detection import ocr_login_detection
from utils.script_crawler import script_crawler
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

MAX_WORKER_COUNT = int(os.environ.get("MAX_WORKER_COUNT", str(os.cpu_count() * 2)))
logging.info(f"Setting MAX_WORKER_COUNT = {MAX_WORKER_COUNT}")

S3_WRITE_ENDPOINT = get_env("S3_WRITE_ENDPOINT")
S3_READ_HOSTNAME = get_env("S3_READ_HOSTNAME")
S3_READ_SCHEME = get_env("S3_READ_SCHEME")
S3_BUCKET_NAME = get_env("S3_BUCKET_NAME")
S3_ACCESS_KEY = get_env("S3_ACCESS_KEY")
S3_PRIVATE_KEY = get_env("S3_PRIVATE_KEY")

APP_NAME = get_env("APP_NAME")

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

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

screenberry.config.from_mapping({
    "DEBUG": True,
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_HOST": REDIS_HOST,
    "CACHE_REDIS_PORT": REDIS_PORT,
    "CACHE_REDIS_PASSWORD": REDIS_PASSWORD,
    "CACHE_KEY_PREFIX": "screenberry_",
    "CACHE_DEFAULT_TIMEOUT": 300
})

request_cache = Cache(screenberry)


@screenberry.get('/api/v1/screenshot/domain/<string:domain>')
@request_cache.cached(timeout=600, unless=lambda: request.args.get("bypass_cache", "0") == "1")
def scan_domain(path: scan_request.DomainRequest, query: scan_request.DomainRequestParams):

    # TODO: sanitize input

    return _scan_domain(path.domain, query.uri_scheme, float(query.pageload_wait_seconds), int(query.timeout))


def get_webdriver(url, timeout):

    time_start = time.time()

    firefox_options = Options()
    firefox_options.add_argument("--width=1920")
    firefox_options.add_argument("--height=1080")
    firefox_options.set_preference("layout.css.devPixelsPerPx", "2.0")
    firefox_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    firefox_profile = webdriver.FirefoxProfile()
    firefox_profile.accept_untrusted_certs = True
    firefox_profile.set_preference("http.response.timeout", timeout)
    firefox_profile.set_preference("dom.max_script_run_time", timeout)

    firefox_options.profile = firefox_profile

    # Create a remote WebDriver session
    driver = webdriver.Remote(
        command_executor=SELENIUM_REMOTE_API,
        options=firefox_options
    )
    driver.set_page_load_timeout(timeout)

    # Set the window size
    # driver.set_window_size(1920, 1080)

    logging.info(f"webdriver firefox init took: {time.time() - time_start:.2f} seconds")

    time_start = time.time()
    driver.get(url)
    WebDriverWait(driver, 1).until(expected_conditions.presence_of_element_located((By.TAG_NAME, "body")))

    logging.info(f"page load took: {time.time() - time_start:.2f} seconds")

    return driver


def _scan_domain(domain: str, uri_scheme: str, pageload_wait_seconds: float, timeout: int):

    profiler = Profiler()
    profiler.start()

    url = uri_scheme + "://" + domain
    request_id = uuid.uuid4()

    logging.info(f"Request id {request_id}: {url}")

    # Get page source html
    page_raw = requests.get(url, verify=False).text
    page_raw_presigned_url = upload_s3(f"page_raw_{request_id}.html", BytesIO(bytes(page_raw, 'utf-8')), "text/html", link_expire_seconds=7 * 24 * 60 * 60)
    logging.info("page_raw_presigned_url: " + page_raw_presigned_url)


    try:
        # Create a remote WebDriver session
        driver = get_webdriver(url, timeout)
        time.sleep(pageload_wait_seconds)
    except WebDriverException as e:
        logging.error(e)
        profiler.stop()
        return {
            "status": "success",
            "domain": domain,
            "uri_scheme": uri_scheme,
            "request_id": request_id,
            "result": {
                "html": {
                    "page_raw_presigned_url": page_raw_presigned_url,
                    "page_raw_size": len(page_raw),
                },
            },
            "webdriver_exception": str(e.msg)
        }
    except Exception as e:
        logging.error(e)
        traceback.print_exc()
        return {
            "error": str(e)
        }

    # Get page title
    site_title = driver.title
    logging.info(f"Screenshot taken for site: {site_title}")
    current_url = driver.current_url
    logging.info(f"Current url: {current_url}")

    page_html = driver.page_source
    page_html_presigned_url = upload_s3(f"html_{request_id}.html", BytesIO(bytes(page_html, 'utf-8')), "text/html", link_expire_seconds=7 * 24 * 60 * 60)
    logging.info("page_html_presigned_url: " + page_html_presigned_url)

    # Capture screenshot in PNG format directly into memory
    screenshot_png = driver.get_screenshot_as_png()

    # Convert the screenshot to a PIL image
    screenshot_image = Image.open(BytesIO(screenshot_png))

    ocr_time_start = time.time()
    predict_login_page, predict_login_page_psm, list_extracted_text = ocr_login_detection(screenshot_image, ["login", "log in", "sign in", "single sign", "dang nhap", "password", "mat khau"])
    logging.info(f"OCR login detection took: {time.time() - ocr_time_start:.2f} seconds")

    # Convert PNG to JPG
    img = Image.open(BytesIO(screenshot_png)).convert("RGB")
    img_bytes = BytesIO()
    img.save(img_bytes, format="JPEG", quality=70)
    img_bytes.seek(0)  # Reset pointer to the beginning

    # Generate pre-signed URL (7 days)
    screenshot_presigned_url = upload_s3(f"screenshot_{request_id}.jpg", img_bytes, "image/jpeg", link_expire_seconds=7 * 24 * 60 * 60)
    logging.info(screenshot_presigned_url)

    # Extract script
    script_tags = driver.find_elements(By.TAG_NAME, "script")
    scripts = script_crawler(script_tags)

    # Extract hrefs
    hrefs = []
    elems = driver.find_elements(by=By.XPATH, value="//a[@href]")
    for elem in elems:
        href = elem.get_attribute("href")
        logging.info(f"Found href: {href}")
        hrefs.append(href)
    logging.info(f"Found {len(hrefs)} hrefs before duplicate removal")
    hrefs = list(set(hrefs))  # Dedup

    profiler.stop()
    profiler_presigned_url = upload_s3(f"profiler_{request_id}.html", BytesIO(profiler.output_html().encode()), "text/html", link_expire_seconds=7 * 24 * 60 * 60)

    # Quit the driver
    logging.info("Shutting down driver ...")
    driver.quit()

    return {
        "status": "success",
        "domain": domain,
        "uri_scheme": uri_scheme,
        "request_id": request_id,
        "result": {
            "html": {
                "page_html_presigned_url": page_html_presigned_url,
                "page_html_size": len(page_html),

                "page_raw_presigned_url": page_raw_presigned_url,
                "page_raw_size": len(page_raw),
            },
            "profiler": {
                "profiler_presigned_url": profiler_presigned_url,
            },
            "screenshot": {
                "screenshot_presigned_url": screenshot_presigned_url,
            },

            "current_url": current_url,
            "site_title": site_title,
            "predict_login_page": predict_login_page,
            "predict_login_page_psm": predict_login_page_psm,
            "extracted_text": list_extracted_text,
            "scripts": scripts,
            "hrefs": hrefs,
            "domain_redirected": domain not in current_url
        }
    }


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
        endpoint_url=S3_READ_SCHEME + '://' + S3_READ_HOSTNAME,
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
        "backend": APP_NAME + "-" + socket.gethostname(),
        "version": "1.0"
    }

    return Response(json.dumps(r), mimetype='application/json')


if __name__ == '__main__':
    screenberry.run(host='0.0.0.0', port=8082, debug=False)
