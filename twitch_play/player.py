import os
import subprocess
import threading
import queue
import traceback
from streamlink import Streamlink
from .chat import start_chat, render_chat, keyboard_listener
from .auth import get_username, strip_oauth

def play_channel(channel: str, title: str = "", streamer: str = "", quality: str = "best", token=None):
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

    os.system("clear")

    mpv = subprocess.Popen(
        ["mpv", "--no-terminal", "--cache=yes", f"--force-media-title={media_title}", "-"],
        stdin=subprocess.PIPE,
    )

    stop_event = threading.Event()
    chat_queue = queue.Queue()
    threads = []

    if token:
        username = None
        try:
            username = get_username(token)
        except Exception:
            print("Chat setup failed, stream will continue without chat:")
            traceback.print_exc()
            token = None

        if token and username:
            chat_state = {
                "paused": False,
                "scroll": 0,
                "anchor": 0,
                "total": 0,
                "mode": "normal",
                "search_query": "",
                "search_active": False,
            }

            t1 = threading.Thread(
                target=start_chat,
                args=(channel, strip_oauth(token), username, chat_queue, stop_event),
                daemon=True,
            )
            t1.start()

            t2 = threading.Thread(
                target=render_chat,
                args=(chat_queue, stop_event, chat_state, channel, quality),
                daemon=True,
            )
            t2.start()

            t3 = threading.Thread(
                target=keyboard_listener,
                args=(chat_state, stop_event),
                daemon=True,
            )
            t3.start()

            threads = [t1, t2, t3]

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
        stop_event.set()
        fd.close()
        try:
            mpv.stdin.close()
        except Exception:
            pass
        mpv.wait()
        for t in threads:
            t.join(timeout=2)