import os
import threading
import enum
from time import sleep
from subprocess import Popen, DEVNULL

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pytube import YouTube
from pytube.exceptions import AgeRestrictedError, VideoUnavailable, RegexMatchError


class State(enum.Enum):
    INTERLUDE = "interlude"
    PLAYING = "playing"

app = FastAPI()
interlude_command = ['ffmpeg', '-re', '-stream_loop', '-1', '-i', "./interlude.mp4", '-vf', 
                     'scale=426:240', '-c:v', 'libx264', 
                     '-preset', 'veryfast', '-tune', 'zerolatency', 
                     '-c:a', 'aac', '-ar', '44100', '-f', 'flv', 
                     'rtmp://localhost:1935/live/mystream']
process_dict = {}
process_dict[State.INTERLUDE] = Popen(interlude_command, stdout=DEVNULL, stdin=DEVNULL, stderr=DEVNULL)
current_video_data = {}

# Ensure video folder exists
if not os.path.exists("./videos"):
   os.makedirs("./videos")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def download_and_play(url:str):
    # Download video
    video = YouTube(url)
    video = video.streams.get_by_resolution("360p")
    videoToPlay = video.default_filename
    # Download video is not already downloaded
    if (videoToPlay not in os.listdir("./videos")):
        video.download("./videos/")
        # Wait until video is downloaded
        while videoToPlay not in os.listdir("./videos"):
            sleep(0.5)
    # Stop interlude
    interlude_process = process_dict.pop(State.INTERLUDE)
    interlude_process.terminate()
    interlude_process.wait()
    # Start streaming video
    process_dict[State.PLAYING] = Popen(['ffmpeg', '-re', '-i', f"./videos/{videoToPlay}", 
                                      '-vf', 'scale=426:240', '-c:v', 'libx264', 
                                      '-preset', 'veryfast', '-tune', 'zerolatency', 
                                      '-c:a', 'aac', '-ar', '44100', '-f', 'flv', 
                                      'rtmp://localhost:1935/live/mystream'],  
                                      stdout=DEVNULL, stdin=DEVNULL, stderr=DEVNULL)
    process_dict[State.PLAYING].wait()
    process_dict.pop(State.PLAYING)
    # Once video is finished playing (or stopped early), restart interlude
    process_dict[State.INTERLUDE] = Popen(interlude_command,  stdout=DEVNULL, stdin=DEVNULL, stderr=DEVNULL)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/state/")
async def state():
    if State.PLAYING in process_dict:
        return { "state": State.PLAYING }
    else:
        return { "state": State.INTERLUDE }

@app.get("/current/")
async def current():
    return { "title": current_video_data["title"], "thumbnail": current_video_data["thumbnail"] }

@app.post("/play/")
async def play(url: str):
    # Check if video is already playing
    if State.INTERLUDE in process_dict:
        # Start thread to download video, stream it, and provide a response
        try:
            video = YouTube(url)
            # Check for age restriction exception
            video.bypass_age_gate()
            threading.Thread(target=download_and_play, args=(url,)).start()
            current_video_data["title"] = video.title
            current_video_data["thumbnail"] = video.thumbnail_url 
            return { "detail": "Success" }
        # If download is unsuccessful, give response and reason
        except AgeRestrictedError:
            return { "detail": "This video is age restricted :(" }
        except VideoUnavailable:
            return { "detail": "This video is unavailable :(" }
        except RegexMatchError:
            return { "detail": "That's not a YouTube link buddy ..." }
        except Exception as e:
            return { "detail": str(e) }
    return { "detail": "please wait for the current video to end, then make the request" }
    
@app.post("/stop/")
async def stop():
    # Check if there is a video playing to stop
    if State.PLAYING in process_dict:
        # Stop the video playing subprocess
        process_dict[State.PLAYING].terminate()
        return { "detail": "EXITED" }
    return { "detail": "no video is playing at the moment" }
    

