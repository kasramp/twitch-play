import os
import socket
import stat
import tempfile
import unittest
import urllib.parse
from unittest import mock

import requests

from twitch_play import __main__ as app
from twitch_play.api import TwitchAPI
from twitch_play.auth import SCOPES, login, token_valid


def response(status, body=None):
    r = mock.Mock(status_code=status)
    r.json.return_value = body or {}
    r.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(status)
    return r


class GetTokenTest(unittest.TestCase):
    def setUp(self):
        patches = {
            "load": mock.patch.object(app, "load", return_value="old"),
            "save": mock.patch.object(app, "save"),
            "login": mock.patch.object(app, "login", return_value="new"),
            "valid": mock.patch.object(app, "token_valid", return_value=True),
        }
        self.m = {name: p.start() for name, p in patches.items()}
        self.addCleanup(mock.patch.stopall)

    def test_valid_cached_token_is_used(self):
        self.assertEqual(app.get_token(), "old")
        self.m["login"].assert_not_called()

    def test_expired_token_logs_in_again(self):
        self.m["valid"].return_value = False
        self.assertEqual(app.get_token(), "new")
        self.m["save"].assert_called_once_with("new")

    def test_no_cached_token_logs_in(self):
        self.m["load"].return_value = None
        self.assertEqual(app.get_token(), "new")

    def test_force_login_skips_cache(self):
        self.assertEqual(app.get_token(force_login=True), "new")
        self.m["valid"].assert_not_called()


class TokenValidTest(unittest.TestCase):
    @mock.patch("twitch_play.auth.requests.get")
    def test_statuses(self, get):
        get.return_value = response(200, {"scopes": SCOPES})
        self.assertTrue(token_valid("abc"))
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "OAuth abc"})
        self.assertIn("timeout", get.call_args.kwargs)
        get.return_value = response(401)
        self.assertFalse(token_valid("abc"))
        get.return_value = response(500)
        with self.assertRaises(requests.HTTPError):
            token_valid("abc")  # a Twitch outage is not a reason to log in again

    @mock.patch("twitch_play.auth.requests.get")
    def test_token_without_chat_scopes_is_invalid(self, get):
        get.return_value = response(200, {"scopes": ["user:read:email", "user:read:follows"]})
        self.assertFalse(token_valid("abc"))


@mock.patch("twitch_play.api.print", create=True, new=mock.Mock())
class TwitchAPIReloginTest(unittest.TestCase):
    @mock.patch("twitch_play.api.requests.get")
    def test_401_logs_in_again_and_retries(self, get):
        get.side_effect = [response(401), response(200, {"data": ["cat"]})]
        relogin = mock.Mock(return_value="fresh")
        api = TwitchAPI("client", "stale", relogin)
        self.assertEqual(api.top_categories(), ["cat"])
        relogin.assert_called_once()
        self.assertEqual(api.token, "fresh")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer fresh")

    @mock.patch("twitch_play.api.requests.get")
    def test_second_401_raises_without_looping(self, get):
        get.side_effect = [response(401), response(401)]
        relogin = mock.Mock(return_value="fresh")
        with self.assertRaises(requests.HTTPError):
            TwitchAPI("client", "stale", relogin).top_categories()
        relogin.assert_called_once()

    @mock.patch("twitch_play.api.requests.get")
    def test_no_relogin_when_token_works(self, get):
        get.return_value = response(200, {"data": []})
        relogin = mock.Mock()
        TwitchAPI("client", "good", relogin).streams("123")
        relogin.assert_not_called()


class LoginServerTest(unittest.TestCase):
    """Runs the real callback server on port 8765, with a fake browser."""

    def fake_browser(self, posts):
        """Stands in for webbrowser.open: sends each (state or None, token) to /token, in order."""
        self.statuses = []

        def open_url(url):
            state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
            for sent_state, token in posts:
                r = requests.post(
                    f"http://localhost:8765/token?state={sent_state or state}", data=token, timeout=5
                )
                self.statuses.append(r.status_code)
        return open_url

    @mock.patch("twitch_play.auth.print", create=True)
    def test_login_twice_in_one_run(self, _print):
        for _ in range(2):  # the port must be free again for a second login
            with mock.patch("twitch_play.auth.webbrowser.open", self.fake_browser([(None, "tok")])):
                self.assertEqual(login(), "tok")
            self.assertEqual(self.statuses, [200])

    @mock.patch("twitch_play.auth.print", create=True)
    def test_idle_connection_does_not_block(self, _print):
        # a browser preconnect: a socket that connects and never sends a request
        open_url = self.fake_browser([(None, "tok")])

        def preconnect_then_post(url):
            with socket.create_connection(("localhost", 8765), timeout=5):
                open_url(url)

        with mock.patch("twitch_play.auth.webbrowser.open", preconnect_then_post):
            self.assertEqual(login(), "tok")

    @mock.patch("twitch_play.auth.print", create=True)
    def test_forged_token_rejected(self, _print):
        posts = [("guessed-state", "attacker-token"), (None, "tok")]
        with mock.patch("twitch_play.auth.webbrowser.open", self.fake_browser(posts)):
            self.assertEqual(login(), "tok")
        self.assertEqual(self.statuses, [403, 200])


class TokenFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "sub", "token.json")
        patch = mock.patch.object(app, "CACHE", self.path)
        patch.start()
        self.addCleanup(patch.stop)

    def mode(self):
        return stat.S_IMODE(os.stat(self.path).st_mode)

    def test_round_trip_owner_only(self):
        app.save("abc")
        self.assertEqual(app.load(), "abc")
        self.assertEqual(self.mode(), 0o600)

    def test_save_over_world_readable_file(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("{}")
        os.chmod(self.path, 0o644)
        app.save("abc")
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(app.load(), "abc")

    def test_old_world_readable_file_is_tightened(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write('{"access_token": "abc"}')
        os.chmod(self.path, 0o644)
        self.assertEqual(app.load(), "abc")
        self.assertEqual(self.mode(), 0o600)

    def test_missing_or_broken_file(self):
        self.assertIsNone(app.load())
        os.makedirs(os.path.dirname(self.path))
        for content in ("", "{not json", "[]", '{"other": 1}'):
            with open(self.path, "w") as f:
                f.write(content)
            self.assertIsNone(app.load(), content)


class MainTest(unittest.TestCase):
    @mock.patch.object(app.shutil, "which", side_effect=lambda cmd: None if cmd == "mpv" else "/usr/bin/fzf")
    def test_missing_mpv(self, _which):
        with self.assertRaises(SystemExit) as ctx:
            app.main()
        self.assertIn("mpv", str(ctx.exception.code))

    @mock.patch.object(app.shutil, "which", return_value="/usr/bin/x")
    @mock.patch.object(app, "get_token_or_exit", return_value="tok")
    @mock.patch.object(app, "browse", side_effect=requests.ConnectionError("network down"))
    def test_api_error_exits_cleanly(self, _browse, _token, _which):
        with self.assertRaises(SystemExit) as ctx:
            app.main()
        self.assertIn("network down", str(ctx.exception.code))


class GetTokenOrExitTest(unittest.TestCase):
    @mock.patch.object(app, "get_token", side_effect=TimeoutError("Auth timed out after 120s"))
    def test_login_failure_exits_cleanly(self, _get_token):
        with self.assertRaises(SystemExit) as ctx:
            app.get_token_or_exit(force_login=True)
        self.assertIn("Twitch login failed", str(ctx.exception.code))


if __name__ == "__main__":
    unittest.main()
