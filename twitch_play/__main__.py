import os
import json
import sys
from .auth import login, token_valid
from .api import TwitchAPI
from .ui import pause, pick_category, pick_stream
from .player import play
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
            return
        if "url" in cat:
            play(cat["url"], cat["quality"], api.token)
            continue

        while True:
            streams = api.streams(cat["id"])
            if not streams:
                pause(f"No live streams in '{cat['name']}' right now.")
                break
            streams.sort(key=lambda s: s["viewer_count"], reverse=True)
            stream, quality = pick_stream(streams)
            if not stream:
                break
            play(
                f"https://twitch.tv/{stream['user_login']}",
                quality,
                api.token,
                title=f"{stream['user_name']} — {stream.get('title', '')}",
            )


if __name__ == "__main__":
    main()
