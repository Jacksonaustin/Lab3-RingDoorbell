"""FastAPI routes. The web page (static/index.html) calls these with fetch()."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import events

app = FastAPI(title="Doorbell")
STATIC_DIR = Path(__file__).parent / "static"


# Request bodies (FastAPI checks the JSON matches these for you)
class ArmBody(BaseModel):
    armed: bool


class ChimeBody(BaseModel):
    name: str


class NoteBody(BaseModel):
    note: str


class MorseBody(BaseModel):
    text: str
    wpm: int = Field(12, ge=5, le=40)  # words per minute


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status():
    return {
        "armed": events.state["armed"],
        "chime": events.state["chime"],
        "chimes": list(events.CHIMES),
        "notes": [n for n in events.NOTES if n != "REST"],
        "morse_progress": events.state["morse_progress"],
    }


@app.get("/api/log")
def get_log():
    return list(reversed(events.log))  # newest first


@app.post("/api/arm")
def set_armed(body: ArmBody):
    events.state["armed"] = body.armed
    events.add_log("armed" if body.armed else "disarmed")
    return {"armed": body.armed}


@app.post("/api/test/leds")
def test_leds():
    events.add_log("test", "LEDs")
    events.run_in_background(events.test_leds)
    return {"ok": True}


@app.post("/api/test/buzzer")
def test_buzzer():
    events.add_log("test", "buzzer")
    events.run_in_background(events.test_buzzer)
    return {"ok": True}


@app.post("/api/chime")
def select_chime(body: ChimeBody):
    if body.name not in events.CHIMES:
        raise HTTPException(404, "unknown chime")
    events.state["chime"] = body.name
    events.add_log("chime", "selected " + body.name)
    return {"chime": body.name}


@app.post("/api/chime/play")
def play_chime():
    events.run_in_background(events.play_chime, events.state["chime"])
    return {"ok": True}


@app.post("/api/piano")
def piano(body: NoteBody):
    if body.note not in events.NOTES:
        raise HTTPException(404, "unknown note")
    events.run_in_background(events.play_note, body.note)
    return {"ok": True}


@app.post("/api/morse")
def morse(body: MorseBody):
    if not events.to_morse(body.text):
        raise HTTPException(400, "nothing to send")
    events.run_in_background(events.send_morse, body.text, body.wpm)
    return {"morse": events.to_morse(body.text)}
