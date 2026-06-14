"""
FastAPI web server — WebSocket event hub, MJPEG camera stream, static web UI.

Architecture:
  - EventHub: thread-safe broadcast from worker threads to all WS clients
    via asyncio.run_coroutine_threadsafe (loop grabbed on startup).
  - /camera.mjpeg: async MJPEG generator streamed from VectorBot camera.
  - /ws: WebSocket hub — receives user commands, broadcasts state events.
  - /  + /style.css + /app.js: serves web/ directory (buildless, no bundler).
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

if TYPE_CHECKING:
    from app import App

WEB_DIR = Path(__file__).parent.parent / "web"

app = FastAPI(title="Vector Companion", docs_url=None, redoc_url=None)

# ── Module-level state (set at startup by App) ────────────────────────────────

_loop: asyncio.AbstractEventLoop | None = None
_clients: set[WebSocket] = set()
_app_ref: App | None = None


def set_app(a: "App") -> None:
    global _app_ref
    _app_ref = a


# ── EventHub — thread-safe broadcast ─────────────────────────────────────────

def emit(event: dict[str, Any]) -> None:
    """
    Thread-safe broadcast: called from any thread (listen loop, turn worker).
    Serialises the event to JSON and schedules _broadcast on the asyncio loop.
    """
    if _loop is None or not _clients:
        return
    data = json.dumps(event)
    asyncio.run_coroutine_threadsafe(_broadcast(data), _loop)


async def _broadcast(data: str) -> None:
    dead: set[WebSocket] = set()
    for ws in list(_clients):
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _on_startup() -> None:
    global _loop
    _loop = asyncio.get_event_loop()


# ── Static file routes ────────────────────────────────────────────────────────

@app.get("/")
async def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/style.css")
async def style_css() -> FileResponse:
    return FileResponse(WEB_DIR / "style.css", media_type="text/css")


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")


# ── Camera MJPEG stream ───────────────────────────────────────────────────────

@app.get("/camera.mjpeg")
async def camera_stream() -> StreamingResponse:
    async def _gen():
        while True:
            frame = None
            if _app_ref is not None:
                try:
                    frame = _app_ref._bot.data.get_pil_frame()
                except Exception:
                    pass
            if frame is not None:
                buf = io.BytesIO()
                frame.convert("RGB").save(buf, "JPEG", quality=72)
                data = buf.getvalue()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + data
                    + b"\r\n"
                )
            else:
                # Send a 1×1 black placeholder so the stream doesn't stall
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8\xff\xd9\r\n"
            await asyncio.sleep(0.10)  # ≈10 fps

    return StreamingResponse(
        _gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ── WebSocket hub ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    # Send current state so the UI syncs on connect
    if _app_ref is not None:
        await ws.send_text(json.dumps({"type": "state", "state": _app_ref.state}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if _app_ref is not None:
                msg_type = msg.get("type", "")
                _app_ref.handle_command(msg_type, msg)
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
