import argparse
import json
import threading
import time
import urllib.request
from urllib.parse import urlparse
import vlc

# Set when the sce-tv server reports "idle", cleared when it is "playing"
idle_event = threading.Event()

def get_stream_state(ip, port=5001, interval=5):

    # Continuously ask the sce-tv server at the given IP for the current state, "idle" or "playing"
    url = f"http://{ip}:{port}/state"
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read())
            state = "playing" if data.get("state") == "playing" else "idle"
            print(f"sce-tv state: {state}")
            if state == "idle":
                idle_event.set()
            else:
                idle_event.clear()
        except Exception as e:
            print(f"Could not reach sce-tv server at {url}: {e}")
        time.sleep(interval)

def play_stream(url):
    instance = vlc.Instance()
    player = instance.media_player_new()

    switch_stream(instance, player, url)
    print("Starting playback...")

    # Buffer
    time.sleep(5)

    return instance, player

def switch_stream(instance, player, url):
    media = instance.media_new(url)
    player.set_media(media)
    player.play()

def stream_switcher(instance, player, sce_tv_url, weather_url):

    # Swap the active stream depending on playing state
    # idle: weather channel, playing: sce-tv
    while True:
        # Block until the server reports idle, then switch to weather
        idle_event.wait()
        print("sce-tv idle, switching to the weather channel...")
        switch_stream(instance, player, weather_url)

        # Block until the server is playing, then switch to sce-tv
        while idle_event.is_set():
            time.sleep(1)
        print("sce-tv playing, switching back to sce-tv...")
        switch_stream(instance, player, sce_tv_url)

if __name__ == "__main__":
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

    state_thread = threading.Thread(
        target=get_stream_state,
        args=(sce_tv_ip,),
        daemon=True,
    )
    state_thread.start()

    instance, player = play_stream(args.sce_tv_rtmp_url)

    # Only enable idle-based switching when a weather channel URL is provided
    if args.weather_rtmp_url:
        switcher_thread = threading.Thread(
            target=stream_switcher,
            args=(instance, player, args.sce_tv_rtmp_url, args.weather_rtmp_url),
            daemon=True,
        )
        switcher_thread.start()

    while True:
        time.sleep(1)
