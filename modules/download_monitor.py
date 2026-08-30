import logging
import threading
import time

from pytubefix import YouTube
from modules.metrics import MetricsHandler


TEST_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def monitor_download():
    start = time.time()

    try:
        video = YouTube(TEST_VIDEO_URL)

        stream = (
            video.streams.filter(
                resolution="360p",
                progressive=True,
            )
            .order_by("resolution")
            .desc()
            .first()
        )

        if stream is None:
            raise Exception("No suitable stream found")

        stream.download(
            output_path="/dev",
            filename="null",
        )

        duration = time.time() - start

        MetricsHandler.download_monitor_success.set(1)
        MetricsHandler.download_monitor_duration_seconds.set(duration)

        logging.info(f"Download monitoring succeeded in {duration:.2f} seconds")

    except Exception as e:
        MetricsHandler.download_monitor_success.set(0)
        MetricsHandler.download_monitor_failures_total.inc()
        logging.exception(f"Download monitoring failed: {e}")


def start_download_monitor(interval: int):
    def monitor_loop():
        while True:
            monitor_download()
            time.sleep(interval)

    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()