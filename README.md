# Decky

An Arduino Uno with a 20×4 LCD, a joystick and a keypad that controls your Mac: **Spotify, app switching, brightness, volume, notifications and quick actions**.

```
DECKY          04:40
>♪ Spotify
 # Apps
 ☼ Brightness
```

📘 **Full manual (wiring, diagrams, controls, source): [docs/Decky-Manual.pdf](docs/Decky-Manual.pdf)**

## How it works

The Uno is a thin client: it draws the 4 lines the Mac sends and reports joystick/keypad input over USB serial.
All menus and actions live in `mac/deck.py` (Python 3, standard library only), so changing Decky never needs a reflash.

```
Joystick ─┐                       @K/@X/@A                macOS
Keypad  ──┼─► Arduino Uno ◄────── USB 9600 ──────► deck.py ──► Spotify · System Events
LCD ◄─────┘   (deck.ino)          @L/@G/@P                  brightness · volume · notifications
```

## Wiring

![Wiring](docs/wiring.svg)

| Part | Pin | Uno |
|---|---|---|
| LCD I2C backpack | GND / VCC / SDA / SCL | − rail / + rail / A4 / A5 |
| Joystick | GND / +5V / VRx / VRy / SW | − rail / + rail / A0 / A1 / A2 |
| 3×4 keypad (optional) | 7 ribbon pins | D2–D8, any order (learned once) |

Uno 5V → breadboard + rail, Uno GND → − rail. Total draw ≈ 35 mA from USB.

## Install

1. **Flash** `firmware/deck/deck.ino` (needs the *LiquidCrystal I2C* library):
   ```
   arduino-cli lib install "LiquidCrystal I2C"
   arduino-cli compile -u -b arduino:avr:uno -p /dev/cu.usbserial-XXXX firmware/deck
   ```
2. **Run** `python3 mac/deck.py`
3. **Start at login** (optional): `mac/install-autostart.sh` — remove with `mac/install-autostart.sh remove`
4. **Approve** the one-time macOS prompts (python3 → System Events / Spotify). For notifications, add `/usr/bin/python3` to Full Disk Access.
5. **Teach the keypad**: press any key, then 1 2 3 … * 0 # as the LCD asks (saved to `mac/keypad.json`).

## Controls

**Joystick:** ↑↓ move (one step per push) · → or click select · ← back · hold click = home

**Keypad:** `2 4 6 8` arrows · `5` select · `*` back · `#` home · `1` play/pause · `3` next track · `7` mute · `9` Mission Control · `0` Spotify

| Screen | ↑ / ↓ | ← / → | Click |
|---|---|---|---|
| Spotify | volume ±5% | prev / next track | play / pause |
| Apps | move | back | switch to app |
| Brightness | ±5% | → +5% | dim / full |
| Volume | ±5% | → +5% | mute |
| Notifications | scroll | back | read message |
| Quick actions | move | back | Mission Control, dark mode, screenshot, keep awake, sleep display, open Desktop, keypad setup |

Spotify shows hints for 5 s, then an animated sound meter (visual effect — Spotify doesn't expose live audio levels).

## Repo layout

```
firmware/deck/deck.ino      Uno firmware (thin client)
mac/deck.py                 Mac controller: menus, screens, actions
mac/install-autostart.sh    LaunchAgent installer
mac/keypad.json             learned keypad wiring (redo via Quick actions → Set up keypad)
docs/Decky-Manual.pdf       full manual · build with: python3 docs/build_docs.py
docs/wiring.svg             wiring schematic
legacy/jarvis/              earlier version: offline LCD assistant + Claude bridge
```

## License

MIT
