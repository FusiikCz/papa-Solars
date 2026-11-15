"""HTTP a WebSocket. Dashboard z internetu neotvírá port baterie."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from solar_diag.collector import Hub, build_hub
from solar_diag.storage import since_hours

WEB = Path(__file__).resolve().parents[2] / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub = await asyncio.to_thread(build_hub)
    app.state.hub = hub
    task = asyncio.create_task(hub.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.to_thread(hub.store.close)


app = FastAPI(title="Diagnostika Force H2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")


def hub() -> Hub:
    return app.state.hub


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    state = hub().public_state()
    return {"ok": True, "subnet": state["subnet"], "phase": state["phase"]}


@app.get("/api/live")
def live():
    return hub().public_state()


def _require(battery_id: int) -> None:
    known = hub().store.list_batteries()
    if not any(row["id"] == battery_id for row in known):
        raise HTTPException(status_code=404, detail="baterie není v diagnostice")


@app.get("/api/batteries/{battery_id}/history")
def history(battery_id: int, hours: int = 24):
    _require(battery_id)
    points = hub().store.history(battery_id, since_hours(hours))
    return {"battery_id": battery_id, "hours": min(max(hours, 1), 168), "points": points}


@app.get("/api/batteries/{battery_id}/events")
def events(battery_id: int, hours: int = 168):
    _require(battery_id)
    return {
        "battery_id": battery_id,
        "hours": min(max(hours, 1), 168),
        "events": hub().store.events(battery_id, since_hours(hours)),
    }


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    queue = hub().subscribe()
    try:
        await socket.send_json(hub().public_state())
        while True:
            payload = await queue.get()
            await socket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        hub().unsubscribe(queue)
