import os
import json
import shutil
import sys
import requests
from .auth import login, token_valid
from .api import TwitchAPI
from .ui import pause, pick_category, pick_stream
from .player import play
from .config import CLIENT_ID

CACHE = os.path.expanduser("~/.config/twitch-play/token.json")


def save(token):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        os.chmod(CACHE, 0o600)  # the token is a credential: owner-only
        json.dump({"access_token": token}, f)


def load():
    """The cached token, or None when there is none or the file is unreadable."""
    try:
        with open(CACHE) as f:
            os.chmod(CACHE, 0o600)  # older versions left it readable by everyone
            return json.load(f)["access_token"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def get_token(force_login=False):
    """The cached token if Twitch still accepts it, else a new one from the browser login."""
    token = None if force_login else load()
    if token and token_valid(token):
        return token
    token = login()
    save(token)
    return token


def get_token_or_exit(force_login=False):
    try:
        return get_token(force_login)
    except OSError as e:  # covers the login timeout, a busy port and requests' network/HTTP errors
        sys.exit(f"Twitch login failed: {e}. Run twitch-play again to retry.")


def main():
    missing = [cmd for cmd in ("fzf", "mpv") if not shutil.which(cmd)]
    if missing:
        sys.exit(f"twitch-play needs {' and '.join(missing)} installed; see the README.")
    api = TwitchAPI(CLIENT_ID, get_token_or_exit(), relogin=lambda: get_token_or_exit(force_login=True))
    try:
        browse(api)
    except requests.RequestException as e:
        sys.exit(f"Twitch API error: {e}")


def browse(api):
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
