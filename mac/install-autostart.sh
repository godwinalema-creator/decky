#!/bin/bash
# Start Decky automatically at login (macOS LaunchAgent). Run again to reinstall; pass "remove" to uninstall.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/local.decky.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
if [ "$1" = "remove" ]; then rm -f "$PLIST"; echo "Decky autostart removed."; exit 0; fi
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.decky</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>-u</string><string>$DIR/deck.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$DIR/deck.log</string>
  <key>StandardErrorPath</key><string>$DIR/deck.log</string>
</dict></plist>
PL
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Decky will now start at login. Log: $DIR/deck.log"
