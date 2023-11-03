# burger
SCE TV

## Running locally
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
- [ ] run the server with
```
python api.py --rtmp-stream-url rtmp://localhost:1935/live/asdf
```
- [ ] visit the webpage at http://localhost:5001/ and add a url from youtube
- [ ] open the rtmp stream url `rtmp://localhost:1935/live/asdf` in VLC with
<img width="586" alt="image" src="https://github.com/SCE-Development/sce-tv/assets/36345325/c5ca995d-de85-4449-8f0c-41721f78792a">
- [ ] ensure the stream runs in VLC
