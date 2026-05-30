import sys
import urllib.parse
import requests

BASE = "https://api.twitch.tv/helix"


class TwitchAPI:
    def __init__(self, client_id, token):
        self.client_id = client_id
        self.token = token

    def _headers(self):
        return {
            "Client-Id": self.client_id,
            "Authorization": f"Bearer {self.token}",
        }

    def _get(self, url):
        r = requests.get(url, headers=self._headers())
        if r.status_code == 401:
            print("Token expired. Delete ~/.config/twitch-play/token.json and re-run.")
            sys.exit(1)
        r.raise_for_status()
        return r.json()

    def top_categories(self, count=100):
        return self._get(f"{BASE}/games/top?first={count}")["data"]

    def search_categories(self, query):
        return self._get(
            f"{BASE}/search/categories?query={urllib.parse.quote(query)}&first=20"
        )["data"]

    def streams(self, game_id, count=50):
        return self._get(
            f"{BASE}/streams?game_id={game_id}&first={count}"
        )["data"]