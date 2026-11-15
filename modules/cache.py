from collections import OrderedDict
import datetime
import json
import os
import typing

from modules.common import synchronized
from modules.logger import logger
from modules import disk_helpers
from modules import youtube_helpers
from modules.metrics import MetricsHandler
from modules.cache_entry import CacheEntry


class Cache:
    """
    Meant to "Cache" downloaded files from YouTube on a machine's disk. Instead
    of downloading a video everytime the server recieves a URL/Playlist, we check
    if the given URL has a mapping to a file location on the disk. Recently
    downloaded files will be kept on disk with the mapping of URLs to file paths
    stored in memory.
    """

    # 2GB default cache size
    def __init__(
            self,
            download_file_location,
            max_size_bytes=2_000_000_000,
            cache_state_file_path=None,
        ) -> None:
        # https://www.geeksforgeeks.org/lru-cache-in-python-using-ordereddict/
        self._download_file_location = download_file_location
        self.max_size_bytes = max_size_bytes
        self.current_size_bytes = 0
        self.mapping = OrderedDict()
        self.cache_state_file_path = cache_state_file_path
    
    def populate(self):
        if self.cache_state_file_path is not None:
            try:
                with open(self.cache_state_file_path, 'r') as f:
                    mapping = json.load(f)
                    for key, entry in mapping.items():
                        if not os.path.exists(entry["file_path"]):
                            logger.debug(f'not recovering {entry["file_path"]} because the file wasnt found')
                            continue
                        self.mapping[key] = CacheEntry(
                            entry["file_path"],
                            entry["size_bytes"],
                            entry["title"],
                            entry["thumbnail"],
                            entry["last_used"],
                        )
                        self.current_size_bytes += int(entry["size_bytes"])
                    logger.info(f"recovered {len(mapping.items())} items from cache file {self.cache_state_file_path}")
            except Exception:
                logger.exception(f"unable to recover cache from file {self.cache_state_file_path}")
                self.mapping = OrderedDict()

        MetricsHandler.cache_entries.set(len(self.mapping))
        MetricsHandler.cache_size_bytes.set(self.current_size_bytes)

    
    def list_entries(self) -> typing.List[typing.Dict[str, typing.Any]]:
        result = []
        for video_id, value in self.mapping.items():
            result.append({
                    "id": video_id,
                    "name": value.title,
                    "path": value.file_path,
                    "thumbnail": value.thumbnail,
                    "size_bytes": value.size_bytes,
                    "last_used":  value.last_used,
                })
        return result

    @synchronized
    def find(self, url) -> CacheEntry | None:
        video_id = youtube_helpers.extract_video_id_from_url(url)
        maybe_entry = self.mapping.get(video_id)
        if maybe_entry == None:
            MetricsHandler.cache_misses.inc()
            return None
        MetricsHandler.cache_hits.inc()
        self.mapping.move_to_end(video_id)
        self.mapping[video_id].last_used = datetime.datetime.now(
            tz=datetime.timezone.utc
        )
        return maybe_entry

    def _downsize_cache_to_target_bytes(self, target):
        logger.info(f"downsizing cache to {target} bytes")
        while self.current_size_bytes > target:
            if len(self.mapping) == 0:
                logger.error(
                    f"for some reason the cache size is 0 but {self.current_size_bytes} > {target}"
                )
                break
            _, entry = self.mapping.popitem(last=False)
            MetricsHandler.cache_entries.dec()
            disk_helpers.maybe_delete_file_from_disk(entry.file_path)
            self.current_size_bytes -= entry.size_bytes
            MetricsHandler.cache_size_bytes.set(self.current_size_bytes)
    
    @synchronized
    def delete(self, videoId) -> bool:
        if videoId not in self.mapping:
            logger.info(f"video id {videoId} not found in mapping, skipping deletion")
            return False
        entry = self.mapping.pop(videoId)
        MetricsHandler.cache_entries.dec()
        disk_helpers.maybe_delete_file_from_disk(entry.file_path)
        self.current_size_bytes -= entry.size_bytes
        MetricsHandler.cache_size_bytes.set(self.current_size_bytes)
        logger.info(f"removed video id {videoId} from cache")
        return True

    @synchronized
    def add(self, url) -> CacheEntry | None:
        video_id = youtube_helpers.extract_video_id_from_url(url)
        cache_already_has_url = video_id in self.mapping
        if cache_already_has_url:
            logger.debug(
                f"attempted to store {url} in cache but it already exists with key {video_id}"
            )
            return self.mapping.get(video_id).file_path

        video_size_bytes = youtube_helpers.get_video_size_bytes(url)
        if video_size_bytes > self.max_size_bytes:
            logger.error(
                f"{url} has size {video_size_bytes}, exceeds max cache size of {self.max_size_bytes} bytes"
            )
            return None
        elif video_size_bytes == False:
            logger.error(f"unable to calculate bytes size of {url}")
            return None

        maybe_path = youtube_helpers.download_video_from_youtube(url, self._download_file_location)
        if not maybe_path:
            return None

        size_bytes = maybe_path.size_bytes
        if size_bytes + self.current_size_bytes > self.max_size_bytes:
            target = self.current_size_bytes - size_bytes
            self._downsize_cache_to_target_bytes(target)

        self.current_size_bytes += size_bytes
        MetricsHandler.cache_size_bytes.set(self.current_size_bytes)
        self.mapping[video_id] = maybe_path
        self.mapping.move_to_end(video_id)
        MetricsHandler.cache_entries.inc()
        logger.debug(f"creating mapping of {video_id} to {maybe_path.file_path}")
        return self.mapping[video_id]

    @synchronized
    def clear(self):
        if self.cache_state_file_path is None:
            self._downsize_cache_to_target_bytes(0)
            return
        
        logger.info(f"persisting cache to {self.cache_state_file_path}")
        json_encoded_dict = {}
        # stupid hack to convert the CacheEntry class to a dict
        for key, value in self.mapping.items():
            json_encoded_dict[key] = value.to_dict()
        with open(self.cache_state_file_path, 'w') as f:
            f.write(json.dumps(json_encoded_dict))
