import os
import queue
import subprocess
import threading
import urllib.parse
import requests
from streamlink import Streamlink
from streamlink.exceptions import StreamlinkError
from .auth import get_username
from .chat import start_chat, render_chat, keyboard_listener
from .ui import pause, pick_quality

TWITCH_HOSTS = ("twitch.tv", "www.twitch.tv", "m.twitch.tv")


def twitch_channel(url):
    """The channel of a twitch.tv channel URL, for chat; None for VODs, clips and other sites."""
    parts = urllib.parse.urlsplit(url if "://" in url else f"https://{url}")
    path = parts.path.strip("/").split("/")
    if parts.hostname in TWITCH_HOSTS and len(path) == 1 and path[0]:
        return path[0].lower()
    return None


def choose_stream(streams, quality):
    """(name, stream) for `quality`, else the best one; Twitch often names qualities with their fps (720p60)."""
    for name in (quality, f"{quality}60", "best"):
        if name in streams:
            return name, streams[name]
    return None, None


def play(url, quality="best", token=None, title=""):
    """Resolve `url` with streamlink and play it in mpv, with chat for Twitch channels."""
    print(f"Fetching {url}...")
    try:
        streams = Streamlink().streams(url)
    except (StreamlinkError, ValueError) as e:  # ValueError: malformed URLs such as "http://[::1"
        pause(f"Could not open {url}: {e}")
        return
    if not streams:
        pause(f"No playable streams for {url} (offline?).")
        return

    if quality == "pick":
        quality = pick_quality([q for q in streams if q not in ("worst", "best")])
        if not quality:
            return
    name, stream = choose_stream(streams, quality)
    if not stream:
        pause(f"No usable stream. Available: {', '.join(streams)}")
        return

    try:
        fd = stream.open()
    except (StreamlinkError, OSError) as e:
        pause(f"Failed to open the stream: {e}")
        return
    _watch(fd, f"[{name}] {title or url}", name, twitch_channel(url), token)


def _watch(fd, media_title, quality, channel, token):
    """Pipe the opened stream into mpv, with the chat in the terminal while it plays."""
    os.system("clear")
    mpv = subprocess.Popen(
        ["mpv", "--no-terminal", "--cache=yes", f"--force-media-title={media_title}", "-"],
        stdin=subprocess.PIPE,
    )
    stop_event = threading.Event()

    def stop_when_mpv_exits():
        mpv.wait()
        stop_event.set()
        fd.close()  # wakes up the fd.read() below, which may wait seconds for the next segment

    threading.Thread(target=stop_when_mpv_exits, daemon=True).start()
    threads = _start_chat(channel, token, quality, stop_event) if channel and token else []

    try:
        while chunk := fd.read(65536):
            mpv.stdin.write(chunk)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        print("Stream ended.")
        stop_event.set()
        fd.close()
        try:
            mpv.stdin.close()
        except OSError:
            pass
        mpv.wait()
        for t in threads:
            t.join(timeout=2)


def _start_chat(channel, token, quality, stop_event):
    """Start the chat threads (IRC client, renderer, keyboard); they talk through the two queues."""
    try:
        username = get_username(token)
    except requests.RequestException as e:
        print(f"Chat unavailable ({e}); the stream plays without it.")
        return []
    events, outgoing = queue.Queue(), queue.Queue()
    threads = [
        threading.Thread(target=start_chat, args=(channel, token, username, events, outgoing, stop_event)),
        threading.Thread(target=render_chat, args=(events, outgoing, stop_event, username, channel, quality)),
        threading.Thread(target=keyboard_listener, args=(events, stop_event)),
    ]
    for t in threads:
        t.daemon = True
        t.start()
    return threads
