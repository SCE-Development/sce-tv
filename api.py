import os
import threading
import enum
import subprocess
import uvicorn

from args import get_args

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pytube import YouTube
<<<<<<< HEAD
import pytube.exceptions 

from cache import Cache

=======
from pytube.exceptions import AgeRestrictedError, VideoUnavailable, RegexMatchError
from time import sleep
>>>>>>> f285529 (frontend created)

class State(enum.Enum):
    INTERLUDE = "interlude"
    PLAYING = "playing"

app = FastAPI()
<<<<<<< HEAD
process_dict = {}
current_video_dict = {}
interlude_lock = threading.Lock()
args = get_args()
video_cache = Cache(file_path=args.videopath)
=======
current_state = State.INTERLUDE
interlude_command = ['ffmpeg', '-re', '-stream_loop', '-1', 
                     '-i', "./interlude.mp4", '-vf', 
                     'scale=426:240', '-c:v', 'libx264', 
                     '-preset', 'veryfast', '-tune', 'zerolatency', 
                     '-c:a', 'aac', '-ar', '44100', '-f', 'flv', 
                     'rtmp://localhost:1935/live/mystream']
interlude_process = subprocess.Popen(interlude_command)
video_process = None
current_video_data = ('','')

# Ensure video folder exists
if not os.path.exists("./videos"):
   os.makedirs("./videos")
>>>>>>> f285529 (frontend created)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def create_ffmpeg_stream(video_path:str, video_type:State, loop=False):
    command = [ 'ffmpeg', '-re', '-i', video_path, '-vf', f'scale=640:360', 
                '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency', 
                '-c:a', 'aac', '-ar', '44100', '-f', 'flv', 'rtmp://localhost:1935/live/mystream' ]
    # Loop the interlude stream
    if loop: 
        command[2:2] = ['-stream_loop', '-1']
    process_dict[video_type] = subprocess.Popen(
        command, 
        stdout=subprocess.DEVNULL, 
        stdin=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL
    )
    
def handle_interlude():
    while True:
        interlude_lock.acquire()
        create_ffmpeg_stream(args.interlude, State.INTERLUDE, True)

def handle_play(url:str):
    # Update process state
    interlude_process = process_dict.pop(State.INTERLUDE)
    # Add video to cache
    video_cache.add(url)
    # Stop interlude
    interlude_process.terminate()
    # Start streaming video
    create_ffmpeg_stream(video_cache.find(Cache.get_video_id(url)), State.PLAYING)
    process_dict[State.PLAYING].wait()
    process_dict.pop(State.PLAYING)
    # Once video is finished playing (or stopped early), restart interlude
    interlude_lock.release()



# Ensure video folder exists
if not os.path.exists("./videos"):
   os.makedirs("./videos")
# Start up interlude by default
if args.interlude:
    threading.Thread(target=handle_interlude).start()

@app.get("/")
async def root():
    return { "message": "Hello World" }

@app.get("/state")
async def state():
    if State.INTERLUDE in process_dict:
        return { "state": State.INTERLUDE }
    else:
        return  {
                    "state": State.PLAYING,
                    "nowPlaying": current_video_dict
                }

<<<<<<< HEAD
@app.post("/play")
async def play(url: str):
    # Check if video is already playing
    if State.PLAYING in process_dict:
        raise HTTPException(status_code=409, detail="please wait for the current video to end, then make the request")
        
    # Start thread to download video, stream it, and provide a response
    try:
        video = YouTube(url)
        # Check for age restriction/video availability
        video.bypass_age_gate()
        video.check_availability()
        current_video_dict["title"] = video.title
        current_video_dict["thumbnail"] = video.thumbnail_url 
        threading.Thread(target=handle_play, args=(url,)).start()
        return { "detail": "Success" }
    # If download is unsuccessful, give response and reason
    except pytube.exceptions.AgeRestrictedError:
        raise HTTPException(status_code=400, detail="This video is age restricted :(")
    except pytube.exceptions.VideoUnavailable:
        raise HTTPException(status_code=404, detail="This video is unavailable :(")
    except pytube.exceptions.RegexMatchError:
        raise HTTPException(status_code=400, detail="That's not a YouTube link buddy ...")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
=======
@app.get("/current/")
async def current():
    global current_video_data
    return { "title": current_video_data[0], "thumbnail": current_video_data[1] }


@app.post("/play/")
async def play(url: str):
    global current_state, interlude_process, current_video_data
    # Check if video is already playing
    if current_state is State.INTERLUDE:
        # Start thread to download video, stream it, and provide a response
        try:
            video = YouTube(url)
            video.bypass_age_gate()
            threading.Thread(target=downloadAndPlay, args=(url,)).start()
            current_video_data = (video.title, video.thumbnail_url)
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
>>>>>>> f285529 (frontend created)
    
@app.post("/stop")
async def stop():
    # Check if there is a video playing to stop
    if State.PLAYING in process_dict:
        # Stop the video playing subprocess
        process_dict[State.PLAYING].terminate()
    
@app.on_event("shutdown")
def signal_handler():
    video_cache.clear()

<<<<<<< HEAD
if __name__ == "__main__":
    
    uvicorn.run(app, host=args.host, port=args.port)
=======
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
                                      '-vf', 'scale=426:240', '-c:v', 'libx264', 
                                      '-preset', 'veryfast', '-tune', 'zerolatency', 
                                      '-c:a', 'aac', '-ar', '44100', '-f', 'flv', 
                                      'rtmp://localhost:1935/live/mystream'])
    video_process.wait()
    # Once video is finished playing, restart interlude
    current_state = State.INTERLUDE
    interlude_process = subprocess.Popen(interlude_command)
>>>>>>> f285529 (frontend created)
