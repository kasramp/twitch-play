import os
import json
import sys
from streamlink import Streamlink
from .auth import login
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


def main():
    token_data = load()
    if not token_data:
        token_data = login()
        save(token_data)

    api = TwitchAPI(CLIENT_ID, token_data["access_token"])

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
                    quality = pick_quality(available) or "best"
            except Exception as e:
                print(f"Could not open {url}: {e}")
                input("Press Enter to go back...")
                continue
            play_channel(url, quality=quality, token=token_data["access_token"])
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
                quality = pick_quality(available) or "best"
            play_channel(
                stream["user_login"],
                title=stream.get("title", ""),
                streamer=stream.get("user_name", ""),
                quality=quality,
                token=token_data["access_token"],
            )


if __name__ == "__main__":
    main()