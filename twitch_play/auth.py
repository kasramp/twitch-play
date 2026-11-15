import secrets
import webbrowser
import threading
import urllib.parse
import logging
import requests
from flask import Flask, request, Response
from werkzeug.serving import make_server
from .config import CLIENT_ID

REDIRECT_URI = "http://localhost:8765/callback"
AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
SCOPES = ["user:read:email", "user:read:follows", "chat:read", "chat:edit"]

_JS_PAGE = """
<script>
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get('access_token');
  if (token) {
    const state = encodeURIComponent(params.get('state') || '');
    fetch('/token?state=' + state, {method:'POST', body: token})
      .then(() => document.write('Authenticated! You can close this tab.'));
  } else {
    document.write('Error: no token found. Please try again.');
  }
</script>
"""


def login():
    app = Flask(__name__)
    # only our own login redirect knows this, so another web page can't post a token of its choosing
    state = secrets.token_urlsafe(16)
    auth_store = {"token": None}
    auth_event = threading.Event()

    @app.route("/callback")
    def callback():
        return Response(_JS_PAGE, mimetype="text/html")

    @app.route("/token", methods=["POST"])
    def receive_token():
        if not secrets.compare_digest(request.args.get("state", ""), state):
            return "bad state", 403
        auth_store["token"] = request.get_data(as_text=True)
        auth_event.set()
        return "ok"

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    # a server we can shut down, so a second login in the same run can bind the port again
    server = make_server("localhost", 8765, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    params = {
        "client_id": CLIENT_ID,
        "response_type": "token",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "force_verify": "false",
    }
    webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode(params))
    print("Waiting for Twitch login in browser...")
    try:
        if not auth_event.wait(timeout=120):
            raise TimeoutError("Auth timed out after 120s")
    finally:
        server.shutdown()
        server.server_close()
    return {"access_token": auth_store["token"]}


def strip_oauth(token: str) -> str:
    if token.startswith("oauth:"):
        return token[len("oauth:"):]
    return token


def token_valid(token: str) -> bool:
    """Ask Twitch whether the token still works and has every scope we ask for (Twitch asks apps to check)."""
    r = requests.get(VALIDATE_URL, headers={"Authorization": f"OAuth {strip_oauth(token)}"})
    if r.status_code == 401:
        return False
    r.raise_for_status()
    # tokens from before the chat feature lack the chat scopes
    return set(SCOPES) <= set(r.json().get("scopes", []))


def get_username(token: str) -> str:
    token = strip_oauth(token)
    r = requests.get(
        VALIDATE_URL,
        headers={"Authorization": f"OAuth {token}"}
    )
    r.raise_for_status()
    return r.json()["login"]