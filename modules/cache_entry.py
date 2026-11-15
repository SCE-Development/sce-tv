import datetime


class CacheEntry:
    def __init__(
        self,
        file_path,
        size_bytes,
        title=None,
        thumbnail=None,
        last_used=None,
    ):
        self.file_path = file_path
        self.size_bytes = size_bytes
        self.last_used = datetime.datetime.now(tz=datetime.timezone.utc)
        # assume last_used was set from reading the persistent cache json file
        if last_used is not None:
            self.last_used = datetime.datetime.strptime(last_used, "%Y-%m-%dT%H:%M:%SZ")
            self.last_used = self.last_used.replace(tzinfo=datetime.timezone.utc)
        self.title = title
        self.thumbnail  = thumbnail

    def to_dict(self):
        return {
                "file_path": self.file_path,
                "size_bytes": self.size_bytes,
                "title": self.title,
                "thumbnail": self.thumbnail,
                "last_used": self.last_used.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    def __repr__(self):
        return repr(self.to_dict())

