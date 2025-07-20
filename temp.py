import argparse
import time
import vlc


def play_stream(url):
    instance = vlc.Instance()
    player = instance.media_player_new()
    media = instance.media_new(url)
    player.set_media(media)

    player.play()
    print("Starting playback...")

    # Let it buffer a bit
    time.sleep(5)

    return player


def stream_is_dead(player):
    state = player.get_state()
    # See: https://www.olivieraubert.net/vlc/python-ctypes/doc/vlc.MediaPlayer-class.html#get_state
    return state in (
        vlc.State.Ended,
        vlc.State.Error,
        vlc.State.Stopped,
        vlc.State.NothingSpecial
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "rtmp_stream_url",
        
        help="RTMP stream URL (e.g. rtmp://server/live/streamkey)"
    )
    args = parser.parse_args()

    while True:
        player = play_stream(args.rtmp_stream_url)

        while True:
            time.sleep(1)
            if stream_is_dead(player):
                print("Stream ended or errored. Reconnecting...")
                player.stop()
                break