import argparse
import json
import logging
import queue
import threading
import time
import urllib.request
from urllib.parse import urlparse
import vlc

receive_weather = threading.Event()
receive_sce_tv = threading.Event()

commands = queue.Queue()

def get_stream_state(ip, port=5001, timeout=5):

    # Ask the sce-tv server at the given IP for the current state, "idle" or "playing"
    url = f"http://{ip}:{port}/state"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read())
        return "playing" if data.get("state") == "playing" else "idle"
    except Exception:
        logging.exception("Could not reach sce-tv server at %s", url)
        return None

def receive_stream(instance, player, urls):

    media = instance.media_new(urls[receive_sce_tv])
    player.set_media(media)
    player.play()
    logging.info("Starting playback...")

    # Buffer
    time.sleep(5)

    # Consume state commands and switch the active stream to match
    while True:
        command = commands.get()
        url = urls[command]
        logging.info("switching stream to %s...", url)
        media = instance.media_new(url)
        player.set_media(media)
        player.play()

def signal(ip, weather_url, interval=5):

    # Defaults to sce-tv, only switches to weather when server is idle and weather url is provided, pushes command when the state changes
    while True:
        state = get_stream_state(ip)

        if weather_url and state == "idle":
            target = receive_weather
        else:
            target = receive_sce_tv

        if not target.is_set():
            receive_weather.clear()
            receive_sce_tv.clear()
            target.set()
            commands.put(target)

        time.sleep(interval)

if __name__ == "__main__":
    logging.Formatter.converter = time.gmtime

    logging.basicConfig(
        format="%(asctime)s.%(msecs)03dZ %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=logging.ERROR
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sce-tv-rtmp-url",
        required=True,
        help="RTMP stream URL (e.g. rtmp://server/live/streamkey)"
    )
    parser.add_argument(
        "--weather-rtmp-url",
        help="weather channel RTMP stream URL (e.g. rtmp://server/live/weather)"
    )
    args = parser.parse_args()

    # State API runs on the same host as the RTMP server, so derive it from the stream URL rather than passing the host separately
    sce_tv_ip = urlparse(args.sce_tv_rtmp_url).hostname

    urls = {
        receive_sce_tv: args.sce_tv_rtmp_url,
        receive_weather: args.weather_rtmp_url,
    }

    receive_sce_tv.set()

    instance = vlc.Instance()
    player = instance.media_player_new()

    receive_stream_thread = threading.Thread(
        target=receive_stream,
        args=(instance, player, urls),
        daemon=True,
    )
    receive_stream_thread.start()

    signal_thread = threading.Thread(
        target=signal,
        args=(sce_tv_ip, args.weather_rtmp_url),
        daemon=True,
    )
    signal_thread.start()

    while True:
        time.sleep(1)
