import subprocess
import pyperclip

QUALITY_MAP = {
    "ctrl-l": "480p",
    "ctrl-h": "720p",
    "ctrl-b": "best",
    "ctrl-o": "pick",
    "":       "best",
}
QUALITY_KEYS = "--expect=ctrl-l,ctrl-h,ctrl-b,ctrl-o"
QUALITY_HELP = "[ Enter ] best   [ Ctrl-L ] 480p   [ Ctrl-H ] 720p   [ Ctrl-B ] best   [ Ctrl-O ] pick quality"
# list pickers show only the text before the tab; the id after it comes back with the selection
LIST_OPTIONS = ("--no-sort", "--delimiter=\t", "--with-nth=1")


def fzf(lines, *options):
    """Run fzf on `lines` and return its output lines, or [] when cancelled with Esc.

    fzf is started without a shell: options can carry clipboard or typed text.
    """
    result = subprocess.run(
        ["fzf", "--no-info", "--layout=reverse", *options],
        input="\n".join(lines),
        stdout=subprocess.PIPE,
        text=True,
    )
    if result.returncode not in (0, 1):  # 1 = nothing matched, which still prints --print-query/--expect lines
        return []
    return result.stdout.splitlines()


def pause(message):
    """Show a message until Enter, so the next fzf screen doesn't wipe it straight away."""
    print(message)
    input("Press Enter to go back...")


def _ask_search():
    out = fzf([], "--print-query", "--prompt=Search> ")
    return out[0].strip() if out else ""


def _ask_url():
    """The URL prompt, prefilled from the clipboard. Returns {"url", "quality"} or None."""
    try:
        clipboard = pyperclip.paste().strip()
    except Exception:  # no clipboard tool, or its subprocess failed
        clipboard = ""
    out = fzf(
        [],
        "--print-query",
        "--prompt=URL > ",
        f"--header={QUALITY_HELP}   [ Esc ] cancel",
        QUALITY_KEYS,
        f"--query={clipboard.splitlines()[0] if clipboard else ''}",
    )
    # --print-query + --expect: out[0] = query, out[1] = key
    url = out[0].strip() if out else ""
    if not url:
        return None
    return {"url": url, "quality": QUALITY_MAP.get(out[1] if len(out) > 1 else "", "best")}


def pick_category(api):
    """Top or searched categories. Returns {"name", "id"}, {"url", "quality"} (Ctrl-O), or None to quit."""
    query = None
    while True:
        cats = api.search_categories(query) if query else api.top_categories()
        if not cats:
            if not query:
                pause("Twitch returned no categories.")
                return None
            pause(f"No categories match '{query}'.")
            query = None
            continue

        if query:
            prompt, ctrl_f, esc = f"Search: {query} > ", "new search", "back to top categories"
        else:
            prompt, ctrl_f, esc = "Category > ", "search Twitch", "quit"
        out = fzf(
            [f"{c['name']}\t{c['id']}" for c in cats],
            *LIST_OPTIONS,
            "--expect=ctrl-f,ctrl-o",
            f"--prompt={prompt}",
            f"--header=[ Enter ] select   [ Ctrl-F ] {ctrl_f}   [ Ctrl-O ] open URL   [ Esc ] {esc}",
        )
        if not out:  # Esc
            if query:
                query = None
                continue
            return None

        key, selected = out[0], out[1] if len(out) > 1 else ""
        if key == "ctrl-f":
            query = _ask_search() or query
        elif key == "ctrl-o":
            choice = _ask_url()
            if choice:
                return choice
        elif "\t" in selected:
            name, cat_id = selected.rsplit("\t", 1)
            return {"name": name, "id": cat_id}


def pick_stream(streams):
    """Returns (stream, quality), or (None, None) to go back. Ctrl-C copies the stream URL and stays."""
    lines = [
        # titles are free text: flatten tabs/newlines so they can't break the line format
        f"{s['user_name']:20s} {s['viewer_count']:>7,} viewers  {' '.join(s.get('title', '').split())[:50]}"
        f"\t{s['user_login']}"
        for s in streams
    ]
    copied = ""
    while True:
        out = fzf(
            lines,
            *LIST_OPTIONS,
            QUALITY_KEYS + ",ctrl-c",
            "--prompt=Stream > ",
            f"--header={QUALITY_HELP}   [ Ctrl-C ] copy URL   [ Esc ] back{copied}",
        )
        if len(out) < 2 or "\t" not in out[1]:
            return None, None

        key, user_login = out[0], out[1].rsplit("\t", 1)[1]
        if key == "ctrl-c":
            url = f"https://twitch.tv/{user_login}"
            try:
                pyperclip.copy(url)
                copied = f"\nCopied {url}"  # shown in the header, since fzf redraws over printed text
            except Exception:  # no clipboard tool, or its subprocess failed
                pause(f"Could not copy {url}: install xclip or xsel (X11) or wl-clipboard (Wayland).")
            continue

        stream = next(s for s in streams if s["user_login"] == user_login)
        return stream, QUALITY_MAP.get(key, "best")


def pick_quality(qualities):
    if not qualities:
        return None
    out = fzf(qualities, "--no-sort", "--prompt=Quality > ", "--header=[ Enter ] select   [ Esc ] cancel")
    return out[0] if out else None
