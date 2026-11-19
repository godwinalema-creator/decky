# JARVIS (legacy)

The earlier version of this project: an offline assistant that lives on the Uno (keyword skills, an order-5 character Markov text model, EEPROM notes, timer, games) with a robot face on the LCD.
`bridge/jarvis_bridge.py` connects it to Claude through the Claude Code CLI for real answers, and to Spotify.
Sketch: `firmware/juno/juno.ino` (set `USE_I2C_LCD`, `HAS_STEPPER`, `HAS_SONAR` at the top).
