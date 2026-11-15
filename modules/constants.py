import enum


class Video(enum.Enum):
    # If no specified video is playing, interlude plays
    INTERLUDE = "interlude"
    PLAYING = "playing"


class UrlType(enum.Enum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    UNKNOWN = "unknown"
