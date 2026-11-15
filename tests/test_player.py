import unittest
from unittest import mock

from streamlink.exceptions import PluginError

from twitch_play import player
from twitch_play.player import choose_stream, twitch_channel


class TwitchChannelTest(unittest.TestCase):
    def test_channel_urls(self):
        for url in ("https://twitch.tv/Shroud", "https://www.twitch.tv/shroud/", "twitch.tv/shroud",
                    "www.twitch.tv/shroud", "https://m.twitch.tv/shroud?ref=x"):
            self.assertEqual(twitch_channel(url), "shroud", url)

    def test_not_a_channel(self):
        for url in ("https://www.twitch.tv/videos/123", "https://clips.twitch.tv/SomeClip",
                    "https://youtube.com/watch?v=x", "https://twitch.tv/", "https://nottwitch.tv/x"):
            self.assertIsNone(twitch_channel(url), url)


class ChooseStreamTest(unittest.TestCase):
    STREAMS = {"160p": 1, "480p": 2, "720p60": 3, "1080p60": 4, "best": 4, "worst": 1}

    def test_exact_and_fps_names(self):
        self.assertEqual(choose_stream(self.STREAMS, "480p"), ("480p", 2))
        self.assertEqual(choose_stream(self.STREAMS, "720p"), ("720p60", 3))  # Ctrl-H on a 60 fps stream
        self.assertEqual(choose_stream(self.STREAMS, "best"), ("best", 4))

    def test_missing_quality_falls_back_to_best(self):
        self.assertEqual(choose_stream(self.STREAMS, "360p"), ("best", 4))
        self.assertEqual(choose_stream({}, "best"), (None, None))


@mock.patch.object(player, "_watch")
@mock.patch.object(player, "pause")
@mock.patch.object(player, "Streamlink")
@mock.patch("builtins.print")
class PlayTest(unittest.TestCase):
    def test_plays_with_chat_channel(self, _print, streamlink, pause, watch):
        stream = mock.Mock()
        streamlink.return_value.streams.return_value = {"720p60": stream, "best": mock.Mock()}
        player.play("twitch.tv/Shroud", "720p", "tok", title="Shroud — hi")
        streamlink.return_value.streams.assert_called_once_with("twitch.tv/Shroud")  # URL used as given
        watch.assert_called_once_with(stream.open.return_value, "[720p60] Shroud — hi", "720p60", "shroud", "tok")
        pause.assert_not_called()

    def test_offline(self, _print, streamlink, pause, watch):
        streamlink.return_value.streams.return_value = {}
        player.play("https://twitch.tv/x")
        pause.assert_called_once()
        watch.assert_not_called()

    def test_streamlink_error_is_shown(self, _print, streamlink, pause, watch):
        streamlink.return_value.streams.side_effect = PluginError("boom")
        player.play("https://twitch.tv/x", "pick")
        self.assertIn("boom", pause.call_args.args[0])
        watch.assert_not_called()

    def test_malformed_url_is_shown(self, _print, streamlink, pause, watch):
        streamlink.return_value.streams.side_effect = ValueError("Invalid IPv6 URL")
        player.play("http://[::1")
        pause.assert_called_once()

    @mock.patch.object(player, "pick_quality", return_value=None)
    def test_pick_cancelled(self, pick, _print, streamlink, pause, watch):
        streamlink.return_value.streams.return_value = {"480p": 1, "720p60": 2, "best": 2, "worst": 1}
        player.play("https://twitch.tv/x", "pick")
        pick.assert_called_once_with(["480p", "720p60"])
        watch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
