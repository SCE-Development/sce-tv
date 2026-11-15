import enum
import prometheus_client


class Metrics(enum.Enum):
    # name, desc, type, labelnames=()
    # above default value referenced from the metrics constructor
    # in the prometheus_client library, see
    # https://github.com/prometheus/client_python/blob/fd4da6cde36a1c278070cf18b4b9f72956774b05/prometheus_client/metrics.py#L115
    FFMPEG_STREAMS_CREATED = (
        "ffmpeg_streams_created",
        "total number of ffmpeg streams created",
        prometheus_client.Counter,
        ["stream_name"],
    )
    FFMPEG_EXIT_CODES = (
        "ffmpeg_exit_codes",
        "exit codes returned by ffmpeg when streaming videos to node media server",
        prometheus_client.Counter,
        ["exit_code", "stream_name"],
    )

    PLAYING_TIME_SECONDS = (
        "playing_time_seconds",
        "total time playing videos in seconds",
        prometheus_client.Summary,
        ["video_type", "stream_name"],
    )
    DOWNLOAD_TIME_SECONDS = (
        "download_time_seconds",
        "total time spent downloading videos in seconds",
        prometheus_client.Summary,
    )

    BYTES_DOWNLOADED = (
        "bytes_downloaded",
        "total bytes downloaded from YouTube",
        prometheus_client.Counter,
    )
    VIDEOS_DOWNLOADED = (
        "videos_downloaded",
        "total number of videos downloaded from YouTube",
        prometheus_client.Counter,
    )
    DOWNLOADS_FAILED = (
        "downloads_failed",
        "total number of failed downloads from YoutTube",
        prometheus_client.Counter,
    )
    FILES_DELETED = (
        "files_deleted",
        "total number of files deleted from disk",
        prometheus_client.Counter,
        ["type"],
    )

    CACHE_ENTRIES = (
        "cache_entries",
        "number of entries in cache",
        prometheus_client.Gauge,
    )
    CACHE_SIZE_BYTES = (
        "cache_size_bytes",
        "total bytes of files pointed to by cache",
        prometheus_client.Gauge,
    )
    CACHE_HITS = (
        "cache_hits",
        "number of cache hits",
        prometheus_client.Counter,
    )
    CACHE_MISSES = (
        "cache_misses",
        "number of cache misses",
        prometheus_client.Counter,
    )
    THUMBNAIL_CACHE_ENTRIES = (
        "thumbnail_cache_entries",
        "number of entries in thumbnail cache",
        prometheus_client.Gauge,
    )
    THUMBNAIL_CACHE_HITS = (
        "thumbnail_cache_hits",
        "number of thumbnail cache hits",
        prometheus_client.Counter,
    )
    THUMBNAIL_CACHE_MISSES = (
        "thumbnail_cache_misses",
        "number of thumbnail cache misses",
        prometheus_client.Counter,
    )

    VIDEOS_RECIEVED = (
        "urls_recieved",
        "number of urls asked to play from the frontend",
        prometheus_client.Counter,
        ["url_type", "stream_name"],
    )

    def __init__(self, title, description, prometheus_type, labels=()):
        # we use the above default value for labels because it matches what's used
        # in the prometheus_client library's metrics constructor, see
        # https://github.com/prometheus/client_python/blob/fd4da6cde36a1c278070cf18b4b9f72956774b05/prometheus_client/metrics.py#L115
        self.title = title
        self.description = description
        self.prometheus_type = prometheus_type
        self.labels = labels


class MetricsHandler:
    @classmethod
    def init(self) -> None:
        for metric in Metrics:
            setattr(
                self,
                metric.title,
                metric.prometheus_type(
                    metric.title, metric.description, labelnames=metric.labels
                ),
            )
