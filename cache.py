import os
from collections import OrderedDict

from pytube import YouTube

from urllib.parse import urlparse, parse_qs

class Cache():
    def __init__(self, file_path:str, max_cache_size_bytes:int=2_000_000_000) -> None:
        self.file_path = file_path
        self.max_cache_size = max_cache_size_bytes
        self.video_id_to_path = OrderedDict()

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
        self._downsize_cache_to_target_bytes(self.max_cache_size)

    def find(self, video_id:str):
        if video_id not in self.video_id_to_path:
            return None
        self.video_id_to_path.move_to_end(video_id)
        return self.video_id_to_path[video_id]
    
    def _downsize_cache_to_target_bytes(self, target_bytes:int):
        self.max_cache_size = target_bytes
        curr_cache_size = self._get_cache_size()
        while curr_cache_size > target_bytes:
            popped_video_path = self.video_id_to_path.popitem(last=False)[1]
            curr_cache_size -= os.path.getsize(popped_video_path)
            os.remove(popped_video_path)
    
    def _get_cache_size(self) -> int:
        cache_size = 0
        for _, _, files in os.walk(self.file_path):
            for file in files:
                if file[len(file)-3:] == "mp4":
                    cache_size += os.path.getsize(os.path.join(self.file_path, file))
        return cache_size

    def clear(self):
        self._downsize_cache_to_target_bytes(0)

    @staticmethod
    def get_video_id(url) -> str:
        parsed_url = urlparse(url)
        video_id = parse_qs(parsed_url.query)['v'][0]
        return(video_id)
