/*
  J.A.R.V.I.S. — a pocket assistant on an Arduino Uno.
  Alone: keyword brain + Markov text model. Plugged into the Mac with
  bridge/jarvis_bridge.py running: anything it does not know goes to Claude.
  No internet, no PC needed once flashed. 2 KB RAM, 32 KB flash.

  Hardware: Uno + 20x4 LCD + 3x4 keypad + HC-SR04 + joystick
            (+ 28BYJ-48/ULN2003 "head" if you add an I2C backpack)

  Talk to it:
    - Keypad, phone-style multi-tap (2=abc, 3=def ... 0=space)
        *  = backspace     # = send
        joystick click = toggle abc/123, push left = backspace, right = space
    - OR Serial Monitor @ 9600 baud, "Newline" line ending — type full sentences.

  Brain:
    - Intent matcher (keywords -> skills)
    - A tiny on-device generative model: order-3 character Markov chain
      trained on a corpus stored in flash. Type "think".
    - EEPROM memory: "remember buy airtime" / "recall" survives power-off.
*/

// ---------- CONFIG ----------
#define USE_I2C_LCD 1   // 1 = LCD has a PCF8574 I2C backpack -> frees pins for the stepper head
#define KEY_DEBUG   0   // 1 = print raw key presses to Serial (to check keypad wiring)
#define HAS_SONAR   0   // HC-SR04 removed (set 1 to bring it back)

#include <Keypad.h>
#include <EEPROM.h>

#if USE_I2C_LCD
  #include <Wire.h>
  #include <LiquidCrystal_I2C.h>
  LiquidCrystal_I2C* lcdp;                      // address auto-detected in setup()
  #define lcd (*lcdp)
  byte rowPins[4] = {8, 7, 6, 5};   // keypad pins 1-4 (left to right)
  byte colPins[3] = {4, 3, 2};      // keypad pins 5-7
  const byte STEP_PINS[4] = {9, 10, 11, 12};  // ULN2003 IN1..IN4
  #define HAS_STEPPER 0              // stepper removed from build (set 1 to bring it back)
#else
  #include <LiquidCrystal.h>
  LiquidCrystal lcd(12, 11, 10, 9, 8, 7);     // RS, E, D4, D5, D6, D7
  byte rowPins[4] = {6, 5, 4, 3};
  byte colPins[3] = {2, A4, A5};
  #define HAS_STEPPER 0
#endif

const byte TRIG = 13, ECHO = A3, JX = A0, JY = A1, JSW = A2;

char keys[4][3] = {{'1','2','3'},{'4','5','6'},{'7','8','9'},{'*','0','#'}};
Keypad keypad = Keypad(makeKeymap(keys), rowPins, colPins, 4, 3);

const char* const T9[10] = {" 0", "1.?!", "abc2", "def3", "ghi4", "jkl5", "mno6", "pqrs7", "tuv8", "wxyz9"};

// ---------- STATE ----------
enum State : byte { S_IDLE, S_TYPING, S_SLEEP, S_MUSIC };
State state = S_IDLE;

char inBuf[61];  byte inLen = 0;
char serBuf[100]; byte serLen = 0;
char out[161];
bool numMode = false;
char lastTap = 0; byte tapIdx = 0; unsigned long lastTapMs = 0;
char pendingKey = 0;

unsigned long lastActivity = 0, lastPresence = 0, lastSonar = 0, nextBlink = 3000, blinkUntil = 0, lastStatus = 0, lastJoyMove = 0;
int lastCm = 999;
byte eyeDx = 1, eyeDy = 1; bool faceDirty = true; byte faceSig = 255;
bool swPrev = HIGH; unsigned long swMs = 0;

bool clockSet = false; int clockBaseMin = 0; unsigned long clockBaseMs = 0;
unsigned long timerEnd = 0;
byte gameTarget = 0, gameTries = 0;
unsigned int chats = 0;
bool seeded = false;
unsigned long lastLook = 0, happyUntil = 0;
unsigned long bridgeSeen = 0;
// Spotify (via Mac bridge)
char spTrack[41] = "", spArtist[31] = "";
char spState = '?';            // p playing, s paused/stopped, x Spotify closed, ? unknown
byte spVol = 0;
unsigned long lastSpPoll = 0, musicFlashUntil = 0, swDownMs = 0, lastMusicDraw = 0;
bool musicDirty = true;
char musicFlash[21] = "";
bool bridgeOn() { return bridgeSeen && millis() - bridgeSeen < 15000UL; }

// ---------- FLASH CONTENT ----------
const char J0[] PROGMEM = "I'd tell a UDP joke. You might not get it.";
const char J1[] PROGMEM = "Dark mode? Light attracts bugs.";
const char J2[] PROGMEM = "10 kinds of people: binary or not.";
const char J3[] PROGMEM = "Why so calm? Lots of resistance.";
const char J4[] PROGMEM = "Long joke? I only have 4 lines.";
const char J5[] PROGMEM = "2KB RAM. Can't afford grudges.";
const char J6[] PROGMEM = "I'm not lazy. I'm in power save.";
const char* const JOKES[] PROGMEM = {J0, J1, J2, J3, J4, J5, J6};

const char F0[] PROGMEM = "Lake Victoria: Africa's biggest lake.";
const char F1[] PROGMEM = "The Nile starts at Jinja.";
const char F2[] PROGMEM = "Octopuses have 3 hearts.";
const char F3[] PROGMEM = "A Venus day outlasts its year.";
const char F4[] PROGMEM = "Bananas are berries.";
const char F5[] PROGMEM = "Uganda sits on the equator.";
const char F6[] PROGMEM = "Sunlight takes 8 min to arrive.";
const char F7[] PROGMEM = "Honey never spoils.";
const char F8[] PROGMEM = "I run on 2048 bytes of RAM.";
const char* const FACTS[] PROGMEM = {F0, F1, F2, F3, F4, F5, F6, F7, F8};

// Training corpus for the Markov "model". Edit it to change JARVIS's personality.
const char CORPUS[] PROGMEM =
  "the best time to start was yesterday. the next best time is now. "
  "small steps every day beat big plans every year. ship it, then make it better. "
  "the market rewards those who show up. keep your costs low and your standards high. "
  "a good plan today is better than a perfect plan next week. learn the rules, then break the right ones. "
  "stay hungry and stay patient. every expert was once a beginner. money follows value, so build value. "
  "focus on the customer and the rest follows. do the hard thing first. sleep is part of the work. "
  "the quiet hours build the loud results. protect your energy like you protect your money. "
  "trust the process but check the numbers. one good customer teaches more than a hundred opinions. "
  "talk less and build more. discipline is choosing what you want most over what you want now. "
  "risk only what you can afford to lose. cut losses fast and let the winners run. "
  "the people you keep around you shape the person you become. build the thing you wish existed. "
  "consistency is louder than talent. rest, then return stronger. ";

// ---------- CUSTOM CHARS (robot head) ----------
// slots: 0/1 eye halves, 2 antenna, 3/4 top corners, 5/6 bottom corners, 7 mouth grille
byte cTL[8] = {0,0,0,0b00111,0b00100,0b00100,0b00100,0b00100};
byte cTR[8] = {0,0,0,0b11100,0b00100,0b00100,0b00100,0b00100};
byte cBL[8] = {0b00100,0b00100,0b00100,0b00100,0b00100,0b00100,0b00111,0};
byte cBR[8] = {0b00100,0b00100,0b00100,0b00100,0b00100,0b00100,0b11100,0};

// ---------- HELPERS ----------
void pumpSerial();
void handleBridgeLine(const char* l);
int readCm() {
#if !HAS_SONAR
  return 999;
#endif
  digitalWrite(TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  unsigned long d = pulseIn(ECHO, HIGH, 25000UL);
  return d ? (int)(d / 58) : 999;
}

int nowMin() { return (clockBaseMin + (millis() - clockBaseMs) / 60000UL) % 1440; }

void lcdLine(byte row, const char* s) {   // print padded to 20 cols (no flicker)
  lcd.setCursor(0, row);
  byte i = 0;
  for (; s[i] && i < 20; i++) lcd.write(s[i]);
  for (; i < 20; i++) lcd.write(' ');
}

char waitKeyOrMs(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) {
    char k = keypad.getKey();
    if (k) return k;
    if (digitalRead(JSW) == LOW) { while (digitalRead(JSW) == LOW) delay(5); return 'J'; }
    pumpSerial();
  }
  return 0;
}

void say() {
  Serial.print(F("JARVIS: ")); Serial.println(out);
  char lines[4][21];
  const char* p = out;
  while (*p) {
    byte ln = 0;
    while (ln < 4) {
      while (*p == ' ') p++;
      if (!*p) break;
      byte len = strlen(p), take = len > 20 ? 20 : len;
      if (len > 20) { byte b = 20; while (b > 0 && p[b] != ' ') b--; if (b > 0) take = b; }
      memcpy(lines[ln], p, take); lines[ln][take] = 0; p += take; ln++;
    }
    while (*p == ' ') p++;
    lcd.clear();
    for (byte i = 0; i < ln; i++) lcdLine(i, lines[i]);
    bool last = !*p;
    if (!last) { lcd.setCursor(19, 3); lcd.write('>'); }
    char k = waitKeyOrMs(last ? 5000 : 3500);
    if (last && k && k != 'J' && k != 'S') pendingKey = k;
  }
  lcd.clear(); faceDirty = true; faceSig = 255;
}
void sayP(PGM_P s) { strncpy_P(out, s, 160); out[160] = 0; say(); }
#define SAY(s) sayP(PSTR(s))
void sayTable(const char* const* tbl, byte n) { strncpy_P(out, (PGM_P)pgm_read_word(&tbl[random(n)]), 160); out[160] = 0; say(); }

#if HAS_STEPPER
const byte HS[8] = {0b1000,0b1100,0b0100,0b0110,0b0010,0b0011,0b0001,0b1001};
int stepPhase = 0; long headSteps = 0;
void stepN(long n) {
  int dir = n > 0 ? 1 : -1;
  for (long i = 0; i < labs(n); i++) {
    stepPhase = (stepPhase + dir + 8) % 8;
    for (byte b = 0; b < 4; b++) digitalWrite(STEP_PINS[b], (HS[stepPhase] >> (3 - b)) & 1);
    delayMicroseconds(1200);
  }
  headSteps += n;
  for (byte b = 0; b < 4; b++) digitalWrite(STEP_PINS[b], LOW);   // release coils, save power
}
void headTo(int deg) { stepN((long)deg * 4096 / 360 - headSteps); }
void nod() { headTo(12); headTo(-12); headTo(0); }
#endif

// ---------- THE "MODEL": order-3 char Markov chain over CORPUS ----------
#define ORDER 5
void think() {
  int N = strlen_P(CORPUS);
  int st = random(N - 10);
  while (st < N - 5 && !(pgm_read_byte(CORPUS + st) == '.' && pgm_read_byte(CORPUS + st + 1) == ' ')) st++;
  st = (st >= N - 5) ? 0 : st + 2;
  byte len = 0;
  for (; len < ORDER; len++) out[len] = pgm_read_byte(CORPUS + st + len);
  while (len < 150) {
    int count = 0; char next = 0;
    for (int i = 0; i < N - ORDER; i++) {
      byte j = 0;
      while (j < ORDER && pgm_read_byte(CORPUS + i + j) == out[len - ORDER + j]) j++;
      if (j == ORDER) { count++; if (random(count) == 0) next = pgm_read_byte(CORPUS + i + ORDER); }
    }
    if (!count) break;
    out[len++] = next;
    if (next == '.' && len > 20) break;
    if (len > 55 && next == ' ') { out[len - 1] = '.'; break; }
  }
  out[len] = 0;
  out[0] = toupper(out[0]);
  say();
}

// ---------- SKILLS ----------
void distanceMode() {
  lcd.clear();
  unsigned long t0 = millis();
  while (millis() - t0 < 10000) {
    int cm = readCm();
    char b[21];
    lcdLine(0, " JARVIS rangefinder");
    if (cm >= 999) snprintf_P(b, 21, PSTR("  nothing in range"));
    else snprintf_P(b, 21, PSTR("  %d cm  (%d.%02d m)"), cm, cm / 100, cm % 100);
    lcdLine(1, b);
    byte bars = cm >= 200 ? 20 : cm / 10;
    lcd.setCursor(0, 2);
    for (byte i = 0; i < 20; i++) lcd.write(i < bars ? (char)255 : ' ');
    lcdLine(3, "any key = exit");
    if (waitKeyOrMs(250)) break;
  }
  lcd.clear(); faceDirty = true; faceSig = 255;
  snprintf_P(out, 161, PSTR("Last reading: %d cm."), lastCm = readCm());
  if (lastCm >= 999) strcpy_P(out, PSTR("Nothing in front of me."));
  say();
}

#if HAS_STEPPER
void scanRoom() {
  int best = 999, bestA = 0;
  for (int a = -90; a <= 90; a += 15) {
    headTo(a); delay(80);
    int cm = readCm();
    char b[21]; snprintf_P(b, 21, PSTR("scan %4d deg %3dcm"), a, cm > 998 ? 0 : cm);
    lcdLine(1, b);
    if (cm < best) { best = cm; bestA = a; }
  }
  headTo(0);
  if (best >= 999) strcpy_P(out, PSTR("Scanned 180 degrees. Room looks empty."));
  else snprintf_P(out, 161, PSTR("Nearest thing: %d cm, %d deg %s."), best, abs(bestA), bestA < 0 ? "left" : bestA > 0 ? "right" : "ahead");
  say();
}
#endif

void greet() {
  const char* when = "Hello";
  if (clockSet) { int h = nowMin() / 60; when = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; }
  snprintf_P(out, 161, PSTR("%s, sir."), when);
#if HAS_STEPPER
  nod();
#endif
  say();
  happyUntil = millis() + 2500;
}

// ---------- MAC BRIDGE ----------
// Uno -> Mac: "@ASK <question>"   Mac -> Uno: "@ANS <answer>", "@HELLO", "@PING", "@TIME HHMM"
void handleBridgeLine(const char* l) {
  if (!strncmp_P(l, PSTR("@NOW "), 5)) {          // @NOW p|60|Track|Artist
    const char* p = l + 5;
    spState = *p;
    p = strchr(p, '|'); if (!p) return; spVol = atoi(++p);
    p = strchr(p, '|'); if (!p) return; p++;
    const char* e = strchr(p, '|'); byte n = e ? e - p : strlen(p); if (n > 40) n = 40;
    memcpy(spTrack, p, n); spTrack[n] = 0;
    if (e) { strncpy(spArtist, e + 1, 30); spArtist[30] = 0; } else spArtist[0] = 0;
    musicDirty = true; bridgeSeen = millis(); return;
  }
  if (!strncmp_P(l, PSTR("@TIME "), 6)) {
    int v = atoi(l + 6);
    clockSet = true; clockBaseMin = (v / 100) * 60 + v % 100; clockBaseMs = millis();
  }
  bridgeSeen = millis();
}

void askMac(const char* q) {
  Serial.print(F("@ASK ")); Serial.println(q);
  lcd.clear(); lcdLine(0, "Thinking..."); lcdLine(3, "* = cancel");
  unsigned long t0 = millis(); byte len = 0; byte dots = 0; unsigned long lastDot = 0;
  while (millis() - t0 < 30000UL) {
    if (millis() - lastDot > 400) { lastDot = millis(); char d[21]; byte n = dots++ % 8; memset(d, ' ', 20); for (byte i = 0; i < n; i++) d[6 + i * 1] = '.'; d[20] = 0; lcdLine(1, d); }
    char k = keypad.getKey();
    if (k == '*') { SAY("Cancelled."); return; }
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\r') continue;
      if (c == '\n') {
        out[len] = 0; len = 0;
        if (!strncmp_P(out, PSTR("@ANS "), 5)) {
          memmove(out, out + 5, strlen(out + 5) + 1);
          bridgeSeen = millis();
          say(); return;
        }
        if (out[0] == '@') handleBridgeLine(out);
      } else if (len < 160) out[len++] = c;
    }
  }
  SAY("No reply from Mac.");
}

// ---------- SPOTIFY ----------
void sp(const char* cmd) { Serial.print(F("@SP ")); Serial.println(cmd); }
void musicMsg(const char* m) { strncpy(musicFlash, m, 20); musicFlash[20] = 0; musicFlashUntil = millis() + 1200; musicDirty = true; }

void enterMusic() {
  state = S_MUSIC; lcd.clear(); musicDirty = true;
  sp("status"); lastSpPoll = millis();
  swPrev = digitalRead(JSW); lastJoyMove = millis();
}
void exitMusic() { state = S_IDLE; lastActivity = millis(); lcd.clear(); faceDirty = true; }

void drawMusic() {
  unsigned long now = millis();
  bool marquee = strlen(spTrack) > 20;
  if (!musicDirty && !(marquee && now - lastMusicDraw > 350) && !(musicFlashUntil && now > musicFlashUntil)) return;
  if (musicFlashUntil && now > musicFlashUntil) musicFlashUntil = 0;
  musicDirty = false; lastMusicDraw = now;
  char b[21];
  if (spState == 'x') strcpy_P(b, PSTR("Spotify closed"));
  else if (spState == '?') strcpy_P(b, PSTR("Spotify..."));
  else snprintf_P(b, 21, PSTR("%-13svol%3d"), spState == 'p' ? "> Playing" : "|| Paused", spVol);
  lcdLine(0, b);
  if (marquee) {
    byte n = strlen(spTrack), span = n + 4, off = (now / 350) % span;
    for (byte i = 0; i < 20; i++) { byte k = (off + i) % span; b[i] = k < n ? spTrack[k] : ' '; }
    b[20] = 0; lcdLine(1, b);
  } else lcdLine(1, spState == 'x' ? "click = open + play" : spTrack);
  lcdLine(2, spArtist);
  lcdLine(3, musicFlashUntil ? musicFlash : "<> skip ^v vol o=||");
}

void musicPoll() {
  unsigned long now = millis();
  if (!bridgeOn()) { exitMusic(); SAY("Mac link lost, sir."); return; }
  if (now - lastSpPoll > 2000) { lastSpPoll = now; sp("status"); }
  int x = analogRead(JX), y = analogRead(JY);
  bool sw = digitalRead(JSW);
  if (sw == LOW && swPrev == HIGH) swDownMs = now;
  if (sw == LOW && swPrev == LOW && swDownMs && now - swDownMs > 800) { swDownMs = 0; swPrev = sw; exitMusic(); return; }
  if (sw == HIGH && swPrev == LOW && swDownMs) {
    swDownMs = 0;
    sp("toggle");
    spState = spState == 'p' ? 's' : 'p';
    musicMsg(spState == 'p' ? "> play" : "|| pause");
    lastSpPoll = now - 1500;
  }
  swPrev = sw;
  if (now - lastJoyMove > 450) {
    if (x < 200)      { sp("prev"); musicMsg("<< previous"); lastJoyMove = now; lastSpPoll = now - 1400; }
    else if (x > 820) { sp("next"); musicMsg("next >>"); lastJoyMove = now; lastSpPoll = now - 1400; }
    else if (y < 200) { sp("volup");   if (spVol <= 90) spVol += 10; musicMsg("volume +"); lastJoyMove = now; }
    else if (y > 820) { sp("voldown"); spVol = spVol >= 10 ? spVol - 10 : 0; musicMsg("volume -"); lastJoyMove = now; }
  }
  drawMusic();
}

void musicKey(char k) {
  if (k == '#') { exitMusic(); return; }
  if (k == '5') { sp("toggle"); musicMsg("play/pause"); }
  else if (k == '4') { sp("prev"); musicMsg("<< previous"); }
  else if (k == '6') { sp("next"); musicMsg("next >>"); }
  else if (k == '2') { sp("volup"); musicMsg("volume +"); }
  else if (k == '8') { sp("voldown"); musicMsg("volume -"); }
  lastSpPoll = millis() - 1400;
}

// ---------- INTENT ENGINE ----------
void process(const char* raw) {
  char q[61]; byte n = 0;
  while (*raw == ' ') raw++;
  for (; raw[n] && n < 60; n++) q[n] = tolower(raw[n]);
  while (n && q[n - 1] == ' ') n--;
  q[n] = 0;
  if (!n) return;
  if (!seeded) { randomSeed(micros() ^ analogRead(JX) ^ (analogRead(JY) << 5)); seeded = true; }
  chats++;
  Serial.print(F("YOU:  ")); Serial.println(q);
  lcd.clear(); lcdLine(1, "   thinking...");

  long nums[3]; byte nc = 0;
  for (const char* p = q; *p && nc < 3; ) {
    if (isdigit(*p)) { nums[nc++] = atol(p); while (isdigit(*p)) p++; } else p++;
  }
  #define HAS(w) (strstr_P(q, PSTR(w)) != NULL)

  // active game eats numbers first
  if (gameTarget && (nc || HAS("quit") || HAS("stop"))) {
    if (!nc) { snprintf_P(out, 161, PSTR("It was %d, sir."), gameTarget); gameTarget = 0; say(); return; }
    gameTries++;
    if (nums[0] < gameTarget)      SAY("Higher.");
    else if (nums[0] > gameTarget) SAY("Lower.");
    else { snprintf_P(out, 161, PSTR("Yes! %d in %d tries."), gameTarget, gameTries); gameTarget = 0; say(); }
    return;
  }

#if HAS_STEPPER
  if (HAS("coils")) {
    for (byte r = 0; r < 2; r++) for (byte b = 0; b < 4; b++) {
      char t[21]; snprintf_P(t, 21, PSTR("IN%d (pin D%d) ON"), b + 1, STEP_PINS[b]);
      lcdLine(0, t); Serial.println(t);
      digitalWrite(STEP_PINS[b], HIGH); delay(1000); digitalWrite(STEP_PINS[b], LOW); delay(200);
    }
    SAY("Coil test done."); return;
  }
#endif
  bool isMusic = HAS("spotify") || HAS("music") || HAS("song") || HAS("pause") || HAS("skip") || HAS("volume") || HAS("louder") || HAS("quieter")
                 || !strcmp_P(q, PSTR("play")) || !strcmp_P(q, PSTR("next")) || !strcmp_P(q, PSTR("previous")) || !strcmp_P(q, PSTR("back")) || HAS("resume");
  if (isMusic) {
    if (!bridgeOn()) { SAY("Music needs the Mac link, sir."); return; }
    if (HAS("pause") || HAS("stop"))                       { sp("pause"); SAY("Paused, sir."); }
    else if (HAS("skip") || HAS("next"))                   { sp("next"); enterMusic(); }
    else if (HAS("previous") || !strcmp_P(q, PSTR("back"))) { sp("prev"); enterMusic(); }
    else if (HAS("louder") || HAS("up"))                   { sp("volup"); sp("volup"); SAY("Louder, sir."); }
    else if (HAS("quieter") || HAS("down"))                { sp("voldown"); sp("voldown"); SAY("Quieter, sir."); }
    else if (HAS("play") || HAS("resume"))                 { sp("play"); enterMusic(); }
    else enterMusic();
    return;
  }
  if (bridgeOn() && !strncmp_P(q, PSTR("ask "), 4)) { askMac(q + 4); return; }
  if (bridgeOn()) {   // real questions go to the AI; short commands stay local
    byte words = 1; for (const char* p = q; *p; p++) if (*p == ' ') words++;
    if (words >= 4 && strncmp_P(q, PSTR("remember"), 8) && strncmp_P(q, PSTR("timer"), 5) && strncmp_P(q, PSTR("set "), 4)) { askMac(q); return; }
  }
  if (HAS("diag")) {
    snprintf_P(out, 161, PSTR("X=%d Y=%d SW=%d dist=%dcm"), analogRead(JX), analogRead(JY), digitalRead(JSW), readCm());
    Serial.print(F("DIAG ")); Serial.println(out);
    lcdLine(0, out); return;
  }
  else   if (HAS("help") || HAS("what can")) {
    SAY("time timer 5 2 plus 2 joke fact flip roll guess think remember recall music"
#if HAS_STEPPER
        " | scan | turn 90"
#endif
    );
    if (bridgeOn()) SAY("Anything else: AI.");
  }
  else if (HAS("remember")) {
    const char* p = strstr_P(q, PSTR("remember")) + 8;
    while (*p == ' ') p++;
    if (!*p) { SAY("Remember what, sir?"); return; }
    EEPROM.update(0, 0x42);
    byte i = 0; for (; p[i] && i < 60; i++) EEPROM.update(1 + i, p[i]);
    EEPROM.update(1 + i, 0);
    snprintf_P(out, 161, PSTR("Noted: %s"), p); say();
  }
  else if (HAS("recall") || HAS("note") || HAS("what did")) {
    if (EEPROM.read(0) != 0x42) { SAY("Nothing saved, sir."); return; }
    strcpy_P(out, PSTR("Note: "));
    byte o = strlen(out);
    for (byte i = 0; i < 60; i++) { char c = EEPROM.read(1 + i); if (!c) break; out[o++] = c; }
    out[o] = 0; say();
  }
  else if (HAS("forget")) { EEPROM.update(0, 0); SAY("Erased."); }
  else if (HAS("set") && nc) {
    int h = nums[0] / 100, m = nums[0] % 100;
    if (nums[0] < 100 && nc >= 2) { h = nums[0]; m = nums[1]; }
    if (h > 23 || m > 59) { SAY("Use 24h, like: set 1430"); return; }
    clockSet = true; clockBaseMin = h * 60 + m; clockBaseMs = millis();
    snprintf_P(out, 161, PSTR("Clock %02d:%02d, sir."), h, m); say();
  }
  else if (HAS("timer")) {
    if (nc && nums[0] == 0) { timerEnd = 0; SAY("Timer off."); return; }
    long mins = nc ? nums[0] : 1;
    if (mins > 600) mins = 600;
    timerEnd = millis() + mins * 60000UL;
    snprintf_P(out, 161, PSTR("%ld min timer set."), mins); say();
  }
  else if (HAS("time") || HAS("clock") || HAS("hour")) {
    if (clockSet) { int t = nowMin(); snprintf_P(out, 161, PSTR("%02d:%02d, sir."), t / 60, t % 60); }
    else snprintf_P(out, 161, PSTR("No clock. Type set 1430 (up %lu min)"), millis() / 60000UL);
    say();
  }
  else if (nc >= 2 && (HAS("plus") || HAS("add") || HAS("minus") || HAS("less") || HAS("times") || HAS(" x ") || HAS("mul") || HAS("over") || HAS("div"))) {
    long a = nums[0], b = nums[1];
    if (HAS("plus") || HAS("add"))        snprintf_P(out, 161, PSTR("%ld + %ld = %ld"), a, b, a + b);
    else if (HAS("minus") || HAS("less")) snprintf_P(out, 161, PSTR("%ld - %ld = %ld"), a, b, a - b);
    else if (HAS("over") || HAS("div")) {
      if (!b) { SAY("Can't divide by 0."); return; }
      long r = (a * 100) / b;
      snprintf_P(out, 161, PSTR("%ld / %ld = %ld.%02ld"), a, b, r / 100, labs(r % 100));
    }
    else snprintf_P(out, 161, PSTR("%ld x %ld = %ld"), a, b, a * b);
    say();
  }
#if HAS_STEPPER
  else if (HAS("scan") || HAS("radar")) scanRoom();
  else if (HAS("turn") || HAS("look")) {
    int d = nc ? (int)nums[0] : 45;
    if (HAS("left")) d = -d;
    if (HAS("back") || HAS("center")) d = 0;
    headTo(constrain(d, -180, 180));
    snprintf_P(out, 161, PSTR("Looking %d deg."), d); say();
  }
#endif
#if HAS_SONAR
  else if (HAS("dist") || HAS("far") || HAS("measure") || HAS("range")) distanceMode();
#endif
  else if (HAS("joke") || HAS("funny") || HAS("laugh")) sayTable(JOKES, 7);
  else if (HAS("fact") || HAS("teach") || HAS("learn")) sayTable(FACTS, 9);
  else if (HAS("flip") || HAS("coin")) { if (random(2)) SAY("Heads."); else SAY("Tails."); }
  else if (HAS("roll") || HAS("dice") || HAS("die")) { snprintf_P(out, 161, PSTR("You rolled a %d."), (int)random(1, 7)); say(); }
  else if (HAS("guess") || HAS("game")) {
    gameTarget = random(1, 101); gameTries = 0;
    SAY("Guess 1-100, sir.");
  }
  else if (HAS("think") || HAS("dream") || HAS("idea") || HAS("advice") || HAS("quote") || HAS("wisdom")) think();
  else if (HAS("who are you") || HAS("your name") || HAS("what are you")) SAY("JARVIS, sir. At your service.");
  else if (HAS("how are") || HAS("mood") || HAS("feel")) {
    unsigned long up = millis() / 60000UL;
    snprintf_P(out, 161, PSTR("All good. %lum up, %u asks. %s"), up, chats,
               (HAS_SONAR && lastCm < 80) ? "Nice to have company." : bridgeOn() ? "AI on." : "AI off.");
    say();
  }
  else if (HAS("thank")) SAY("Pleasure, sir.");
  else if (HAS("bye") || HAS("sleep") || HAS("night")) { SAY("Sleeping, sir."); state = S_SLEEP; return; }
  else if ((q[0] == 'h' && (q[1] == 'i' || (q[1] == 'e' && (q[2] == 'y' || q[2] == 'l')))) || (q[0] == 'y' && q[1] == 'o') || !strcmp_P(q, PSTR("sup"))) greet();
  else if (bridgeOn()) askMac(q);
  else {
    if (random(2)) SAY("Beyond my 2KB, sir.");
    else { SAY("Not sure. A thought:"); think(); }
  }
}

// ---------- INPUT ----------
void drawInput() {
  char b[21];
  snprintf_P(b, 21, PSTR("JARVIS>    [%s] %2d"), numMode ? "123" : "abc", inLen);
  lcdLine(0, b);
  int start = inLen > 59 ? inLen - 59 : 0;
  for (byte r = 0; r < 3; r++) {
    char line[21]; byte j = 0;
    for (; j < 20; j++) {
      int i = start + r * 20 + j;
      if (i < inLen) line[j] = inBuf[i];
      else if (i == inLen) line[j] = '_';
      else line[j] = ' ';
    }
    line[20] = 0; lcdLine(r + 1, line);
  }
}

void startTyping() {
  state = S_TYPING; inLen = 0; inBuf[0] = 0; lastTap = 0;
  lcd.clear(); drawInput();
}

void append(char c) { if (inLen < 60) { inBuf[inLen++] = c; inBuf[inLen] = 0; } }

void endTyping() { if (state == S_TYPING) state = S_IDLE; lcd.clear(); faceDirty = true; faceSig = 255; }

void handleKey(char k) {
#if KEY_DEBUG
  Serial.print(F("key: ")); Serial.println(k);
#endif
  lastActivity = millis();
  if (state == S_MUSIC) { musicKey(k); return; }
  if (state != S_TYPING) {
    startTyping();
    if (k == '#' || k == '*') return;
  }
  if (k == '*') { if (inLen) inBuf[--inLen] = 0; lastTap = 0; }
  else if (k == '#') {
    if (inLen) { char tmp[61]; strcpy(tmp, inBuf); inLen = 0; inBuf[0] = 0; state = S_IDLE; process(tmp); }
    endTyping();
    return;
  }
  else if (numMode) { append(k); lastTap = 0; }
  else {
    const char* s = T9[k - '0'];
    if (k == lastTap && millis() - lastTapMs < 900 && inLen) {
      tapIdx = (tapIdx + 1) % strlen(s);
      inBuf[inLen - 1] = s[tapIdx];
    } else { tapIdx = 0; append(s[0]); }
    lastTap = k; lastTapMs = millis();
  }
  drawInput();
}

bool lineReady = false;
// Reads serial into serBuf. Bridge lines (@...) are handled at once; a chat line is
// held until serialPoll can process it. Called during waits so the 64-byte RX buffer never overflows.
void pumpSerial() {
  while (!lineReady && Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      serBuf[serLen] = 0;
      if (serLen && serBuf[0] == '@') { handleBridgeLine(serBuf); serLen = 0; }
      else if (serLen) lineReady = true;
    } else if (serLen < 99) serBuf[serLen++] = c;
  }
}

void serialPoll() {
  pumpSerial();
  if (!lineReady) return;
  char tmp[61]; strncpy(tmp, serBuf, 60); tmp[60] = 0;
  lineReady = false; serLen = 0;
  lastActivity = millis();
  State before = state; state = S_IDLE;
  process(tmp);
  if (before == S_TYPING && state == S_IDLE) { state = S_TYPING; lcd.clear(); drawInput(); }
}

void joystickPoll() {
  if (state == S_MUSIC) return;
  int x = analogRead(JX), y = analogRead(JY);
  bool sw = digitalRead(JSW);
  unsigned long now = millis();
  if (sw == LOW && swPrev == HIGH && now - swMs > 200) {
    swMs = now; lastActivity = now;
    if (state == S_TYPING) { numMode = !numMode; lastTap = 0; drawInput(); }
    else { if (state == S_SLEEP) state = S_IDLE; startTyping(); }
  }
  swPrev = sw;

  bool moved = x < 300 || x > 720 || y < 300 || y > 720;
  if (state == S_TYPING) {
    if (now - lastJoyMove > 350) {
      if (x < 200) { if (inLen) inBuf[--inLen] = 0; lastTap = 0; drawInput(); lastJoyMove = now; lastActivity = now; }
      else if (x > 820) { append(' '); lastTap = 0; drawInput(); lastJoyMove = now; lastActivity = now; }
    }
    return;
  }
  if (moved) {
    lastActivity = now;
    if (state == S_SLEEP) { state = S_IDLE; greet(); }
  }
  eyeDx = x < 300 ? 0 : x > 720 ? 2 : 1;
  eyeDy = y < 300 ? 0 : y > 720 ? 2 : 1;
  if (moved) lastLook = now;
}

// ---------- FACE (robot) ----------
byte eyeKey = 255, antKey = 255, mouthKey = 255;

// Eyes are 10x8 px (two LCD cells), redrawn by redefining the custom chars.
// mode: 0 open, 1 blink, 2 asleep, 3 happy
void setEyes(byte mode, byte dx, byte dy) {
  byte key = mode * 16 + dx * 4 + dy;
  if (key == eyeKey) return;
  eyeKey = key;
  uint16_t r[8] = {0};
  if (mode == 0) {
    r[0] = r[7] = 0b0111111110;
    for (byte y = 1; y < 7; y++) r[y] = 0b1000000001;
    for (byte y = 1 + dy; y < 5 + dy; y++) r[y] |= (0b111 << (5 - dx * 2));   // pupil
  } else if (mode == 1) { r[4] = 0b0111111110; }
  else if (mode == 2) { r[4] = 0b1000000001; r[5] = 0b0111111110; }
  else { r[2] = 0b0011111100; r[3] = 0b0100000010; r[4] = 0b1000000001; }
  byte L[8], R[8];
  for (byte y = 0; y < 8; y++) { L[y] = (r[y] >> 5) & 31; R[y] = r[y] & 31; }
  lcd.createChar(0, L); lcd.createChar(1, R);
}
void setAnt(byte on) {
  if (antKey == on) return;
  antKey = on;
  byte a[8] = {0b01110, (byte)(on ? 0b11111 : 0b10001), 0b01110, 0b11111, 0, 0, 0, 0};
  lcd.createChar(2, a);
}
void setMouth(byte m) {            // 0 grille, 1 flat (asleep), 2 open (happy)
  if (mouthKey == m) return;
  mouthKey = m;
  byte g[8] = {0, 0b11111, 0b10101, 0b10101, 0b11111, 0, 0b11111, 0};
  byte f[8] = {0, 0, 0, 0b11111, 0, 0, 0b11111, 0};
  byte o[8] = {0, 0b11111, 0b10101, 0b10101, 0b10101, 0b11111, 0b11111, 0};
  lcd.createChar(7, m == 0 ? g : m == 1 ? f : o);
}

void drawFace() {
  unsigned long now = millis();
  bool sleeping = state == S_SLEEP;
  byte mode = sleeping ? 2 : now < blinkUntil ? 1 : now < happyUntil ? 3 : 0;
  byte dx = eyeDx, dy = eyeDy;
  if (!sleeping && now - lastLook > 2500) {           // idle: visor scan
    static const byte P[4] = {0, 1, 2, 1};
    dx = P[(now / 650) % 4]; dy = 1;
  }
  setEyes(mode, dx, dy);
  setAnt(sleeping ? 0 : (now / 800) % 2);
  setMouth(sleeping ? 1 : mode == 3 ? 2 : 0);

  if (faceDirty) {
    faceDirty = false;
    byte rows[3][20]; memset(rows, ' ', sizeof(rows));
    rows[0][3] = 3; for (byte c = 4; c < 15; c++) rows[0][c] = '-'; rows[0][9] = 2; rows[0][15] = 4;
    if (sleeping) { rows[0][17] = 'z'; rows[0][18] = 'Z'; }
    rows[1][2] = 255; rows[1][3] = '|'; rows[1][6] = 0; rows[1][7] = 1; rows[1][11] = 0; rows[1][12] = 1; rows[1][15] = '|'; rows[1][16] = 255;
    rows[2][3] = 5; for (byte c = 4; c < 15; c++) rows[2][c] = '_'; for (byte c = 7; c < 12; c++) rows[2][c] = 7; rows[2][15] = 6;
    for (byte r = 0; r < 3; r++) { lcd.setCursor(0, r); for (byte i = 0; i < 20; i++) lcd.write(rows[r][i]); }
    lastStatus = 0;
  }
  if (now - lastStatus > 1000) {
    lastStatus = now;
    char st[21], clk[6], tm[8];
    if (clockSet) { int t = nowMin(); snprintf_P(clk, 6, PSTR("%02d:%02d"), t / 60, t % 60); } else strcpy_P(clk, PSTR("--:--"));
    if (timerEnd) { unsigned long sec = (timerEnd - now) / 1000; snprintf_P(tm, 8, PSTR("T%lu:%02lu"), sec / 60, sec % 60); } else tm[0] = 0;
    if (sleeping) snprintf_P(st, 21, PSTR("%s  %-7s   joy"), clk, tm);
    else if (lastCm < 999) snprintf_P(st, 21, PSTR("%s  %-7s %4dcm"), clk, tm, lastCm);
    else snprintf_P(st, 21, PSTR("%s  %-7s %s"), clk, tm, bridgeOn() ? " AI on" : "#=talk");
    lcdLine(3, st);
  }
}

void idlePoll() {
  unsigned long now = millis();
  if (HAS_SONAR && now - lastSonar > 400) {
    lastSonar = now;
    lastCm = readCm();
    if (lastCm < 70) lastPresence = now;
    if (state == S_SLEEP && lastCm < 50) { state = S_IDLE; lastActivity = now; greet(); return; }
  }
  if (state == S_IDLE && now - lastActivity > 60000UL && (!HAS_SONAR || now - lastPresence > 60000UL)) { state = S_SLEEP; faceDirty = true; }
  if (now > nextBlink) { blinkUntil = now + 150; nextBlink = now + random(2500, 6000); }
  drawFace();
}

void timerPoll() {
  if (!timerEnd || (long)(millis() - timerEnd) < 0) return;
  timerEnd = 0;
  Serial.println(F("JARVIS: Timer complete, sir."));
  State before = state;
  for (byte i = 0; i < 30; i++) {
    if (i % 2 == 0) { lcd.clear(); lcdLine(1, "  ** TIME'S UP **"); lcdLine(2, "   any key = ok"); }
    else lcd.clear();
#if HAS_STEPPER
    if (i < 4) { headTo(i % 2 ? 20 : -20); }
#endif
    if (waitKeyOrMs(400)) break;
  }
#if HAS_STEPPER
  headTo(0);
#endif
  lcd.clear();
  if (before == S_TYPING) drawInput(); else { if (state == S_SLEEP) state = S_IDLE; faceDirty = true; faceSig = 255; }
  lastActivity = millis();
  musicDirty = true;
}

// ---------- MAIN ----------
void setup() {
  Serial.begin(9600);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT); pinMode(JSW, INPUT_PULLUP);
#if HAS_STEPPER
  for (byte b = 0; b < 4; b++) pinMode(STEP_PINS[b], OUTPUT);
#endif
#if USE_I2C_LCD
  Wire.begin();
  Wire.setClock(50000);        // slower I2C = tolerant of long breadboard wires
  delay(200);                  // let the LCD finish powering up
  byte addr = 0x27;
  for (byte a = 0x20; a < 0x40; a++) { Wire.beginTransmission(a); if (Wire.endTransmission() == 0) { addr = a; break; } }
  Serial.print(F("LCD I2C address: 0x")); Serial.println(addr, HEX);
  lcdp = new LiquidCrystal_I2C(addr, 20, 4);
  lcd.init(); delay(50); lcd.init(); lcd.backlight();   // double init re-syncs a scrambled LCD
#else
  lcd.begin(20, 4);
#endif
  lcd.createChar(3, cTL); lcd.createChar(4, cTR); lcd.createChar(5, cBL); lcd.createChar(6, cBR);
  randomSeed(analogRead(JX) * 31 + analogRead(JY));
  lcd.clear();
  lcdLine(1, "    J.A.R.V.I.S.");
  lcdLine(2, " systems booting...");
  delay(1200);
  Serial.println(F("JARVIS online. Type a message and press Enter (try: help)."));
  lastActivity = millis();
  greet();
}

void loop() {
  serialPoll();
  if (pendingKey) { char k = pendingKey; pendingKey = 0; handleKey(k); }
  char k = keypad.getKey();
  if (k) handleKey(k);
  joystickPoll();
  timerPoll();
  if (state == S_MUSIC) musicPoll();
  else if (state != S_TYPING) idlePoll();
  else if (millis() - lastActivity > 30000UL) endTyping();
}
