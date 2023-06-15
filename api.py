from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os, subprocess, threading, enum
from pytube import YouTube
from time import sleep

class State(enum.Enum):
    INTERLUDE = "interlude"
    PLAYING = "playing"

app = FastAPI()
current_state = State.INTERLUDE
interlude_command = ['ffmpeg', '-re', '-stream_loop', '-1', 
                     '-i', "./interlude.mp4", '-vf', 
                     'scale=256:144', '-c:v', 'libx264', 
                     '-preset', 'veryfast', '-tune', 'zerolatency', 
                     '-c:a', 'aac', '-ar', '44100', '-f', 'flv', 
                     'rtmp://localhost:1935/live/mystream']
interlude_process = subprocess.Popen(interlude_command)
video_process = None

# Enable CORS
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/state/")
async def state():
    global current_state
    return { "state": current_state }

@app.post("/play/")
async def play(url: str):
    global current_state, interlude_process
    # Check if video is already playing
    if current_state is State.INTERLUDE:
        # Start thread to download video, stream it, and provide a response
        try:
            YouTube(url).bypass_age_gate()
            threading.Thread(target=downloadAndPlay, args=(url,)).start()
            return { "detail": "Success" }
        # If download is unsuccessful, give failed response
        except:
            return { "detail": "Failed" }
    
@app.post("/stop/")
async def stop():
    global current_state, video_process, interlude_process
    # Check if there is a video playing to stop
    if current_state is State.PLAYING:
        # Stop the video playing subprocess
        video_process.terminate()
        video_process.wait()
        # Restart the interlude subprocess
        current_state = State.INTERLUDE
        interlude_process = subprocess.Popen(interlude_command)
        return { "message": "EXITED" }

def downloadAndPlay(url:str):
    global video_process, interlude_process, current_state
    # Download video
    video = YouTube(url)
    video = video.streams.get_by_resolution("360p")
    videoToPlay = video.default_filename
    video.download("./videos/")
    # Wait until video is downloaded
    while videoToPlay not in os.listdir("./videos"):
        sleep(0.25) 
    # Stop interlude 
    interlude_process.terminate()
    interlude_process.wait()
    # Start streaming video
    current_state = State.PLAYING
    video_process = subprocess.Popen(['ffmpeg', '-re', '-i', f"./videos/{videoToPlay}", 
                                      '-vf', 'scale=256:144', '-c:v', 'libx264', 
                                      '-preset', 'veryfast', '-tune', 'zerolatency', 
                                      '-c:a', 'aac', '-ar', '44100', '-f', 'flv', 
                                      'rtmp://localhost:1935/live/mystream'])
    video_process.wait()
    # Once video is finished playing, restart interlude
    current_state = State.INTERLUDE
    interlude_process = subprocess.Popen(interlude_command)
