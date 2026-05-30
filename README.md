# Twitch Play

A minimal Twitch CLI app built on top of MPV, Steamlink, and Fzf.

## Requirements

- Python 3.10+
- [mpv](https://mpv.io)
- [streamlink](https://streamlink.github.io)
- [fzf](https://github.com/junegunn/fzf)

## Setup

There's a clientId in the `config.py` file, which you can use for experiments. Ideally, you want to create your own app and use it, following the steps below:

1. Register an app at [dev.twitch.tv/console](https://dev.twitch.tv/console), set OAuth redirect to `http://localhost:8765/callback`, type **Website Integration**, and copy your Client ID.
2. Set your Client ID in `twitch_play/config.py`.

```bash
$ git clone https://github.com/yourname/twitch-play
$ cd twitch-play
$ python -m venv venv && source venv/bin/activate
$ pip install -r requirements.txt
$ ./play-twitch
```

## Usage

| Key | Action |
|---|---|
| Enter | Play stream at best quality |
| Ctrl-L | Play at 480p |
| Ctrl-H | Play at 720p |
| Ctrl-B | Play at best quality |
| Ctrl-O | Pick quality from list |
| Ctrl-F | Search categories (category screen) |
| Esc | Go back |
