#!/usr/bin/env python3
"""Builds docs/Decky-Manual.pdf from the source files, so the manual always matches the code.

  python3 docs/build_docs.py

Needs Google Chrome (used headless to print the PDF).
"""
import html, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def code(rel):
    return f'<h3 class="file">{rel}</h3><pre><code>{html.escape(read(rel))}</code></pre>'


ARCH = """
<svg viewBox="0 0 860 300" xmlns="http://www.w3.org/2000/svg" class="fig">
 <style>.b{fill:#fff;stroke:#9fb0aa;stroke-width:1.5}.t{font:600 14px Helvetica,Arial,sans-serif;fill:#17211d}.s{font:11px Menlo,monospace;fill:#5a6862}.a{stroke:#2463d6;stroke-width:2.5;fill:none;marker-end:url(#h)}.r{stroke:#cf5a22;stroke-width:2.5;fill:none;marker-end:url(#h2)}</style>
 <defs><marker id="h" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 z" fill="#2463d6"/></marker>
 <marker id="h2" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 z" fill="#cf5a22"/></marker></defs>
 <rect class="b" x="10" y="40" width="150" height="90" rx="8"/><text class="t" x="24" y="66">Joystick</text><text class="s" x="24" y="86">A0 A1 A2</text>
 <rect class="b" x="10" y="160" width="150" height="90" rx="8"/><text class="t" x="24" y="186">3x4 Keypad</text><text class="s" x="24" y="206">D2..D8, any order</text><text class="s" x="24" y="222">(learned once)</text>
 <rect class="b" x="230" y="70" width="190" height="150" rx="8" style="fill:#e6f3f8"/><text class="t" x="246" y="96">Arduino Uno</text><text class="s" x="246" y="118">deck.ino</text><text class="s" x="246" y="140">draws lines</text><text class="s" x="246" y="158">reports input</text><text class="s" x="246" y="176">no menus/logic</text>
 <rect class="b" x="230" y="250" width="190" height="42" rx="8"/><text class="t" x="246" y="276">20x4 LCD (I2C)</text>
 <rect class="b" x="500" y="70" width="170" height="150" rx="8" style="fill:#fff6ef"/><text class="t" x="516" y="96">Mac: deck.py</text><text class="s" x="516" y="118">menus, screens</text><text class="s" x="516" y="136">key handling</text><text class="s" x="516" y="154">renders 4 lines</text><text class="s" x="516" y="172">auto-reconnect</text>
 <rect class="b" x="720" y="20" width="130" height="260" rx="8"/><text class="t" x="732" y="44">macOS</text>
 <text class="s" x="732" y="70">Spotify</text><text class="s" x="732" y="84">(AppleScript)</text>
 <text class="s" x="732" y="110">System Events</text><text class="s" x="732" y="124">(apps, dark)</text>
 <text class="s" x="732" y="150">DisplayServices</text><text class="s" x="732" y="164">(brightness)</text>
 <text class="s" x="732" y="190">volume</text>
 <text class="s" x="732" y="216">notification DB</text>
 <text class="s" x="732" y="244">screencapture</text><text class="s" x="732" y="258">caffeinate, pmset</text>
 <path class="a" d="M160,85 H230"/><path class="a" d="M160,205 H195 V185 H230"/>
 <path class="a" d="M420,120 H500"/><text class="s" x="428" y="112">@K / @X / @A</text>
 <path class="r" d="M500,170 H420"/><text class="s" x="428" y="190">@L / @G / @P</text>
 <path class="r" d="M325,220 V250"/>
 <path class="a" d="M670,145 H720"/>
 <text class="s" x="440" y="245">USB serial 9600</text>
</svg>"""


def build():
    svg = read("docs/wiring.svg")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Decky manual</title>
<style>
@page {{ size: A4; margin: 16mm 14mm; }}
body {{ font: 11pt/1.5 Helvetica, Arial, sans-serif; color: #17211d; }}
h1 {{ font-size: 34pt; margin: 0 0 4px; letter-spacing: -.5px; }}
h2 {{ font-size: 17pt; margin: 26px 0 8px; border-bottom: 2px solid #17211d; padding-bottom: 4px; page-break-after: avoid; }}
h3 {{ font-size: 12.5pt; margin: 18px 0 6px; page-break-after: avoid; }}
h3.file {{ font-family: Menlo, monospace; font-size: 10.5pt; background: #eef2f0; padding: 6px 8px; border-radius: 4px; }}
p, li {{ max-width: 170mm; }}
.lede {{ font-size: 13pt; color: #3d4a45; }}
table {{ border-collapse: collapse; width: 100%; margin: 6px 0 12px; font-size: 10pt; page-break-inside: avoid; }}
th, td {{ text-align: left; border-bottom: 1px solid #cbd5d1; padding: 5px 6px; vertical-align: top; }}
th {{ background: #eef2f0; }}
td code, li code, p code {{ font-family: Menlo, monospace; font-size: 9.5pt; background: #eef2f0; padding: 0 3px; border-radius: 3px; }}
pre {{ font: 7.4pt/1.35 Menlo, monospace; white-space: pre-wrap; word-break: break-word; background: #fafbfa; border: 1px solid #dfe5e2; padding: 8px; border-radius: 4px; }}
.fig {{ width: 100%; height: auto; border: 1px solid #dfe5e2; border-radius: 6px; page-break-inside: avoid; }}
.cover {{ height: 245mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }}
.lcd {{ font: 15pt/1.25 Menlo, monospace; background: #1f3fb0; color: #d7e3ff; padding: 14px 18px; border-radius: 6px; width: max-content; margin: 22px 0; white-space: pre; }}
.break {{ page-break-before: always; }}
.note {{ background: #fff6ef; border-left: 4px solid #cf5a22; padding: 8px 12px; font-size: 10pt; }}
</style></head><body>

<section class="cover">
  <h1>Decky</h1>
  <p class="lede">An Arduino Uno, a 20&times;4 LCD, a joystick and a keypad that control your Mac:
  Spotify, app switching, brightness, volume, notifications and quick actions.</p>
  <div class="lcd">DECKY          04:40
&gt;&#9834; Spotify
 # Apps
 &#9788; Brightness</div>
  <p>Contents: 1 Parts &middot; 2 Wiring &middot; 3 How it works &middot; 4 Install &middot; 5 Controls &middot; 6 Troubleshooting &middot; 7 Source code</p>
</section>

<h2>1. Parts</h2>
<table><tr><th>Part</th><th>Notes</th></tr>
<tr><td>Arduino Uno (or clone with CH340 USB)</td><td>Powered by the Mac's USB, which also carries data</td></tr>
<tr><td>20&times;4 character LCD with PCF8574 I2C backpack</td><td>Address 0x27 or 0x3F, found automatically. Blue knob = contrast</td></tr>
<tr><td>Analog joystick module (VRx, VRy, SW)</td><td>Main control</td></tr>
<tr><td>3&times;4 membrane keypad (7-pin ribbon)</td><td>Optional. Wire order does not matter: Decky learns it</td></tr>
<tr><td>Breadboard + jumper wires</td><td>Male-to-male and male-to-female</td></tr></table>

<h2>2. Wiring</h2>
<p>Unplug USB before wiring. Run the Uno's <b>5V</b> to the breadboard red (+) rail and <b>GND</b> to the blue (&minus;) rail; every +5V / GND tag below goes to those rails.
Long breadboards split their rails in the middle; bridge the gap if a part sits on the far half.</p>
<div class="fig" style="border:none">{svg}</div>
<table><tr><th>Part</th><th>Pin</th><th>Uno</th></tr>
<tr><td rowspan="4">LCD backpack</td><td>GND</td><td>&minus; rail</td></tr><tr><td>VCC</td><td>+ rail</td></tr><tr><td>SDA</td><td>A4</td></tr><tr><td>SCL</td><td>A5</td></tr>
<tr><td rowspan="5">Joystick</td><td>GND</td><td>&minus; rail</td></tr><tr><td>+5V</td><td>+ rail</td></tr><tr><td>VRx</td><td>A0</td></tr><tr><td>VRy</td><td>A1</td></tr><tr><td>SW</td><td>A2</td></tr>
<tr><td>Keypad</td><td>7 ribbon pins</td><td>D8, D7, D6, D5, D4, D3, D2 (any order works)</td></tr></table>
<p class="note">Power budget is about 35&nbsp;mA total, well within USB's 500&nbsp;mA. D9&ndash;D13 and A3 are free for future parts.</p>

<h2 class="break">3. How it works</h2>
<p>The Uno is a <b>thin client</b>: it only draws the four lines the Mac sends and reports joystick and keypad input.
Every menu, screen and action lives in <code>mac/deck.py</code>, so changing Decky never needs a reflash.</p>
{ARCH}
<h3>Serial protocol (9600 baud, one message per line)</h3>
<table><tr><th>Direction</th><th>Message</th><th>Meaning</th></tr>
<tr><td>Mac &rarr; Uno</td><td><code>@L&lt;row&gt;&lt;text&gt;</code></td><td>Draw row 0&ndash;3 (padded to 20 chars). Bytes 1&ndash;7 = custom glyphs, 255 = full block</td></tr>
<tr><td>Mac &rarr; Uno</td><td><code>@G&lt;slot&gt;&lt;16 hex&gt;</code></td><td>Redefine custom glyph 1&ndash;7 (icons vs sound-meter bars)</td></tr>
<tr><td>Mac &rarr; Uno</td><td><code>@P</code></td><td>Heartbeat. No Mac data for 7 s &rArr; Uno shows "waiting for Mac"</td></tr>
<tr><td>Uno &rarr; Mac</td><td><code>@HELLO</code></td><td>Booted / waiting: Mac redraws everything</td></tr>
<tr><td>Uno &rarr; Mac</td><td><code>@K&lt;U|D|L|R|C|H&gt;</code></td><td>Joystick: one event per push; C = click, H = hold 0.7 s</td></tr>
<tr><td>Uno &rarr; Mac</td><td><code>@X&lt;a&gt;&lt;b&gt;</code></td><td>Keypad press joining pins Da and Db; mapped to keys via <code>keypad.json</code></td></tr>
<tr><td>Uno &rarr; Mac</td><td><code>@A</code></td><td>Alive every 4 s. Silence for 15 s &rArr; Mac reconnects</td></tr></table>

<h2>4. Install</h2>
<ol>
<li><b>Flash the firmware.</b> Arduino IDE: install the <i>LiquidCrystal I2C</i> library, open <code>firmware/deck/deck.ino</code>, upload. Or with arduino-cli:<br>
<code>arduino-cli lib install "LiquidCrystal I2C"</code><br><code>arduino-cli compile -u -b arduino:avr:uno -p /dev/cu.usbserial-XXXX firmware/deck</code></li>
<li><b>Run the Mac side</b> (Python 3, standard library only): <code>python3 mac/deck.py</code></li>
<li><b>Start at login</b> (optional): <code>mac/install-autostart.sh</code> &nbsp;&middot;&nbsp; remove with <code>mac/install-autostart.sh remove</code></li>
<li><b>Approve macOS prompts once</b>: "python3 wants to control System Events / Spotify" &rarr; OK.
For notifications, add <code>/usr/bin/python3</code> under Privacy &amp; Security &rarr; Full Disk Access.</li>
<li><b>Teach the keypad</b> (first key press, or Quick actions &rarr; Set up keypad): press 1 2 3 &hellip; * 0 # as the LCD asks. Saved to <code>mac/keypad.json</code>.</li>
</ol>
<p class="note">Close the Arduino IDE Serial Monitor while Decky runs, and stop Decky (<code>launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/local.decky.plist</code>) before flashing: only one program can hold the USB port.</p>

<h2 class="break">5. Controls</h2>
<h3>Joystick</h3>
<table><tr><th>Move</th><th>Action</th></tr><tr><td>Up / Down</td><td>Move one step per push (return to centre for the next)</td></tr>
<tr><td>Right or click</td><td>Open / select</td></tr><tr><td>Left</td><td>Back</td></tr><tr><td>Hold click 0.7 s</td><td>Home</td></tr></table>
<h3>Keypad</h3>
<table><tr><th>Key</th><th>Action</th><th>Key</th><th>Action</th><th>Key</th><th>Action</th></tr>
<tr><td>1</td><td>Spotify play/pause (anywhere)</td><td>2</td><td>Up</td><td>3</td><td>Next track (anywhere)</td></tr>
<tr><td>4</td><td>Left / back</td><td>5</td><td>Select</td><td>6</td><td>Right</td></tr>
<tr><td>7</td><td>Mute Mac (anywhere)</td><td>8</td><td>Down</td><td>9</td><td>Mission Control (anywhere)</td></tr>
<tr><td>*</td><td>Back</td><td>0</td><td>Open Spotify screen</td><td>#</td><td>Home</td></tr></table>
<h3>Screens</h3>
<table><tr><th>Screen</th><th>Up / Down</th><th>Left / Right</th><th>Click</th></tr>
<tr><td>Spotify</td><td>Volume &plusmn;5%</td><td>Previous / next track</td><td>Play / pause (opens Spotify if closed)</td></tr>
<tr><td>Apps</td><td>Move through open apps</td><td>Back</td><td>Switch to app</td></tr>
<tr><td>Brightness</td><td>&plusmn;5%</td><td>Right = +5%</td><td>Dim / full</td></tr>
<tr><td>Volume</td><td>&plusmn;5%</td><td>Right = +5%</td><td>Mute</td></tr>
<tr><td>Notifications</td><td>Scroll</td><td>Back</td><td>Read full message</td></tr>
<tr><td>Quick actions</td><td>Move</td><td>Back</td><td>Run: Mission Control, dark mode, screenshot, keep awake, sleep display, open Desktop, set up keypad</td></tr></table>
<p>Spotify shows control hints for 5 seconds, then an animated sound meter on the bottom row (a visual effect; Spotify does not expose live audio levels). New notifications pop up as a banner on any screen.</p>

<h2>6. Troubleshooting</h2>
<table><tr><th>Symptom</th><th>Fix</th></tr>
<tr><td>LCD backlight on, no text</td><td>Turn the blue contrast knob on the backpack</td></tr>
<tr><td>Garbled characters</td><td>Unplug USB 5 s and replug; re-seat SDA (A4) and SCL (A5)</td></tr>
<tr><td>"waiting for Mac..."</td><td>deck.py is not running, or another program holds the port</td></tr>
<tr><td>Directions reversed</td><td>Set <code>INVERT_X</code> / <code>INVERT_Y</code> at the top of <code>mac/deck.py</code></td></tr>
<tr><td>Some keypad keys dead</td><td>Push the jumpers fully into the ribbon socket; check all 7 reach D2&ndash;D8; redo keypad setup</td></tr>
<tr><td>Notifications: "Needs Full Disk Access"</td><td>Add <code>/usr/bin/python3</code> in Privacy &amp; Security &rarr; Full Disk Access</td></tr>
<tr><td>Anything else</td><td>Read <code>mac/deck.log</code> when running at login</td></tr></table>

<h2 class="break">7. Source code</h2>
{code("firmware/deck/deck.ino")}
{code("mac/deck.py")}
{code("mac/install-autostart.sh")}
</body></html>"""
    out_html = os.path.join(DOCS, "manual.html")
    with open(out_html, "w") as f:
        f.write(page)
    pdf = os.path.join(DOCS, "Decky-Manual.pdf")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", "file://" + out_html],
                   check=True, capture_output=True)
    print("wrote", pdf)


if __name__ == "__main__":
    build()
