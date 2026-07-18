import os
import shutil
import time
import threading
from modules.metrics import Metrics, MetricsHandler
from modules.args import get_args
from pytubefix import YouTube
from pytubefix.exceptions import RegexMatchError, VideoUnavailable

args = get_args()

def download_loop(interval):
    video_url = "https://www.youtube.com/watch?v=X96RjH8WC5o"
    while True:
        try:
            start_time = time.time()
            # Download YouTube video to a temp directory
            video =  YouTube(video_url)
            stream = video.streams.get_highest_resolution()
            os.makedirs("temp", exist_ok=True)
            download_path = stream.download(output_path="temp")
            if not os.path.exists(download_path):
                raise Exception()
            shutil.rmtree("temp", ignore_errors=True)
            end_time = time.time()

            # Calculate and update download speed and success metrics
            download_time = end_time - start_time
            video_size = stream.filesize
            if download_time > 0:
                speed = video_size / download_time 
            else:
                speed = "video did not download"
            MetricsHandler.download_speed.set(speed)
            MetricsHandler.download_success.labels(reason="video_downloaded").set(1)
        
        except VideoUnavailable:
            MetricsHandler.download_success.labels(reason="video_not_found").set(0)
        except RegexMatchError:
            MetricsHandler.download_success.labels(reason="regex_mismatch").set(0)
        except Exception:
            MetricsHandler.download_success.labels(reason="download_failed").set(0)
    
        time.sleep(interval)