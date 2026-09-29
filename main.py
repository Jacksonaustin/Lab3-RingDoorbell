"""Entry point: set up GPIO, then start the web server."""
import uvicorn

import events
from api import app

if __name__ == "__main__":
    events.setup()
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        events.cleanup()
