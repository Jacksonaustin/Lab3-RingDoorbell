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
SENSOR_PIN = 17
LED_PINS = [22, 27]
BUZZER_PIN = 18

# Passive buzzer = can play real notes with PWM. Active buzzer = one pitch only.
# Test: an active buzzer beeps when you just connect it to 3.3V; a passive one doesn't.
PASSIVE_BUZZER = True

LOG_FILE = "doorbell.log"

# TODO: pick a delay and explain why in your write-up.
COOLDOWN_SECONDS = 5.0

sensor = None
leds = []
buzzer = None

# Shared state the web page reads/writes
state = {
    "armed": True,
    "chime": "front_door",
    "last_ring": 0.0,      # time.monotonic() of the last visitor that actually rang
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
    "C5": 523, "D5": 587, "E5": 659, "G5": 784,
    "REST": 0,
}

# Each chime is a list of (note, seconds).
CHIMES = {
    "front_door": [("E5", 0.5), ("C5", 0.8)],  # classic "ding-dong"
    "double_beep": [],                         # TODO
    "my_chime": [],                            # TODO: your own
}


def play_chime(name):
    # TODO: look up CHIMES[name], and for each (note, seconds):
    #   - turn LEDs on (or toggle them) so they flash with the chime
    #   - call tone(NOTES[note], seconds)
    #   - short gap between notes, e.g. time.sleep(0.05)
    pass


def play_note(note):
    # TODO: piano key pressed. Passive: tone(NOTES[note], 0.3).
    # Active buzzer: map each key to its own rhythm pattern instead (document this!).
    pass


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

    # TODO: cooldown. If less than COOLDOWN_SECONDS since state["last_ring"], return.
    #       Otherwise update state["last_ring"] = now.

    add_log("visitor", "armed" if state["armed"] else "disarmed")

    # TODO: only chime/flash when armed (visits are logged either way).
    run_in_background(play_chime, state["chime"])


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
    # TODO: uppercase text, split into words, look each letter up in MORSE.
    return ""


def send_morse(text, wpm):
    # Standard timing: dot = 1 unit, dash = 3, gap inside letter = 1,
    # between letters = 3, between words = 7.  PARIS standard: unit = 1.2 / wpm seconds.
    unit = 1.2 / wpm
    state["morse_progress"] = ""
    # TODO: walk through to_morse(text). For each symbol:
    #   '.'  -> LEDs on + tone(freq, unit), LEDs off
    #   '-'  -> LEDs on + tone(freq, 3 * unit), LEDs off
    #   after each symbol sleep 1 unit; between letters 3 total; between words 7 total
    #   append the symbol to state["morse_progress"] so the page can show it
    add_log("morse", text)
