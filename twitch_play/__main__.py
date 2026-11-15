import os
import json
import sys
from streamlink import Streamlink
from .auth import login, token_valid
from .api import TwitchAPI
from .ui import pick_category, pick_stream, pick_quality
from .player import play_channel
from .config import CLIENT_ID

CACHE = os.path.expanduser("~/.config/twitch-play/token.json")


def save(token):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(token, f)


def load():
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            return json.load(f)
    return None


def get_token(force_login=False):
    """The cached token if Twitch still accepts it, else a new one from the browser login."""
    token_data = None if force_login else load()
    if token_data and token_valid(token_data["access_token"]):
        return token_data["access_token"]
    token_data = login()
    save(token_data)
    return token_data["access_token"]


def get_token_or_exit(force_login=False):
    try:
        return get_token(force_login)
    except OSError as e:  # covers the login timeout, a busy port and requests' network/HTTP errors
        sys.exit(f"Twitch login failed: {e}. Run twitch-play again to retry.")


def main():
    api = TwitchAPI(CLIENT_ID, get_token_or_exit(), relogin=lambda: get_token_or_exit(force_login=True))

    while True:
        cat = pick_category(api)
        if not cat:
            sys.exit(0)

        # direct URL flow
        if "url" in cat:
            url = cat["url"]
            quality = cat.get("quality", "best")
            print(f"Validating {url}...")
            try:
                session = Streamlink()
                streams = session.streams(url)
                if not streams:
                    print(f"No playable streams found for: {url}")
                    input("Press Enter to go back...")
                    continue
                if quality == "pick":
                    available = [q for q in streams.keys() if q not in ("worst", "best")]
                    quality = pick_quality(available)
                    if not quality:
                        continue
            except Exception as e:
                print(f"Could not open {url}: {e}")
                input("Press Enter to go back...")
                continue
            play_channel(url, quality=quality, token=api.token)
            continue

        # normal category -> stream flow
        while True:
            streams = api.streams(cat["id"])
            if not streams:
                print(f"No live streams in '{cat['name']}' right now.")
                break
            streams.sort(key=lambda s: s["viewer_count"], reverse=True)
            stream, quality = pick_stream(streams)
            if not stream:
                break
            if quality == "pick":
                session = Streamlink()
                sl_streams = session.streams(f"twitch.tv/{stream['user_login']}")
                available = [q for q in sl_streams.keys() if q not in ("worst", "best")]
                quality = pick_quality(available)
                if not quality:
                    continue
            play_channel(
                stream["user_login"],
                title=stream.get("title", ""),
                streamer=stream.get("user_name", ""),
                quality=quality,
                token=api.token,
            )


if __name__ == "__main__":
    main()