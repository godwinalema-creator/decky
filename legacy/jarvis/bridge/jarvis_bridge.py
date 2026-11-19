#!/usr/bin/env python3
"""
JARVIS bridge: gives the Arduino a real brain while it's plugged into this Mac.

  python3 ~/juno/bridge/jarvis_bridge.py            # auto-finds the Uno, uses Claude
  python3 ~/juno/bridge/jarvis_bridge.py --ollama llama3.2:3b   # use a local Ollama model instead

The Uno answers what it can by itself (timer, maths, notes, games). Anything else it
sends here as "@ASK <question>"; this script asks the AI and replies "@ANS <answer>".
It also syncs the Uno's clock and sends a heartbeat so the LCD shows "AI on".
You can type messages to JARVIS in this terminal too. Ctrl+C to quit.
Spotify: type "music" on JARVIS, then use the joystick (first time, macOS asks to allow control).

Standard library only: no pip installs.
"""
import argparse, glob, json, os, select, subprocess, sys, tempfile, termios, threading, time, unicodedata, urllib.request

PERSONA = (
    "You are J.A.R.V.I.S., a calm, witty British AI butler. You live inside an Arduino Uno and "
    "speak through a 20x4 character LCD, so every reply must be plain ASCII, one paragraph, "
    "at most 60 characters (about 10 words), no markdown, no emoji, no lists. Address the user as 'sir'. "
    "Answer the question directly in as few words as possible; add wit only if it fits. "
    "Typed input comes from a phone-style keypad, so forgive typos and missing punctuation."
)
MAX_CHARS = 70
HISTORY_TURNS = 6


SPOTIFY = {
    "play":    'tell application "Spotify" to play',
    "pause":   'tell application "Spotify" to pause',
    "toggle":  'tell application "Spotify" to playpause',
    "next":    'tell application "Spotify" to next track',
    "prev":    'tell application "Spotify" to previous track',
    "volup":   'tell application "Spotify" to set sound volume to ((sound volume) + 10)',
    "voldown": 'tell application "Spotify" to set sound volume to ((sound volume) - 10)',
}
STATUS = (
    'if application "Spotify" is running then\n'
    '  tell application "Spotify"\n'
    '    set s to player state as string\n'
    '    try\n'
    '      return s & "|" & (sound volume as string) & "|" & (name of current track) & "|" & (artist of current track)\n'
    '    on error\n'
    '      return s & "|" & (sound volume as string) & "||"\n'
    '    end try\n'
    '  end tell\n'
    'end if\n'
    'return "closed|0||"'
)


def osa(script):
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        print("  [spotify] no response - is macOS asking to allow Terminal to control Spotify? Click OK.", file=sys.stderr)
        return ""
    if r.returncode != 0 and "not allowed" in r.stderr.lower():
        print("  [spotify] macOS blocked control. Allow it in System Settings > Privacy & Security > Automation.", file=sys.stderr)
    return r.stdout.strip()


def ascii_field(text, n):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(text.replace("|", "/").replace("\\", "/").replace("~", "-").split())[:n]


def spotify_status():
    parts = (osa(STATUS) + "|||").split("|")
    state, vol, track, artist = parts[0], parts[1], parts[2], parts[3]
    code = {"playing": "p", "paused": "s", "stopped": "s"}.get(state, "x")
    try:
        vol = int(float(vol or 0))
    except ValueError:
        vol = 0
    return f"@NOW {code}|{vol}|{ascii_field(track, 40)}|{ascii_field(artist, 30)}"


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.wchusbserial*"))
    if not ports:
        sys.exit("No Arduino found. Plug in the Uno and close the Arduino IDE Serial Monitor.")
    return ports[0]


def open_serial(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0; a[1] = 0; a[3] = 0
    a[2] |= termios.CLOCAL | termios.CREAD
    a[4] = a[5] = termios.B9600
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def to_lcd(text):
    """Make any AI reply safe for an HD44780: ASCII, single line, length-capped at a word boundary."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = " ".join(text.replace("*", "").replace("#", "").replace("`", "").split())
    text = text.replace("\\", "/").replace("~", "-")      # these two show as other glyphs on the LCD
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS].rsplit(" ", 1)[0]
        text = cut.rstrip(",;:") + "..."
    return text or "No answer, sir."


class Brain:
    def __init__(self, ollama_model=None):
        self.ollama = ollama_model
        self.history = []          # (question, answer)
        self.workdir = tempfile.mkdtemp(prefix="jarvis-")   # neutral cwd: no project context leaks in

    def context(self):
        now = time.strftime("%A %d %B %Y, %H:%M")
        convo = "".join(f"User: {q}\nJARVIS: {a}\n" for q, a in self.history[-HISTORY_TURNS:])
        return f"Current local date and time: {now}.\n" + (f"Recent conversation:\n{convo}" if convo else "")

    def ask(self, question):
        prompt = self.context() + f"\nUser: {question}\nReply as JARVIS:"
        try:
            if self.ollama:
                body = json.dumps({"model": self.ollama, "system": PERSONA, "prompt": prompt, "stream": False}).encode()
                req = urllib.request.Request("http://localhost:11434/api/generate", body, {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    answer = json.loads(r.read())["response"]
            else:
                res = subprocess.run(
                    ["claude", "-p", "--model", "haiku", "--tools", "", "--system-prompt", PERSONA, prompt],
                    capture_output=True, text=True, timeout=25, cwd=self.workdir)
                answer = res.stdout.strip()
                if res.returncode != 0 or not answer:
                    raise RuntimeError(res.stderr.strip()[:200] or "empty reply")
        except Exception as e:
            print(f"  [brain error] {e}", file=sys.stderr)
            return "Brain link failed, sir."
        answer = to_lcd(answer)
        self.history.append((question, answer))
        return answer


def main():
    ap = argparse.ArgumentParser(description="Connect the Arduino JARVIS to a real AI.")
    ap.add_argument("--port", help="serial port (default: auto-detect)")
    ap.add_argument("--ollama", metavar="MODEL", help="use a local Ollama model instead of Claude")
    args = ap.parse_args()

    port = args.port or find_port()
    try:
        fd = open_serial(port)
    except OSError as e:
        sys.exit(f"Can't open {port}: {e}. Close the Arduino IDE Serial Monitor and try again.")
    brain = Brain(args.ollama)
    lock = threading.Lock()

    def send(line):
        with lock:
            os.write(fd, (line + "\n").encode("ascii", "ignore"))

    print(f"JARVIS bridge on {port} - brain: {'Ollama ' + args.ollama if args.ollama else 'Claude (haiku)'}")
    print("Waiting for the Uno to boot...")
    time.sleep(3)   # opening the port resets the Uno

    def hello():
        send("@HELLO")
        send("@TIME " + time.strftime("%H%M"))

    hello()
    print("Linked. The LCD status line should now say 'AI on'. Type here to talk, Ctrl+C to quit.\n")

    def heartbeat():
        n = 0
        while True:
            time.sleep(5)
            n += 1
            send("@TIME " + time.strftime("%H%M") if n % 12 == 0 else "@PING")

    def answer(q):
        print(f"  [asking AI] {q}")
        a = brain.ask(q)
        send("@ANS " + a)

    def keyboard():
        for line in sys.stdin:
            line = line.strip()
            if line:
                send(line[:60])

    threading.Thread(target=heartbeat, daemon=True).start()
    threading.Thread(target=keyboard, daemon=True).start()

    buf = b""
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            try:
                buf += os.read(fd, 512)
            except BlockingIOError:
                continue
            except OSError:
                print("\nUno disconnected. Bye, sir.")
                return
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode(errors="replace").strip()
                if line.startswith("@SP "):
                    cmd = line[4:].strip()
                    def run_sp(cmd=cmd):
                        if cmd in SPOTIFY:
                            osa(SPOTIFY[cmd])
                            print(f"  [spotify] {cmd}")
                            time.sleep(0.4)
                        send(spotify_status())
                    threading.Thread(target=run_sp, daemon=True).start()
                elif line.startswith("@ASK "):
                    threading.Thread(target=answer, args=(line[5:],), daemon=True).start()
                elif line.startswith("JARVIS online"):
                    hello()        # Uno rebooted: re-link
                    print(line)
                elif line:
                    print(line)
    except KeyboardInterrupt:
        print("\nBridge closed. JARVIS is back on his own 2 KB.")


if __name__ == "__main__":
    main()
