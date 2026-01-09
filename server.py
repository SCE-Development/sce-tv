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
from typing import List

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
    UNKNOWN = "unknown"


# Create FastAPI instance
app = FastAPI()

# This dictionary is used to store the process IDs of running subprocesses, keyed by the type of video being processed (interlude or playing).
process_dict = {}

# This dictionary is used to store the title and thumbnail of the currently playing video.
current_video_dict = {}

interlude_lock = threading.Lock()

args = get_args()

cancel_event = threading.Event()

# Create a cache object to store video files, initializing it with the file path specified in the command-line arguments or configuration settings. This instance is used to cache downloaded videos.
video_cache = Cache(file_path=args.videopath, cache_file=args.cache_state_file)

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
    video_path: str,
    video_type: State,
    loop=False,
    title=None,
    thumbnail=None,
    play_interlude_after=True,
):
    if video_path is None:
        logging.info("video_path is None. ffmpeg_stream cancelled.")
        return 2
    
    if (stop_all_videos()):

        time.sleep(5)

    # Create a subprocess to stream the video using FFmpeg
    command = [
        "ffmpeg",
        "-re",
        "-i",
        video_path,
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
    # Loop the interlude stream
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

    logging.info(f"Process {process.pid} started for {video_type.value} video: {video_path}")
    process_dict[video_type] = process.pid
    MetricsHandler.streams_count.labels(video_type=video_type.value).inc(amount=1)
    MetricsHandler.stream_state.labels(video_type=video_type.value).set(1)
    # the below function returns 0 if the video ended on its own
    # 137, 1
    exit_code = process.wait()
    logging.info(f"Process {process.pid} exited with code {exit_code}")
    write_log_to_client(f"Process {process.pid} started for {video_type.value} video: {video_path}")

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

#stop_all_videos should also return a boolean, from what stop_video_by_type returned
def stop_all_videos():
    return stop_video_by_type(State.INTERLUDE) or stop_video_by_type(State.PLAYING)
    

 
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


def download_next_video_in_list(playlist, current_index):
    next_index = current_index + 1
    if next_index == (len(playlist)):
        next_index = 0
    video_url = playlist[next_index]
    if video_cache.find(Cache.get_video_id(video_url)) is None:
        write_log_to_client(f"Downloading next video in playlist: {video_url}")
        video_cache.add(video_url)


@dataclass
class VideoConfig:
    url: str
    loop: bool = False
    title: str = None
    thumbnail: str = None
    play_interlude_after: bool = True
    repeat: bool = False


def download_and_play_video(config: VideoConfig):
    # Attempt to find video in cache
    video_path = video_cache.find(Cache.get_video_id(config.url))
    # Download video if not in cache
    if video_path is None:
        write_log_to_client(f"Downloading {config.url} to disk")
        video_cache.add(config.url)
        video_path = video_cache.find(Cache.get_video_id(config.url))
        write_log_to_client(f"Downloaded {config.url} to {video_path}")
    
    # Stop any existing streams before starting new one to prevent conflicts
    stop_all_videos()
    # Start stream
    exit_code = create_ffmpeg_stream(
        video_path,
        State.PLAYING,
        config.loop,
        config.title,
        config.thumbnail,
        play_interlude_after=config.play_interlude_after,
    )
    # If repeat mode is enabled and video ended normally, play all cached videos on repeat
    if config.repeat and exit_code == 0:
        write_log_to_client("Repeat mode: starting cache playback loop")
        handle_cache_play(repeat=True)
    return exit_code


def handle_playlist(playlist_url: str, loop: bool, repeat: bool = False):
    logging.info("Function handle_playlist started")
    playlist = Playlist(playlist_url)
    result = 0
    # Stop interlude
    while True:
        for i in range(len(playlist)):
            # Stop playlist
            if cancel_event.is_set():
                logging.info("Playlist stop flag set, exiting playlist thread")
                write_log_to_client("Playlist stop flag set, exiting playlist thread")
                if args.interlude:
                    interlude_lock.release()
                return
            
            # Get video information
            video_url = playlist[i]
            logging.info(f"Playlist video URL: {video_url}")
            video = YouTube(video_url)
            
            # Skip age-restricted videos to avoid exceptions
            if video.age_restricted:
                logging.info(f"Skipping age-restricted video: {video_url}")
                write_log_to_client(f"Skipping age-restricted video: {video_url}")
                continue
            
            # Download the next video in the playlist
            t = threading.Thread(
                target=download_next_video_in_list,
                args=(playlist, i),
                daemon=True,
            )
            logging.info("THREAD START: Start new thread for downloading next video")
            t.start()
            
            # Download and play current video
            logging.info("=== CURRENT VIDEO INFO ===")
            logging.info(f"{video_url}")
            logging.info(f"{video.title}")
            logging.info(f"{video.thumbnail_url}")
            logging.info(f"Video Object: {video}")
            logging.info("==========================")
            logging.info("THREAD START: Download and play current video")
            result = download_and_play_video(VideoConfig(
                url=video_url,
                loop=False,
                title=video.title,
                thumbnail=video.thumbnail_url,
                play_interlude_after=False,
            ))
            
            # Wait for download next video thread to terminate.
            t.join()
            logging.info("THREAD ENDED: Download next video thread finished.")
            
            # Exit Codes
            logging.info(f"EXIT CODE: {result}")
            if result == 2:
                logging.info(f"Video {video_url} failed to download, skipping to next video in playlist")
                write_log_to_client(f"Video {video_url} failed to download, skipping to next video in playlist")
                continue
        if not loop:
            if args.interlude:
                interlude_lock.release()
            # If repeat mode is enabled and playlist ended normally, play all cached videos on repeat
            if repeat and result == 0:
                write_log_to_client("Repeat mode: starting cache playback loop")
                handle_cache_play(repeat=True)
            break
    logging.info("End of function: handle_playlist")

def _get_url_type(url: str):
    logging.info("_get_url_type is running")
    try:
        playlist = pytubefix.Playlist(url)
        logging.info(f"{url} is a playlist with {len(playlist)-1} videos")
        return UrlType.PLAYLIST
    except:
        try:
            pytubefix.YouTube(url)
            logging.info(f"{url} is a video")
            return UrlType.VIDEO
        except:
            logging.error(f"url {url} is not a playlist or video!")
            return UrlType.UNKNOWN


def handle_cache_play(repeat: bool = False):
    # Get all the videos in the cache
    cache_videos = video_cache.video_id_to_path

    # Loop through each video in the cache (continuously if repeat=True)
    while True:
        for _, video in cache_videos.items():

            # Store the current playing video information
            current_video_dict["title"] = video.title
            current_video_dict["thumbnail"] = video.thumbnail

            # Get the file path of the video to stream
            file_path = video.file_path
            response = create_ffmpeg_stream(
                file_path,
                State.PLAYING,
                loop=False,
                title=video.title,
                thumbnail=video.thumbnail,
            )

            # if the video ended on its own, continue to the next video, otherwise break out of the loop
            if response != 0:
                return

        # If not in repeat mode, exit after one pass through the cache
        if not repeat:
            break

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

        # check if we are going to play all videos or a single video in the cache
        if file_path == "cache":
            # Start a thread to play all videos in the cache
            threading.Thread(target=handle_cache_play).start()
            return {"detail": "Success"}

        # Start a thread to play a single video in the cache
        threading.Thread(
            target=create_ffmpeg_stream,
            args=(
                file_path,
                State.PLAYING,
                False,
                title,
                thumbnail,
            ),
        ).start()

        return {"detail": "Success"}

    except Exception:
        logging.exception('unable to play file from cache')
        raise HTTPException(status_code=500, detail="check logs")

@app.post("/play")
async def play(url: str, loop: bool = False, repeat: bool = False):
    cancel_event.clear()
    # Decode URL
    url = unquote(url)
    write_log_to_client("PROCESSING REQUEST for " + url)
    
    # Start thread to download video, stream it, and provide a response
    try:

        # Get the type of URL (VIDEO, PLAYLIST, UNKNOWN)
        url_type = _get_url_type(url)
        logging.info(f"{url} is a {url_type}")
        if url_type == UrlType.UNKNOWN:
            raise HTTPException(status_code=400, detail="given url is of unknown type")

        # Update Metrics
        MetricsHandler.video_count.inc()

        # Check the type of URL and start the appropriate thread
        if url_type == UrlType.PLAYLIST:
            logging.info("URL is a playlist")
            t = threading.Thread(
                target=handle_playlist,
                args=(url, loop, repeat),
            )
            logging.info("Thread Start")
            t.start()
            return {"detail": "Success"}

        # if url_type == UrlType.VIDEO:
        video = YouTube(url)
        logging.info("=== CURRENT VIDEO INFO ===")
        logging.info(f"Video Object: {video}")
        logging.info(f"Video URL: {url}")
        logging.info(f"Video Title: {video.title}")
        logging.info(f"Video Thumbnail URL: {video.thumbnail_url}")
        logging.info("==========================")
        config = VideoConfig(
            url=url,
            loop=loop,
            title=video.title,
            thumbnail=video.thumbnail_url,
            play_interlude_after=True,
            repeat=repeat,
        )
        t = threading.Thread(
            target=download_and_play_video,
            args=(config,),
        )
        t.start()

        return {"detail": "Success"}

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
        logging.exception('unable to play video from url')
        raise HTTPException(status_code=500, detail="check logs")
    

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
        raise HTTPException(status_code=500, detail="check logs")


@app.post("/stop")
async def stop():
    cancel_event.set()
    current_video_dict.clear()
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
