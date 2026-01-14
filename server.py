import enum
import os
import json
import subprocess
import threading
from urllib.parse import unquote
import uvicorn
import signal
import logging
import ssl
import time
from pathlib import Path
import asyncio  # Add this import for async queues
from dataclasses import dataclass
from typing import List, Tuple
from queue import Queue, Empty

ssl._create_default_https_context = ssl._create_stdlib_context

from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pytubefix import YouTube, Playlist
import pytubefix.exceptions
import prometheus_client
import psutil

from modules.args import get_args
from modules.cache import Cache
from modules.metrics import MetricsHandler


logging.Formatter.converter = time.gmtime
logging.basicConfig(
    # in mondo we trust
    format="%(asctime)s.%(msecs)03dZ %(threadName)s %(levelname)s:%(name)s:%(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

# Enum for the state of the video being processed
class State(enum.Enum):
    INTERLUDE = "interlude"
    PLAYING = "playing"


# Enum for the type of URL being processed
class UrlType(enum.Enum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    EMPTY = "empty"
    UNKNOWN = "unknown"

# Video Configuration
@dataclass
class VideoConfig:
    url_type: UrlType
    url: str
    loop: bool = False
    title: str = None
    thumbnail: str = None
    play_interlude_after: bool = True
    repeat: bool = False


# Create FastAPI instance
app = FastAPI()

# This dictionary is used to store the process IDs of running subprocesses, keyed by the type of video being processed (interlude or playing).
process_dict = {}

# This dictionary is used to store the title and thumbnail of the currently playing video.
current_video_dict = {}

# Threading Locks
interlude_lock = threading.Lock()

download_lock = threading.Lock()

args = get_args()

cancel_event = threading.Event()

# Create a cache object to store video files, initializing it with the file path specified in the command-line arguments or configuration settings. This instance is used to cache downloaded videos.
video_cache = Cache(file_path=args.videopath, cache_file=args.cache_state_file)

# Queue for video downloading
download_url_queue: Queue[VideoConfig] = Queue()

# Queue for completed videos
play_video_queue: Queue[Tuple[VideoConfig, str]] = Queue()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def http_request_count(request: Request, call_next):
    MetricsHandler.http_request_count.labels(endpoint=request.url.path).inc()
    return await call_next(request)


# return the result of process.wait()
def create_ffmpeg_stream(
    file_path: str,
    video_type: State,
    loop=False,
    title=None,
    thumbnail=None,
    play_interlude_after=True,
    announcement=False,
    duration=5
):
    if file_path is None:
        logging.info("file_path is None. ffmpeg_stream cancelled.")
        return 2

    if stop_all_processes():
        time.sleep(5)

    # Create a subprocess to stream the video using FFmpeg
    command = [
        "ffmpeg",
        "-re",
        "-i",
        file_path,
        "-vf",
        f"scale=640:360",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-c:a",
        "aac",
        "-ar",
        "44100",
        "-f",
        "flv",
        args.rtmp_stream_url,
    ]

    if announcement:
        command[2:2] = ["-loop", "1"]
        command[command.index("-vf") + 1] += (",drawtext=expansion=none:fontfile=/usr/share/fonts/truetype/freefont/FreeSerif.ttf:" 
                                            "textfile='/tmp/videos/announcement.txt':" 
                                            "fontsize=h/10: x=(w-text_w)/2: y=(h-text_h)/2")

    # Loop the video stream
    if loop:
        command[2:2] = ["-stream_loop", "-1"]
    process = subprocess.Popen(
        command,
        stderr=None,
        stdout=None,
        text=True,
        bufsize=1,
    )

    current_video_dict.clear()  
    if None not in [title, thumbnail]:
        current_video_dict["title"] = title
        current_video_dict["thumbnail"] = thumbnail

    logging.info(f"Process {process.pid} started for {video_type.value} video: {file_path}")
    process_dict[video_type] = process.pid
    MetricsHandler.streams_count.labels(video_type=video_type.value).inc(amount=1)
    MetricsHandler.stream_state.labels(video_type=video_type.value).set(1)

    # If duration is nonpositive, the announcement is played indefinitely
    # The loop checks every 0.5 secs to check if the subprocess has already exited
    # If the end of duration is reached, end the ffmpeg stream
    if announcement and duration > 0:
        for _ in range(duration*2):
            if process.poll() is not None:
                break
            time.sleep(0.5)
        kill_child_processes(process.pid)

    # the below function returns 0 if the video ended on its own
    # 137, 1
    exit_code = process.wait()
    logging.info(f"Process {process.pid} exited with code {exit_code}")
    write_log_to_client(f"Process {process.pid} started for {video_type.value} video: {file_path}")

    MetricsHandler.subprocess_count.labels(
        exit_code=exit_code,
    ).inc()
    if video_type in process_dict:
        process_dict.pop(video_type)

    MetricsHandler.stream_state.labels(video_type=video_type.value).set(0)

    if (exit_code == 0 or video_type == State.PLAYING) and play_interlude_after and args.interlude:
        interlude_lock.release()
    logging.info(f"Process {process.pid} exited with code {exit_code}")
    write_log_to_client(f"Process {process.pid} exited with code {exit_code}")

    return exit_code


# stop the video by type
# have stop_video_by_type return true if kill_child_processes was called
# else have it return false
def stop_video_by_type(video_type: State):
    if video_type in process_dict:
        write_log_to_client(f"Stopping {video_type} video")
        kill_child_processes(process_dict[video_type])
        write_log_to_client(f"Successfully stopped {video_type} video")
        process_dict.pop(video_type)
        return True
    return False


# Stops FFMPEG stream, stop_all_processes should also return a boolean, from what stop_video_by_type returned
def stop_all_processes():
    return stop_video_by_type(State.INTERLUDE) or stop_video_by_type(State.PLAYING)


# Stop FFMPEG stream and clear the queue
def stop_all_videos():
    # Clear the queue
    clear_queue(play_video_queue)
    return stop_all_processes()


# terminate a parent process and all its child processes using a specified signal.
def kill_child_processes(parent_pid, sig=signal.SIGKILL):
    try:
        parent = psutil.Process(parent_pid)
        parent.send_signal(sig)
        children = parent.children(recursive=True)
        for process in children:
            process.send_signal(sig)
    except psutil.NoSuchProcess:
        return


# Start a thread to handle the interlude stream
def handle_interlude():
    while True:
        # Wait for the lock to be released
        interlude_lock.acquire()
        write_log_to_client("Interlude thread unblocked...")
        # Check if the interlude stream is already running
        create_ffmpeg_stream(args.interlude, State.INTERLUDE, loop=True)


# Removes all entries in a queue
def clear_queue(q: Queue):
    while True:
        try:
            q.get_nowait()
            q.task_done()
        except Empty:
            break


# Worker thread for downloading videos.
def download_video_worker():
    while True:
        # Get the config from the queue
        config = download_url_queue.get()
        # Download and add it to the play video queue
        try:
            if config is None:
                time.sleep(1)
                continue
            video_path = download_video(config)
            play_video_queue.put((config, video_path))
        finally:
            download_url_queue.task_done()


# Downloads video, returns the video path
def download_video(config: VideoConfig):
    with download_lock:
        # Attempt to find video in cache
        video_path = video_cache.find(Cache.get_video_id(config.url))
        # Download video if not in cache
        if video_path is None:
            # Check age restriction
            try:
                video = YouTube(config.url)
                if video.age_restricted:
                    write_log_to_client(f"Skipping age-restricted video: {config.url}")
                    return None
            except Exception as e:
                write_log_to_client(f"Failed to check video {config.url}: {e}")
                raise
            write_log_to_client(f"Downloading {config.url} to disk")
            try:
                # Download video
                video_cache.add(config.url)
            except Exception as e:
                write_log_to_client(f"Failed to download {config.url}: {e}")
                raise
            # Get video path of downloaded video and log
            video_path = video_cache.find(Cache.get_video_id(config.url))
            if video_path is not None:
                write_log_to_client(f"Downloaded {config.url} to {video_path}")
            else:
                write_log_to_client(f"Failed to download {config.url}")
        return video_path


# Worker Thread for video playing.
def play_video_worker():
    while True:
        # Get the video info from queue, play video, and log exit code
        config, video_path = play_video_queue.get()
        try:
            if video_path is None:
                time.sleep(1)
                continue
            # Play Video
            logging.info(f"Playing {video_path}")
            exit_code = play_video(video_path, config)
            logging.info(f"EXIT CODE: {exit_code}")
        finally:
            play_video_queue.task_done()


# Plays a video, returns exit code
def play_video(video_path: str, config: VideoConfig):
    try:
        # Stop any existing streams
        stop_all_processes()
        # Start stream
        write_log_to_client(f"Playing {video_path}")
        exit_code = create_ffmpeg_stream(
            video_path,
            State.PLAYING,
            config.loop,
            config.title,
            config.thumbnail,
            play_interlude_after=config.play_interlude_after,
        )
        return exit_code
    except Exception as e:
        logging.exception(f"Error playing video: {e}")
        write_log_to_client(f"Error playing video: {e}")
        return 1


# Handle video downloading based on URL type (VIDEO, PLAYLIST)
def download_url_types(config: VideoConfig):
    if config.url_type == UrlType.PLAYLIST:
        # Loop to add all individual video URLs in a playlist into the queue
        playlist = Playlist(config.url)
        add_playlist_videos_to_download_queue(playlist, config)
    if config.url_type == UrlType.VIDEO:
        # Add single video to queue
        download_url_queue.put(config)


# Adds individual video configurations from a playlist into queue
def add_playlist_videos_to_download_queue(playlist: Playlist, config: VideoConfig):
    for i in range(len(playlist)):
        # Get video information
        video_url = playlist[i]
        video = YouTube(video_url)
        # Change config information into individual video
        individual_video_config = VideoConfig(
            url_type=UrlType.VIDEO,
            url=video_url,
            loop=config.loop,
            title=video.title,
            thumbnail=video.thumbnail_url,
            play_interlude_after=config.play_interlude_after,
            repeat=config.repeat,
        )
        # Put videos into queue
        download_url_queue.put(individual_video_config)


# Returns whether the URL is a playlist, video, empty or unknown
def _get_url_type(url: str):
    if not url or url.strip() == "":
        return UrlType.EMPTY
    try:
        playlist = pytubefix.Playlist(url)
        logging.info(f"{url} is a playlist with {len(playlist)} videos")
        return UrlType.PLAYLIST
    except:
        try:
            pytubefix.YouTube(url)
            logging.info(f"{url} is a video")
            return UrlType.VIDEO
        except:
            logging.error(f"url {url} is not a playlist or video!")
            return UrlType.UNKNOWN


# Returns the video config of a video in the cache
def get_cache_config(video):
    cache_video_config = VideoConfig(
        url_type=UrlType.VIDEO,
        url=None,
        loop=False,
        title=video.title,
        thumbnail=video.thumbnail,
    )
    return cache_video_config


# Enqueue all cached videos
def enqueue_all_cached():
    try:
        cache_videos = video_cache.video_id_to_path
        for _, cached_video in cache_videos.items():
            cache_video_config = get_cache_config(cached_video)
            # Prevents infinite repeating
            cache_video_config.repeat = False
            play_video_queue.put((cache_video_config, cached_video.file_path))
    except Exception as e:
        logging.exception(f"Exception enqueuing all cached: {e}")


# Repeat Mode Easter Egg
async def repeat_mode():
    # Ensure cache is not empty
    if video_cache.video_id_to_path:
        try:
            # Endless repeat loop until cancel_event is set
            while not cancel_event.is_set():
                # Keeps enqueuing cached forever
                if play_video_queue.empty():
                    enqueue_all_cached()
                await asyncio.sleep(1)
        except Exception as e:
            logging.exception(f"Exception activating repeat mode: {e}")


# --- SSE Log Broadcasting Integration ---

# Sample default responses
default_get_response = {
    "message": "Default GET response"
}

default_post_response = {
    "message": "Default POST response"
}

# List of queues for connected clients
clients: List[asyncio.Queue] = []

@app.get("/events")
async def events(request: Request):
    """
    SSE endpoint. Clients connect here to receive events.
    """
    client_queue = asyncio.Queue()
    clients.append(client_queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await client_queue.get()
                yield f"data: {json.dumps(message)}\n\n"
        finally:
            clients.remove(client_queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def write_log_to_client(message: str):

    response = {
        "message": message,
    }

    for queue in clients:
        queue.put_nowait(response)

# Example endpoint to trigger log broadcast
@app.post("/log")
async def log_event(request: Request):
    data = await request.json()
    request_type = data.get("requestType", "POST")
    response_data = data.get("responseData", {})
    write_log_to_client("I HAVE A ")
    return {"message": "Log sent to clients"}

@app.get("/state")
async def state():
    result = {"state": State.INTERLUDE}
    if State.PLAYING in process_dict:
        result = {"state": State.PLAYING, "nowPlaying": current_video_dict}
    write_log_to_client("I HAVE A STATE " + str(result))
    return result


@app.post("/play/file")
async def play_file(file_path: str = "cache", title: str = None, thumbnail: str = None):
    try:
        # Stop all videos when pressing play, this also breaks out of video loops
        stop_all_videos()
        cancel_event.clear()

        # Check if we are going to play all videos or a single video in the cache
        if file_path == "cache":
            enqueue_all_cached()
            return {"detail": "Success"}

        # Add a single video in the cache into the queue
        cache_video_config = VideoConfig(
            url_type=UrlType.VIDEO,
            url=None,
            loop=False,
            title=title,
            thumbnail=thumbnail,
            play_interlude_after=False,
        )
        play_video_queue.put((cache_video_config, file_path))
        return {"detail": "Success"}
    except Exception:
        logging.exception("Unable to play file from cache")
        raise HTTPException(status_code=500, detail="Check logs")


@app.post("/play")
async def play(url: str, loop: bool = False, repeat: bool = False):
    # Stop all videos when pressing play, this also breaks out of video loops
    stop_all_videos()
    cancel_event.clear()

    # Decode URL
    url = unquote(url)
    write_log_to_client("PROCESSING REQUEST for " + url)

    # Repeat Cache Mode
    if repeat:
        write_log_to_client("Repeat Mode Activated")
        asyncio.create_task(repeat_mode())
        return {"detail": "Success"}

    # Get the type of URL (VIDEO, PLAYLIST, UNKNOWN)
    url_type = _get_url_type(url)
    logging.info(f"{url} is a {url_type}")
    if url_type == UrlType.UNKNOWN:
        raise HTTPException(status_code=400, detail="Unknown URL")
    elif url_type == UrlType.EMPTY:
        return Response(status_code=204)

    # Config for generic url type (VIDEO, PLAYLIST)
    config = VideoConfig(
        url_type=url_type,
        url=url,
        loop=loop,
        play_interlude_after=True,
        repeat=repeat,
    )

    # Build the playlist before download for accurate cache checking
    if url_type == UrlType.PLAYLIST:
        try:
            playlist_for_cache_check = Playlist(config.url)
        except:
            playlist_for_cache_check = None

    # Submit video config to pipeline
    try:
        # Add URL's video config to queue
        download_url_types(config)

        # Update Metrics
        MetricsHandler.video_count.inc()

        # Post cache status
        # For playlists, "in cache" is defined as the entire playlist being in the cache
        if url_type == UrlType.PLAYLIST:
            if playlist_for_cache_check is None:
                in_cache = False
            else:
                in_cache = True
                # Check if every video in the playlist is cached
                for video_url in playlist_for_cache_check:
                    video_path = video_cache.find(Cache.get_video_id(video_url))
                    if video_path is None:
                        in_cache = False
                        break
        elif url_type == UrlType.VIDEO:
            cached_video_path = video_cache.find(Cache.get_video_id(url))
            in_cache = cached_video_path is not None
        return {"detail": "Success", "in_cache": in_cache}

    # If download is unsuccessful, give response and reason
    except pytubefix.exceptions.AgeRestrictedError:
        raise HTTPException(status_code=400, detail="This video is age restricted :(")
    except pytubefix.exceptions.RegexMatchError:
        raise HTTPException(
            status_code=400, detail="That's not a YouTube link buddy ..."
        )
    except pytubefix.exceptions.VideoUnavailable:
        raise HTTPException(status_code=404, detail="This video is unavailable :(")
    except Exception:
        logging.exception("unable to play video from url")
        raise HTTPException(status_code=500, detail="Check logs")


@app.get("/metadata")
def metadata(url: str):
    url = unquote(url)
    try:
        url_type = _get_url_type(url)
        if url_type == UrlType.UNKNOWN:
            logging.error(f"unable to determine url type from {url}")
            raise HTTPException(status_code=400, detail="given url is of unknown type")

        # Check if the given url is a valid video or playlist
        if url_type == UrlType.PLAYLIST:
            playlist = Playlist(url)
            first_video = playlist.videos[0]
            return {"title": playlist.title, "thumbnail": first_video.thumbnail_url}

        # if url_type == UrlType.VIDEO:
        video = YouTube(url)
        return {"title": video.title, "thumbnail": video.thumbnail_url}
    # If pytubefix is unable to fetch video metadata, give response and reason
    except pytubefix.exceptions.AgeRestrictedError:
        raise HTTPException(status_code=400, detail="This video is age restricted :(")
    except pytubefix.exceptions.RegexMatchError:
        raise HTTPException(
            status_code=400, detail="That's not a YouTube link buddy ..."
        )
    except pytubefix.exceptions.VideoUnavailable:
        raise HTTPException(status_code=404, detail="This video is unavailable :(")
    except Exception:
        logging.exception(f"unable to get metadata for url {url}")
        raise HTTPException(status_code=500, detail="Check logs")


@app.post("/stop")
async def stop():
    cancel_event.set()
    current_video_dict.clear()
    clear_queue(play_video_queue)
    # Check if there is a video playing to stop
    if State.PLAYING in process_dict:
        # Stop the video playing subprocess
        stop_video_by_type(State.PLAYING)


@app.get("/list")
async def getVideos():
    returnedResponse = []
    file_size = 0
    for key, value in video_cache.video_id_to_path.items():
        if os.path.exists(value.file_path):
            file_size = os.path.getsize(value.file_path)
        returnedResponse.append(
            {
                "id": key,
                "name": value.title,
                "path": value.file_path,
                "thumbnail": value.thumbnail,
                "size_bytes": file_size,
            }
        )
    return json.dumps(returnedResponse)


@app.get("/metrics")
def get_metrics():
    return Response(
        media_type="text/plain",
        content=prometheus_client.generate_latest(),
    )


@app.get("/cache")
def get_cache():
    return FileResponse("static/cache.html")


@app.get("/debug")
def debug():
    return {
        "state": {
            "process_dict": process_dict,
            "current_video_dict": current_video_dict,
        },
        "cache": vars(video_cache),
    }


# Start worker threads on startup
@app.on_event("startup")
def startup():
    threading.Thread(target=download_video_worker, daemon=True).start()
    threading.Thread(target=play_video_worker, daemon=True).start()


@app.get("/announcement")
async def announcement():
    return FileResponse("static/announcement.html")


@app.post("/play/text")
async def play_text(announcement: str = None, duration: int = 5):
    announcement = unquote(announcement)
    with open("/tmp/videos/announcement.txt", "w") as announcement_file:
        announcement_file.write(announcement)
    # Start a thread to play the announcement
    threading.Thread(
        target=create_ffmpeg_stream,
        args=(
            "/app/static/background.png",
            State.PLAYING,
            False,
            "an announcement :)",
            "background.png",
            True,
            True,
            duration
        )
    ).start()

    return {"detail": "Success"}


@app.on_event("shutdown")
def signal_handler():
    stop_all_videos()

    # if the cache file is specfied, write the cache to the file and not clear the downloaded videos
    if args.cache_state_file:
        video_cache.write_cache()

    # if the cache file isn't specified, clear all uncache videos
    else:
        video_cache.clear()


app.mount("/", StaticFiles(directory="static", html=True), name="static")

# we have a separate __name__ check here due to how FastAPI starts
# a server. the file is first ran (where __name__ == "__main__")
# and then calls `uvicorn.run`. the call to run() reruns the file,
# this time __name__ == "server". the separate __name__ if statement
# is so a thread starts up the interlude after the server is ready to go
if __name__ == "server":
    MetricsHandler.init()
    MetricsHandler.cache_size.set(0)
    MetricsHandler.cache_size_bytes.set(0)
    
    # Start up interlude by default
    if args.interlude:
        threading.Thread(target=handle_interlude).start()
    # Ensure video folder exists
    if not os.path.exists(args.videopath):
        os.makedirs(args.videopath)

    # if the cache file is specified, populate the cache from the file
    if args.cache_state_file:
        video_cache.populate_cache()


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=True,
    )
