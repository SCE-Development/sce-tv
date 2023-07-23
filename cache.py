import os

from pytube import YouTube

from urllib.parse import urlparse, parse_qs

class Cache():
    def __init__(self, file_path:str, max_cache_size_bytes:int=2_000_000_000) -> None:
        self.file_path = file_path
        self.cache_size = max_cache_size_bytes
        self.video_id_to_path = {}

    def add(self, url:str):
        video = YouTube(url)
        # Check for age restriction/video availability
        video.bypass_age_gate()
        video.check_availability()
        # Download video of set resolution
        video = video.streams.filter(
                        resolution="360p",
                        progressive=True,
                    ).order_by("resolution").desc().first()
        video_file_name = video.default_filename
        if (video_file_name not in os.listdir(self.file_path)):
            video.download(self.file_path)

        video_id = self.get_video_id(url)
        self.video_id_to_path[video_id] = os.path.join(self.file_path, video_file_name)

    def find(self, video_id:str):
        if video_id not in self.video_id_to_path:
            return None
        return self.video_id_to_path[video_id]
    
    @staticmethod
    def get_video_id(url):
        parsed_url = urlparse(url)
        video_id = parse_qs(parsed_url.query)['v'][0]
        return(video_id)