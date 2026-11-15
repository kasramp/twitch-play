import subprocess
import unittest
from unittest import mock

from twitch_play import ui


def fzf_returning(*outputs):
    """Patch ui.fzf to return each output in turn (one per screen shown)."""
    return mock.patch.object(ui, "fzf", side_effect=list(outputs))


STREAMS = [
    {"user_name": "Alice", "user_login": "alice", "viewer_count": 1200, "title": "tabs\there\nand lines"},
    {"user_name": "Bob", "user_login": "bob", "viewer_count": 5, "title": "hi"},
]


class FzfTest(unittest.TestCase):
    @mock.patch("twitch_play.ui.subprocess.run")
    def test_runs_without_shell(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="q\nctrl-o\n")
        out = ui.fzf(["a", "b"], '--query=$(rm -rf ~)"')
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "fzf")
        self.assertIn('--query=$(rm -rf ~)"', argv)  # one argument, never parsed by a shell
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["input"], "a\nb")
        self.assertEqual(out, ["q", "ctrl-o"])

    @mock.patch("twitch_play.ui.subprocess.run")
    def test_exit_codes(self, run):
        run.return_value = subprocess.CompletedProcess([], 130, stdout="")
        self.assertEqual(ui.fzf([]), [])  # Esc
        run.return_value = subprocess.CompletedProcess([], 1, stdout="typed\n\n")
        self.assertEqual(ui.fzf([]), ["typed", ""])  # no match keeps --print-query output
        run.return_value = subprocess.CompletedProcess([], 2, stdout="junk\n")
        self.assertEqual(ui.fzf([]), [])  # fzf error


class PickStreamTest(unittest.TestCase):
    def test_enter_plays_best(self):
        with fzf_returning(["", "Bob ...\tbob"]):
            stream, quality = ui.pick_stream(STREAMS)
        self.assertEqual((stream["user_login"], quality), ("bob", "best"))

    def test_quality_keys(self):
        with fzf_returning(["ctrl-h", "x\talice"]):
            self.assertEqual(ui.pick_stream(STREAMS)[1], "720p")

    def test_esc_goes_back(self):
        with fzf_returning([]):
            self.assertEqual(ui.pick_stream(STREAMS), (None, None))

    def test_titles_cannot_break_lines(self):
        with fzf_returning([]) as fzf:
            ui.pick_stream(STREAMS)
        lines = fzf.call_args.args[0]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].count("\t"), 1)
        self.assertIn("tabs here and lines", lines[0])

    @mock.patch("twitch_play.ui.pyperclip.copy")
    def test_ctrl_c_copies_and_shows_it(self, copy):
        with fzf_returning(["ctrl-c", "x\talice"], []) as fzf:
            self.assertEqual(ui.pick_stream(STREAMS), (None, None))
        copy.assert_called_once_with("https://twitch.tv/alice")
        header = [a for a in fzf.call_args.args if str(a).startswith("--header=")][0]
        self.assertIn("Copied https://twitch.tv/alice", header)


class PickCategoryTest(unittest.TestCase):
    def setUp(self):
        self.api = mock.Mock()
        self.api.top_categories.return_value = [{"name": "Chess", "id": "1"}]
        self.api.search_categories.return_value = [{"name": "Go", "id": "2"}]

    def test_select(self):
        with fzf_returning(["", "Chess\t1"]):
            self.assertEqual(ui.pick_category(self.api), {"name": "Chess", "id": "1"})

    def test_esc_quits(self):
        with fzf_returning([]):
            self.assertIsNone(ui.pick_category(self.api))

    def test_search_then_esc_back_to_top(self):
        # Ctrl-F, type "go", Esc out of results (back to top), Esc again (quit)
        with fzf_returning(["ctrl-f"], ["go"], [], []):
            self.assertIsNone(ui.pick_category(self.api))
        self.api.search_categories.assert_called_once_with("go")

    @mock.patch("twitch_play.ui.pyperclip.paste", return_value="https://twitch.tv/x\nsecond line")
    def test_open_url_prefills_first_clipboard_line(self, _paste):
        with fzf_returning(["ctrl-o"], ["https://twitch.tv/x", "ctrl-l"]) as fzf:
            self.assertEqual(ui.pick_category(self.api), {"url": "https://twitch.tv/x", "quality": "480p"})
        self.assertIn("--query=https://twitch.tv/x", fzf.call_args.args)

    @mock.patch("twitch_play.ui.pause")
    def test_empty_search_returns_to_top(self, pause):
        self.api.search_categories.return_value = []
        with fzf_returning(["ctrl-f"], ["zzz"], []):
            self.assertIsNone(ui.pick_category(self.api))
        pause.assert_called_once()


class PickQualityTest(unittest.TestCase):
    def test_pick_and_cancel(self):
        with fzf_returning(["720p60"], []):
            self.assertEqual(ui.pick_quality(["720p60", "480p"]), "720p60")
            self.assertIsNone(ui.pick_quality(["720p60"]))
        self.assertIsNone(ui.pick_quality([]))


if __name__ == "__main__":
    unittest.main()
