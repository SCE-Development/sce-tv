import logging
import os
import shutil
import tempfile
import time

from modules.cache import Cache
from modules.metrics import MetricsHandler


TEST_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def monitor_download(interval: int, download_path: str):
    while True:
        start = time.time()
        temp_dir = tempfile.mkdtemp(dir=download_path)

        try:
            cache = Cache(file_path=temp_dir)
            cache.add(TEST_VIDEO_URL)

            duration = time.time() - start
            MetricsHandler.download_monitor_success.set(1)
            MetricsHandler.download_monitor_duration_seconds.set(duration)

            logging.info("Download monitoring succeeded")

        except Exception as e:
            MetricsHandler.download_monitor_success.set(0)
            MetricsHandler.download_monitor_failures_total.inc()
            logging.exception(f"Download monitoring failed: {e}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        time.sleep(interval)

