/*
  DECKY — Uno firmware (thin client).
  The Mac (deck.py) decides everything; the Uno just draws lines and reports input.

  Mac -> Uno:  "@L<row><text>"  draw row 0-3 (text padded to 20)
               "@P"             heartbeat
               "@G<slot><16hex>" redefine custom glyph 1-7
  Uno -> Mac:  "@HELLO"         on boot
               "@K<c>"          joystick: U D L R, C click, H hold
               "@X<a><b>"       keypad press connecting pins Da and Db
               "@A"             alive, every 4 s

  Wiring: LCD I2C backpack SDA A4, SCL A5. Joystick VRx A0, VRy A1, SW A2.
          Keypad (optional) pins 1-7 -> D8..D2.
*/
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

LiquidCrystal_I2C* lcdp;
#define lcd (*lcdp)

const byte JX = A0, JY = A1, JSW = A2;
// Keypad: no fixed pinout. Every press reports which two of D2..D8 it connects ("@X<a><b>"),
// and the Mac maps pairs to keys after a one-time calibration.
const byte KP_FIRST = 2, KP_LAST = 8;

// glyphs the Mac can use as bytes 1-7
byte gPlay[8]  = {0b01000,0b01100,0b01110,0b01111,0b01110,0b01100,0b01000,0};
byte gPause[8] = {0b11011,0b11011,0b11011,0b11011,0b11011,0b11011,0b11011,0};
byte gNote[8]  = {0b00100,0b00110,0b00101,0b00101,0b00100,0b11100,0b11100,0};
byte gSun[8]   = {0b00100,0b10101,0b01110,0b11011,0b01110,0b10101,0b00100,0};
byte gSpk[8]   = {0b00001,0b00011,0b11111,0b11111,0b11111,0b00011,0b00001,0};
byte gBell[8]  = {0b00100,0b01110,0b01110,0b01110,0b11111,0,0b00100,0};
byte gHalf[8]  = {0b11100,0b11100,0b11100,0b11100,0b11100,0b11100,0b11100,0};

char buf[64]; byte blen = 0;
unsigned long lastMac = 0;
bool waiting = true;

void row(byte r, const char* s) {
  lcd.setCursor(0, r);
  byte i = 0;
  for (; s[i] && i < 20; i++) lcd.write((uint8_t)s[i]);
  for (; i < 20; i++) lcd.write(' ');
}

void waitScreen() {
  row(0, "       DECKY");
  row(1, "");
  row(2, "  waiting for Mac...");
  row(3, " run deck.py on Mac");
}

void send(char c) { Serial.print(F("@K")); Serial.println(c); }

void handleLine() {
  buf[blen] = 0;
  if (blen >= 2 && buf[0] == '@') {
    lastMac = millis();
    if (waiting) { waiting = false; lcd.clear(); }
    if (buf[1] == 'L' && blen >= 3 && buf[2] >= '0' && buf[2] <= '3') row(buf[2] - '0', buf + 3);
    if (buf[1] == 'G' && blen >= 19 && buf[2] >= '1' && buf[2] <= '7') {   // @G<slot><16 hex> redefine a glyph
      byte g[8];
      for (byte i = 0; i < 8; i++) {
        char h = buf[3 + i * 2], l = buf[4 + i * 2];
        g[i] = ((h <= '9' ? h - '0' : h - 'a' + 10) << 4) | (l <= '9' ? l - '0' : l - 'a' + 10);
      }
      lcd.createChar(buf[2] - '0', g);
    }
  }
  blen = 0;
}

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') handleLine();
    else if (c != '\r' && blen < 63) buf[blen++] = c;
  }
}

// joystick -> one event per push (must return to centre before the next step)
char lastDir = 0;
bool swWas = false, holdSent = false; unsigned long swDown = 0, centredAt = 0;

void pollJoystick() {
  unsigned long now = millis();
  int x = analogRead(JX) - 512, y = analogRead(JY) - 512;
  if (lastDir == 0) {
    if (now - centredAt > 120 && (abs(x) > 300 || abs(y) > 300)) {
      lastDir = abs(x) > abs(y) ? (x < 0 ? 'L' : 'R') : (y < 0 ? 'U' : 'D');
      send(lastDir);
    }
  } else if (abs(x) < 150 && abs(y) < 150) {     // back near centre: arm the next step
    lastDir = 0; centredAt = now;
  }

  bool sw = digitalRead(JSW) == LOW;
  if (sw && !swWas) { swDown = now; holdSent = false; }
  if (sw && !holdSent && now - swDown > 700) { send('H'); holdSent = true; }
  if (!sw && swWas && !holdSent && now - swDown > 25) send('C');
  swWas = sw;
}

// scan all pin pairs; returns a*10+b (a<b) for the connected pair, or 0
byte scanPair() {
  for (byte a = KP_FIRST; a <= KP_LAST; a++) {
    pinMode(a, OUTPUT); digitalWrite(a, LOW);
    delayMicroseconds(30);
    for (byte b = a + 1; b <= KP_LAST; b++) {
      if (digitalRead(b) == LOW) { pinMode(a, INPUT_PULLUP); return a * 10 + b; }
    }
    pinMode(a, INPUT_PULLUP);
  }
  return 0;
}
byte kpLast = 0, kpCand = 0; unsigned long kpSince = 0;
void pollKeypad() {
  byte p = scanPair();
  unsigned long now = millis();
  if (p != kpCand) { kpCand = p; kpSince = now; return; }
  if (now - kpSince < 30 || p == kpLast) return;       // debounce, one event per press
  kpLast = p;
  if (p) { Serial.print(F("@X")); Serial.println(p); }
}

void setup() {
  for (byte a = KP_FIRST; a <= KP_LAST; a++) pinMode(a, INPUT_PULLUP);
  Serial.begin(9600);
  pinMode(JSW, INPUT_PULLUP);
  Wire.begin();
  Wire.setClock(100000);
  delay(200);
  byte addr = 0x27;
  for (byte a = 0x20; a < 0x40; a++) { Wire.beginTransmission(a); if (Wire.endTransmission() == 0) { addr = a; break; } }
  lcdp = new LiquidCrystal_I2C(addr, 20, 4);
  lcd.init(); delay(50); lcd.init(); lcd.backlight();
  lcd.createChar(1, gPlay); lcd.createChar(2, gPause); lcd.createChar(3, gNote); lcd.createChar(4, gSun);
  lcd.createChar(5, gSpk);  lcd.createChar(6, gBell);  lcd.createChar(7, gHalf);
  lcd.clear();
  waitScreen();
  Serial.println(F("@HELLO"));
}

void loop() {
  pollSerial();
  pollJoystick();
  pollKeypad();
  if (!waiting && millis() - lastMac > 7000) { waiting = true; lcd.clear(); waitScreen(); }
  if (waiting && millis() % 3000 < 2) { Serial.println(F("@HELLO")); delay(2); }
  static unsigned long lastAlive = 0;
  if (millis() - lastAlive > 4000) { lastAlive = millis(); Serial.println(F("@A")); }   // lets the Mac detect a dead link
}
