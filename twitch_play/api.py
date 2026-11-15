import requests
from .config import HTTP_TIMEOUT

BASE = "https://api.twitch.tv/helix"


class TwitchAPI:
    def __init__(self, client_id, token, relogin):
        self.client_id = client_id
        self.token = token
        self.relogin = relogin  # returns a fresh token after logging in again

    def _get(self, path, **params):
        def get():
            headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {self.token}"}
            return requests.get(f"{BASE}/{path}", params=params, headers=headers, timeout=HTTP_TIMEOUT)

        r = get()
        if r.status_code == 401:
            print("Twitch login expired, logging in again...")
            self.token = self.relogin()
            r = get()
        r.raise_for_status()
        return r.json()["data"]

    def top_categories(self, count=100):
        return self._get("games/top", first=count)

    def search_categories(self, query):
        return self._get("search/categories", query=query, first=20)

    def streams(self, game_id, count=50):
        return self._get("streams", game_id=game_id, first=count)
