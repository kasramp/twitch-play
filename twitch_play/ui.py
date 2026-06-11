import pyperclip
from pyfzf.pyfzf import FzfPrompt

fzf = FzfPrompt()


def _pick(lines, flags=""):
    if not lines:
        return None
    try:
        result = fzf.prompt(lines, f"--no-sort --no-info --delimiter='\t' --with-nth=1 --layout=default {flags}")
        return result[0] if result else None
    except (Exception, SystemExit):
        return None


def _pick_with_expect(lines, flags=""):
    if not lines:
        return "", None
    try:
        result = fzf.prompt(lines, f"--no-sort --no-info --delimiter='\t' --with-nth=1 --layout=default --expect=ctrl-f {flags}")
        if not result:
            return "", None
        key = result[0] if len(result) > 0 else ""
        item = result[1] if len(result) > 1 else None
        return key, item
    except (Exception, SystemExit):
        return "", None


def pick_category(api):
    search_query = None

    while True:
        if search_query:
            cats = api.search_categories(search_query)
            flags = (
                f'--prompt="Search: {search_query} > "'
                ' --header="[ Enter ] select   [ Ctrl-F ] new search   [ Esc ] back to top categories"'
                ' --layout=reverse'
            )
        else:
            cats = api.top_categories(100)
            flags = (
                '--prompt="Category > "'
                ' --header="[ Enter ] select   [ Ctrl-F ] search Twitch   [ Esc ] quit"'
                ' --layout=reverse'
            )

        lines = [f"{c['name']}\t{c['id']}" for c in cats] if cats else []

        if not lines:
            print("No results.")
            search_query = None
            continue

        key, selected = _pick_with_expect(lines, flags)

        if key == "ctrl-f":
            try:
                result = fzf.prompt([], "--print-query --prompt='Search> ' --layout=reverse --no-info")
                query = result[0].strip() if result else ""
            except (Exception, SystemExit):
                continue
            if query:
                search_query = query
            continue

        if selected and "\t" in selected:
            name, cat_id = selected.split("\t", 1)
            return {"name": name, "id": cat_id}

        if search_query:
            search_query = None
            continue

        return None


def pick_stream(streams):
    if not streams:
        return None

    lines = [
        f"{s['user_name']:20s} {s['viewer_count']:>7,} viewers  {s.get('title', '')[:50]}\t{s['user_login']}"
        for s in streams
    ]
    while True:
        try:
            result = fzf.prompt(
                lines,
                '--no-sort --no-info --delimiter="\t" --with-nth=1 --layout=reverse'
                ' --expect=ctrl-l,ctrl-h,ctrl-b,ctrl-o,ctrl-c'
                ' --prompt="Stream > "'
                ' --header="[ Enter ] best   [ Ctrl-L ] 480p   [ Ctrl-H ] 720p   [ Ctrl-B ] best   [ Ctrl-O ] pick quality   [ Esc ] back"',
            )
        except (Exception, SystemExit):
            return None, None

        if not result:
            return None, None

        key = result[0] if len(result) > 0 else ""
        selected = result[1] if len(result) > 1 else None

        if not selected or "\t" not in selected:
            return None, None

        _, user_login = selected.rsplit("\t", 1)
        stream = next((s for s in streams if s["user_login"] == user_login), None)

        if key == "ctrl-c":
            url = f"https://twitch.tv/{user_login}"
            pyperclip.copy(url)
            print(f"Copied: {url}")
            continue

        quality_map = {
            "ctrl-l": "480p",
            "ctrl-h": "720p",
            "ctrl-b": "best",
            "ctrl-o": "pick",
            "":       "best",
        }
        quality = quality_map.get(key, "best")

        return stream, quality


def pick_quality(qualities):
    if not qualities:
        return None
    selected = _pick(
        qualities,
        '--prompt="Quality > " --layout=reverse --header="[ Enter ] select   [ Esc ] cancel"',
    )
    return selected or None
