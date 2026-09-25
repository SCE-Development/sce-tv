import argparse
import json
import logging
import queue
import threading
import time
import urllib.request
from urllib.parse import urlparse
import vlc
from prometheus_client import start_http_server, Gauge

# --- Prometheus Metrics ---
stream_running = Gauge(
    "receive_stream_running",
    "Indicates whether the received stream is running (1=running, 0=stopped)"
)

# Replaced Info metric with a Gauge so label values can be toggled to 0
stream_current_url = Gauge(
    "receive_stream_current_url",
    "Indicates which RTMP stream URL is currently active (1=active, 0=inactive)",
    ["url"]
)

# --- State & Synchronization ---
receive_weather = threading.Event()
receive_sce_tv = threading.Event()
commands = queue.Queue()


def get_stream_state(ip, timeout=5):
    """Ask the sce-tv server at the given IP for the current state ('idle' or 'playing')."""
    url = f"http://{ip}/tv/state"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read())
        return "playing" if data.get("state") == "playing" else "idle"
    except Exception:
        logging.exception("Could not reach sce-tv server at %s", url)
        return None


def stream_is_dead(player):
    """Check whether the VLC player has stopped, ended, or errored."""
    state = player.get_state()
    if state in [vlc.State.Stopped, vlc.State.Ended, vlc.State.Error]:
        logging.warning("Stream state indicates stream is dead: %s", state)
        return True
    return False


def set_active_stream_metric(new_url, previous_url, all_urls):
    """Ensures only the currently active stream URL metric is 1, and others are 0."""
    # Ensure every known URL is initialized in Prometheus if not already present
    for u in all_urls.values():
        if u:
            stream_current_url.labels(url=u).set(0)

    # Explicitly clear previous URL to 0 and active URL to 1
    if previous_url:
        stream_current_url.labels(url=previous_url).set(0)
    if new_url:
        stream_current_url.labels(url=new_url).set(1)


def receive_stream(instance, player, urls):
    """Handles stream playback, dynamic switching, and Prometheus metric updates."""
    current_target = receive_sce_tv
    current_url = urls[current_target]

    if current_url:
        set_active_stream_metric(current_url, previous_url=None, all_urls=urls)
        media = instance.media_new(current_url)
        player.set_media(media)
        player.play()
        logging.info("Starting initial playback for: %s", current_url)

    time.sleep(5)  # Buffer warm-up period

    while True:
        try:
            # Check for stream switch commands
            try:
                command = commands.get(block=False)
                new_url = urls[command]

                if new_url and new_url != current_url:
                    logging.info("Switching stream to %s...", new_url)
                    set_active_stream_metric(new_url, previous_url=current_url, all_urls=urls)
                    current_url = new_url

                    player.stop()
                    media = instance.media_new(current_url)
                    player.set_media(media)
                    player.play()
                    time.sleep(2)
            except queue.Empty:
                pass

            # Update health metric based on player state
            if player.is_playing() and not stream_is_dead(player):
                stream_running.set(1)
            else:
                stream_running.set(0)

        except Exception as e:
            logging.error("Playback monitor loop error: %s", e)
            stream_running.set(0)

        time.sleep(1)


def signal(ip, weather_url, interval=5):
    """Periodically queries the backend state and pushes target stream changes."""
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
        level=logging.INFO
    )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sce-tv-rtmp-url",
        required=True,
        help="RTMP stream URL (e.g. rtmp://server/live/streamkey)"
    )
    parser.add_argument(
        "--weather-rtmp-url",
        help="Weather channel RTMP stream URL (e.g. rtmp://server/live/weather)"
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=8000,
        help="Port to expose Prometheus metrics on (default: 8000)"
    )
    args = parser.parse_args()

    # Start Prometheus Exporter
    start_http_server(args.metrics_port)
    logging.info("Prometheus metrics server started on port %d", args.metrics_port)

    # Derive backend host IP from the main stream URL
    sce_tv_ip = urlparse(args.sce_tv_rtmp_url).hostname

    urls = {
        receive_sce_tv: args.sce_tv_rtmp_url,
        receive_weather: args.weather_rtmp_url,
    }

    # Initial state setup
    receive_sce_tv.set()

    # Initialize VLC player
    instance = vlc.Instance()
    player = instance.media_player_new()

    # Run stream loop thread
    receive_stream_thread = threading.Thread(
        target=receive_stream,
        args=(instance, player, urls),
        daemon=True,
    )
    receive_stream_thread.start()

    # Run signal polling thread
    signal_thread = threading.Thread(
        target=signal,
        args=(sce_tv_ip, args.weather_rtmp_url),
        daemon=True,
    )
    signal_thread.start()

    # Keep main thread alive
    while True:
        time.sleep(1)
