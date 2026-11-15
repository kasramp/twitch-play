import unittest

from twitch_play.chat import ChatView, parse_privmsg, split_keys


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
        self.assertEqual(split_keys("ab\r\x7f"), ["a", "b", "enter", "backspace"])

    def test_arrows(self):
        self.assertEqual(split_keys("\x1b[A\x1b[B\x1bOA\x1bOB"), ["up", "down", "up", "down"])

    def test_esc_alone(self):
        self.assertEqual(split_keys("\x1b"), ["esc"])
        self.assertEqual(split_keys("\x1bp"), ["esc", "p"])

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


if __name__ == "__main__":
    unittest.main()
