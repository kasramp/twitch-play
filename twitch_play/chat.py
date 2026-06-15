# chat.py
import asyncio
import ssl
import sys
import tty
import termios
import select
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
    """
    Normal mode:
      p = toggle pause
      j/k = scroll down/up while paused
      / = enter search mode
    Search mode:
      type to build query
      Enter = apply filter, return to normal (filter stays active)
      Escape = cancel search, resume normal
    Normal mode while search_active:
      p = clear search and resume
    """
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
                    chat_state["scroll"] = 0
                elif ch == "\x1b":
                    chat_state["mode"] = "normal"
                    chat_state["search_query"] = ""
                    chat_state["search_active"] = False
                    chat_state["paused"] = False
                    chat_state["scroll"] = 0
                elif ch in ("\x7f", "\x08"):
                    chat_state["search_query"] = chat_state["search_query"][:-1]
                elif ch.isprintable():
                    chat_state["search_query"] += ch
                continue

            # normal mode
            if ch == "p":
                if chat_state["search_active"]:
                    chat_state["search_active"] = False
                    chat_state["search_query"] = ""
                    chat_state["paused"] = False
                    chat_state["scroll"] = 0
                else:
                    chat_state["paused"] = not chat_state["paused"]
                    if chat_state["paused"]:
                        chat_state["anchor"] = chat_state["total"]
                        chat_state["scroll"] = 0
                    else:
                        chat_state["scroll"] = 0
            elif ch == "/":
                chat_state["mode"] = "search"
                chat_state["search_query"] = ""
                chat_state["paused"] = True
                chat_state["anchor"] = chat_state["total"]
                chat_state["scroll"] = 0
            elif ch == "k" and chat_state["paused"]:
                chat_state["scroll"] += 1
            elif ch == "j" and chat_state["paused"]:
                chat_state["scroll"] = max(0, chat_state["scroll"] - 1)
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

    messages = []

    with Live(console=console, refresh_per_second=10, screen=False) as live:
        while not stop_event.is_set():
            while not queue.empty():
                user, text = queue.get()
                messages.append(
                    Text.assemble(
                        (f"{user}: ", "bold cyan"),
                        (text.strip(), "white"),
                    )
                )

            total = len(messages)
            chat_state["total"] = total

            panel_overhead = 2
            available = console.size.height - header_lines - panel_overhead
            visible_count = max(1, available)

            mode = chat_state["mode"]
            search_active = chat_state["search_active"]
            search_query = chat_state["search_query"]

            if search_active and search_query:
                pool = [
                    m for m in messages[: chat_state["anchor"]]
                    if search_query.lower() in m.plain.lower()
                ]
            else:
                pool = messages

            pool_total = len(pool)

            if mode == "search":
                status = f"/{search_query}\u2588"
                border = "cyan"
                end = pool_total
            elif search_active:
                status = f"[search: {search_query}] (j/k scroll, p clear)"
                border = "cyan"
                end = max(0, min(chat_state["anchor"], pool_total) - chat_state["scroll"])
            elif chat_state["paused"]:
                status = f"[PAUSED — j/k scroll, p resume, / search] ({chat_state['scroll']} back)"
                border = "yellow"
                end = max(0, min(chat_state["anchor"], pool_total) - chat_state["scroll"])
            else:
                status = "[p pause, / search]"
                border = "magenta"
                end = pool_total

            start = max(0, end - visible_count)
            if pool_total:
                visible = pool[start:end]
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