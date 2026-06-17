import asyncio
import ssl
import sys
import tty
import termios
import select
import time
import pyperclip
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


class TwitchChatClient:
    def __init__(self, channel, token, username, queue, stop_event):
        self.channel = channel.lower()
        self.token = token[len("oauth:"):] if token.startswith("oauth:") else token
        self.username = username
        self.queue = queue
        self.stop_event = stop_event

    async def run(self):
        ssl_ctx = ssl.create_default_context()
        reader, writer = await asyncio.open_connection(
            "irc.chat.twitch.tv",
            6697,
            ssl=ssl_ctx,
        )
        writer.write(f"PASS oauth:{self.token}\r\n".encode())
        writer.write(f"NICK {self.username}\r\n".encode())
        writer.write(f"JOIN #{self.channel}\r\n".encode())
        await writer.drain()

        while not self.stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break

            line = line.decode(errors="ignore").strip()

            if line.startswith("PING"):
                writer.write(b"PONG :tmi.twitch.tv\r\n")
                await writer.drain()
                continue

            if "PRIVMSG" in line:
                try:
                    prefix, msg = line.split("PRIVMSG", 1)
                    user = prefix.split("!", 1)[0].replace(":", "")
                    text = msg.split(":", 1)[1]
                    self.queue.put((user, text))
                except Exception:
                    pass

        writer.close()
        try:
            await writer.wait_closed()
        except ssl.SSLError:
            pass


def start_chat(channel, token, username, queue, stop_event):
    try:
        asyncio.run(
            TwitchChatClient(channel, token, username, queue, stop_event).run()
        )
    except Exception:
        import traceback
        traceback.print_exc()


def keyboard_listener(chat_state, stop_event):
    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except termios.error:
        return

    try:
        tty.setcbreak(fd)
        while not stop_event.is_set():
            r, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not r:
                continue
            ch = sys.stdin.read(1)

            if chat_state["mode"] == "search":
                if ch in ("\r", "\n"):
                    chat_state["mode"] = "normal"
                    chat_state["search_active"] = bool(chat_state["search_query"])
                    chat_state["selected"] = 10**9
                elif ch == "\x1b":
                    chat_state["mode"] = "normal"
                    chat_state["search_query"] = ""
                    chat_state["search_active"] = False
                    chat_state["paused"] = False
                elif ch in ("\x7f", "\x08"):
                    chat_state["search_query"] = chat_state["search_query"][:-1]
                elif ch.isprintable():
                    chat_state["search_query"] += ch
                continue

            if ch == "p":
                if chat_state["search_active"]:
                    chat_state["search_active"] = False
                    chat_state["search_query"] = ""
                    chat_state["paused"] = False
                else:
                    chat_state["paused"] = not chat_state["paused"]
                    if chat_state["paused"]:
                        chat_state["anchor"] = chat_state["total"]
                        chat_state["selected"] = 10**9
            elif ch == "/":
                chat_state["mode"] = "search"
                chat_state["search_query"] = ""
                chat_state["paused"] = True
                chat_state["anchor"] = chat_state["total"]
                chat_state["selected"] = 10**9
            elif ch == "k" and (chat_state["paused"] or chat_state["search_active"]):
                chat_state["selected"] = max(0, chat_state["selected"] - 1)
            elif ch == "j" and (chat_state["paused"] or chat_state["search_active"]):
                chat_state["selected"] += 1
            elif ch == "y" and (chat_state["paused"] or chat_state["search_active"]):
                chat_state["copy_requested"] = True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def render_chat(queue, stop_event, chat_state, channel="", quality="best"):
    console = Console()
    console.clear()

    header = Group(
        Text(f"Fetching stream for {channel} [{quality}]...", style="dim"),
        Text(f"Opening [{quality}] {channel}...", style="dim"),
        Text(""),
    )
    header_lines = 3

    messages_plain = []
    messages_rich = []

    filter_cache = []
    cache_key = (None, -1)

    last_render_key = None

    with Live(console=console, refresh_per_second=10, screen=False) as live:
        while not stop_event.is_set():
            time.sleep(0.05)  # ~20fps max, keeps CPU sane

            while not queue.empty():
                user, text = queue.get()
                plain = f"{user}: {text.strip()}".lower()
                rich_text = Text.assemble(
                    (f"{user}: ", "bold cyan"),
                    (text.strip(), "white"),
                )
                messages_plain.append(plain)
                messages_rich.append(rich_text)

            total = len(messages_rich)
            chat_state["total"] = total

            mode = chat_state["mode"]
            search_active = chat_state["search_active"]
            search_query = chat_state["search_query"]
            anchor = chat_state["anchor"]
            paused = chat_state["paused"]
            raw_selected = chat_state["selected"]
            copy_requested = chat_state.get("copy_requested", False)

            interactive = paused or search_active

            panel_overhead = 2
            available = console.size.height - header_lines - panel_overhead
            visible_count = max(1, available)

            if search_active and search_query:
                key = (search_query, anchor)
                if key != cache_key:
                    q_lower = search_query.lower()
                    filter_cache = [
                        messages_rich[i]
                        for i, p in enumerate(messages_plain[:anchor])
                        if q_lower in p
                    ]
                    cache_key = key
                pool = filter_cache
            else:
                cache_key = (None, -1)
                pool = messages_rich[:anchor] if interactive else messages_rich

            pool_total = len(pool)

            selected = None
            if interactive and pool_total > 0:
                selected = max(0, min(raw_selected, pool_total - 1))
                chat_state["selected"] = selected

                # center view on selected
                half = visible_count // 2
                start = max(0, selected - half)
                end = min(pool_total, start + visible_count)
                start = max(0, end - visible_count)

                if copy_requested:
                    try:
                        pyperclip.copy(pool[selected].plain)
                        chat_state["flash_text"] = "Copied!"
                    except Exception:
                        chat_state["flash_text"] = "Copy failed"
                    chat_state["flash_until"] = time.time() + 1.5
                    chat_state["copy_requested"] = False
            else:
                start = max(0, pool_total - visible_count)
                end = pool_total

            flash = ""
            if time.time() < chat_state.get("flash_until", 0):
                flash = f"  {chat_state['flash_text']}"

            if mode == "search":
                status = f"/{search_query}\u2588{flash}"
                border = "cyan"
            elif search_active:
                status = f"[search: {search_query}] j/k move, y copy, p clear{flash}"
                border = "cyan"
            elif paused:
                status = f"[PAUSED] j/k move, y copy, p resume, / search{flash}"
                border = "yellow"
            else:
                status = "[p pause, / search]"
                border = "magenta"

            render_key = (start, end, selected, mode, search_query, border, flash)
            if render_key == last_render_key:
                continue
            last_render_key = render_key

            if pool_total:
                visible = []
                for i in range(start, end):
                    t = pool[i]
                    if selected is not None and i == selected:
                        t = t.copy()
                        t.stylize("reverse")
                    visible.append(t)
            elif search_active and search_query:
                visible = [Text("(no matches)", style="dim italic")]
            else:
                visible = []

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
            live.update(Group(header, panel))