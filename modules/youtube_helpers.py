import os
import pathlib
import uuid
import urllib

import pytubefix

from modules.logger import logger
from modules.constants import UrlType
from modules.metrics import MetricsHandler
from modules.cache_entry import CacheEntry


class VideoMetadata:
    def __init__(self, pid, video_id, url=None, title=None, thumbnail=None):
        self.pid = pid
        self.video_id = video_id
        self.title = title
        # if there is no title and no url, we are playing a video
        # that already exists on disk, so we use the file name as the title
        if not title and not url:
            # remove any escaped spaces which happen when we are playing a
            # video that already exists on disk.
            self.title = pathlib.Path(video_id).name.replace("\\ ", " ")
        self.thumbnail = thumbnail

        # if there is no title and no thumbnail but a url, we load the title and
        # thumbnail from the (assumed) youtube url with pytubefix
        no_title_or_thumbnail = all([value is None for value in [title, thumbnail]])
        if no_title_or_thumbnail and url is not None:
            self.title = get_video_title(url)
            self.thumbnail = get_video_thumbnail(url)

    def as_json_object(self):
        return {
            "title": self.title,
            "thumbnail": self.thumbnail,
        }


def get_video_size_bytes(url):
    try:
        yt = pytubefix.YouTube(url)
        size = (
            yt.streams.filter(
                resolution="360p",
                progressive=True,
            )
            .order_by("resolution")
            .desc()
            .first()
            .filesize
        )
        return size
    except pytubefix.exceptions.VideoUnavailable:
        logger.exception(f"Video with url {url} not found, skipping")
        return False
    except:
        logger.exception(f"Getting size of {url} had an error")
        return False


# Example:
# download_video_from_youtube('https://www.youtube.com/watch?v=uhXo5Pj7mQs')
def download_video_from_youtube(url, output_path) -> CacheEntry | None:
    try:
        yt = pytubefix.YouTube(url)
        with MetricsHandler.download_time_seconds.time():
            video_to_download = (
                yt.streams.filter(
                    resolution="360p",
                    progressive=True,
                )
                .order_by("resolution")
                .desc()
                .first()
            )
            MetricsHandler.bytes_downloaded.inc(video_to_download.filesize)
            path = video_to_download.download(output_path=output_path)
            logger.info(f"Successfully downloaded {url} to {path}")
            renamed_video_path = os.path.join(output_path, str(uuid.uuid4()))
            os.rename(path, renamed_video_path)
            logger.info(f"Successfully renamed {path} to {renamed_video_path}")
            MetricsHandler.videos_downloaded.inc()
            return CacheEntry(
                renamed_video_path,
                os.path.getsize(renamed_video_path),
                get_video_title(url),
                get_video_thumbnail(url),
            )
    except pytubefix.exceptions.VideoUnavailable:
        logger.error(f"Video with url {url} not found, skipping")
        MetricsHandler.downloads_failed.inc()
        return False
    except Exception:
        logger.exception(f"Downloading video with url {url} had an error")
        MetricsHandler.downloads_failed.inc()
        return False


def get_length_of_video_seconds(url):
    try:
        yt = pytubefix.YouTube(url)
        return yt.length
    except pytubefix.exceptions.VideoUnavailable:
        logger.error(f"Video with url {url} not found, skipping")
        return False
    except Exception as e:
        logger.error(f"Unable to get length error: {e}")
        return False


def get_video_title(url):
    try:
        url_type = determine_url_type(url)
        if url_type == UrlType.PLAYLIST:
            yt = pytubefix.Playlist(url)
            return yt.title
        elif url_type == UrlType.VIDEO:
            yt = pytubefix.YouTube(url)
            return yt.title
    except pytubefix.exceptions.VideoUnavailable:
        logger.error(f"Video with url {url} not found, skipping")
        return False
    except Exception as e:
        logger.error(f"Unable to get video title: {e}")
        return False


def get_video_thumbnail(url):
    try:
        yt = pytubefix.YouTube(url)
        return yt.thumbnail_url
    except pytubefix.exceptions.VideoUnavailable:
        logger.error(f"Video with url {url} not found, skipping")
        return False
    except Exception as e:
        logger.error(f"Unable to get video thumbnail: {e}")
        return False


def determine_url_type(url):
    try:
        playlist = pytubefix.Playlist(url)
        logger.debug(f"{url} is a playlist with {len(playlist)} videos")
        return UrlType.PLAYLIST
    except:
        try:
            pytubefix.YouTube(url)
            return UrlType.VIDEO
        except:
            logger.error(f"url {url} is not a playlist or video!")
            return UrlType.UNKNOWN


def get_playlist_videos(url):
    try:
        index = 1
        # for parsing a url see https://stackoverflow.com/a/5075477
        parsed_url = urllib.parse.urlparse(url)
        query_dict = urllib.parse.parse_qs(parsed_url.query)
        url_to_use = f'https://www.youtube.com/playlist?list={query_dict["list"][0]}'
        if "index" in query_dict:
            try:
                index = int(query_dict["index"][0])
            except:
                logger.exception(f"unable to extract index parameter from url {url}")
        # playlist videos are indexed at 1, so if there is an index,
        # we extract it and play the playlist from the video
        # https://www.youtube.com/watch?v=t5lIhDDUZms&list=<list id>&index=4&ab_channel=WebdriverTorso
        correct_index = index - 1
        return list(pytubefix.Playlist(url_to_use).video_urls)[correct_index:]
    except:
        logger.exception(f"unable to get list of videos from {url}")
        return []


def extract_video_id_from_url(url):
    try:
        yt = pytubefix.YouTube(url)
        return yt.video_id
    except:
        return None
