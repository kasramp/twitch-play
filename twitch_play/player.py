import subprocess
from streamlink import Streamlink


def play_channel(channel: str, title: str = "", streamer: str = "", quality: str = "best"):
    session = Streamlink()
    print(f"Fetching stream for {channel} [{quality}]...")

    try:
        streams = session.streams(f"twitch.tv/{channel}")
    except Exception as e:
        print(f"Streamlink error: {e}")
        return

    if not streams:
        print("No streams found.")
        return

    # resolve quality
    if quality == "best" or quality not in streams:
        for q in ("best", "1080p60", "720p60", "720p", "480p", "worst"):
            if q in streams:
                stream = streams[q]
                quality = q
                break
        else:
            print(f"No usable stream. Available: {list(streams.keys())}")
            return
    else:
        stream = streams[quality]

    print(f"Opening [{quality}] {channel}...")
    media_title = f"[{quality}] {streamer} — {title}" if title else f"[{quality}] {channel}"

    try:
        fd = stream.open()
    except Exception as e:
        print(f"Failed to open stream: {e}")
        return

    mpv = subprocess.Popen(
        ["mpv", "--no-terminal", "--cache=yes", f"--force-media-title={media_title}", "-"],
        stdin=subprocess.PIPE,
    )

    try:
        while True:
            chunk = fd.read(65536)
            if not chunk:
                break
            mpv.stdin.write(chunk)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        print("Stream ended.")
        fd.close()
        try:
            mpv.stdin.close()
        except Exception:
            pass
        mpv.wait()