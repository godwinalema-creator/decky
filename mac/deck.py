#!/usr/bin/env python3
"""
DECKY — turns the Arduino (LCD + joystick) into a control deck for this Mac.

  python3 mac/deck.py

Joystick: up/down move, right or click select, left back, hold click = back to home.
All menus and actions live here, so changing them never needs a reflash.
Standard library only.
"""
import ctypes, glob, os, plistlib, queue, select, shutil, sqlite3, subprocess, sys, termios, threading, time, unicodedata

# ---- joystick orientation (flip these if directions feel reversed) ----
INVERT_Y = False
INVERT_X = False
BAUD = termios.B9600

# LCD glyph bytes defined in the firmware
PLAY, PAUSE, NOTE, SUN, SPK, BELL, HALF, FULL = "\x01", "\x02", "\x03", "\x04", "\x05", "\x06", "\x07", "\xff"


# glyph sets (5x8 bitmaps) the deck can load into LCD slots 1-7
GLYPHS = {
    "icons": [[0x08,0x0c,0x0e,0x0f,0x0e,0x0c,0x08,0], [0x1b]*7+[0], [0x04,0x06,0x05,0x05,0x04,0x1c,0x1c,0],
              [0x04,0x15,0x0e,0x1b,0x0e,0x15,0x04,0], [0x01,0x03,0x1f,0x1f,0x1f,0x03,0x01,0],
              [0x04,0x0e,0x0e,0x0e,0x1f,0,0x04,0], [0x1c]*7+[0]],
    # bar heights 1..7 for the sound meter (slot n = n rows lit from the bottom)
    "bars": [[0]*(8-n) + [0x0e]*n for n in range(1, 8)],
}


# ---------------- helpers ----------------
def ascii20(text, n=20):
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = " ".join(text.replace("\\", "/").replace("~", "-").split())
    return text[:n] if n else text


def osa(script, timeout=8):
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def bar(frac, width=20):
    frac = max(0.0, min(1.0, frac))
    halves = round(frac * width * 2)
    return (FULL * (halves // 2) + (HALF if halves % 2 else "")).ljust(width)


def marquee(text, width=20, t=None):
    if len(text) <= width:
        return text
    t = time.time() if t is None else t
    span = text + "    "
    off = int(t / 0.35) % len(span)
    return (span + span)[off:off + width]


# ---------------- Mac controls ----------------
class Display:
    def __init__(self):
        try:
            self.cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
            self.cg.CGMainDisplayID.restype = ctypes.c_uint32
            self.ds = ctypes.CDLL("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")
            self.ds.DisplayServicesSetBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
            self.ok = True
        except OSError:
            self.ok = False

    def get(self):
        if not self.ok: return 0.0
        v = ctypes.c_float(); self.ds.DisplayServicesGetBrightness(self.cg.CGMainDisplayID(), ctypes.byref(v)); return v.value

    def set(self, v):
        if self.ok: self.ds.DisplayServicesSetBrightness(self.cg.CGMainDisplayID(), max(0.0, min(1.0, v)))


DISPLAY = Display()


def volume_get():
    out = osa("set s to get volume settings\nreturn (output volume of s as string) & \"|\" & (output muted of s as string)")
    try:
        v, m = out.split("|"); return int(v), m == "true"
    except ValueError:
        return 0, False


def spotify_status():
    out = osa(
        'if application "Spotify" is running then\n tell application "Spotify"\n  set s to player state as string\n'
        '  try\n   return s & "|" & (sound volume as string) & "|" & (name of current track) & "|" & (artist of current track)\n'
        '  on error\n   return s & "|" & (sound volume as string) & "||"\n  end try\n end tell\nend if\nreturn "closed|0||"')
    p = (out + "|||").split("|")
    try: vol = int(float(p[1] or 0))
    except ValueError: vol = 0
    return p[0] or "closed", vol, ascii20(p[2], 0), ascii20(p[3], 0)


def spotify(cmd):
    osa({"toggle": 'tell application "Spotify" to playpause', "next": 'tell application "Spotify" to next track',
         "prev": 'tell application "Spotify" to previous track',
         "up": 'tell application "Spotify" to set sound volume to (((round ((sound volume) / 5)) * 5) + 5)',
         "down": 'tell application "Spotify" to set sound volume to (((round ((sound volume) / 5)) * 5) - 5)'}[cmd])


def running_apps():
    """Open apps via NSWorkspace (about 10x faster than System Events)."""
    out = osa_js('ObjC.import("AppKit");var ws=$.NSWorkspace.sharedWorkspace,apps=ws.runningApplications,'
                 'f=ws.frontmostApplication.bundleIdentifier.js,o=[];for(var i=0;i<apps.count;i++){var a=apps.objectAtIndex(i);'
                 'if(a.activationPolicy==0){var b=a.bundleIdentifier.js||"";o.push(a.localizedName.js+"|"+b+"|"+(b==f));}}o.join("\\n")')
    apps = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 3:
            apps.append((parts[0], parts[1], parts[2] == "true"))
    return sorted(apps, key=lambda a: (not a[2], a[0].lower()))


def osa_js(script, timeout=8):
    try:
        return subprocess.run(["osascript", "-l", "JavaScript", "-e", script], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


# ---------------- background work: slow Mac calls never block the screen ----------------
JOBS = queue.Queue()


def do(fn):
    """Run a Mac action in the background, in order."""
    JOBS.put(fn)


def _worker():
    while True:
        fn = JOBS.get()
        try: fn()
        except Exception as e: print("action failed:", e)


class Cache:
    """Latest known Mac state, refreshed by poller threads; screens only read from here."""
    spotify = ("?", 0, "", "")      # state, volume, track, artist
    spotify_t = 0
    volume = (0, False)
    volume_t = 0
    apps = None
    apps_t = 0
    want = set()                    # which caches the visible screen needs


def _poller():
    while True:
        now = time.time()
        if "spotify" in Cache.want and now - Cache.spotify_t > 1.0:
            Cache.spotify = spotify_status(); Cache.spotify_t = time.time()
        if "volume" in Cache.want and now - Cache.volume_t > 1.0:
            Cache.volume = volume_get(); Cache.volume_t = time.time()
        if "apps" in Cache.want and now - Cache.apps_t > 3.0:
            Cache.apps = running_apps(); Cache.apps_t = time.time()
        time.sleep(0.1)


NOTIF_DIR = os.path.expanduser("~/Library/Group Containers/group.com.apple.usernoted")


def notifications(limit=15):
    """Recent notifications from macOS's own database. Needs Full Disk Access for Terminal."""
    paths = glob.glob(NOTIF_DIR + "/db2/db") + glob.glob(NOTIF_DIR + "/**/db", recursive=True)
    if not os.access(NOTIF_DIR, os.R_OK) or not paths:
        return None
    try:
        con = sqlite3.connect(f"file:{paths[0]}?mode=ro", uri=True)
        rows = con.execute("select a.identifier, r.data, r.delivered_date from record r join app a on a.app_id = r.app_id "
                           "order by r.delivered_date desc limit ?", (limit,)).fetchall()
        con.close()
    except sqlite3.Error:
        return None
    out = []
    for ident, data, when in rows:
        try:
            req = plistlib.loads(data).get("req", {})
        except Exception:
            req = {}
        app = ident.split(".")[-1].capitalize() if ident else "App"
        out.append({"app": ascii20(app, 0), "title": ascii20(req.get("titl", ""), 0), "body": ascii20(req.get("body", ""), 0),
                    "when": (when or 0) + 978307200})
    return out


def ago(ts):
    s = int(time.time() - ts)
    return f"{s // 60}m" if s < 3600 else f"{s // 3600}h" if s < 86400 else f"{s // 86400}d"


# ---------------- screens ----------------
class Screen:
    title = ""
    def lines(self): return ["", "", "", ""]
    def key(self, k, deck): pass
    def tick(self): pass


class ListScreen(Screen):
    def __init__(self): self.i = 0
    def items(self): return []
    def header(self): return self.title
    def lines(self):
        items = self.items()
        if not items: return [self.header(), "", "  (nothing here)", ""]
        self.i = max(0, min(self.i, len(items) - 1))
        top = max(0, min(self.i - 1, len(items) - 3))
        rows = [self.header()]
        for j in range(top, top + 3):
            rows.append(((">" if j == self.i else " ") + items[j])[:20] if j < len(items) else "")
        return rows
    def key(self, k, deck):
        n = len(self.items())
        if k == "U": self.i = (self.i - 1) % max(n, 1)
        elif k == "D": self.i = (self.i + 1) % max(n, 1)
        elif k in "CR" and n: self.select(self.i, deck)
        elif k == "L": deck.back()
    def select(self, i, deck): pass


class Home(ListScreen):
    def __init__(self):
        super().__init__()
        self.entries = [(NOTE + " Spotify", SpotifyScreen), ("# Apps", AppsScreen), (SUN + " Brightness", BrightnessScreen),
                        (SPK + " Volume", VolumeScreen), (BELL + " Notifications", NotificationsScreen), ("* Quick actions", QuickScreen)]
    def header(self): return "DECKY" + time.strftime("%H:%M").rjust(15)
    def items(self): return [e[0] for e in self.entries]
    def select(self, i, deck): deck.push(self.entries[i][1]())
    def key(self, k, deck):
        if k == "L": return
        super().key(k, deck)


class SpotifyScreen(Screen):
    glyphs = "bars"
    needs = "spotify"
    def __init__(self):
        self.toast, self.toast_until = "", 0
        self.hint_until = time.time() + 5
        self.levels = [0.0] * 20
        Cache.spotify_t = 0                       # fresh read on entry
    @property
    def state(self): return Cache.spotify[0]
    def meter(self):
        """Animated 20-band sound profile: bass-heavy, with a ~118 bpm pulse. Flat when paused."""
        import math, random
        t = time.time()
        playing = self.state == "playing"
        beat = max(0.0, math.cos(t * 2 * math.pi * 118 / 60)) ** 6
        out = ""
        for i in range(20):
            if playing:
                shape = 0.85 - 0.45 * (i / 19)                       # louder lows, softer highs
                target = shape * (0.45 + 0.55 * random.random()) + 0.35 * beat * (1 - i / 25)
            else:
                target = 0.0
            self.levels[i] = max(target, self.levels[i] * 0.6)        # fast attack, smooth fall
            h = round(min(1.0, self.levels[i]) * 7)
            out += chr(h) if h else ("_" if not playing else " ")
        return out
    def flash(self, m): self.toast, self.toast_until = m, time.time() + 1.2
    def lines(self):
        state, vol, track, artist = Cache.spotify
        if state == "?":
            return [NOTE + " Spotify", "", "  loading...", ""]
        if state == "closed":
            return [NOTE + " Spotify", "Spotify is closed", "click = open + play", "left = back"]
        top = ("> Playing" if state == "playing" else "|| Paused").ljust(13) + f"vol{round(vol / 5) * 5:3d}"
        now = time.time()
        if now < self.toast_until: foot = self.toast
        elif now < self.hint_until: foot = "<>skip ^v vol o=play"
        else: foot = self.meter()
        return [top, marquee(track), artist[:20], foot]
    def setvol(self, delta):
        state, vol, track, artist = Cache.spotify
        new = max(0, min(100, round(vol / 5) * 5 + delta))
        Cache.spotify = (state, new, track, artist); Cache.spotify_t = time.time() + 1.5   # show now, re-read later
        do(lambda: osa(f'tell application "Spotify" to set sound volume to {new}'))
        self.flash(f"volume {new}")
    def key(self, k, deck):
        state, vol, track, artist = Cache.spotify
        if state == "closed" and k == "C":
            do(lambda: osa('tell application "Spotify" to play')); self.flash("opening Spotify...")
        elif k == "C":
            Cache.spotify = ("paused" if state == "playing" else "playing", vol, track, artist)
            Cache.spotify_t = time.time() + 0.6
            do(lambda: spotify("toggle")); self.flash("play / pause")
        elif k == "R": do(lambda: spotify("next")); self.flash("next >>"); Cache.spotify_t = time.time() - 0.4
        elif k == "L": do(lambda: spotify("prev")); self.flash("<< previous"); Cache.spotify_t = time.time() - 0.4
        elif k == "U": self.setvol(+5)
        elif k == "D": self.setvol(-5)


class AppsScreen(ListScreen):
    title = "# Switch app"
    needs = "apps"
    def __init__(self):
        super().__init__(); self.toast_until = 0; Cache.apps_t = 0
        self.apps = Cache.apps or []
    def items(self):
        if Cache.apps is not None and Cache.apps is not self.apps:      # new list arrived: keep the cursor on the same app
            cur = self.apps[self.i][0] if self.apps and self.i < len(self.apps) else None
            self.apps = Cache.apps
            names = [x[0] for x in self.apps]
            if cur in names: self.i = names.index(cur)
        return [ascii20(x[0], 18) + (" *" if x[2] else "") for x in self.apps]
    def lines(self):
        if not self.apps and Cache.apps is None: return [self.title, "", "  loading...", ""]
        return super().lines()
    def header(self): return "Switched!" if time.time() < self.toast_until else self.title
    def select(self, i, deck):
        name, bid, _ = self.apps[i]
        do(lambda: subprocess.run(["open", "-b", bid] if bid else ["open", "-a", name], capture_output=True))
        self.apps = [(n, b, n == name) for n, b, _ in self.apps]
        self.toast_until = time.time() + 1.2; Cache.apps_t = time.time() - 2


class LevelScreen(Screen):
    step = 0.05
    def get(self): return 0.0
    def set(self, v): pass
    def name(self): return ""
    def hint(self): return "^v adjust  < back"
    def lines(self):
        v = self.get()
        return [self.name().ljust(15) + f"{round(v * 100):4d}%", bar(v), "", self.hint()]
    def key(self, k, deck):
        snap = lambda v: max(0.0, min(1.0, round(v * 20) / 20))     # clean 5% steps
        if k in "UR": self.set(snap(snap(self.get()) + self.step))
        elif k == "D": self.set(snap(snap(self.get()) - self.step))
        elif k == "L": deck.back()
        elif k == "C": self.click()
    def click(self): pass


class BrightnessScreen(LevelScreen):
    def __init__(self): self.saved = None; self.v = DISPLAY.get()
    def name(self): return SUN + " Brightness"
    def get(self): return self.v
    def set(self, v):
        self.v = max(0.0, min(1.0, v)); DISPLAY.set(self.v)
    def hint(self): return "^v adjust o=dim/max"
    def click(self):
        if self.v > 0.25: self.saved = self.v; self.set(0.15)
        else: self.set(self.saved or 1.0)


class VolumeScreen(LevelScreen):
    needs = "volume"
    def __init__(self): Cache.volume_t = 0             # poller fetches the real value right away
    def get(self): return Cache.volume[0] / 100
    def set(self, v):
        new = round(max(0, min(1, v)) * 100)
        Cache.volume = (new, False); Cache.volume_t = time.time() + 1.5
        do(lambda: osa(f"set volume output volume {new} without output muted"))
    def hint(self): return "^v adjust  o=mute"
    def click(self):
        v, m = Cache.volume
        Cache.volume = (v, not m); Cache.volume_t = time.time() + 1.5
        do(lambda: osa(f"set volume output muted {'false' if m else 'true'}"))
    def lines(self):
        v, muted = Cache.volume
        return [(SPK + (" Muted" if muted else " Volume")).ljust(15) + f"{v:4d}%", bar(0 if muted else v / 100), "", self.hint()]


class NotificationsScreen(ListScreen):
    title = BELL + " Notifications"
    def __init__(self):
        super().__init__(); self.data = notifications(); self.last = time.time()
    def tick(self):
        if time.time() - self.last > 5: self.data = notifications(); self.last = time.time()
    def lines(self):
        if self.data is None:
            return [BELL + " Notifications", "Needs Full Disk", "Access for Terminal", "click = open setting"]
        return super().lines()
    def items(self): return [f"{n['app'][:8]}:{n['title'] or n['body']}"[:19] for n in (self.data or [])]
    def key(self, k, deck):
        if self.data is None:
            if k == "C":
                subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
            elif k == "L": deck.back()
            return
        super().key(k, deck)
    def select(self, i, deck): deck.push(NotificationDetail(self.data[i]))


class NotificationDetail(Screen):
    def __init__(self, n):
        self.n, self.off = n, 0
        words, cur, self.wrapped = (n["title"] + " - " + n["body"]).split(), "", []
        for w in words:
            if len(cur) + len(w) + (1 if cur else 0) > 20: self.wrapped.append(cur); cur = w
            else: cur = (cur + " " + w) if cur else w
        if cur: self.wrapped.append(cur)
    def lines(self):
        body = self.wrapped[self.off:self.off + 3]
        return [f"{self.n['app'][:14]} {ago(self.n['when'])}".ljust(20)[:20]] + body + [""] * (3 - len(body))
    def key(self, k, deck):
        if k == "D" and self.off + 3 < len(self.wrapped): self.off += 1
        elif k == "U" and self.off: self.off -= 1
        elif k in "LC": deck.back()


class QuickScreen(ListScreen):
    title = "* Quick actions"
    def __init__(self):
        super().__init__(); self.toast, self.toast_until, self.caf = "", 0, None
    def header(self): return self.toast if time.time() < self.toast_until else self.title
    def items(self):
        return ["Mission Control", "Dark mode on/off", "Screenshot", ("Keep awake: ON" if self.caf else "Keep awake: off"),
                "Sleep display", "Show Desktop folder", "Set up keypad"]
    def select(self, i, deck):
        msg = "Done"
        if i == 0: subprocess.Popen(["open", "-a", "Mission Control"])
        elif i == 1:
            do(lambda: osa('tell application "System Events" to tell appearance preferences to set dark mode to not dark mode')); msg = "Dark mode toggled"
        elif i == 2:
            path = os.path.expanduser(time.strftime("~/Desktop/Deck shot %Y-%m-%d %H.%M.%S.png"))
            do(lambda: subprocess.run(["screencapture", "-x", path])); msg = "Saved to Desktop"
        elif i == 3:
            if self.caf: self.caf.terminate(); self.caf = None; msg = "Normal sleep"
            else: self.caf = subprocess.Popen(["caffeinate", "-d"]); msg = "Mac stays awake"
        elif i == 4: subprocess.run(["pmset", "displaysleepnow"]); msg = "Display asleep"
        elif i == 5: subprocess.Popen(["open", os.path.expanduser("~/Desktop")]); msg = "Opened Desktop"
        elif i == 6: deck.push(KeypadSetup()); return
        self.toast, self.toast_until = msg[:20], time.time() + 1.5


KEYMAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keypad.json")
KEY_ORDER = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"]


def load_keymap():
    try:
        import json
        with open(KEYMAP_FILE) as f: return json.load(f)
    except (OSError, ValueError):
        return {}


class KeypadSetup(Screen):
    """Press each key once; learns which wire pair is which key."""
    def __init__(self): self.map, self.i, self.done_at = {}, 0, 0
    def lines(self):
        if self.i >= len(KEY_ORDER):
            return ["Keypad setup", "All 12 keys learned", "Saved. Keypad ready.", "any key = back"]
        return ["Keypad setup " + f"{self.i + 1:2d}/12", "", "  Press key:  " + KEY_ORDER[self.i], "joystick < = cancel"]
    def raw(self, pair, deck):
        if self.i >= len(KEY_ORDER): deck.back(); return
        if pair in self.map: return               # same wires as an earlier key: ignore
        self.map[pair] = KEY_ORDER[self.i]; self.i += 1
        if self.i == len(KEY_ORDER):
            import json
            with open(KEYMAP_FILE, "w") as f: json.dump(self.map, f, indent=1)
            deck.keymap = dict(self.map)
    def key(self, k, deck):
        if k in "LH" or self.i >= len(KEY_ORDER): deck.back()


# ---------------- deck engine ----------------
class Deck:
    def __init__(self, fd):
        self.fd, self.stack, self.sent = fd, [Home()], [None] * 4
        self.lock = threading.Lock()
        self.banner, self.banner_until, self.seen_notif = None, 0, None
        self.glyphset = None
        self.keymap = load_keymap()

    def write(self, s):
        with self.lock:
            os.write(self.fd, s.encode("latin-1", "replace"))

    def push(self, scr): self.stack.append(scr)
    def back(self):
        if len(self.stack) > 1: self.stack.pop()
    def home(self): self.stack = self.stack[:1]

    def load_glyphs(self, name):
        if name == self.glyphset: return
        self.glyphset = name
        for slot, rows in enumerate(GLYPHS[name], start=1):
            self.write(f"@G{slot}" + "".join(f"{b:02x}" for b in rows) + "\n")
        self.sent = [None] * 4      # glyphs changed meaning: redraw everything

    def render(self, force=False):
        scr = self.stack[-1]
        Cache.want = {getattr(scr, "needs", None)} - {None}
        self.load_glyphs(getattr(scr, "glyphs", "icons") if time.time() >= self.banner_until else "icons")
        try:
            scr.tick(); rows = scr.lines()
        except Exception as e:
            rows = ["Error", ascii20(str(e)), "", "hold = home"]
        if time.time() < self.banner_until and self.banner:
            rows = [BELL + " " + self.banner["app"][:17], self.banner["title"][:20], self.banner["body"][:20], self.banner["body"][20:40]]
        for r in range(4):
            line = (rows[r] if r < len(rows) else "")[:20]
            if force or line != self.sent[r]:
                self.write(f"@L{r}{line}\n"); self.sent[r] = line

    def on_key(self, k):
        if k in "UD" and INVERT_Y: k = "D" if k == "U" else "U"
        if k in "LR" and INVERT_X: k = "R" if k == "L" else "L"
        if time.time() < self.banner_until: self.banner_until = 0; return     # any key dismisses a banner
        if k == "H": self.home(); return
        keymap = {"2": "U", "8": "D", "4": "L", "6": "R", "5": "C", "#": "H", "*": "L"}
        k = keymap.get(k, k)
        if k == "H": self.home(); return
        self.stack[-1].key(k, self)

    def on_raw(self, pair):
        print(f"keypad wires D{pair[0]}-D{pair[1]} -> {self.keymap.get(pair, '?')}")
        scr = self.stack[-1]
        if isinstance(scr, KeypadSetup): scr.raw(pair, self); return
        key = self.keymap.get(pair)
        if not key:
            if not self.keymap: self.push(KeypadSetup())      # first ever press: start setup
            return
        if time.time() < self.banner_until: self.banner_until = 0; return
        hot = {"1": lambda: do(lambda: spotify("toggle")), "3": lambda: do(lambda: spotify("next")),
               "7": lambda: do(lambda: osa("set volume output muted (not (output muted of (get volume settings)))")),
               "9": lambda: subprocess.Popen(["open", "-a", "Mission Control"]),
               "0": lambda: self.push(SpotifyScreen()) if not isinstance(scr, SpotifyScreen) else None}
        if key in hot: hot[key](); return
        nav = {"2": "U", "8": "D", "4": "L", "6": "R", "5": "C", "*": "L", "#": "H"}[key]
        if nav == "H": self.home(); return
        if key == "*": self.back(); return
        scr.key(nav, self)

    def watch_notifications(self):
        while True:
            data = notifications(3)
            if data:
                newest = data[0]
                key = (newest["app"], newest["title"], newest["when"])
                if self.seen_notif is not None and key != self.seen_notif and time.time() - newest["when"] < 60:
                    self.banner, self.banner_until = newest, time.time() + 5
                self.seen_notif = key
            time.sleep(3)


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.wchusbserial*"))
    return ports[0] if ports else None


def open_serial(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0; a[1] = 0; a[3] = 0; a[2] |= termios.CLOCAL | termios.CREAD; a[4] = a[5] = BAUD
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def run_once(port):
    fd = open_serial(port)
    deck = Deck(fd)
    print(f"Decky connected on {port}. Ctrl+C to quit.")
    threading.Thread(target=deck.watch_notifications, daemon=True).start()
    buf, last_render, last_ping, last_rx = b"", 0, 0, time.time()
    while True:
        r, _, _ = select.select([fd], [], [], 0.05)
        if time.time() - last_rx > 15:
            os.close(fd); raise OSError("no signal from the Uno for 15 s")
        if r:
            chunk = os.read(fd, 256)
            if not chunk: raise OSError("disconnected")
            buf += chunk; last_rx = time.time()
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode(errors="ignore").strip()
                if line == "@HELLO":
                    deck.sent = [None] * 4; deck.glyphset = None; deck.render(force=True)
                elif line.startswith("@X") and len(line) >= 4:
                    deck.on_raw(line[2:]); deck.render()
                elif line.startswith("@K") and len(line) >= 3:
                    deck.on_key(line[2]); deck.render()
        now = time.time()
        fast = isinstance(deck.stack[-1], SpotifyScreen)
        if now - last_render > (0.13 if fast else 0.35): deck.render(); last_render = now
        if now - last_ping > 3: deck.write("@P\n"); last_ping = now


def prime_permissions():
    """Ask macOS for every permission up front, once. After approval these never prompt again."""
    osa('tell application "System Events" to get name of first application process whose frontmost is true')   # Apps + dark mode
    osa('tell application "System Events" to tell appearance preferences to get dark mode')
    osa('if application "Spotify" is running then tell application "Spotify" to get sound volume')              # Spotify (if open)
    notifications(1)                                                                                             # Full Disk Access check


def main():
    threading.Thread(target=prime_permissions, daemon=True).start()
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_poller, daemon=True).start()
    while True:
        port = find_port()
        if not port:
            print("Waiting for the Arduino to be plugged in..."); time.sleep(3); continue
        try:
            run_once(port)
        except KeyboardInterrupt:
            print("\nDeck closed."); return
        except OSError as e:
            print(f"Lost the Arduino ({e}). Reconnecting...")
            time.sleep(2)


if __name__ == "__main__":
    main()
