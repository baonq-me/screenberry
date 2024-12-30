from datetime import time
from typing import List
import logging
import hashlib
import asyncio
import aiohttp
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from selenium.webdriver.remote.webelement import WebElement


def fetch(url):

    time_start = time.time()
    response_text = requests.get(url, verify=False).text
    content_f64 = response_text[:64]
    content_sha256 = hashlib.sha256(response_text.encode('utf-8')).hexdigest()

    logging.info(f"Fetch done in {time.time() - time_start:.2f}s: {url}")

    return {
        "type": "external",
        "src": url,
        "content_f64": content_f64,
        "content_sha256": content_sha256
    }


def script_crawler(script_tags: List[WebElement]):

    time_start = time.time()

    scripts = []

    # script that need to manually fetch
    list_url = []

    for script in script_tags:
        try:
            src = script.get_attribute('src')
        except Exception as e:
            scripts.append({"error": str(e)})
            continue

        if src:
            if "http" not in src and "https" not in src:
                continue

            list_url.append(src)
        else:
            content = script.get_attribute('innerHTML')
            if len(content or "") == 0:
                continue

            content_f64 = content[:64]
            content_sha256 = hashlib.sha256(content.encode('utf-8')).hexdigest()
            scripts.append({"type": "inline", "content_f64": content_f64, "content_sha256": content_sha256})

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(fetch, url): url for url in list_url}
        for future in as_completed(futures):
            scripts.append(future.result())

    logging.info(f"Script crawler took: {time.time() - time_start:.2f} seconds")

    return scripts
