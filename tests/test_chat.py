import io
import unittest

from rich.cells import cell_len
from rich.console import Console, Group
from rich.text import Text

from twitch_play.chat import (
    MAX_CHAT_MESSAGE, ChatView, Overlay, message_box, parse_notice, parse_privmsg, split_keys,
)


def one_line(_text):
    return 1


def view_with(n):
    view = ChatView()
    for i in range(n):
        view.add(f"user{i}", f"message {i}")
    return view


def names(texts):
    return [t.plain.split(":")[0] for t in texts]


class ParsePrivmsgTest(unittest.TestCase):
    def test_privmsg(self):
        line = ":alice!alice@alice.tmi.twitch.tv PRIVMSG #chan :hello: world"
        self.assertEqual(parse_privmsg(line), ("alice", "hello: world"))

    def test_other_lines(self):
        self.assertIsNone(parse_privmsg("PING :tmi.twitch.tv"))
        self.assertIsNone(parse_privmsg(":tmi.twitch.tv 001 bob :Welcome, GLHF!"))
        self.assertIsNone(parse_privmsg(":alice!a@a JOIN #chan"))

    def test_text_mentioning_privmsg(self):
        line = ":bob!bob@bob.tmi.twitch.tv PRIVMSG #chan :I typed PRIVMSG here"
        self.assertEqual(parse_privmsg(line), ("bob", "I typed PRIVMSG here"))


class SplitKeysTest(unittest.TestCase):
    def test_plain_and_named(self):
        self.assertEqual(split_keys("ab\x7f"), ["a", "b", "backspace"])
        self.assertEqual(split_keys("\r"), ["enter"])
        self.assertEqual(split_keys("\n"), ["enter"])

    def test_arrows(self):
        self.assertEqual(split_keys("\x1b[A\x1b[B\x1bOA\x1bOB"), ["up", "down", "up", "down"])

    def test_esc_alone(self):
        self.assertEqual(split_keys("\x1b"), ["esc"])
        self.assertEqual(split_keys("\x1bp"), ["esc", "p"])

    def test_paste_with_newlines_is_text(self):
        self.assertEqual(split_keys("ab\ncd p"), list("ab cd p"))
        self.assertEqual(split_keys("x\r\ny"), list("x y"))

    def test_other_sequences_ignored(self):
        self.assertEqual(split_keys("\x1b[C\x1b[D\x1b[3~x"), ["x"])


class ChatViewTest(unittest.TestCase):
    def test_history_is_capped(self):
        view = ChatView(max_messages=3)
        for i in range(5):
            view.add(f"u{i}", "hi")
        self.assertEqual(names(m[1] for m in view.messages), ["u2", "u3", "u4"])

    def test_live_window_shows_newest(self):
        view = view_with(10)
        visible, selected = view.window(3, one_line)
        self.assertEqual(names(visible), ["user7", "user8", "user9"])
        self.assertIsNone(selected)

    def test_window_counts_wrapped_lines(self):
        view = view_with(5)
        # every message takes 2 lines, so 5 lines fit only the last 2
        visible, _ = view.window(5, lambda t: 2)
        self.assertEqual(names(visible), ["user3", "user4"])

    def test_pause_freezes_and_moves(self):
        view = view_with(10)
        view.handle_key("p")
        view.add("late", "after pause")
        visible, selected = view.window(3, one_line)
        self.assertEqual(names(visible)[selected], "user9")
        for key in ("k", "up", "k"):
            view.handle_key(key)
        visible, selected = view.window(3, one_line)
        self.assertEqual(names(visible)[selected], "user6")
        self.assertEqual(selected, 1)  # kept in the middle
        view.handle_key("down")
        self.assertEqual(view.selected, 7)

    def test_selection_is_clamped(self):
        view = view_with(3)
        view.handle_key("p")
        for _ in range(5):
            view.handle_key("j")
        self.assertEqual(view.selected, 2)
        for _ in range(5):
            view.handle_key("k")
        self.assertEqual(view.selected, 0)

    def test_moving_needs_pause(self):
        view = view_with(3)
        view.handle_key("k")
        self.assertEqual(view.selected, 0)
        self.assertIsNone(view.handle_key("y"))
        self.assertFalse(view.interactive)

    def test_unfinished_sequence_is_esc(self):
        self.assertEqual(split_keys("\x1b["), ["esc", "["])

    def test_unpause_shows_new_messages(self):
        view = view_with(3)
        view.handle_key("p")
        view.add("late", "hi")
        view.handle_key("p")
        visible, _ = view.window(1, one_line)
        self.assertEqual(names(visible), ["late"])

    def test_search_filters_case_insensitive(self):
        view = ChatView()
        view.add("alice", "Hello there")
        view.add("bob", "nothing")
        view.add("carol", "say HELLO")
        for key in ["/", *"hello", "enter"]:
            view.handle_key(key)
        visible, selected = view.window(10, one_line)
        self.assertEqual(names(visible), ["alice", "carol"])
        self.assertEqual(selected, 1)

    def test_search_typing_and_backspace(self):
        view = view_with(3)
        for key in ["/", "x", "y", "backspace", "p", "k"]:
            view.handle_key(key)
        # while typing, p and k are text, not commands
        self.assertEqual(view.query, "xpk")
        self.assertEqual(view.mode, "search")

    def test_search_filters_while_typing(self):
        view = ChatView()
        view.add("alice", "cats")
        view.add("bob", "dogs")
        view.add("carol", "cars")
        view.handle_key("/")
        self.assertEqual(len(view.window(10, one_line)[0]), 3)  # empty query shows everything
        view.handle_key("c")
        view.handle_key("a")
        self.assertEqual(names(view.window(10, one_line)[0]), ["alice", "carol"])
        view.handle_key("t")
        visible, selected = view.window(10, one_line)
        self.assertEqual((names(visible), selected), (["alice"], 0))
        view.handle_key("backspace")
        self.assertEqual(names(view.window(10, one_line)[0]), ["alice", "carol"])
        view.handle_key("enter")
        self.assertTrue(view.search_active)
        self.assertEqual(names(view.window(10, one_line)[0]), ["alice", "carol"])

    def test_search_empty_enter_stays_paused(self):
        view = view_with(3)
        for key in ["/", "enter"]:
            view.handle_key(key)
        self.assertTrue(view.paused)
        self.assertFalse(view.search_active)
        self.assertEqual(view.selected, 2)

    def test_search_esc_resumes_live(self):
        view = view_with(3)
        for key in ["/", "u", "esc"]:
            view.handle_key(key)
        self.assertFalse(view.interactive)
        self.assertEqual(view.query, "")

    def test_search_no_matches(self):
        view = view_with(3)
        for key in ["/", "z", "enter"]:
            view.handle_key(key)
        self.assertEqual(view.window(5, one_line), ([], None))
        self.assertIsNone(view.handle_key("y"))

    def test_p_clears_search(self):
        view = view_with(3)
        for key in ["/", "1", "enter", "p"]:
            view.handle_key(key)
        self.assertFalse(view.interactive)

    def test_copy_selected(self):
        view = ChatView()
        view.add("Alice", "Hi There")
        view.add("bob", "second")
        view.handle_key("p")
        view.handle_key("k")
        self.assertEqual(view.handle_key("y"), ("copy", "Alice: Hi There"))


class ParseNoticeTest(unittest.TestCase):
    def test_notice(self):
        line = ":tmi.twitch.tv NOTICE #chan :This room is in followers-only mode."
        self.assertEqual(parse_notice(line), "This room is in followers-only mode.")

    def test_other_lines(self):
        self.assertIsNone(parse_notice(":alice!a@a PRIVMSG #chan :NOTICE me"))
        self.assertIsNone(parse_notice(":tmi.twitch.tv CAP * ACK :twitch.tv/commands"))


class ComposeTest(unittest.TestCase):
    def type_keys(self, view, keys):
        result = None
        for key in keys:
            result = view.handle_key(key)
        return result

    def test_send(self):
        view = view_with(2)
        self.assertEqual(self.type_keys(view, ["i", *"hi kp/", "enter"]), ("send", "hi kp/"))
        self.assertEqual((view.mode, view.draft), ("normal", ""))

    def test_command_keys_are_text_while_writing(self):
        view = view_with(2)
        self.type_keys(view, ["i", "p", "/", "y", "k"])
        self.assertEqual(view.draft, "p/yk")
        self.assertFalse(view.paused)

    def test_backspace_and_esc(self):
        view = view_with(2)
        self.type_keys(view, ["i", "a", "b", "backspace"])
        self.assertEqual(view.draft, "a")
        self.assertIsNone(view.handle_key("esc"))
        self.assertEqual((view.mode, view.draft), ("normal", ""))

    def test_blank_message_not_sent(self):
        view = view_with(2)
        self.assertIsNone(self.type_keys(view, ["i", " ", " ", "enter"]))
        self.assertEqual(view.mode, "normal")

    def test_length_capped(self):
        view = view_with(1)
        self.type_keys(view, ["i", *("x" * (MAX_CHAT_MESSAGE + 10))])
        self.assertEqual(len(view.draft), MAX_CHAT_MESSAGE)

    def test_writing_while_paused_keeps_pause(self):
        view = view_with(3)
        self.type_keys(view, ["p", "k", "i", "x", "enter"])
        self.assertTrue(view.paused)
        self.assertEqual(view.selected, 1)

    def test_notice_shown_and_searchable(self):
        view = view_with(2)
        view.add_notice("You are banned")
        self.type_keys(view, ["/", *"banned"])
        self.assertEqual([t.plain for t in view.window(5, one_line)[0]], ["You are banned"])


class OverlayTest(unittest.TestCase):
    def render(self, base_text, draft, width=50, box_width=30):
        console = Console(width=width, height=12, record=True, file=io.StringIO())
        base = Group(*[Text(base_text) for _ in range(10)])
        console.print(Overlay(base, message_box(console, draft, "chan", box_width), box_width))
        return console.export_text().splitlines()

    def test_box_centred_over_base(self):
        lines = self.render("x" * 50, "hello")
        box_rows = [i for i, line in enumerate(lines) if "Message #chan" in line]
        self.assertEqual(box_rows, [3])  # 3-line box centred in 10 lines
        self.assertTrue(lines[4].startswith("x" * 10 + "│ hello"))
        self.assertTrue(lines[4].endswith("x" * 10))
        self.assertEqual(lines[0], "x" * 50)

    def test_wide_characters_keep_alignment(self):
        # box_width 29 puts the right cut at cell 39, inside a wide character
        for line in self.render("😀日" * 25, "hi", box_width=29):
            self.assertEqual(cell_len(line), 50)

    def test_long_draft_shows_its_end(self):
        lines = self.render("x" * 50, "word " * 60 + "END")
        box = [line for line in lines if "│" in line]
        self.assertEqual(len(box), 5)
        self.assertTrue(any("END" in line for line in box))


if __name__ == "__main__":
    unittest.main()
