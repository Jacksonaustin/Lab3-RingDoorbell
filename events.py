"""Hardware + doorbell logic: IR sensor, LEDs, buzzer, chimes, piano, Morse, event log."""
import os
import threading
import time
from datetime import datetime

from gpiozero import LED, Buzzer, DigitalInputDevice, Device, PWMOutputDevice

# Run on a laptop without a Pi:  DOORBELL_MOCK=1 python main.py
if os.environ.get("DOORBELL_MOCK"):
    from gpiozero.pins.mock import MockFactory, MockPWMPin
    Device.pin_factory = MockFactory(pin_class=MockPWMPin)

# ---------------------------------------------------------------------------
# Pin config (BCM numbers, not physical pin numbers). Change to match your wiring.
# ---------------------------------------------------------------------------
SENSOR_PIN = 22
LED_PINS = [18, 26]
BUZZER_PIN = 17

# Passive buzzer = can play real notes with PWM. Active buzzer = one pitch only.
# Test: an active buzzer beeps when you just connect it to 3.3V; a passive one doesn't.
PASSIVE_BUZZER = True

LOG_FILE = "doorbell.log"

# A visitor only rings again after the sensor has seen NOTHING for this long.
# The timer restarts on every detection, so someone standing at the door (and the
# sensor flickering on/off while they move) counts as one visit. 5 s is longer than
# the whole chime plus a person shuffling around, but short enough that a second
# visitor a little later still gets a ring.
COOLDOWN_SECONDS = 5.0

sensor = None
leds = []
buzzer = None

# Shared state the web page reads/writes
state = {
    "armed": True,
    "chime": "front_door",
    "last_seen": -COOLDOWN_SECONDS,  # time.monotonic() of the last sensor trigger
    "morse_progress": "",  # dots/dashes sent so far, so the page can show it live
}
log = []                   # list of dicts: {"time", "type", "detail"}

_play_lock = threading.Lock()  # only one sound at a time


# ---------------------------------------------------------------------------
# Setup / cleanup (called from main.py)
# ---------------------------------------------------------------------------
def setup():
    global sensor, leds, buzzer
    # Most IR obstacle modules pull OUT low when something is in front of them,
    # so pull_up=True makes "is_active" mean "obstacle detected".
    sensor = DigitalInputDevice(SENSOR_PIN, pull_up=True)
    leds = [LED(p) for p in LED_PINS]
    buzzer = PWMOutputDevice(BUZZER_PIN) if PASSIVE_BUZZER else Buzzer(BUZZER_PIN)

    sensor.when_activated = on_visitor
    add_log("system", "doorbell started")


def cleanup():
    all_off()
    for dev in [sensor, buzzer, *leds]:
        if dev:
            dev.close()


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------
def add_log(kind, detail=""):
    entry = {
        "time": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "type": kind,
        "detail": detail,
    }
    log.append(entry)
    with open(LOG_FILE, "a") as f:
        f.write(f"{entry['time']}\t{kind}\t{detail}\n")
    return entry


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def leds_on():
    for led in leds:
        led.on()


def leds_off():
    for led in leds:
        led.off()


def all_off():
    leds_off()
    if buzzer:
        buzzer.off()


def tone(freq, seconds):
    """Play one note. freq=0 means a rest (silence)."""
    if freq:
        if PASSIVE_BUZZER:
            buzzer.frequency = freq
            buzzer.value = 0.5  # 50% duty cycle = loudest square wave
        else:
            buzzer.on()          # active buzzer ignores freq
    time.sleep(seconds)
    buzzer.off()


def run_in_background(fn, *args):
    """Run a sound function in a thread so the web request returns immediately.
    If something is already playing, this call is skipped."""
    def worker():
        if not _play_lock.acquire(blocking=False):
            return
        try:
            fn(*args)
        finally:
            all_off()
            _play_lock.release()

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Notes, chimes, piano
# ---------------------------------------------------------------------------
NOTES = {
    "C4": 262, "C#4": 277, "D4": 294, "D#4": 311, "E4": 330, "F4": 349,
    "F#4": 370, "G4": 392, "G#4": 415, "A4": 440, "A#4": 466, "B4": 494,
    "C5": 523, "C#5": 554, "D5": 587, "D#5": 622, "E5": 659, "F5": 698,
    "F#5": 740, "G5": 784, "G#5": 831, "A5": 880, "A#5": 932, "B5": 988,
    "C6": 1047,
    "REST": 0,
}

MORSE_FREQ = 700  # Hz, a typical Morse "beep" pitch

# Each chime is a list of (note, seconds).
CHIMES = {
    "front_door": [("E5", 0.5), ("C5", 0.8)],  # classic "ding-dong"
    "double_beep": [("A5", 0.12), ("REST", 0.08), ("A5", 0.12)],
    "rising_arpeggio": [("C5", 0.15), ("E5", 0.15), ("G5", 0.15), ("C6", 0.4)],
}


def play_chime(name):
    for i, (note, seconds) in enumerate(CHIMES[name]):
        # Alternate which LED is lit on each note so they flash with the chime
        for j, led in enumerate(leds):
            led.value = (i + j) % 2 == 0
        tone(NOTES[note], seconds)
        time.sleep(0.05)  # small gap so repeated notes don't blur together
    leds_off()


def play_note(note):
    # Passive buzzer: PWM at the note's frequency plays the real pitch.
    tone(NOTES[note], 0.3)


def test_leds():
    leds_on()
    time.sleep(1)
    leds_off()


def test_buzzer():
    tone(NOTES["A4"], 0.5)


# ---------------------------------------------------------------------------
# Doorbell
# ---------------------------------------------------------------------------
def on_visitor():
    """Called by gpiozero every time the IR sensor sees something."""
    now = time.monotonic()
    quiet_for = now - state["last_seen"]
    state["last_seen"] = now
    if quiet_for < COOLDOWN_SECONDS:
        return  # same visitor still there -> don't ring or log again

    if state["armed"]:
        add_log("visitor", "rang " + state["chime"])
        run_in_background(play_chime, state["chime"])
    else:
        add_log("visitor", "disarmed - silent")


# ---------------------------------------------------------------------------
# Morse
# ---------------------------------------------------------------------------
MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}


def to_morse(text):
    """'SOS HI' -> '... --- ... / .... ..'  (space between letters, / between words)"""
    words = []
    for word in text.upper().split():
        letters = [MORSE[ch] for ch in word if ch in MORSE]  # skip unknown characters
        if letters:
            words.append(" ".join(letters))
    return " / ".join(words)


def send_morse(text, wpm):
    # Standard timing: dot = 1 unit, dash = 3, gap inside letter = 1,
    # between letters = 3, between words = 7.  PARIS standard: unit = 1.2 / wpm seconds.
    unit = 1.2 / wpm
    code = to_morse(text)
    state["morse_progress"] = ""
    add_log("morse", f"{text} ({wpm} wpm)")

    for w, word in enumerate(code.split(" / ")):
        if w > 0:
            state["morse_progress"] += " / "
            time.sleep(7 * unit)
        for l, letter in enumerate(word.split(" ")):
            if l > 0:
                state["morse_progress"] += " "
                time.sleep(3 * unit)
            for i, symbol in enumerate(letter):
                if i > 0:
                    time.sleep(unit)
                state["morse_progress"] += symbol
                leds_on()
                tone(MORSE_FREQ, unit if symbol == "." else 3 * unit)
                leds_off()
