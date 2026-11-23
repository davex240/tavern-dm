# Tavern DM

AI character chat, dungeon master and story roleplay for **LM Studio** — in the style of LinkyAI / RosyChat, running on your own PC and playable from any device (PC, phone over Tailscale).

## Features
- **Characters** — gallery with avatars, tags, first messages and swipeable alternate greetings. Imports SillyTavern / TavernAI cards (PNG or JSON).
- **Chats** — messaging-style list, swipe between reply versions, edit / continue / delete any message, group chats.
- **Stories** — saved adventures with cover, genres, story types, setting, premise and cast; Dungeon Master or story-roleplay mode; quick "surprise me" stories.
- **Lorebook** — keyword-triggered world info, grouped into lorebooks; imports SillyTavern World Info JSON.
- **Memory** — automatic "story so far" summaries plus pinned notes.
- **RPG mode** — dice, gold, XP, HP, levels and inventory tracked from the AI's replies.
- **Personas** — who you are in each chat.
- **Desktop manager** (PyQt6) — server status, LM Studio status, QR code for your phone, library editors, tray icon.
- **Always-on** — keeps the PC awake while serving and can start at boot as a systemd user service.

## Run from source
```
pip install PyQt6 qrcode
python tavern_dm.py            # window + server
python tavern_dm.py --nogui    # server only
```
Then open `http://localhost:8090/`. Point it at LM Studio in **Settings** (default `http://127.0.0.1:4117`).

## Build the AppImage
```
./build.sh        # -> Tavern_DM-x86_64.AppImage
```

## Files
| Path | What |
|---|---|
| `tavern_dm.py` | Server (static files, LM Studio proxy, saves, library, card import) and the PyQt6 manager window |
| `web/tavern-dm.html` | The chat app (single page) |
| `web/manifest.json`, `web/icon.png` | Home-screen install |
| `build.sh`, `make_icon.py` | AppImage build |

User data lives in `~/.local/share/tavern-dm` (saves, library, avatars, settings).
