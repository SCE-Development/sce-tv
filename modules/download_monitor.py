import logging
import threading
import time

from pytubefix import YouTube

from modules.metrics import MetricsHandler


TEST_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def monitor_download() -> None:
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
            raise RuntimeError("No suitable stream found")

        bytes_downloaded = stream.filesize

        if bytes_downloaded is None:
            raise RuntimeError("Unable to determine stream file size")

        stream.download(
            output_path="/dev",
            filename="null",
        )

        duration = time.time() - start

        if duration <= 0:
            raise RuntimeError("Download duration must be greater than zero")

        bitrate = bytes_downloaded / duration

        MetricsHandler.download_monitor_success.set(1)
        MetricsHandler.download_monitor_duration_seconds.set(duration)
        MetricsHandler.download_bitrate_latest_bytes_per_second.set(bitrate)
        MetricsHandler.download_bitrate_bytes_per_second.observe(bitrate)

        logging.info(
            "Download monitoring succeeded in %.2f seconds "
            "with bitrate %.2f bytes/sec",
            duration,
            bitrate,
        )

    except Exception as error:
        duration = time.time() - start

        MetricsHandler.download_monitor_success.set(0)
        MetricsHandler.download_monitor_duration_seconds.set(duration)
        MetricsHandler.download_monitor_failures_total.inc()

        logging.exception("Download monitoring failed: %s", error)


def start_download_monitor(interval: int) -> None:
    def monitor_loop() -> None:
        while True:
            monitor_download()
            time.sleep(interval)

    thread = threading.Thread(
        target=monitor_loop,
        daemon=True,
        name="download-monitor",
    )
    thread.start()