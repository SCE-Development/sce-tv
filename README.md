# burger

SCE TV

## Running locally

### With Docker

- [ ] run the server with:

```
docker-compose -f docker-compose.dev.yml up --build
```

### Without Docker

make sure you have docker and python installed!

- [ ] create a virtual environment with

```
mkdir venv
python -m venv ./venv
source ./venv/bin/activate
```

- [ ] install requirements locally with

```
pip install -r requirements.txt
```

- [ ] also install latest working version of pytube with:

```
pip install git+https://github.com/joejztang/pytube.git@499268313ada0b971dc5b6718986b27d97731f05
```

- [ ] start the streaming server with

```
docker-compose -f docker-compose.dev.yml up -d streaming-server
```

- [ ] run the server with:

```
python server.py --rtmp-stream-url rtmp://localhost:1935/live/mystream
```

## Playing a video

- [ ] visit the webpage at http://localhost:5001/ and add a url from youtube
- [ ] open the rtmp stream url `rtmp://localhost/live/mystream` in VLC with
      <img width="591" alt="image" src="https://github.com/SCE-Development/sce-tv/assets/36345325/58238640-f26a-4d7c-87b3-bdf645e30a22">
- [ ] ensure the stream runs in VLC

## PI Code
```py
import argparse
from time import sleep
from prometheus_client import start_http_server, Gauge

import vlc

def stream_is_dead(player):
    state = player.get_state()
    if state in [vlc.State.Stopped, vlc.State.Ended, vlc.State.Error]:
        print("Pack it up streams over")
        return True
    return False

parser = argparse.ArgumentParser()
parser.add_argument(
    "--rtmp-stream-url",
    required=True,
    help="the url to recieve video streams, i.e. rtmp://proliant.rio/live/ASDF"
)
parser.add_argument(
    "--metrics-port",
    type=int,
    default=8000,
    help="Port to expose Prometheus metrics on (default: 8000)"
)


if __name__ == '__main__':
    args = parser.parse_args()

    start_http_server(args.metrics_port)
    stream_running = Gauge(
            "receive_stream_running",
            "Indicates whether the received stream is running (1=running, 0=stopped)"
            )

    while 1:
        try:
            media = vlc.MediaPlayer(args.rtmp_stream_url)
            media.play()
            #stream_running.set(1)
            sleep(5)
            while not stream_is_dead(media):
                stream_running.set(1)
                sleep(1)
            media.stop()
            stream_running.set(0)
        except Exception as e:
            print("we crashed", e)
            stream_running.set(0)

```
