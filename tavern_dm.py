#!/usr/bin/env python3
"""Tavern DM - AI character chat, dungeon master & story roleplay app for LM Studio.

One app that:
  * serves the chat app to any device (PC, phone over Tailscale)
  * proxies the AI requests to LM Studio (no CORS/browser blocking)
  * stores chats, characters, avatars and the library in ~/.local/share/tavern-dm
  * imports SillyTavern / TavernAI character cards (PNG or JSON)
  * gives you a window to run the server and manage the library

Run:  tavern-dm               -> app window (server starts automatically)
      tavern-dm --minimized   -> start in the system tray
      tavern-dm --nogui       -> server only, no window
"""
import http.server, urllib.request, urllib.error, os, sys, json, shutil, threading, re, uuid, socket
import subprocess, copy, webbrowser, datetime, base64, zlib, time

APP_ID = "tavern-dm"
APP_NAME = "Tavern DM"
VERSION = "3.2.0"


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


WEB_DIR = resource("web")
ICON_FILE = resource("icon.png")
HOME = os.path.expanduser("~")
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), APP_ID)
SAVES_DIR = os.path.join(DATA_DIR, "saves")
LIBRARY_FILE = os.path.join(DATA_DIR, "library.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
AVATAR_DIR = os.path.join(DATA_DIR, "avatars")
WEB_SETTINGS_FILE = os.path.join(DATA_DIR, "web_settings.json")
SECTIONS = ("genres", "tones", "characters", "stories", "personas", "lore")
LEGACY_DIRS = [os.path.join(HOME, "tavern")]          # where the old serve.py version kept its files
LOCK = threading.RLock()

DEFAULT_CONFIG = {"port": 8090, "lmstudio": "http://127.0.0.1:4117", "autostart_server": True, "keep_awake": True,
                  "tray": True, "tray_hint_shown": False}


def new_id():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------- library defaults
def _g(name, prompt):
    return {"id": new_id(), "name": name, "prompt": prompt}


def seed_library():
    genres = [
        _g("High Fantasy", "Swords and sorcery, magic, elves, dwarves, dragons, kingdoms and ancient ruins."),
        _g("Dark Fantasy", "A bleak, dangerous fantasy world of corrupt powers, curses and moral grey areas."),
        _g("Sci-Fi", "Spaceships, alien worlds, advanced technology and interstellar politics."),
        _g("Cyberpunk", "Neon megacities, megacorporations, hackers, implants and street gangs."),
        _g("Post-Apocalyptic", "A ruined world after collapse: scavenging, factions, mutants and scarce resources."),
        _g("Modern Day", "The present-day real world, ordinary places and people."),
        _g("Western", "Frontier towns, outlaws, sheriffs, gold rushes and lawless deserts."),
        _g("Pirates", "High seas, ships, treasure, naval battles, ports and smugglers."),
        _g("Steampunk", "Victorian-era brass and steam technology, airships and inventors."),
        _g("Superhero", "Powered heroes and villains, secret identities and city-wide threats."),
    ]
    tones = [
        _g("Adventure", "Exploration, quests, discovery and journeys into the unknown."),
        _g("Action", "Fast, kinetic fights, chases and set pieces."),
        _g("Comedy", "Lighthearted and funny: witty dialogue, absurd situations and comic characters."),
        _g("Horror", "Dread, tension and fear: unsettling atmosphere, monsters and the unknown."),
        _g("Mystery", "Clues, secrets, suspects and a puzzle to solve."),
        _g("Romance", "Relationships, attraction and emotional connection develop over the story."),
        _g("Sexual (Adult)", "Adult 18+ story: explicit sexual content between consenting adult characters is allowed when the story leads there. All characters are adults."),
        _g("Drama", "Emotional stakes, personal conflict and character growth."),
        _g("Survival", "Scarce resources, hostile environments and hard choices to stay alive."),
        _g("Intrigue", "Politics, scheming, betrayal and shifting alliances."),
    ]
    gid = {g["name"]: g["id"] for g in genres}
    tid = {t["name"]: t["id"] for t in tones}
    mira = new_character(name="Mira Thornwood", role="NPC", cls="Tavern keeper",
                         tagline="Runs the Rusty Flagon. Knows every secret in town.",
                         tags=["Fantasy", "Mentor"],
                         appearance="Middle-aged, scarred forearms, sharp green eyes.",
                         personality="Warm but blunt, hears every rumour in town.",
                         description="Ex-adventurer who runs the Rusty Flagon and quietly hires heroes for odd jobs.",
                         scenario="{{user}} walks into the Rusty Flagon on a stormy night.",
                         greeting="*Mira slides a mug across the bar before you even sit down.* \"You've got the look of "
                                  "someone who needs coin. Lucky for you, I've got a job nobody else will take.\"",
                         rpg=True)
    grax = new_character(name="Grax", role="Companion", cls="Half-orc mercenary",
                         tagline="Gruff sellsword with a secret love of poetry.",
                         tags=["Fantasy", "Companion", "Wholesome"],
                         appearance="Huge, tusked, carries a notched greataxe.",
                         personality="Gruff, loyal, secretly loves poetry.",
                         description="A sellsword who joins {{user}} for coin and stays for friendship.",
                         greeting="*Grax looks up from the campfire, quickly hiding a small notebook.* \"You didn't "
                                  "see anything. ...You hungry? There's stew.\"",
                         example_dialogue="{{user}}: What are you writing?\n{{char}}: *grumbles* Weapon inventory. "
                                          "Very boring. *the page clearly says 'Ode to the Moon'*")
    veyne = new_character(name="Lord Veyne", role="Villain", cls="Necromancer noble",
                          tagline="Charming host. Ruthless necromancer.",
                          tags=["Fantasy", "Villain", "Dark"],
                          appearance="Pale, elegant, silver rings on every finger.",
                          personality="Charming, patient, utterly ruthless.",
                          description="A noble secretly raising an undead army beneath his estate.",
                          greeting="*Lord Veyne rises from his chair with a thin smile.* \"Ah, a guest. How rare. "
                                   "Do sit — I insist.\"")
    hero = new_character(name="Rowan", role="Player", cls="Rogue",
                         tagline="Former street thief trying to go straight.", tags=["Fantasy"],
                         appearance="Lean, hooded, quick hands.",
                         personality="Clever, sarcastic, soft spot for underdogs.",
                         description="A former street thief trying to go straight.")
    stories = [
        {"id": new_id(), "title": "The Sunken Crypt", "mode": "dm",
         "genres": [gid["High Fantasy"]], "tones": [tid["Adventure"], tid["Action"]],
         "setting": "The river town of Ashford, built over older, drowned ruins.",
         "premise": "Townsfolk are vanishing at night, and the trail leads into a crypt below the flooded old quarter.",
         "opening": "Start in the Rusty Flagon as Mira offers the player the job.",
         "role": "A wandering adventurer short on coin.",
         "characters": [mira["id"], grax["id"], veyne["id"]], "instructions": ""},
        {"id": new_id(), "title": "Station Nine", "mode": "story",
         "genres": [gid["Sci-Fi"]], "tones": [tid["Horror"], tid["Survival"]],
         "setting": "A remote mining station orbiting a gas giant, cut off from all contact.",
         "premise": "The player wakes from cryosleep to find the crew gone and something moving in the vents.",
         "opening": "Begin as the cryopod opens to emergency lighting and silence.",
         "role": "A replacement engineer who just arrived.",
         "characters": [], "instructions": "Build dread slowly. Keep the creature mostly unseen early on."},
        {"id": new_id(), "title": "The Laughing Goblin", "mode": "dm",
         "genres": [gid["High Fantasy"]], "tones": [tid["Comedy"], tid["Adventure"]],
         "setting": "A chaotic market city where goblins run half the shops.",
         "premise": "The player accidentally becomes the owner of a cursed, sarcastic talking tavern sign.",
         "opening": "", "role": "", "characters": [grax["id"]], "instructions": "Lean into absurd humour and running gags."},
    ]
    lore = [{"id": new_id(), "name": "The Rusty Flagon", "book": "Ashford", "keys": ["Rusty Flagon", "Flagon", "tavern"],
             "content": "The Rusty Flagon is a cramped, smoky tavern in Ashford with a hidden cellar door behind the bar. "
                        "Mira hires adventurers there.", "characters": [], "enabled": True}]
    return {"genres": genres, "tones": tones, "characters": [mira, grax, veyne, hero], "stories": stories,
            "personas": [default_persona()], "lore": lore}


def default_persona():
    return {"id": new_id(), "name": "You", "avatar": "", "description": ""}


def new_character(name="New character", role="NPC", cls="", **kw):
    c = {"id": new_id(), "name": name, "avatar": "", "tagline": "", "tags": [], "role": role, "class": cls,
         "appearance": "", "personality": "", "description": "", "scenario": "", "greeting": "",
         "alt_greetings": [], "example_dialogue": "", "instructions": "", "rpg": False}
    c.update(kw)
    return c


# ---------------------------------------------------------------- storage
def load_json(path, default):
    with LOCK:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return copy.deepcopy(default)
        except Exception:
            try:
                shutil.copyfile(path, path + ".broken")
            except Exception:
                pass
            return copy.deepcopy(default)


def save_json(path, data, backup=False):
    with LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if backup and os.path.exists(path):
            shutil.copyfile(path, path + ".bak")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def migrate_legacy():
    """Bring over saves/library/config from the old ~/tavern serve.py setup (copy, never move)."""
    os.makedirs(SAVES_DIR, exist_ok=True)
    for old in LEGACY_DIRS:
        if not os.path.isdir(old):
            continue
        for name in ("library.json", "config.json"):
            src, dst = os.path.join(old, name), os.path.join(DATA_DIR, name)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copyfile(src, dst)
        old_saves = os.path.join(old, "saves")
        if os.path.isdir(old_saves):
            for fn in os.listdir(old_saves):
                if fn.endswith(".json") and not os.path.exists(os.path.join(SAVES_DIR, fn)):
                    shutil.copyfile(os.path.join(old_saves, fn), os.path.join(SAVES_DIR, fn))
        single = os.path.join(old, "save.json")
        if os.path.exists(single) and not os.path.exists(os.path.join(SAVES_DIR, "default.json")):
            shutil.copyfile(single, os.path.join(SAVES_DIR, "default.json"))


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_FILE, {}))
    return cfg


def save_config():
    save_json(CONFIG_FILE, CONFIG)


def load_library():
    if not os.path.exists(LIBRARY_FILE):
        save_json(LIBRARY_FILE, seed_library())
    with LOCK:
        lib = load_json(LIBRARY_FILE, {})
        changed = False
        for k in SECTIONS:
            if k not in lib:
                lib[k] = []
                changed = True
        if not lib["personas"]:
            lib["personas"].append(default_persona())
            changed = True
        for c in lib["characters"]:                 # fill fields added in v3 for older libraries
            for k, v in new_character().items():
                if k not in c:
                    c[k] = copy.deepcopy(v)
                    changed = True
        if changed:
            save_json(LIBRARY_FILE, lib)
    return lib


def save_library(lib):
    save_json(LIBRARY_FILE, lib, backup=True)


def upsert_item(section, item):
    """Add or replace one item by id, re-reading the file first so other editors' changes are kept."""
    if section not in SECTIONS:
        raise ValueError("unknown section")
    with LOCK:
        lib = load_library()
        item = dict(item)
        item.setdefault("id", new_id())
        if not item["id"]:
            item["id"] = new_id()
        lst = lib[section]
        for i, it in enumerate(lst):
            if it.get("id") == item["id"]:
                lst[i] = item
                break
        else:
            lst.append(item)
        save_library(lib)
    return item


def delete_item(section, item_id):
    if section not in SECTIONS:
        raise ValueError("unknown section")
    with LOCK:
        lib = load_library()
        lib[section] = [it for it in lib[section] if it.get("id") != item_id]
        save_library(lib)


# ---------------------------------------------------------------- avatars & card import
IMG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.(png|jpg|jpeg|webp|gif)$")


def save_avatar(raw, ext="png"):
    os.makedirs(AVATAR_DIR, exist_ok=True)
    ext = ext.lower().lstrip(".")
    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
        ext = "png"
    name = f"{uuid.uuid4().hex[:12]}.{ext}"
    with open(os.path.join(AVATAR_DIR, name), "wb") as f:
        f.write(raw)
    return name


def avatar_from_file(path):
    with open(path, "rb") as f:
        return save_avatar(f.read(), os.path.splitext(path)[1] or ".png")


def _png_text_chunks(raw):
    texts, pos = {}, 8
    while pos + 8 <= len(raw):
        ln = int.from_bytes(raw[pos:pos + 4], "big")
        typ = raw[pos + 4:pos + 8]
        body = raw[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"tEXt":
            k, _, v = body.partition(b"\x00")
            texts[k.decode("latin-1").lower()] = v
        elif typ == b"iTXt":
            k, _, rest = body.partition(b"\x00")
            comp, rest = rest[0], rest[2:]
            _, _, rest = rest.partition(b"\x00")
            _, _, txt = rest.partition(b"\x00")
            texts[k.decode("latin-1").lower()] = zlib.decompress(txt) if comp else txt
        elif typ == b"IEND":
            break
    return texts


def parse_card(raw):
    """Returns (card_dict, png_bytes_or_None) from a SillyTavern/TavernAI PNG or JSON card."""
    png = None
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        png = raw
        texts = _png_text_chunks(raw)
        blob = texts.get("ccv3") or texts.get("chara")
        if not blob:
            raise ValueError("This PNG has no character data in it (not a character card).")
        try:
            card = json.loads(base64.b64decode(blob).decode("utf-8"))
        except Exception:
            card = json.loads(blob.decode("utf-8"))
    else:
        try:
            card = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            raise ValueError("Not a character card. Use a SillyTavern / TavernAI card (.png or .json).")
    if not isinstance(card, dict):
        raise ValueError("Unrecognised card format.")
    return card.get("data") if isinstance(card.get("data"), dict) else card, png


def import_card(raw, filename=""):
    """Imports a character card into the library. Returns the new character."""
    d, png = parse_card(raw)
    name = (d.get("name") or d.get("char_name") or os.path.splitext(os.path.basename(filename))[0] or "Imported").strip()
    notes = (d.get("creator_notes") or "").strip()
    desc = (d.get("description") or d.get("char_persona") or "").strip()
    tagline = (notes or desc).split("\n")[0]
    tagline = tagline[:117] + "…" if len(tagline) > 120 else tagline
    c = new_character(
        name=name, role="NPC", tagline=tagline,
        tags=[str(t) for t in (d.get("tags") or []) if str(t).strip()][:12],
        description=desc,
        personality=(d.get("personality") or "").strip(),
        scenario=(d.get("scenario") or d.get("world_scenario") or "").strip(),
        greeting=(d.get("first_mes") or d.get("char_greeting") or "").strip(),
        alt_greetings=[g.strip() for g in (d.get("alternate_greetings") or []) if str(g).strip()],
        example_dialogue=(d.get("mes_example") or d.get("example_dialogue") or "").strip(),
        instructions=(d.get("system_prompt") or "").strip(),
    )
    if png:
        c["avatar"] = save_avatar(png, "png")
    upsert_item("characters", c)
    book = d.get("character_book") or {}
    add_items("lore", lore_entries(book, book.get("name") or name, [c["id"]]))
    log(f"Imported character card: {name}")
    return c


def add_items(section, items):
    if not items:
        return
    with LOCK:
        lib = load_library()
        lib[section].extend(items)
        save_library(lib)


def lore_entries(book, book_name, char_ids=()):
    """Converts SillyTavern World Info / character_book entries into lore entries."""
    entries = book.get("entries") or []
    if isinstance(entries, dict):                     # World Info files: {"0": {...}, "1": {...}}
        entries = sorted(entries.values(), key=lambda e: (e.get("displayIndex", e.get("order", 0)) or 0))
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        content = (e.get("content") or e.get("entry") or "").strip()
        if not content:
            continue
        keys = e.get("keys") if e.get("keys") is not None else e.get("key", [])
        if isinstance(keys, str):
            keys = keys.split(",")
        keys = [str(k).strip() for k in keys if str(k).strip()]
        if e.get("constant"):
            keys = []                                  # always included
        name = (e.get("comment") or e.get("name") or (keys[0] if keys else "") or content[:40]).strip()
        enabled = e.get("enabled", True) is not False and not e.get("disable", False)
        out.append({"id": new_id(), "name": name, "book": book_name, "keys": keys, "content": content,
                    "characters": list(char_ids), "enabled": enabled})
    return out


def import_file(raw, filename=""):
    """Imports a character card (PNG/JSON) or a lorebook (SillyTavern World Info JSON).
    Returns the new character, or {"kind": "lore", "book": name, "count": n}."""
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        try:
            d = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            raise ValueError("Not a character card or lorebook. Use a SillyTavern / TavernAI .png or .json file.")
        if isinstance(d, dict) and "entries" in d and not any(k in d for k in ("first_mes", "char_greeting", "data")):
            name = (d.get("name") or os.path.splitext(os.path.basename(filename))[0] or "Imported lore").strip()
            items = lore_entries(d, name)
            if not items:
                raise ValueError("That lorebook has no entries with text in them.")
            add_items("lore", items)
            log(f"Imported lorebook '{name}' ({len(items)} entries)")
            return {"kind": "lore", "book": name, "count": len(items)}
    return import_card(raw, filename)


SLOT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def slot_path(slot):
    return os.path.join(SAVES_DIR, slot + ".json") if SLOT_RE.match(slot or "") else None


def list_saves():
    out = []
    os.makedirs(SAVES_DIR, exist_ok=True)
    for fn in os.listdir(SAVES_DIR):
        if not fn.endswith(".json"):
            continue
        d = load_json(os.path.join(SAVES_DIR, fn), {})
        ch = d.get("char") or d.get("persona") or {}
        stats = d.get("stats") or d.get("char") or {}
        cast = d.get("cast") or {}
        names = [v.get("name", "") for v in cast.values()]
        title = (d.get("title") or (d.get("story") or {}).get("title") or ", ".join(n for n in names if n)
                 or ("My adventure" if d.get("messages") else "Untitled"))
        msgs = [m for m in (d.get("messages") or []) if m.get("role") in ("user", "assistant") and m.get("content")]
        last = ""
        if msgs:
            m = msgs[-1]
            who = "You: " if m["role"] == "user" else ""
            last = who + re.sub(r"\[[A-Z]+\s*:[^\]]*\]|<think>[\s\S]*?</think>|[*_]", "", m["content"]).strip().replace("\n", " ")[:90]
        avatars = [v.get("avatar", "") for v in cast.values()] if cast else ["__narrator"]
        out.append({"id": fn[:-5], "title": title, "type": d.get("type", "story"),
                    "template": (d.get("story") or {}).get("template", ""), "avatars": avatars[:3],
                    "names": names[:3], "last": last, "members": d.get("members") or [], "char": ch.get("name") or "", "level": stats.get("level", 1),
                    "updatedAt": d.get("updatedAt", 0), "messages": len(d.get("messages") or [])})
    out.sort(key=lambda g: g["updatedAt"], reverse=True)
    return out


def delete_save(slot):
    path = slot_path(slot)
    with LOCK:
        if path and os.path.exists(path):
            shutil.move(path, path + ".deleted")     # recoverable by renaming


# ---------------------------------------------------------------- HTTP server
os.makedirs(DATA_DIR, exist_ok=True)
migrate_legacy()
CONFIG = load_config()
_log_cb = lambda m: print(m, flush=True)


def log(msg):
    try:
        _log_cb(f"{datetime.datetime.now():%H:%M:%S}  {msg}")
    except Exception:
        pass


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            pass   # browser dropped an idle/pre-opened connection - harmless

    def route(self):
        return self.path.split("?", 1)[0]

    def do_GET(self):
        p = self.route()
        if p.startswith("/v1"):
            return self.proxy()
        if p == "/api/ping":
            return self.send_json(json.dumps({"app": APP_ID, "version": VERSION}).encode())
        if p == "/api/library":
            return self.send_json(json.dumps(load_library()).encode())
        if p == "/api/saves":
            return self.send_json(json.dumps(list_saves()).encode())
        if p == "/api/settings":
            return self.send_json(json.dumps(load_json(WEB_SETTINGS_FILE, {})).encode())
        if p.startswith("/api/save"):
            return self.get_save(p)
        if p.startswith("/avatars/"):
            return self.send_avatar(p[len("/avatars/"):])
        if p in ("/", ""):
            self.path = "/tavern-dm.html"
        return super().do_GET()

    def read_body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def read_json(self):
        try:
            return json.loads(self.read_body() or b"{}")
        except Exception:
            return None

    def do_POST(self):
        p = self.route()
        if p.startswith("/v1"):
            return self.proxy()
        if p.startswith("/api/save"):
            return self.put_save(p)
        if p == "/api/settings":
            d = self.read_json()
            if not isinstance(d, dict):
                return self.send_error(400)
            save_json(WEB_SETTINGS_FILE, d)
            return self.send_json(b'{"ok":true}')
        if p == "/api/avatar":                      # {"data": "data:image/png;base64,..."}
            d = self.read_json() or {}
            m = re.match(r"data:image/(png|jpeg|jpg|webp|gif);base64,(.+)", d.get("data", ""), re.S)
            if not m:
                return self.send_error(400, "Expected an image data URL")
            name = save_avatar(base64.b64decode(m.group(2)), m.group(1))
            return self.send_json(json.dumps({"file": name}).encode())
        if p == "/api/import":                      # {"name": "card.png", "data": "<base64>"}
            d = self.read_json() or {}
            try:
                c = import_file(base64.b64decode(d.get("data", "")), d.get("name", ""))
            except Exception as e:
                return self.send_json(json.dumps({"error": str(e)}).encode(), 400)
            return self.send_json(json.dumps(c).encode())
        if p.startswith("/api/library/"):
            d = self.read_json()
            section = p[len("/api/library/"):].strip("/")
            if not isinstance(d, dict) or section not in SECTIONS:
                return self.send_error(400)
            return self.send_json(json.dumps(upsert_item(section, d)).encode())
        self.send_error(404)

    def send_avatar(self, name):
        path = os.path.join(AVATAR_DIR, name)
        if not IMG_RE.match(name) or not os.path.exists(path):
            return self.send_error(404)
        ext = name.rsplit(".", 1)[1].lower()
        ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, f"image/{ext}")
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_DELETE(self):
        p = self.route()
        if p.startswith("/api/library/"):
            parts = p[len("/api/library/"):].strip("/").split("/")
            if len(parts) != 2 or parts[0] not in SECTIONS:
                return self.send_error(400)
            delete_item(parts[0], parts[1])
            return self.send_json(b'{"ok":true}')
        if p.startswith("/api/save/"):
            slot = p[len("/api/save/"):]
            if not slot_path(slot):
                return self.send_error(400)
            delete_save(slot)
            log(f"Deleted save {slot}")
            return self.send_json(b'{"ok":true}')
        self.send_error(404)

    def _slot(self, p):
        return p[len("/api/save"):].strip("/") or "default"

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        if self.route().endswith(".html") or self.route() in ("/", ""):
            self.send_header("Cache-Control", "no-cache")   # phones always get the latest page
        super().end_headers()

    def get_save(self, p):
        path = slot_path(self._slot(p))
        if not path:
            return self.send_error(400)
        with LOCK:
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except FileNotFoundError:
                data = b"{}"
        self.send_json(data)

    def put_save(self, p):
        path = slot_path(self._slot(p))
        if not path:
            return self.send_error(400)
        body = self.read_body()
        try:
            json.loads(body)
        except Exception:
            return self.send_error(400, "Invalid save data")
        with LOCK:
            os.makedirs(SAVES_DIR, exist_ok=True)
            if os.path.exists(path):
                shutil.copyfile(path, path + ".bak")
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
        self.send_json(b'{"ok":true}')

    def proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(CONFIG["lmstudio"].rstrip("/") + self.path, data=body, method=self.command,
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            resp = e
        except Exception as e:
            log(f"LM Studio unreachable: {e}")
            self.send_error(502, "LM Studio unreachable - is it running with the server started?")
            return
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()   # keeps streaming replies live
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        path = getattr(self, "path", "")
        if path.startswith(("/api/", "/avatars/")) or path.endswith((".ico", ".png", ".json")):
            return
        log(f"{self.client_address[0]}  {fmt % args}")


def host_env():
    """Environment for running the PC's own programs (undoes the AppImage's bundled library paths)."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        for k in ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "SSL_CERT_FILE"):
            orig = env.pop(k + "_ORIG", None)
            if orig is not None:
                env[k] = orig
            else:
                env.pop(k, None)
    return env


def run_host(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=host_env())
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


class SleepBlocker:
    """Holds a systemd 'sleep' + 'idle' block while the server runs. systemd-inhibit runs `cat` on a pipe
    from us, so if Tavern DM quits or crashes the pipe closes and the PC can sleep again."""

    def __init__(self):
        self.proc = None

    @property
    def active(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.active:
            return True
        if not shutil.which("systemd-inhibit"):
            log("Can't keep the PC awake: systemd-inhibit not found")
            return False
        try:
            self.proc = subprocess.Popen(
                ["systemd-inhibit", "--what=sleep:idle", f"--who={APP_NAME}",
                 "--why=Serving chats to your devices", "--mode=block", "cat"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=host_env())
        except Exception as e:
            log(f"Can't keep the PC awake: {e}")
            self.proc = None
            return False
        try:
            self.proc.wait(timeout=0.5)            # exits straight away only if it was refused
        except subprocess.TimeoutExpired:
            log("Keeping this PC awake while the server runs")
            return True
        err = (self.proc.stderr.read() or b"").decode(errors="replace").strip()
        log(f"Can't keep the PC awake: {err or 'permission refused'}")
        self.proc = None
        return False

    def stop(self):
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
            self.proc = None
            log("PC is allowed to sleep again")


BLOCKER = SleepBlocker()


class ServerControl:
    def __init__(self):
        self.httpd = None

    @property
    def running(self):
        return self.httpd is not None

    def start(self):
        if self.httpd:
            return
        load_library()
        self.httpd = http.server.ThreadingHTTPServer(("0.0.0.0", int(CONFIG["port"])), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        log(f"Server running on port {CONFIG['port']}")
        self.apply_keep_awake()

    def apply_keep_awake(self):
        if self.httpd and CONFIG.get("keep_awake", True):
            BLOCKER.start()
        else:
            BLOCKER.stop()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            log("Server stopped")
        BLOCKER.stop()


def other_instance(port):
    """'tavern' if another Tavern DM answers on the port, 'other' if something else holds it, None if free."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return "tavern" if json.load(r).get("app") == APP_ID else "other"
    except Exception:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", int(port)))
        return None
    except OSError:
        return "other"
    finally:
        s.close()


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def tailscale_ip():
    try:
        out = run_host(["tailscale", "ip", "-4"], timeout=3).stdout.strip()
        return out.splitlines()[0] if out else ""
    except Exception:
        return ""


def lm_models():
    with urllib.request.urlopen(CONFIG["lmstudio"].rstrip("/") + "/v1/models", timeout=4) as r:
        return [m["id"] for m in json.load(r).get("data", []) if "embed" not in m["id"].lower()]


# ---------------------------------------------------------------- desktop integration
def launch_command():
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return f'"{appimage}"'
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def desktop_entry(extra_args=""):
    icon_dir = os.path.join(HOME, ".local", "share", "icons", "hicolor", "256x256", "apps")
    os.makedirs(icon_dir, exist_ok=True)
    if os.path.exists(ICON_FILE):
        shutil.copyfile(ICON_FILE, os.path.join(icon_dir, APP_ID + ".png"))
    return (f"[Desktop Entry]\nType=Application\nName={APP_NAME}\n"
            f"Comment=AI dungeon master and story roleplay for LM Studio\n"
            f"Exec={launch_command()}{extra_args}\nIcon={APP_ID}\nTerminal=false\n"
            f"Categories=Game;RolePlaying;\nStartupWMClass={APP_ID}\n")


MENU_FILE = os.path.join(HOME, ".local", "share", "applications", APP_ID + ".desktop")
AUTOSTART_FILE = os.path.join(HOME, ".config", "autostart", APP_ID + ".desktop")


def install_menu_entry():
    os.makedirs(os.path.dirname(MENU_FILE), exist_ok=True)
    with open(MENU_FILE, "w") as f:
        f.write(desktop_entry())
    os.chmod(MENU_FILE, 0o755)
    run_host(["update-desktop-database", os.path.dirname(MENU_FILE)])


def remove_menu_entry():
    if os.path.exists(MENU_FILE):
        os.remove(MENU_FILE)


def set_autostart(on):
    if on:
        os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
        with open(AUTOSTART_FILE, "w") as f:
            f.write(desktop_entry(" --minimized"))
    elif os.path.exists(AUTOSTART_FILE):
        os.remove(AUTOSTART_FILE)


# ---------------------------------------------------------------- start at boot (systemd user service)
SERVICE = APP_ID + ".service"
SERVICE_FILE = os.path.join(HOME, ".config", "systemd", "user", SERVICE)


def service_unit():
    return (f"[Unit]\nDescription={APP_NAME} server (AI chat for LM Studio)\n"
            f"Wants=network-online.target\nAfter=network-online.target\n\n"
            f"[Service]\nType=simple\nExecStart={launch_command()} --nogui --service\n"
            f"Restart=on-failure\nRestartSec=10\n\n"
            f"[Install]\nWantedBy=default.target\n")


def systemctl(*args):
    return run_host(["systemctl", "--user", *args])


def service_enabled():
    return os.path.exists(SERVICE_FILE) and systemctl("is-enabled", SERVICE).stdout.strip() == "enabled"


def service_active():
    return os.path.exists(SERVICE_FILE) and systemctl("is-active", SERVICE).stdout.strip() == "active"


def linger_on():
    user = os.environ.get("USER") or os.path.basename(HOME)
    return run_host(["loginctl", "show-user", user, "-p", "Linger"]).stdout.strip() == "Linger=yes"


def enable_boot_service():
    """Installs and enables the user service, and turns on lingering so it starts at boot without logging in.
    Returns (ok, message)."""
    os.makedirs(os.path.dirname(SERVICE_FILE), exist_ok=True)
    with open(SERVICE_FILE, "w") as f:
        f.write(service_unit())
    r = systemctl("daemon-reload")
    if r.returncode:
        return False, "systemd user services aren't available: " + (r.stderr.strip() or "systemctl failed")
    r = systemctl("enable", SERVICE)
    if r.returncode:
        return False, "Couldn't enable the service: " + r.stderr.strip()
    note = ""
    if not linger_on():
        user = os.environ.get("USER") or os.path.basename(HOME)
        r = run_host(["loginctl", "enable-linger", user], timeout=60)
        if r.returncode or not linger_on():
            note = ("It will start when you log in. To start it at boot before login, run once in a terminal:\n"
                    f"    sudo loginctl enable-linger {user}")
    return True, note


def disable_boot_service():
    systemctl("disable", "--now", SERVICE)
    if os.path.exists(SERVICE_FILE):
        os.remove(SERVICE_FILE)
    systemctl("daemon-reload")


def refresh_service_unit():
    """Keeps the service pointing at the current AppImage if it was moved."""
    if os.path.exists(SERVICE_FILE):
        with open(SERVICE_FILE) as f:
            if f.read() == service_unit():
                return
        with open(SERVICE_FILE, "w") as f:
            f.write(service_unit())
        systemctl("daemon-reload")


# ---------------------------------------------------------------- GUI
STYLE = """
QWidget { background:#14110f; color:#ece3d6; font-size:14px; }
QMainWindow, QDialog { background:#14110f; }
QTabWidget::pane { border:1px solid #3a322b; border-radius:8px; top:-1px; }
QTabBar::tab { background:#1d1916; color:#a3968a; padding:8px 18px; border:1px solid #3a322b; border-bottom:none;
               border-top-left-radius:8px; border-top-right-radius:8px; margin-right:2px; }
QTabBar::tab:selected { background:#26211d; color:#d9a441; }
QPushButton { background:#26211d; border:1px solid #3a322b; border-radius:8px; padding:7px 14px; }
QPushButton:hover { border-color:#d9a441; }
QPushButton:disabled { color:#6b6158; }
QPushButton#primary { background:#d9a441; color:#1a1408; border-color:#d9a441; font-weight:bold; }
QPushButton#primary:hover { background:#e6b55a; }
QPushButton#big { background:#d9a441; color:#1a1408; border-color:#d9a441; font-weight:bold; font-size:17px; padding:12px; }
QPushButton#danger { color:#d9625f; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget, QTableWidget {
    background:#110e0c; border:1px solid #3a322b; border-radius:6px; padding:5px; selection-background-color:#3a322b; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color:#d9a441; }
QListWidget::item { padding:5px; }
QListWidget::item:selected, QTableWidget::item:selected { background:#3a322b; color:#d9a441; }
QHeaderView::section { background:#1d1916; color:#a3968a; border:none; padding:6px; }
QGroupBox { border:1px solid #3a322b; border-radius:10px; margin-top:16px; padding:12px 10px 10px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 4px; color:#d9a441; font-weight:bold; }
QLabel#muted { color:#a3968a; font-size:12px; }
QLabel#title { color:#d9a441; font-size:22px; font-weight:bold; }
QScrollArea { border:none; }
QStatusBar { color:#a3968a; }
QCheckBox { spacing:8px; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:#3a322b; border-radius:4px; min-height:24px; }
QScrollBar::handle:vertical:hover { background:#d9a441; }
QScrollBar:horizontal { background:transparent; height:10px; margin:2px; }
QScrollBar::handle:horizontal { background:#3a322b; border-radius:4px; min-width:24px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QMenu { background:#1d1916; border:1px solid #3a322b; }
QMenu::item:selected { background:#3a322b; color:#d9a441; }
"""


def run_gui(start_minimized=False):
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
                                 QGridLayout, QFormLayout, QLabel, QPushButton, QLineEdit, QPlainTextEdit,
                                 QComboBox, QListWidget, QListWidgetItem, QSpinBox, QCheckBox, QScrollArea,
                                 QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
                                 QAbstractItemView, QSystemTrayIcon, QMenu, QFileDialog)
    from PyQt6.QtCore import Qt, pyqtSignal, QObject, QUrl, QTimer, QRectF, QEvent
    from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap, QPainter, QColor, QGuiApplication

    global _log_cb

    class Bridge(QObject):
        log = pyqtSignal(str)
        lm = pyqtSignal(bool, str)

    bridge = Bridge()
    _log_cb = bridge.log.emit

    def qr_pixmap(text, size=170):
        try:
            import qrcode
        except ImportError:
            return None
        qr = qrcode.QRCode(border=2, box_size=1)
        qr.add_data(text)
        qr.make(fit=True)
        m = qr.get_matrix()
        n = len(m)
        pm = QPixmap(size, size)
        pm.fill(QColor("white"))
        p = QPainter(pm)
        cell = size / n
        for y, row in enumerate(m):
            for x, v in enumerate(row):
                if v:
                    p.fillRect(QRectF(x * cell, y * cell, cell + 0.6, cell + 0.6), QColor("black"))
        p.end()
        return pm

    ROLES = ["NPC", "Companion", "Villain", "Player"]
    MODES = ["dm", "story"]

    class ImageField(QWidget):
        changed = pyqtSignal()

        def __init__(self):
            super().__init__()
            self._value = ""
            h = QHBoxLayout(self)
            h.setContentsMargins(0, 0, 0, 0)
            self.pic = QLabel()
            self.pic.setFixedSize(72, 72)
            self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.pic.setStyleSheet("border:1px solid #3a322b;border-radius:8px;color:#a3968a;font-size:11px")
            b = QPushButton("Choose image…")
            b.clicked.connect(self.choose)
            c = QPushButton("Clear")
            c.clicked.connect(lambda: self.setValue("", emit=True))
            h.addWidget(self.pic)
            h.addWidget(b)
            h.addWidget(c)
            h.addStretch()

        def value(self):
            return self._value

        def setValue(self, v, emit=False):
            self._value = v or ""
            path = os.path.join(AVATAR_DIR, self._value) if self._value else ""
            if path and os.path.exists(path):
                self.pic.setPixmap(QPixmap(path).scaled(70, 70, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                        Qt.TransformationMode.SmoothTransformation))
            else:
                self.pic.clear()
                self.pic.setText("No image")
            if emit:
                self.changed.emit()

        def choose(self):
            fn, _ = QFileDialog.getOpenFileName(self, "Choose image", HOME, "Images (*.png *.jpg *.jpeg *.webp *.gif)")
            if fn:
                self.setValue(avatar_from_file(fn), emit=True)

    class Editor(QWidget):
        """List on the left, form on the right, for one library section. Saves item-by-item so edits
        made in the web app at the same time are never overwritten."""

        def __init__(self, main, key, fields, title_key, defaults, hint):
            super().__init__()
            self.main, self.key, self.fields, self.title_key, self.defaults = main, key, fields, title_key, defaults
            self.cur = None
            self.loading = False
            self.visible_items = []
            lay = QHBoxLayout(self)
            lay.setContentsMargins(10, 10, 10, 10)

            self.left = QVBoxLayout()
            self.filter = QLineEdit()
            self.filter.setPlaceholderText("Search…")
            self.filter.textChanged.connect(lambda: self.refresh(keep_current=True))
            self.left.addWidget(self.filter)
            self.list = QListWidget()
            self.left.addWidget(self.list, 1)
            row = QHBoxLayout()
            add_b = QPushButton("+ Add")
            add_b.setObjectName("primary")
            add_b.clicked.connect(self.add)
            dup_b = QPushButton("Duplicate")
            dup_b.clicked.connect(self.dup)
            del_b = QPushButton("Delete")
            del_b.setObjectName("danger")
            del_b.clicked.connect(self.delete)
            for b in (add_b, dup_b, del_b):
                row.addWidget(b)
            self.left.addLayout(row)
            lw = QWidget()
            lw.setLayout(self.left)
            lw.setFixedWidth(300)

            right = QVBoxLayout()
            h = QLabel(hint)
            h.setObjectName("muted")
            h.setWordWrap(True)
            right.addWidget(h)
            self.form = QFormLayout()
            self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            self.widgets = {}
            for f in fields:
                k, label, typ = f[0], f[1], f[2]
                if typ in ("line", "tags"):
                    w = QLineEdit()
                    if typ == "tags":
                        w.setPlaceholderText("Comma separated")
                    w.editingFinished.connect(self.autosave)
                elif typ in ("text", "textlist"):
                    w = QPlainTextEdit()
                    w.setMinimumHeight(f[3] if len(f) > 3 else 64)
                    w.setTabChangesFocus(True)
                    w.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    if typ == "textlist":
                        w.setPlaceholderText("Separate each one with a line containing only ---")
                elif typ == "combo":
                    w = QComboBox()
                    w.addItems(f[3])
                    w.currentIndexChanged.connect(self.autosave)
                elif typ == "bool":
                    w = QCheckBox(f[3] if len(f) > 3 else "")
                    w.toggled.connect(self.autosave)
                elif typ == "image":
                    w = ImageField()
                    w.changed.connect(self.autosave)
                else:  # checks
                    w = QListWidget()
                    w.setMinimumHeight(100)
                    w.setMaximumHeight(150)
                    w.itemChanged.connect(self.autosave)
                self.widgets[k] = w
                self.form.addRow(label, w)
            fw = QWidget()
            fw.setLayout(self.form)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(fw)
            right.addWidget(scroll, 1)
            rw = QWidget()
            rw.setLayout(right)
            lay.addWidget(lw)
            lay.addWidget(rw, 1)
            self.list.currentRowChanged.connect(self.on_row)

        def add_button(self, label, fn):
            b = QPushButton(label)
            b.clicked.connect(fn)
            self.left.addWidget(b)

        def items(self):
            return self.main.lib[self.key]

        def refresh(self, select_id=None, keep_current=False):
            if keep_current and select_id is None and self.cur:
                select_id = self.cur.get("id")
            self.main.lib = load_library()
            q = self.filter.text().strip().lower()
            self.visible_items = [it for it in self.items() if q in (it.get(self.title_key) or "").lower()]
            self.list.blockSignals(True)
            self.list.clear()
            for it in self.visible_items:
                self.list.addItem(it.get(self.title_key) or "(untitled)")
            self.list.blockSignals(False)
            ids = [it.get("id") for it in self.visible_items]
            row = ids.index(select_id) if select_id in ids else (0 if ids else -1)
            self.cur = None                      # already saved by the caller; don't re-save a stale copy
            self.list.blockSignals(True)
            self.list.setCurrentRow(row)
            self.list.blockSignals(False)
            self.on_row(row)

        def on_row(self, row):
            if self.cur is not None and not self.loading:
                self.save()                       # keep edits to the item we're leaving
            self.cur = self.visible_items[row] if 0 <= row < len(self.visible_items) else None
            self.loading = True
            for f in self.fields:
                k, typ = f[0], f[2]
                w = self.widgets[k]
                v = (self.cur or {}).get(k)
                if typ == "line":
                    w.setText(str(v or ""))
                elif typ == "tags":
                    w.setText(", ".join(v or []))
                elif typ == "text":
                    w.setPlainText(str(v or ""))
                elif typ == "textlist":
                    w.setPlainText("\n---\n".join(v or []))
                elif typ == "combo":
                    w.setCurrentIndex(max(0, w.findText(str(v or ""))))
                elif typ == "bool":
                    w.setChecked(bool(v))
                elif typ == "image":
                    w.setValue(v or "")
                else:
                    w.clear()
                    for it in self.main.lib[f[3]]:
                        li = QListWidgetItem(it.get("name") or it.get("title") or "?")
                        li.setData(Qt.ItemDataRole.UserRole, it["id"])
                        li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        li.setCheckState(Qt.CheckState.Checked if it["id"] in (v or []) else Qt.CheckState.Unchecked)
                        w.addItem(li)
                w.setEnabled(self.cur is not None)
            self.loading = False

        def collect(self):
            if not self.cur:
                return False
            changed = False
            for f in self.fields:
                k, typ = f[0], f[2]
                w = self.widgets[k]
                if typ == "line":
                    v = w.text().strip()
                elif typ == "tags":
                    v = [t.strip() for t in w.text().split(",") if t.strip()]
                elif typ == "text":
                    v = w.toPlainText().strip()
                elif typ == "textlist":
                    v = [t.strip() for t in re.split(r"\n\s*-{3,}\s*\n", w.toPlainText()) if t.strip()]
                elif typ == "combo":
                    v = w.currentText()
                elif typ == "bool":
                    v = w.isChecked()
                elif typ == "image":
                    v = w.value()
                else:
                    v = [w.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.count())
                         if w.item(i).checkState() == Qt.CheckState.Checked]
                if self.cur.get(k) != v:
                    self.cur[k] = v
                    changed = True
            return changed

        def save(self):
            if self.collect():
                upsert_item(self.key, self.cur)
                return True
            return False

        def autosave(self, *_):
            if self.loading or not self.save():
                return
            row = self.list.currentRow()
            if 0 <= row < self.list.count():
                self.list.item(row).setText(self.cur.get(self.title_key) or "(untitled)")
            self.main.status("Saved")

        def add(self):
            self.save()
            item = copy.deepcopy(self.defaults)
            item["id"] = new_id()
            upsert_item(self.key, item)
            self.filter.clear()
            self.refresh(select_id=item["id"])
            first = self.widgets[self.fields[0][0]]
            if self.fields[0][2] == "image" and len(self.fields) > 1:
                first = self.widgets[self.fields[1][0]]
            first.setFocus()
            if isinstance(first, QLineEdit):
                first.selectAll()

        def dup(self):
            if not self.cur:
                return
            self.save()
            item = copy.deepcopy(self.cur)
            item["id"] = new_id()
            item[self.title_key] = (item.get(self.title_key) or "") + " (copy)"
            upsert_item(self.key, item)
            self.refresh(select_id=item["id"])

        def delete(self):
            if not self.cur:
                return
            name = self.cur.get(self.title_key) or "this item"
            if QMessageBox.question(self, "Delete", f"Delete “{name}”?") != QMessageBox.StandardButton.Yes:
                return
            delete_item(self.key, self.cur["id"])
            self.cur = None
            self.refresh()

    class Main(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(APP_NAME)
            self.resize(1080, 760)
            self.server = ServerControl()
            self.lib = load_library()
            self.urls = {}
            self.quitting = False
            self.attached = False          # True when the boot service is the one serving
            refresh_service_unit()

            self.tabs = QTabWidget()
            self.setCentralWidget(self.tabs)
            self.tabs.addTab(self.build_home(), "Home")

            char_defaults = new_character()
            del char_defaults["id"]
            self.characters = Editor(self, "characters", [
                ("avatar", "Avatar", "image"),
                ("name", "Name", "line"),
                ("tagline", "Tagline", "line"),
                ("tags", "Tags", "tags"),
                ("role", "Role", "combo", ROLES),
                ("class", "Class / job", "line"),
                ("description", "Description", "text", 100),
                ("personality", "Personality", "text"),
                ("appearance", "Appearance", "text"),
                ("scenario", "Scenario", "text"),
                ("greeting", "First message", "text", 90),
                ("alt_greetings", "Other first messages", "textlist", 80),
                ("example_dialogue", "Example dialogue", "text", 90),
                ("instructions", "Extra instructions", "text"),
                ("rpg", "RPG mode", "bool", "Dice, gold, XP and HP in chats with this character"),
            ], "name", char_defaults,
                "Characters you can chat with. Use {{char}} for the character's name and {{user}} for yours. "
                "Other first messages become swipeable greetings. Import SillyTavern / TavernAI cards (PNG or JSON) "
                "with the button below the list.")
            self.characters.add_button("Import character cards or lorebooks…", self.import_cards)
            self.stories = Editor(self, "stories", [
                ("cover", "Cover image", "image"),
                ("title", "Title", "line"),
                ("tags", "Tags", "tags"),
                ("mode", "Mode", "combo", MODES),
                ("genres", "Genres", "checks", "genres"),
                ("tones", "Story types", "checks", "tones"),
                ("setting", "Setting", "text"),
                ("premise", "Premise / hook", "text"),
                ("opening", "Opening scene", "text"),
                ("role", "Player's role", "line"),
                ("characters", "Characters", "checks", "characters"),
                ("instructions", "Extra instructions", "text"),
                ("rpg", "RPG mode", "bool", "Dice, gold, XP and HP"),
            ], "title", {"title": "New story", "cover": "", "tags": [], "mode": "dm", "genres": [], "tones": [], "setting": "",
                         "premise": "", "opening": "", "role": "", "characters": [], "instructions": "", "rpg": True},
                "Narrated adventures. Mode: dm = dungeon master with dice, story = free roleplay. "
                "Anything left blank is invented by the AI. Changes save automatically.")
            self.lore = Editor(self, "lore", [
                ("name", "Name", "line"),
                ("book", "Lorebook", "line"),
                ("keys", "Trigger words", "tags"),
                ("content", "What the AI should know", "text", 140),
                ("characters", "Only for", "checks", "characters"),
                ("enabled", "Enabled", "bool", "Use this entry"),
            ], "name", {"name": "New entry", "book": "", "keys": [], "content": "", "characters": [], "enabled": True},
                "Lorebook: when a trigger word comes up in the chat, the entry is given to the AI. Leave trigger words "
                "empty to always include it. Leave “Only for” unticked to use it in every chat.")
            self.personas = Editor(self, "personas", [
                ("avatar", "Avatar", "image"),
                ("name", "Name", "line"),
                ("description", "About you", "text", 120),
            ], "name", {"name": "New persona", "avatar": "", "description": ""},
                "Who you are in chats. Pick your active persona in the app under Me.")
            self.genres = Editor(self, "genres", [
                ("image", "Image", "image"),
                ("name", "Name", "line"),
                ("prompt", "Description for the AI", "text", 130),
            ], "name", {"name": "New genre", "prompt": ""},
                "The world type for stories. The description is sent to the AI.")
            self.tones = Editor(self, "tones", [
                ("image", "Image", "image"),
                ("name", "Name", "line"),
                ("prompt", "Description for the AI", "text", 130),
            ], "name", {"name": "New story type", "prompt": ""},
                "The kind of story (comedy, horror, action…). The description tells the AI how to play it.")

            self.lore.add_button("Import lorebooks…", self.import_cards)
            order = [("Characters", self.characters), ("Stories", self.stories), ("Lorebook", self.lore),
                     ("Personas", self.personas), ("Genres", self.genres), ("Story Types", self.tones)]
            self.editors = {}
            for label, ed in order:
                self.editors[self.tabs.addTab(ed, label)] = ed
            self.saves_tab = self.tabs.addTab(self.build_saves(), "Chats")
            self.tabs.addTab(self.build_settings(), "Settings")
            for e in self.editors.values():
                e.refresh()
            self.prev_tab = 0
            self.tabs.currentChanged.connect(self.tab_changed)

            bridge.log.connect(self.log_view.appendPlainText)
            bridge.lm.connect(self.show_lm)
            self.setup_tray()

            if CONFIG.get("autostart_server", True):
                self.start_server()
            self.update_state()
            QTimer.singleShot(50, self.update_urls)
            self.lm_timer = QTimer(self)
            self.lm_timer.timeout.connect(self.check_lm)
            self.lm_timer.timeout.connect(self.update_state)
            self.lm_timer.start(10000)
            QTimer.singleShot(300, self.check_lm)
            self.save_timer = QTimer(self)        # catches edits in the big text boxes
            self.save_timer.timeout.connect(self.autosave_current)
            self.save_timer.start(3000)

        def autosave_current(self):
            ed = self.editors.get(self.tabs.currentIndex())
            if ed:
                ed.save()

        def import_cards(self):
            files, _ = QFileDialog.getOpenFileNames(self, "Import character cards or lorebooks", HOME,
                                                    "Cards and lorebooks (*.png *.json);;All files (*)")
            last_char, books, errors = None, 0, []
            for fn in files:
                try:
                    with open(fn, "rb") as f:
                        r = import_file(f.read(), fn)
                    if r.get("kind") == "lore":
                        books += 1
                    else:
                        last_char = r
                except Exception as e:
                    errors.append(f"{os.path.basename(fn)}: {e}")
            if last_char:
                self.characters.refresh(select_id=last_char["id"])
            if books:
                self.lore.refresh()
            if last_char or books:
                self.status(f"Imported {len(files) - len(errors)} file(s)")
            if errors:
                QMessageBox.warning(self, "Import", "Some files could not be imported:\n\n" + "\n".join(errors))

        def changeEvent(self, e):
            if e.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
                ed = self.editors.get(self.tabs.currentIndex())
                if ed:                            # pick up changes made in the web app
                    ed.save()
                    ed.refresh(keep_current=True)
            super().changeEvent(e)

        # ---------- helpers
        def status(self, msg):
            self.statusBar().showMessage(msg, 3000)

        def tab_changed(self, idx):
            if self.prev_tab in self.editors:
                self.editors[self.prev_tab].save()
            if idx in self.editors:
                self.editors[idx].refresh(keep_current=True)    # pick up new genres / characters
            if idx == self.saves_tab:
                self.refresh_saves()
            self.prev_tab = idx

        # ---------- home
        def build_home(self):
            w = QWidget()
            outer = QVBoxLayout(w)
            outer.setContentsMargins(18, 14, 18, 14)
            head = QHBoxLayout()
            t = QLabel("⚔  Tavern DM")
            t.setObjectName("title")
            head.addWidget(t)
            head.addStretch()
            v = QLabel(f"v{VERSION}")
            v.setObjectName("muted")
            head.addWidget(v)
            outer.addLayout(head)

            grid = QGridLayout()
            grid.setHorizontalSpacing(14)

            srv = QGroupBox("Game server")
            sl = QVBoxLayout(srv)
            self.srv_lbl = QLabel()
            self.srv_lbl.setStyleSheet("font-size:16px;font-weight:bold")
            self.srv_btn = QPushButton()
            self.srv_btn.clicked.connect(self.toggle_server)
            self.awake_lbl = QLabel("")
            self.awake_lbl.setObjectName("muted")
            self.awake_lbl.setWordWrap(True)
            sl.addWidget(self.srv_lbl)
            sl.addWidget(self.awake_lbl)
            sl.addWidget(self.srv_btn)
            sl.addStretch()

            lm = QGroupBox("LM Studio")
            ll = QVBoxLayout(lm)
            self.lm_lbl = QLabel("Checking…")
            self.lm_lbl.setStyleSheet("font-size:16px;font-weight:bold")
            self.lm_detail = QLabel("")
            self.lm_detail.setObjectName("muted")
            self.lm_detail.setWordWrap(True)
            ll.addWidget(self.lm_lbl)
            ll.addWidget(self.lm_detail)
            ll.addStretch()

            grid.addWidget(srv, 0, 0)
            grid.addWidget(lm, 0, 1)
            outer.addLayout(grid)

            self.open_btn = QPushButton("▶  Open the game")
            self.open_btn.setObjectName("big")
            self.open_btn.clicked.connect(lambda: self.open_url("local"))
            outer.addWidget(self.open_btn)

            links = QGroupBox("Play on other devices")
            lh = QHBoxLayout(links)
            form = QFormLayout()
            self.url_lbls = {}
            for key, label in (("local", "This PC"), ("lan", "Home Wi-Fi"), ("ts", "Anywhere (Tailscale)")):
                row = QHBoxLayout()
                lbl = QLabel("…")
                lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                cb = QPushButton("Copy")
                cb.clicked.connect(lambda _, k=key: self.copy_url(k))
                ob = QPushButton("Open")
                ob.clicked.connect(lambda _, k=key: self.open_url(k))
                row.addWidget(lbl, 1)
                row.addWidget(cb)
                row.addWidget(ob)
                self.url_lbls[key] = lbl
                form.addRow(label, row)
            tip = QLabel("On your phone: connect Tailscale (or your home Wi-Fi), then scan the code "
                         "or type the address into the browser.")
            tip.setObjectName("muted")
            tip.setWordWrap(True)
            form.addRow("", tip)
            refresh_b = QPushButton("Refresh addresses")
            refresh_b.clicked.connect(self.update_urls)
            form.addRow("", refresh_b)
            fw = QWidget()
            fw.setLayout(form)
            lh.addWidget(fw, 1)
            qv = QVBoxLayout()
            self.qr_lbl = QLabel()
            self.qr_lbl.setFixedSize(170, 170)
            self.qr_cap = QLabel("")
            self.qr_cap.setObjectName("muted")
            self.qr_cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qv.addWidget(self.qr_lbl)
            qv.addWidget(self.qr_cap)
            lh.addLayout(qv)
            outer.addWidget(links)

            lg = QLabel("Activity")
            lg.setObjectName("muted")
            outer.addWidget(lg)
            self.log_view = QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumBlockCount(1000)
            outer.addWidget(self.log_view, 1)
            return w

        def update_state(self):
            if self.attached and not service_active():
                self.attached = False
            on = self.server.running or self.attached
            self.srv_lbl.setText(("● Running (background service)" if self.attached else "● Running") if on else "● Stopped")
            awake = on and CONFIG.get("keep_awake", True) and (self.attached or BLOCKER.active)
            parts = []
            if on:
                parts.append("☕ Keeping this PC awake" if awake else "💤 PC may sleep")
            if service_enabled():
                parts.append("⏻ Starts at boot")
            self.awake_lbl.setText("   ·   ".join(parts))
            self.srv_lbl.setStyleSheet(f"font-size:16px;font-weight:bold;color:{'#7fb069' if on else '#d9625f'}")
            self.srv_btn.setText("Stop server" if on else "Start server")
            self.open_btn.setEnabled(on)
            if self.tray:
                self.tray.setToolTip(f"{APP_NAME} — {'running' if on else 'stopped'}")

        def update_urls(self):
            port = CONFIG["port"]
            ip, ts = lan_ip(), tailscale_ip()
            self.urls = {"local": f"http://localhost:{port}/",
                         "lan": f"http://{ip}:{port}/" if ip else "",
                         "ts": f"http://{ts}:{port}/" if ts else ""}
            for k, lbl in self.url_lbls.items():
                lbl.setText(self.urls[k] or ("Tailscale not running" if k == "ts" else "Not available"))
            target = self.urls["ts"] or self.urls["lan"]
            pm = qr_pixmap(target) if target else None
            if pm:
                self.qr_lbl.setPixmap(pm)
                self.qr_cap.setText("Scan on your phone")
            else:
                self.qr_lbl.clear()
                self.qr_cap.setText("")

        def copy_url(self, key):
            if self.urls.get(key):
                QGuiApplication.clipboard().setText(self.urls[key])
                self.status("Address copied")

        def open_url(self, key):
            if self.urls.get(key):
                QDesktopServices.openUrl(QUrl(self.urls[key]))

        def start_server(self):
            if service_enabled() or service_active():
                self.attach_service()
                return
            try:
                self.server.start()
            except OSError:
                who = other_instance(CONFIG["port"])
                msg = (f"Port {CONFIG['port']} is already in use"
                       + (" by another copy of Tavern DM (or the old serve.py)." if who == "tavern" else ".")
                       + "\n\nClose it, then press Start server, or change the port in Settings.")
                log(msg.replace("\n\n", " "))
                QMessageBox.warning(self, APP_NAME, msg)
            self.update_state()

        def attach_service(self):
            """Use the background (boot) service instead of serving from this window."""
            if not service_active():
                systemctl("start", SERVICE)
            for _ in range(40):                      # wait up to ~10s for it to answer
                if other_instance(CONFIG["port"]) == "tavern":
                    break
                QApplication.processEvents()
                time.sleep(0.25)
            self.attached = service_active()
            if self.attached:
                log("Using the background service (starts at boot). Its activity log: journalctl --user -u tavern-dm -f")
            else:
                log("The background service didn't start - check: systemctl --user status tavern-dm")
            self.update_state()

        def toggle_server(self):
            if self.attached:
                systemctl("stop", SERVICE)
                self.attached = False
                log("Background service stopped (it will start again at the next boot)")
                self.update_state()
            elif self.server.running:
                self.server.stop()
                self.update_state()
            else:
                self.start_server()

        def check_lm(self):
            def work():
                try:
                    ids = lm_models()
                    bridge.lm.emit(True, ("Models: " + ", ".join(ids)) if ids else "No chat models found in LM Studio")
                except Exception:
                    bridge.lm.emit(False, f"Can't reach {CONFIG['lmstudio']}. Start LM Studio's server "
                                          "(Developer tab) and load a model.")
            threading.Thread(target=work, daemon=True).start()

        def show_lm(self, ok, text):
            self.lm_lbl.setText("● Connected" if ok else "● Not reachable")
            self.lm_lbl.setStyleSheet(f"font-size:16px;font-weight:bold;color:{'#7fb069' if ok else '#d9625f'}")
            self.lm_detail.setText(text)

        # ---------- saves
        def build_saves(self):
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(10, 10, 10, 10)
            self.saves_table = QTableWidget(0, 5)
            self.saves_table.setHorizontalHeaderLabels(["Story", "Character", "Level", "Messages", "Last played"])
            self.saves_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self.saves_table.verticalHeader().setVisible(False)
            self.saves_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.saves_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            lay.addWidget(self.saves_table)
            row = QHBoxLayout()
            for label, fn, name in (("Refresh", self.refresh_saves, ""),
                                    ("Delete selected", self.delete_selected_save, "danger"),
                                    ("Open saves folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(SAVES_DIR)), "")):
                b = QPushButton(label)
                if name:
                    b.setObjectName(name)
                b.clicked.connect(fn)
                row.addWidget(b)
            row.addStretch()
            lay.addLayout(row)
            return w

        def refresh_saves(self):
            self.save_rows = list_saves()
            t = self.saves_table
            t.setRowCount(len(self.save_rows))
            for r, g in enumerate(self.save_rows):
                when = datetime.datetime.fromtimestamp(g["updatedAt"] / 1000).strftime("%d %b %Y %H:%M") if g["updatedAt"] else ""
                for c, val in enumerate((g["title"], g["char"], str(g["level"]), str(g["messages"]), when)):
                    t.setItem(r, c, QTableWidgetItem(val))

        def delete_selected_save(self):
            r = self.saves_table.currentRow()
            if r < 0:
                return
            g = self.save_rows[r]
            if QMessageBox.question(self, "Delete", f"Delete the save “{g['title']}”?") == QMessageBox.StandardButton.Yes:
                delete_save(g["id"])
                self.refresh_saves()

        # ---------- settings
        def build_settings(self):
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(18, 14, 18, 14)

            conn = QGroupBox("Connection")
            f = QFormLayout(conn)
            self.lm_edit = QLineEdit(CONFIG["lmstudio"])
            self.port_spin = QSpinBox()
            self.port_spin.setRange(1024, 65535)
            self.port_spin.setValue(int(CONFIG["port"]))
            apply_b = QPushButton("Save & restart server")
            apply_b.setObjectName("primary")
            apply_b.clicked.connect(self.apply_connection)
            f.addRow("LM Studio address", self.lm_edit)
            f.addRow("Game port", self.port_spin)
            f.addRow("", apply_b)
            lay.addWidget(conn)

            beh = QGroupBox("Behaviour")
            bl = QVBoxLayout(beh)
            self.auto_chk = QCheckBox("Start the game server when the app opens")
            self.auto_chk.setChecked(CONFIG.get("autostart_server", True))
            self.auto_chk.toggled.connect(lambda v: self.set_cfg("autostart_server", v))
            self.tray_chk = QCheckBox("Keep running in the system tray when the window is closed")
            self.tray_chk.setChecked(CONFIG.get("tray", True))
            self.tray_chk.toggled.connect(lambda v: self.set_cfg("tray", v))
            self.login_chk = QCheckBox("Open this window in the tray when I log in")
            self.login_chk.setChecked(os.path.exists(AUTOSTART_FILE))
            self.login_chk.toggled.connect(self.toggle_login)
            self.awake_chk = QCheckBox("Keep this PC awake while the server is running (no sleep or suspend)")
            self.awake_chk.setChecked(CONFIG.get("keep_awake", True))
            self.awake_chk.toggled.connect(self.toggle_awake)
            self.boot_chk = QCheckBox("Start the server when the PC boots (no need to log in or open this window)")
            self.boot_chk.setChecked(service_enabled())
            self.boot_chk.toggled.connect(self.toggle_boot)
            for c in (self.boot_chk, self.awake_chk, self.auto_chk, self.tray_chk, self.login_chk):
                bl.addWidget(c)
            lay.addWidget(beh)

            inst = QGroupBox("Install")
            il = QVBoxLayout(inst)
            self.menu_lbl = QLabel()
            self.menu_lbl.setObjectName("muted")
            self.menu_lbl.setWordWrap(True)
            row = QHBoxLayout()
            self.menu_btn = QPushButton()
            self.menu_btn.clicked.connect(self.toggle_menu)
            data_b = QPushButton("Open data folder")
            data_b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR)))
            row.addWidget(self.menu_btn)
            row.addWidget(data_b)
            row.addStretch()
            il.addWidget(self.menu_lbl)
            il.addLayout(row)
            lay.addWidget(inst)
            lay.addStretch()
            self.update_menu_state()
            return w

        def set_cfg(self, key, val):
            CONFIG[key] = val
            save_config()

        def apply_connection(self):
            CONFIG["lmstudio"] = self.lm_edit.text().strip() or DEFAULT_CONFIG["lmstudio"]
            CONFIG["port"] = self.port_spin.value()
            save_config()
            if self.attached:
                systemctl("restart", SERVICE)
                self.attach_service()
            else:
                if self.server.running:
                    self.server.stop()
                self.start_server()
            self.update_urls()
            self.check_lm()
            self.status("Settings saved")

        def toggle_awake(self, on):
            self.set_cfg("keep_awake", on)
            if self.attached:
                systemctl("restart", SERVICE)       # the service reads the setting when it starts
                self.attach_service()
            else:
                self.server.apply_keep_awake()
                self.update_state()
            self.status("PC will stay awake while serving" if on else "PC may sleep normally")

        def toggle_boot(self, on):
            if on:
                ok, note = enable_boot_service()
                if not ok:
                    QMessageBox.warning(self, APP_NAME, note)
                    self.boot_chk.blockSignals(True)
                    self.boot_chk.setChecked(False)
                    self.boot_chk.blockSignals(False)
                    return
                if self.server.running:
                    self.server.stop()                # hand over to the service
                self.attach_service()
                if note:
                    QMessageBox.information(self, APP_NAME, note)
                self.status("Server will start at boot")
            else:
                disable_boot_service()
                self.attached = False
                log("Background service removed")
                if CONFIG.get("autostart_server", True):
                    self.start_server()
                self.update_state()
                self.status("Server won't start at boot")

        def toggle_login(self, on):
            set_autostart(on)
            self.status("Will start at login" if on else "Won't start at login")

        def update_menu_state(self):
            installed = os.path.exists(MENU_FILE)
            self.menu_btn.setText("Remove from app menu" if installed else "Add to app menu")
            where = os.environ.get("APPIMAGE") or "this location"
            self.menu_lbl.setText(("Tavern DM is in your application menu. " if installed else
                                   "Add Tavern DM to your application menu (Games). ")
                                  + f"The menu entry points to {where}, so keep the AppImage there.")

        def toggle_menu(self):
            if os.path.exists(MENU_FILE):
                remove_menu_entry()
            else:
                install_menu_entry()
                if self.login_chk.isChecked():
                    set_autostart(True)     # refresh path in case the AppImage moved
                refresh_service_unit()
            self.update_menu_state()

        # ---------- tray / closing
        def setup_tray(self):
            self.tray = None
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            menu = QMenu()
            menu.addAction("Open the game", lambda: self.open_url("local"))
            menu.addAction("Show window", self.show_window)
            menu.addSeparator()
            menu.addAction("Quit", self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda r: self.show_window()
                                        if r == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()

        def show_window(self):
            self.showNormal()
            self.raise_()
            self.activateWindow()

        def quit_app(self):
            self.quitting = True
            self.close()

        def closeEvent(self, e):
            for ed in self.editors.values():
                ed.save()
            if self.tray and CONFIG.get("tray", True) and not self.quitting:
                e.ignore()
                self.hide()
                if not CONFIG.get("tray_hint_shown"):
                    self.tray.showMessage(APP_NAME, "Still running in the tray so your phone can keep playing. "
                                                    "Right-click the icon to quit.")
                    self.set_cfg("tray_hint_shown", True)
                return
            self.server.stop()
            if self.tray:
                self.tray.hide()
            e.accept()
            QApplication.quit()

    QGuiApplication.setDesktopFileName(APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    if os.path.exists(ICON_FILE):
        app.setWindowIcon(QIcon(ICON_FILE))
    win = Main()
    win.setWindowIcon(app.windowIcon())
    if win.tray:
        win.tray.setIcon(app.windowIcon())
    if not (start_minimized and win.tray):
        win.show()
    sys.exit(app.exec())


def run_headless():
    import signal
    srv = ServerControl()
    srv.start()
    print(f"{APP_NAME} server running: http://localhost:{CONFIG['port']}/  (data: {DATA_DIR})  Ctrl+C to stop", flush=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())      # systemctl stop
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    srv.stop()


def main():
    who = other_instance(CONFIG["port"])
    if who == "tavern":
        if "--nogui" in sys.argv:
            print(f"{APP_NAME} is already running.")
            return
        if not service_active():
            print(f"{APP_NAME} is already running - opening the game.")
            webbrowser.open(f"http://localhost:{CONFIG['port']}/")
            return
        # the background service is serving: open the window to manage it
    if "--nogui" in sys.argv:
        run_headless()
        return
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        print("PyQt6 is not installed - running the server without a window.")
        run_headless()
        return
    run_gui(start_minimized="--minimized" in sys.argv)


if __name__ == "__main__":
    main()
