import argparse


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="the location to stream downloaded files to, i.e. rtmp://localhost/stream/live"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="the location to stream downloaded files to, i.e. rtmp://localhost/stream/live"
    )
    parser.add_argument(
        "--rtmp-stream-url",
        help="the location to stream downloaded files to, i.e. rtmp://localhost/stream/live"
    )
    parser.add_argument(
        "--rtmp-base-url",
        help="base url of the rtmp stream, i.e. rtmp://localhost/stream. meant to be used with --rtmp-stream-names"
    )
    parser.add_argument(
        "--rtmp-stream-names",
        type=str,
        help="""
            names of streams to append to the base url, i.e. supplying
            "foo,bar" with a base url of rtmp://localhost/stream makes
            the server stream to rtmp://localhost/stream/foo and
            rtmp://localhost/stream/bar
        """
    )
    parser.add_argument(
        "--download-file-location",
        required=True,
        help="directory to store of downloaded videos"
    )
    parser.add_argument(
        "--interlude-file-path",
        help="path to interlude file"
    )
    parser.add_argument(
        "--cache-size-bytes",
        type=int,
        # 2GB default
        default=2_000_000_000,
        help="total file size of downloaded video cache. default 2GB"
    )
    parser.add_argument(
        "--cache-state-file",
        help="JSON file to persist cache state on server shutdown and recover on startup. if specified, the server will not empty the cache on shutdown"
    )
    parser.add_argument(
        "--thumbnail-cache-size",
        type=int,
        default=20,
        help="total file size of thumbnail cache, max number of pngs to store at any time"
    )
    parser.add_argument(
        "--prometheus-port",
        type=int,
        default=5000,
        help="total file size of cache"
    )
    args = parser.parse_args()
    args.rtmp_stream_names = args.rtmp_stream_names.split(',') if args.rtmp_stream_names else []
    return args
