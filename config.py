"""gunicorn WSGI server configuration."""
import os
from multiprocessing import cpu_count
from os import environ
import gunicorn

bind = '0.0.0.0:8080'
max_requests = 1000
worker_class = 'sync'
workers = int(os.getenv("GUNICORN_WORKERS", cpu_count))
gunicorn.SERVER = 'undisclosed'
preload_app = True
