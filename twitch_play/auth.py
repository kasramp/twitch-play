import http.server
import secrets
import threading
import urllib.parse
import webbrowser
import requests
from .config import CLIENT_ID, HTTP_TIMEOUT

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"
AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
SCOPES = ["user:read:email", "user:read:follows", "chat:read", "chat:edit"]

# Twitch puts the token in the URL fragment, which never reaches a server: this page posts it back to us.
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


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Serves the redirect page and receives the token it posts back."""

    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path == "/callback":
            self._reply(200, _JS_PAGE, "text/html")
        else:
            self._reply(404, "not found")

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        state = urllib.parse.parse_qs(url.query).get("state", [""])[0]
        # only our own login redirect knows the state, so another web page can't post a token of its choosing
        if url.path != "/token" or not secrets.compare_digest(state.encode(), self.server.state.encode()):
            self._reply(403, "bad state")
            return
        length = min(int(self.headers.get("Content-Length", 0)), 4096)
        self.server.token = self.rfile.read(length).decode(errors="ignore")
        self._reply(200, "ok")
        self.server.got_token.set()

    def _reply(self, status, body, content_type="text/plain"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # keep request logs out of the terminal


def login():
    """Log in through the browser (OAuth implicit grant) and return the access token."""
    server = http.server.HTTPServer(("localhost", PORT), _CallbackHandler)
    server.state = secrets.token_urlsafe(16)
    server.token = None
    server.got_token = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    params = {
        "client_id": CLIENT_ID,
        "response_type": "token",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": server.state,
        "force_verify": "false",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    webbrowser.open(url)
    print(f"Waiting for Twitch login in your browser. If none opened, visit:\n{url}")
    try:
        if not server.got_token.wait(timeout=120):
            raise TimeoutError("Auth timed out after 120s")
    finally:
        # frees the port, so a second login in the same run can use it again
        server.shutdown()
        server.server_close()
    return server.token


def _validate(token):
    return requests.get(VALIDATE_URL, headers={"Authorization": f"OAuth {token}"}, timeout=HTTP_TIMEOUT)


def token_valid(token):
    """Ask Twitch whether the token still works and has every scope we ask for (Twitch asks apps to check)."""
    r = _validate(token)
    if r.status_code == 401:
        return False
    r.raise_for_status()
    # tokens from before the chat feature lack the chat scopes
    return set(SCOPES) <= set(r.json().get("scopes", []))


def get_username(token):
    r = _validate(token)
    r.raise_for_status()
    return r.json()["login"]
