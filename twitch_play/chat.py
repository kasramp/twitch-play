import asyncio
import codecs
import os
import queue
import ssl
import sys
import tty
import termios
import select
import time
from collections import deque
import pyperclip
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.segment import Segment
from rich.text import Text

MAX_MESSAGES = 5000
FRAME = 1 / 30  # redraw at most 30 times a second
FLASH_SECONDS = 1.5
MAX_CHAT_MESSAGE = 500  # Twitch's limit per message
MESSAGE_BOX_WIDTH = 70
MESSAGE_BOX_LINES = 5  # longer drafts scroll, showing their end

KEY_NAMES = {"\r": "enter", "\n": "enter", "\x7f": "backspace", "\x08": "backspace"}
ARROWS = {"\x1b[A": "up", "\x1b[B": "down", "\x1bOA": "up", "\x1bOB": "down"}


def parse_privmsg(line):
    """Return (user, text) for an IRC PRIVMSG line, or None for anything else."""
    # :nick!nick@nick.tmi.twitch.tv PRIVMSG #channel :message text
    if not line.startswith(":") or " PRIVMSG " not in line:
        return None
    prefix, rest = line[1:].split(" PRIVMSG ", 1)
    _, sep, text = rest.partition(" :")
    if not sep:
        return None
    return prefix.split("!", 1)[0], text


def parse_notice(line):
    """Return the text of a server NOTICE (e.g. why a sent message was refused), or None."""
    # :tmi.twitch.tv NOTICE #channel :You are permanently banned from talking in channel.
    if not line.startswith(":tmi.twitch.tv NOTICE "):
        return None
    _, sep, text = line.partition(" :")
    return text if sep else None


def split_keys(data):
    """Split raw terminal input into key names: 'up', 'esc', 'enter', ... or the character itself."""
    if len(data) > 1 and ("\r" in data or "\n" in data):
        # several characters with a newline in one read is a paste: keep it as text, not Enter + hotkeys
        data = data.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    keys = []
    i = 0
    while i < len(data):
        ch = data[i]
        if ch != "\x1b":
            keys.append(KEY_NAMES.get(ch, ch))
            i += 1
            continue
        if data[i:i + 3] in ARROWS:
            keys.append(ARROWS[data[i:i + 3]])
            i += 3
            continue
        if data[i + 1:i + 2] in ("[", "O"):
            # some other escape sequence (left/right, F-keys...): skip it whole
            # shortcut: Esc then a typed "[" in one read is taken as a sequence, fine unless input lags badly
            j = i + 2
            while j < len(data) and not (data[j].isalpha() or data[j] == "~"):
                j += 1
            if j < len(data):
                i = j + 1
                continue
        keys.append("esc")
        i += 1
    return keys


class ChatView:
    """Chat history and the paused/search/selection state, without any terminal code."""

    def __init__(self, max_messages=MAX_MESSAGES):
        self.messages = deque(maxlen=max_messages)  # (lowercase plain text, rich Text)
        self.mode = "normal"  # "search" while typing a query, "compose" while typing a chat message
        self.draft = ""
        self.paused = False
        self.query = ""
        self.search_active = False
        self.frozen = []  # snapshot shown while paused
        self.matches = []
        self.selected = 0

    def add(self, user, text):
        text = text.strip()
        rich_text = Text.assemble((f"{user}: ", "bold cyan"), (text, "white"))
        self.messages.append((f"{user}: {text}".lower(), rich_text))

    def add_notice(self, text):
        self.messages.append((text.lower(), Text(text, style="dim italic")))

    @property
    def interactive(self):
        return self.paused or self.search_active

    def pool(self):
        if self.search_active or self.mode == "search":
            return self.matches
        if self.paused:
            return self.frozen
        return self.messages

    def _freeze(self):
        self.paused = True
        self.frozen = list(self.messages)
        self.selected = len(self.frozen) - 1

    def _filter(self):
        # runs on every typed key; ~1 ms for a full history even on old laptops
        q = self.query.lower()
        self.matches = [m for m in self.frozen if q in m[0]] if q else self.frozen
        self.selected = len(self.matches) - 1

    def _clear_search(self):
        self.query = ""
        self.search_active = False
        self.paused = False

    def handle_key(self, key):
        """Apply one key. Returns ("copy", text) or ("send", text) when the key asks for it, else None."""
        if self.mode == "compose":
            if key == "enter":
                self.mode = "normal"
                text, self.draft = self.draft.strip(), ""
                return ("send", text) if text else None
            if key == "esc":
                self.mode = "normal"
                self.draft = ""
            elif key == "backspace":
                self.draft = self.draft[:-1]
            elif len(key) == 1 and key.isprintable() and len(self.draft) < MAX_CHAT_MESSAGE:
                self.draft += key
            return None

        if self.mode == "search":
            if key == "enter":
                self.mode = "normal"
                self.search_active = bool(self.query)
            elif key == "esc":
                self.mode = "normal"
                self._clear_search()
            elif key == "backspace":
                self.query = self.query[:-1]
                self._filter()
            elif len(key) == 1 and key.isprintable():
                self.query += key
                self._filter()
            return None

        if key == "i":
            self.mode = "compose"
        elif key == "p":
            if self.search_active:
                self._clear_search()
            elif self.paused:
                self.paused = False
            else:
                self._freeze()
        elif key == "/":
            self.mode = "search"
            self.search_active = False
            self.query = ""
            self._freeze()
            self._filter()
        elif self.interactive and key in ("k", "up"):
            self.selected = max(0, self.selected - 1)
        elif self.interactive and key in ("j", "down"):
            self.selected = min(len(self.pool()) - 1, self.selected + 1)
        elif self.interactive and key == "y" and self.pool():
            return ("copy", self.pool()[self.selected][1].plain)
        return None

    def window(self, height, line_count):
        """Messages that fit in `height` lines, and the index of the selected one among them (or None).

        line_count(text) gives a message's height once wrapped. Live chat keeps the newest
        message at the bottom; paused/search keeps the selected message near the middle.
        """
        pool = self.pool()
        if not pool:
            return [], None
        sel = min(max(self.selected, 0), len(pool) - 1) if self.interactive else len(pool) - 1
        start = end = sel
        used = line_count(pool[sel][1])

        def grow_up(limit):
            nonlocal start, used
            while start > 0:
                n = line_count(pool[start - 1][1])
                if used + n > limit:
                    break
                start -= 1
                used += n

        def grow_down(limit):
            nonlocal end, used
            while end < len(pool) - 1:
                n = line_count(pool[end + 1][1])
                if used + n > limit:
                    break
                end += 1
                used += n

        grow_up(used + height // 2)
        grow_down(height)
        grow_up(height)
        visible = [pool[i][1] for i in range(start, end + 1)]
        return visible, (sel - start if self.interactive else None)


class TwitchChatClient:
    def __init__(self, channel, token, username, events, outgoing, stop_event):
        self.channel = channel.lower()
        self.token = token[len("oauth:"):] if token.startswith("oauth:") else token
        self.username = username
        self.events = events
        self.outgoing = outgoing  # chat messages to send, filled by the render thread
        self.stop_event = stop_event

    async def run(self):
        ssl_ctx = ssl.create_default_context()
        reader, writer = await asyncio.open_connection(
            "irc.chat.twitch.tv",
            6697,
            ssl=ssl_ctx,
        )
        # twitch.tv/commands: Twitch then sends a NOTICE when it refuses a message (slow mode, bans, ...)
        writer.write(b"CAP REQ :twitch.tv/commands\r\n")
        writer.write(f"PASS oauth:{self.token}\r\n".encode())
        writer.write(f"NICK {self.username}\r\n".encode())
        writer.write(f"JOIN #{self.channel}\r\n".encode())
        await writer.drain()

        while not self.stop_event.is_set():
            while not self.outgoing.empty():
                writer.write(f"PRIVMSG #{self.channel} :{self.outgoing.get()}\r\n".encode())
                await writer.drain()
            try:
                # short timeout so a sent message goes out within ~0.1 s
                line = await asyncio.wait_for(reader.readline(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if not line:
                break

            line = line.decode(errors="ignore").strip()

            if line.startswith("PING"):
                writer.write(b"PONG :tmi.twitch.tv\r\n")
                await writer.drain()
                continue

            message = parse_privmsg(line)
            if message:
                self.events.put(("msg", message))
                continue
            notice = parse_notice(line)
            if notice:
                self.events.put(("notice", notice))

        writer.close()
        try:
            await writer.wait_closed()
        except ssl.SSLError:
            pass


def start_chat(channel, token, username, events, outgoing, stop_event):
    try:
        asyncio.run(
            TwitchChatClient(channel, token, username, events, outgoing, stop_event).run()
        )
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        if not stop_event.is_set():
            # sent messages would otherwise look delivered while going nowhere
            events.put(("notice", "Disconnected from chat; messages can't be sent"))


def keyboard_listener(events, stop_event):
    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except termios.error:
        return

    # keeps a UTF-8 character split across two reads (long pastes) instead of dropping it
    decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")
    try:
        tty.setcbreak(fd)
        while not stop_event.is_set():
            r, _, _ = select.select([fd], [], [], 0.1)
            if not r:
                continue
            # os.read, not sys.stdin.read: Python's buffer would hide pending keys from select()
            data = os.read(fd, 1024)
            if not data:
                break
            for key in split_keys(decoder.decode(data)):
                events.put(("key", key))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class Overlay:
    """Draws `box` centred on top of `base`. rich has no layers, so this pastes the box's lines over the base's."""

    def __init__(self, base, box, box_width):
        self.base = base
        self.box = box
        self.box_width = box_width

    def __rich_console__(self, console, options):
        width = options.max_width
        box_width = min(self.box_width, width)
        base_lines = console.render_lines(self.base, options, pad=True)
        box_lines = console.render_lines(self.box, options.update_width(box_width), pad=True)
        top = max(0, (len(base_lines) - len(box_lines)) // 2)
        left = (width - box_width) // 2
        for i, line in enumerate(base_lines):
            if top <= i < top + len(box_lines):
                # divide() pads a wide character cut in half, so the columns stay aligned
                before, _, after = Segment.divide(line, [left, left + box_width, width])
                line = before + box_lines[i - top] + after
            yield from line
            yield Segment.line()


def message_box(console, draft, channel, width):
    """The input box shown while writing a chat message; long drafts wrap and show their last lines."""
    lines = Text(draft + "\u2588").wrap(console, max(1, width - 4))
    return Panel(
        Group(*lines[-MESSAGE_BOX_LINES:]),
        title=f"Message #{channel}",
        title_align="left",
        subtitle=f"{len(draft)}/{MAX_CHAT_MESSAGE}  Enter send, Esc cancel",
        subtitle_align="right",
        border_style="green",
        padding=(0, 1),
        width=width,
    )


def _status(view, flash):
    if view.mode == "compose":
        return "[writing a message]", "green"
    if view.mode == "search":
        return f"/{view.query}█{flash}", "cyan"
    if view.search_active:
        return f"[search: {view.query}] j/k move, y copy, p clear{flash}", "cyan"
    if view.paused:
        return f"[PAUSED] j/k move, y copy, p resume, / search{flash}", "yellow"
    return f"[i chat, p pause, / search]{flash}", "magenta"


def render_chat(events, outgoing, stop_event, username, channel="", quality="best"):
    console = Console()
    console.clear()

    header = Group(
        Text(f"Fetching stream for {channel} [{quality}]...", style="dim"),
        Text(f"Opening [{quality}] {channel}...", style="dim"),
        Text(""),
    )
    header_lines = 3

    view = ChatView()
    flash_text, flash_until = "", 0.0
    last_draw = 0.0
    last_shown = None

    with Live(console=console, auto_refresh=False) as live:
        while not stop_event.is_set():
            # sleep off the rest of the frame so busy chats batch up instead of redrawing per message
            time.sleep(max(0.0, last_draw + FRAME - time.monotonic()))
            batch = []
            try:
                batch.append(events.get(timeout=0.25))
                while True:
                    batch.append(events.get_nowait())
            except queue.Empty:
                pass

            for kind, value in batch:
                if kind == "msg":
                    view.add(*value)
                    continue
                if kind == "notice":
                    view.add_notice(value)
                    continue
                action = view.handle_key(value)
                if action is None:
                    continue
                what, text = action
                if what == "send":
                    outgoing.put(text)
                    view.add(username, text)  # Twitch doesn't echo our own messages back
                    flash_text = "Sent"  # visible even while paused, when the new line is not
                    flash_until = time.monotonic() + FLASH_SECONDS
                    continue
                try:
                    pyperclip.copy(text)
                    flash_text = "Copied!"
                except Exception:  # pyperclip can also raise OSError from its subprocess backends
                    flash_text = "Copy failed"
                flash_until = time.monotonic() + FLASH_SECONDS

            flash = f"  {flash_text}" if time.monotonic() < flash_until else ""
            width, height = console.size
            if not batch and (flash, width, height) == last_shown:
                continue
            last_shown = (flash, width, height)
            status, border = _status(view, flash)

            inner_width = max(1, width - 4)  # panel border + padding
            visible_count = max(1, height - header_lines - 2)
            visible, selected = view.window(
                visible_count, lambda t: len(t.wrap(console, inner_width))
            )
            if selected is not None:
                visible[selected] = visible[selected].copy()
                visible[selected].stylize("reverse")
            if not visible and view.query:
                visible = [Text("(no matches)", style="dim italic")]

            panel = Panel(
                Group(*visible),
                title=f"#{channel} chat",
                title_align="left",
                subtitle=status,
                subtitle_align="right",
                border_style=border,
                padding=(0, 1),
                height=visible_count + 2,
            )
            screen = Group(header, panel)
            if view.mode == "compose":
                box_width = max(10, min(MESSAGE_BOX_WIDTH, width - 4))
                screen = Overlay(screen, message_box(console, view.draft, channel, box_width), box_width)
            live.update(screen, refresh=True)
            last_draw = time.monotonic()
