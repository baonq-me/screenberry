# screenberry

Screenshot website, analyze and predict if the site show a login page

## Tech stack

- Programming language: Python + Gunicorn (parallel processing with `multiprocessing` and asynchronous processing with `concurrent.futures`)
- Web backend framework: Flask
- Screenshot website: Selenium Hub + Firefox
- Text extraction: Tesseract Open Source OCR Engine, image enhancement with Pillow + OpenCV
- S3 Storage: Minio
- Request caching: Redis
- Packaging: 
  - Docker compose with Apline base image, manually built to reduce container image size from 2.46 GB to 0.6 GB (for exchange, performance of Tesseract drop by 80% due to using `musl` on Alpine over `glibc` on other distro)
  - Load balancing and rolling upgrade capability with `docker compose scale`