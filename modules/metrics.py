import enum

import prometheus_client


class Metrics(enum.Enum):
    VIDEO_COUNT = (
        "video_count",
        "Number of videos played",
        prometheus_client.Counter,
    )

    STREAMS_COUNT = (
        "streams_count",
        "Number of streams created",
        prometheus_client.Counter,
        ["video_type"],  # playing, interlude
    )

    SUBPROCESS_COUNT = (
        "subprocess_count",
        "Number of subprocesses ended",
        prometheus_client.Counter,
        ["exit_code"],  # 0, 137, 1 etc.
    )

    DOWNLOAD_TIME = (
        "download_time",
        "Total time spent downloading videos in seconds",
        prometheus_client.Summary,
    )

    DATA_DOWNLOADED = (
        "data_downloaded",
        "Total video data downloaded in bytes",
        prometheus_client.Counter,
    )

    VIDEO_DOWNLOAD_COUNT = (
        "video_download_count",
        "Number of videos downloaded",
        prometheus_client.Counter,
    )

    CACHE_SIZE = (
        "cache_size",
        "Total entries in cache",
        prometheus_client.Gauge,
    )

    CACHE_SIZE_BYTES = (
        "cache_size_bytes",
        "Current cache size in bytes",
        prometheus_client.Gauge,
    )

    CACHE_HIT_COUNT = (
        "cache_hit_count",
        "Number of successful cache retrievals",
        prometheus_client.Counter,
    )

    CACHE_MISS_COUNT = (
        "cache_miss_count",
        "Number of failed cache retrievals",
        prometheus_client.Counter,
    )

    HTTP_REQUEST_COUNT = (
        "http_request_count",
        "Number of requests received for each endpoint",
        prometheus_client.Counter,
        ["endpoint"],
    )

    STREAM_STATE = (
        "stream_state",
        "Indicates whether the given stream type is running "
        "(1=running, 0=stopped)",
        prometheus_client.Gauge,
        ["video_type"],
    )

    DOWNLOAD_MONITOR_SUCCESS = (
        "download_monitor_success",
        "Whether the most recent monitoring download succeeded",
        prometheus_client.Gauge,
    )

    DOWNLOAD_MONITOR_DURATION_SECONDS = (
        "download_monitor_duration_seconds",
        "Duration of the most recent monitoring download in seconds",
        prometheus_client.Gauge,
    )

    DOWNLOAD_MONITOR_FAILURES_TOTAL = (
        "download_monitor_failures_total",
        "Total number of failed monitoring downloads",
        prometheus_client.Counter,
    )

    DOWNLOAD_BITRATE = (
        "download_bitrate_bytes_per_second",
        "Observed bitrate of the 360p test video download in bytes per second",
        prometheus_client.Histogram,
    )

    DOWNLOAD_BITRATE_LATEST = (
        "download_bitrate_latest_bytes_per_second",
        "Bitrate of the most recent 360p test video download "
        "in bytes per second",
        prometheus_client.Gauge,
    )

    def __init__(self, title, description, prometheus_type, labels=()):
        self.title = title
        self.description = description
        self.prometheus_type = prometheus_type
        self.labels = labels


class MetricsHandler:
    @classmethod
    def init(cls) -> None:
        for metric in Metrics:
            setattr(
                cls,
                metric.title,
                metric.prometheus_type(
                    metric.title,
                    metric.description,
                    labelnames=metric.labels,
                ),
            )
