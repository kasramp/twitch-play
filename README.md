# Twitch Play

A minimal Twitch CLI app built on top of mpv, streamlink, and fzf.

## Requirements

- Python 3.10+
- [mpv](https://mpv.io)
- [streamlink](https://streamlink.github.io)
- [fzf](https://github.com/junegunn/fzf)

## Installation

### Quick install (recommended)

```bash
$ pipx install twitch-play
```

Or with pip:

```bash
$ pip install twitch-play
```

Then run:

```bash
$ twitch-play
```

### From source

```bash
$ git clone https://github.com/kasramp/twitch-play
$ cd twitch-play
$ python -m venv venv && source venv/bin/activate
$ pip install -r requirements.txt
$ ./play-twitch
```

## Configuration

There's a Client ID in the config.py file, which you can use for experiments. Ideally, you want to create your own app and use it, following the steps below:

1. Go to [dev.twitch.tv/console](https://dev.twitch.tv/console) and register a new app.
2. Set the OAuth redirect URL to `http://localhost:8765/callback` and category to **Website Integration**.
3. Copy your Client ID and set it in `twitch_play/config.py`.

## Usage

| Key    | Action                              |
|--------|-------------------------------------|
| Enter  | Play stream at best quality         |
| Ctrl-L | Play at 480p                        |
| Ctrl-H | Play at 720p                        |
| Ctrl-B | Play at best quality                |
| Ctrl-O | Pick quality from list              |
| Ctrl-F | Search categories (category screen) |
| Esc    | Go back                             |
