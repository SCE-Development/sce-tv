import collections
import os
import pathlib
import queue
import signal
import subprocess
import sys
import time
import threading
import typing
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Response
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import prometheus_client
import psutil
import uvicorn

from modules.args import get_args
from modules.logger import logger
from modules.cache import Cache
from modules.constants import Video, UrlType
from modules.metrics import MetricsHandler
from modules import youtube_helpers


app = FastAPI()
args = get_args()

# yes i know the default param is 1 but this is
# so reading this later with 0 context makess sense
interlude_mutex = collections.defaultdict(lambda: threading.Semaphore(1))
process_dict_mutex = threading.Semaphore(1)

process_dict = collections.defaultdict(dict)
current_playlist = collections.defaultdict(lambda: queue.Queue())
cache = Cache(
    args.download_file_location,
    args.cache_size_bytes,
    args.cache_state_file,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def validate_stream_name(data):
    if not args.rtmp_stream_url:
        if "stream" not in data:
            raise HTTPException(
                status_code=400, detail="`stream` field must be set if no stream URL was specified"
            )
        stream = data.get("stream")
        if stream not in args.rtmp_stream_names:
            raise HTTPException(
                status_code=400, detail=f"{stream} is not an available stream name"
            )

def get_playing_state(rtmp_stream_url):
    value = Video.INTERLUDE
    now_playing = None
    process_dict_mutex.acquire()
    if Video.PLAYING in process_dict[rtmp_stream_url]:
        value = Video.PLAYING
        now_playing = process_dict[rtmp_stream_url][value]
    process_dict_mutex.release()
    result = {"state": value.name}
    if now_playing:
        result["now_playing"] = now_playing.as_json_object()
    return result


def kill_child_processes(parent_pid, sig=signal.SIGKILL):
    try:
        parent = psutil.Process(parent_pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for process in children:
        process.send_signal(sig)


def start_vlc_process(
    video_id,
    rtmp_stream_url,
    video_type,
    start_offset_seconds=None,
    loop=False,
    url=None,
    title=None,
    thumbnail=None,
):
    if not video_id:
        logger.error(f'start_vlc_process was sent bad value for video_id: "{video_id}"')
        return None
    maybe_loop = ""
    maybe_start_offset = ""

    if loop:
        maybe_loop += " -stream_loop -1"
    if start_offset_seconds != None:
        maybe_start_offset = f" -ss {start_offset_seconds}"

    COMMAND = f"ffmpeg {maybe_start_offset} -re {maybe_loop} -i {video_id} -c:v libx264 -preset veryfast -tune zerolatency -c:a aac -ar 44100 -f flv {rtmp_stream_url} > /dev/null"
    process = subprocess.Popen(
        COMMAND,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True,
    )
    MetricsHandler.ffmpeg_streams_created.labels(stream_name=rtmp_stream_url).inc()
    process_dict_mutex.acquire()
    logger.info(f"playing {video_id} on process {process.pid} for stream {rtmp_stream_url}")
    process_dict[rtmp_stream_url][video_type] = youtube_helpers.VideoMetadata(
        process.pid,
        video_id,
        url=url,
        title=title,
        thumbnail=thumbnail,
    )
    process_dict_mutex.release()
    with MetricsHandler.playing_time_seconds.labels(video_type=video_type.value, stream_name=rtmp_stream_url).time():
        exit_code = process.wait()
    logger.info(f"process {process.pid} exited with code {exit_code}")
    MetricsHandler.ffmpeg_exit_codes.labels(exit_code=exit_code, stream_name=rtmp_stream_url).inc()
    return exit_code


def play_interlude(interlude_file_path, rtmp_stream_url):
    while 1:
        logger.info("interlude is waiting for mutex...")
        interlude_mutex[rtmp_stream_url].acquire()
        logger.info(f"running interlude thing for stream {rtmp_stream_url}")
        start_vlc_process(interlude_file_path, rtmp_stream_url, Video.INTERLUDE, loop=True)


def stop_video_by_type(video_type, rtmp_stream_url):
    process_dict_mutex.acquire()
    if video_type not in process_dict[rtmp_stream_url]:
        process_dict_mutex.release()
        logger.error(f"attempted to stop {video_type}, not found in process dict")
        return False
    logger.info(f"stopping video with type {video_type}")
    current_playing_video = process_dict[rtmp_stream_url][video_type]
    kill_child_processes(current_playing_video.pid)
    process_dict[rtmp_stream_url].pop(video_type)
    process_dict_mutex.release()
    return True


def stop_all_videos(rtmp_stream_url):
    stop_video_by_type(Video.INTERLUDE, rtmp_stream_url)
    stop_video_by_type(Video.PLAYING, rtmp_stream_url)


def play_video(
    video_id,
    rtmp_stream_url,
    start_offset_seconds=None,
    loop=False,
    play_interlude_after=True,
    url=None,
    title=None,
    thumbnail=None,
):
    # before we play a specified video, stop any existing media to avoid collisions
    stop_all_videos(rtmp_stream_url)
    return_code = None
    if start_offset_seconds and loop:
        # if a start offset and loop was specified, the first iteration of the video
        # is played at the specified offset. after, a new process is created which loops
        # the video in its entirety. the reason why we don't spin up a process combining
        # both looping and an offset is cause the ffmpeg process becomes a zombie when we
        # try to stop it
        start_vlc_process(
            video_id,
            rtmp_stream_url,
            Video.PLAYING,
            start_offset_seconds,
            loop=False,
            url=url,
            title=title,
            thumbnail=thumbnail,
        )
        return_code = start_vlc_process(
            video_id,
            rtmp_stream_url,
            Video.PLAYING,
            None,
            loop,
            url=url,
            title=title,
            thumbnail=thumbnail,
        )
    else:
        return_code = start_vlc_process(
            video_id,
            rtmp_stream_url,
            Video.PLAYING,
            start_offset_seconds,
            loop,
            url=url,
            title=title,
            thumbnail=thumbnail,
        )
    if return_code == 0:
        stop_video_by_type(Video.PLAYING, rtmp_stream_url)
        if play_interlude_after:
            logger.info("releasing interlude mutex...")
            interlude_mutex[rtmp_stream_url].release()
    return return_code


def download_and_play_video(
    video_url, rtmp_stream_url, start_offset_seconds=None, loop=False, play_interlude_after=True
):
    cached_path = cache.find(video_url)
    if not cached_path:
        # if we didn't find the url, add it to the cache,
        # that way if the playlist loops we'll have it ready
        # on the next time around
        cached_path = cache.add(video_url)
        if not cached_path:
            logger.warning(f"not playing {video_url} for stream {rtmp_stream_url}")
            return
        logger.info(
            f"attempted to cache url {video_url}, should live at path {cached_path.file_path} "
        )

    return play_video(
        cached_path.file_path,
        rtmp_stream_url,
        start_offset_seconds,
        loop,
        play_interlude_after=play_interlude_after,
        url=video_url,
        title=cached_path.title,
        thumbnail=cached_path.thumbnail,
    )


def handle_youtube_playlist(videos_in_playlist, rtmp_stream_url, loop=False):
    def download_next_video_in_list(playlist, current_index):
        next_index = current_index + 1
        if next_index < len(playlist):
            video_url = playlist[next_index]
            if not cache.find(video_url):
                cache.add(video_url)

    [current_playlist[rtmp_stream_url].put(video_url) for video_url in videos_in_playlist]
    queue_as_list = current_playlist[rtmp_stream_url].queue
    while 1:
        for i in range(len(queue_as_list)):
            video_url = queue_as_list[i]
            exit_code = None

            t = threading.Thread(
                target=download_next_video_in_list, args=(queue_as_list, i), daemon=True
            )
            t.start()

            exit_code = download_and_play_video(video_url, rtmp_stream_url, play_interlude_after=False)
            # if the exit code is None then the vlc process never even ran.
            if exit_code not in [0, None]:
                # exit the entire thread routine if the video we just played was killed
                logger.info(f"playlist routine recieved code {exit_code}, exiting")
                return
        if loop:
            continue
        break

    logger.info("out of playlist videos")
    interlude_mutex[rtmp_stream_url].release()


def handle_play_cache(rtmp_stream_url):
    # assume we want to loop over cache
    while 1:
        cache_entries = cache.list_entries()
        for entry in cache_entries:
            # there is a possibility that the cache video could get deleted
            # while playing. this if statement doesnt cover us in that case
            if entry.get("id") in cache.mapping:
                exit_code = play_video(
                    entry.get("path"),
                    rtmp_stream_url,
                    title=entry.get("name"),
                    thumbnail=entry.get("thumbnail")
                )
                if exit_code not in [0, None]:
                    # exit the entire thread routine if the video we just played was killed
                    logger.info(f"cache routine recieved code {exit_code}, exiting")
                    return


def handle_disk_playlist(path: pathlib.Path, rtmp_stream_url, loop=False):
    [current_playlist[rtmp_stream_url].put(video_url) for video_url in path.iterdir()]
    # cache the first file's thumbnail
    logger.error(f"current_playlist[rtmp_stream_url].qsize() = {current_playlist[rtmp_stream_url].qsize()}")
    if current_playlist[rtmp_stream_url].qsize():
        first_path = current_playlist[rtmp_stream_url].queue[0].resolve()
        logger.error(f"first_path = {(first_path, str(first_path))}")
    while 1:
        queue_as_list = current_playlist[rtmp_stream_url].queue
        for i in range(len(queue_as_list)):
            resolved = queue_as_list[i].resolve()
            logger.error(f"resolved was {resolved}")
            maybe_thumbnail = None

            exit_code = play_video(
                resolved,
                rtmp_stream_url,
                # start_offset_seconds:
                None,
                # loop:
                False,
                # play_interlude_after:
                True,
                # url:
                None,
                # title:
                None,
                # thumbnail:
                maybe_thumbnail,
            )
            # if the exit code is None then the vlc process never even ran.
            if exit_code not in [0, None]:
                # exit the entire thread routine if the video we just played was killed
                logger.info(f"playlist routine recieved code {exit_code}, exiting")
                return
            time.sleep(10)
        if loop:
            continue
        break


def clear_playlist(rtmp_stream_url):
    logger.info("emptying queue...")
    while not current_playlist[rtmp_stream_url].empty():
        try:
            current_playlist[rtmp_stream_url].get(block=False)
        except:
            continue
    logger.info("done emptying queue")


@app.get("/file/list")
async def play(path: typing.Optional[str] = None):
    if path is None:
        path = args.download_file_location
    if str(path).lower() == 'cache':
        return {
            "result": {
                "content": cache.list_entries(),
                "parent": None,
            }
        }

    p = pathlib.Path(path)
    required = pathlib.Path(args.download_file_location)
    resolved = p.resolve()
    path_valid = required in list(resolved.parents) or resolved == required
    if path_valid:
        result = []
        parent = resolved.parents[0]
        if resolved == required:
            parent = None

        for path in resolved.iterdir():
            result.append(
                {
                    "name": path.name,
                    "is_directory": path.is_dir(),
                    "path": path,
                }
            )
        return {
            "result": {
                "content": result,
                "parent": parent,
            },
        }
    raise HTTPException(
        status_code=400, detail=f"path {resolved} must be within {required}"
    )


@app.post("/play/file")
async def play_file(request: Request):
    data = await request.json()
    if "path" not in data:
        raise HTTPException(
            status_code=400, detail="path field must be set in JSON request"
        )
    validate_stream_name(data)

    rtmp_stream_url = args.rtmp_stream_url or os.path.join(args.rtmp_base_url, data.get("stream"))
    required = pathlib.Path(args.download_file_location)
    p = pathlib.Path(data["path"])
    resolved = p.resolve()
    # what if its `/valid/path/thing; rm -rf /`?
    path_valid = required in list(resolved.parents)
    play_cache = data["path"] == "cache"
    if not path_valid and not play_cache:
        raise HTTPException(
            status_code=400, detail=f"path {resolved} must be within {required}"
        )

    clear_playlist(rtmp_stream_url)
    if play_cache:
        t = threading.Thread(
            target=handle_play_cache,
            args=(
                rtmp_stream_url,
            ),
            daemon=True,
        )
        t.start()
    elif resolved.is_file():
        # todo make handle_disk_playlist be one function that
        # a single file and multiple file request go to
        # accepts an array of files as param, handles thumbnail logic
        # within itself
        maybe_thumbnail = data.get("thumbnail")
        maybe_title = data.get("name")
        t = threading.Thread(
            target=play_video,
            args=(
                # escape any spaces
                str(resolved).replace(" ", "\ "),
                rtmp_stream_url,
                # start_offset_seconds:
                None,
                # loop:
                False,
                # play_interlude_after:
                True,
                # url:
                None,
                # title:
                maybe_title,
                # thumbnail:
                maybe_thumbnail,
            ),
            daemon=True,
        )
        t.start()
    elif resolved.is_dir():
        # loop over cache if the user asked to play all videos in the cache
        t = threading.Thread(
            target=handle_disk_playlist,
            args=(
                # escape any spaces
                pathlib.Path(str(resolved).replace(" ", "\ ")),
                rtmp_stream_url,
                bool(data.get("loop")),
            ),
            daemon=True,
        )
        t.start()
    return {"message": "we're playing what you sent, check logs"}


@app.post("/play")
async def play(request: Request):
    data = await request.json()
    if "url" not in data:
        raise HTTPException(
            status_code=400, detail="url field must be set in JSON request"
        )
    validate_stream_name(data)

    rtmp_stream_url = args.rtmp_stream_url or os.path.join(args.rtmp_base_url, data.get("stream"))
    url_type = youtube_helpers.determine_url_type(data["url"])
    MetricsHandler.urls_recieved.labels(url_type=url_type.value, stream_name=rtmp_stream_url).inc()
    if url_type == UrlType.UNKNOWN:
        raise HTTPException(status_code=400, detail="given url is of unknown type")
    

    clear_playlist(rtmp_stream_url)
    if url_type == UrlType.VIDEO:
        t = threading.Thread(
            target=download_and_play_video,
            args=(
                data["url"],
                rtmp_stream_url,
                data.get("startOffsetSeconds"),
                bool(data.get("loop")),
            ),
            daemon=True,
        )
        t.start()
    elif url_type == UrlType.PLAYLIST:
        t = threading.Thread(
            target=handle_youtube_playlist,
            args=(
                youtube_helpers.get_playlist_videos(data["url"]),
                rtmp_stream_url,
                bool(data.get("loop")),
            ),
            daemon=True,
        )
        t.start()

    return {"message": "we're downloading what you sent, check logs"}


@app.get("/video/title")
async def play(video: typing.Optional[str] = None):
    decoded_video = unquote(video)
    if not video:
        raise HTTPException(
            status_code=400, detail="video field must be set in request"
        )
    maybe_entry = cache.find(decoded_video)
    result = None
    if maybe_entry:
        result = maybe_entry.title
    else:
        result = youtube_helpers.get_video_title(decoded_video)
    return {"result": result}


@app.get("/video/thumbnail")
async def play(video: typing.Optional[str] = None):
    decoded_video = unquote(video)
    if not video:
        raise HTTPException(
            status_code=400, detail="video field must be set in request"
        )
    maybe_entry = cache.find(decoded_video)
    result = None
    if maybe_entry:
        result = maybe_entry.thumbnail
    else:
        result = youtube_helpers.get_video_thumbnail(decoded_video)
    return {"result": result}


@app.get("/video/durationSeconds")
async def play(video: typing.Optional[str] = None):
    decoded_video = unquote(video)
    if not video:
        raise HTTPException(
            status_code=400, detail="video field must be set in request"
        )
    # todo validate start seconds
    # todo add end seconds
    # todo validate end seconds
    logger.info(f"attempting to calculate duration for {decoded_video}")
    return {"result": youtube_helpers.get_length_of_video_seconds(decoded_video)}

@app.post("/cache/delete")
async def delete(request: Request):
    data = await request.json()
    if "videoId" not in data:
        raise HTTPException(
            status_code=400, detail="videoId field must be set in JSON request"
        )
    return {"result": cache.delete(data["videoId"])}


@app.post("/api/stop")
async def stop(request: Request):
    data = await request.json()
    validate_stream_name(data)
    rtmp_stream_url = args.rtmp_stream_url or os.path.join(args.rtmp_base_url, data.get("stream"))
    clear_playlist(rtmp_stream_url)
    video_stopped = stop_video_by_type(Video.PLAYING, rtmp_stream_url)
    if video_stopped:
        interlude_mutex[rtmp_stream_url].release()
    return {"success": video_stopped}


@app.get("/api/state")
async def play(stream: typing.Optional[str] = None):
    validate_stream_name({"stream": stream})
    rtmp_stream_url = args.rtmp_stream_url or os.path.join(args.rtmp_base_url, stream)
    return get_playing_state(rtmp_stream_url)

@app.get("/metrics")
def get_metrics():
    return Response(
        media_type="text/plain",
        content=prometheus_client.generate_latest(),
    )


@app.get("/debug")
async def debug(request: Request):
    result = {}
    result["state"] = process_dict
    result["cache"] = vars(cache)
    return result


@app.on_event("shutdown")
def signal_handler():
    logger.info("stopping all videos and clearing cache")
    for name in args.rtmp_stream_names:
        stream_name = os.path.join(args.rtmp_base_url, name)
        stop_all_videos(stream_name)
    if args.rtmp_stream_url:
        stop_all_videos(args.rtmp_stream_url)
    cache.clear()
    logger.info("shutting down")


app.mount("/", StaticFiles(directory="static", html=True), name="static")


# we have a separate __name__ check here due to how FastAPI starts
# a server. the file is first ran (where __name__ == "__main__")
# and then calls `uvicorn.run`. the call to run() reruns the file,
# this time __name__ == "server". the separate __name__ if statement
# is so a thread starts up the interlude after the server is ready to go
if __name__ == "server":
    MetricsHandler.init()
    cache.populate()
    
    # Start up interlude by default    
    if args.interlude_file_path:
        if args.rtmp_stream_url:
            threading.Thread(target=play_interlude, args=(args.interlude_file_path,args.rtmp_stream_url)).start()
        else:
            for name in args.rtmp_stream_names:
                stream_name = os.path.join(args.rtmp_base_url, name)
                threading.Thread(target=play_interlude, args=(args.interlude_file_path,stream_name)).start()


if __name__ == "__main__":
    if not args.rtmp_stream_url:
        if not args.rtmp_base_url or not args.rtmp_stream_names:
            logger.error("""
                --rtmp-stream-url must be specified, or --rtmp-base-url
                and --rtmp-stream-names must be specified
            """)
            sys.exit(1)

    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["loggers"]["uvicorn.access"]["level"] = "WARNING"
    log_config["loggers"]["uvicorn.error"]["level"] = "WARNING"

    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=True,
    )
