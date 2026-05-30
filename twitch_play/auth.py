import secrets
import webbrowser
import threading
import time
import urllib.parse
import logging
from flask import Flask, request, Response

from .config import CLIENT_ID

REDIRECT_URI = "http://localhost:8765/callback"
AUTH_URL = "https://id.twitch.tv/oauth2/authorize"

_JS_PAGE = """
<script>
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get('access_token');
  if (token) {
    fetch('/token', {method:'POST', body: token})
      .then(() => document.write('Authenticated! You can close this tab.'));
  } else {
    document.write('Error: no token found. Please try again.');
  }
</script>
"""


def login():
    app = Flask(__name__)
    auth_store = {"token": None}
    auth_event = threading.Event()

    @app.route("/callback")
    def callback():
        return Response(_JS_PAGE, mimetype="text/html")

    @app.route("/token", methods=["POST"])
    def receive_token():
        auth_store["token"] = request.get_data(as_text=True)
        auth_event.set()
        return "ok"

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    threading.Thread(
        target=lambda: app.run(port=8765, debug=False, use_reloader=False),
        daemon=True,
    ).start()
    time.sleep(0.5)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "token",
        "redirect_uri": REDIRECT_URI,
        "scope": "user:read:email user:read:follows",
        "state": secrets.token_urlsafe(16),
        "force_verify": "false",
    }
    webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode(params))
    print("Waiting for Twitch login in browser...")

    if not auth_event.wait(timeout=120):
        raise TimeoutError("Auth timed out after 120s")

    return {"access_token": auth_store["token"]}