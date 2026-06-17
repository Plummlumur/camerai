import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from api.auth import BasicAuthMiddleware
from api.hub import WebSocketHub
from api.routes import router
from config import Settings, get_settings
from counter.counting import LineCrossingCounter, OccupancyState
from counter.factory import build_source
from counter.preview import FrameBuffer
from counter.service import CounterService
from counter.tracker import CentroidTracker
from storage.events import EventStore
from timeutils import (
    occupancy_day_start_utc,
    parse_reset_time,
    seconds_until_next_reset,
    utc_now_iso,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tz = ZoneInfo(app_settings.timezone)
        reset_time = parse_reset_time(app_settings.nightly_reset_time)
        store = EventStore(app_settings.db_path)
        since = occupancy_day_start_utc(datetime.now(UTC), tz, reset_time)
        occupancy = OccupancyState(initial=store.replay_occupancy(since))
        hub = WebSocketHub()
        # Only the imx500 source produces preview frames; creating a buffer for
        # any other source would make /api/status report a preview that never
        # streams an image.
        frame_buffer = (
            FrameBuffer()
            if app_settings.camera_preview_enabled and app_settings.counter_source == "imx500"
            else None
        )
        event_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_event(payload: dict) -> None:
            try:
                loop.call_soon_threadsafe(event_queue.put_nowait, payload)
            except RuntimeError:
                pass  # loop already closed during shutdown

        service = CounterService(
            source=build_source(app_settings, frame_buffer=frame_buffer),
            tracker=CentroidTracker(),
            line_counter=LineCrossingCounter(
                line_position=app_settings.line_position,
                axis=app_settings.line_axis,
                invert=app_settings.invert_direction,
            ),
            occupancy=occupancy,
            store=store,
            sensor_id=app_settings.sensor_id,
            on_event=on_event,
        )
        counter_thread = threading.Thread(target=service.run, name="counter", daemon=True)
        counter_thread.start()

        async def pump_events() -> None:
            while True:
                payload = await event_queue.get()
                await hub.broadcast(payload)

        async def nightly_reset() -> None:
            while True:
                delay = seconds_until_next_reset(datetime.now(UTC), tz, reset_time)
                await asyncio.sleep(delay)
                occupancy.set_count(0)
                await hub.broadcast({"type": "reset", "occupancy": 0, "ts_utc": utc_now_iso()})

        background_tasks = [
            asyncio.create_task(pump_events()),
            asyncio.create_task(nightly_reset()),
        ]
        app.state.settings = app_settings
        app.state.store = store
        app.state.occupancy = occupancy
        app.state.hub = hub
        app.state.frame_buffer = frame_buffer
        yield
        service.stop()
        if frame_buffer is not None:
            frame_buffer.close()
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        counter_thread.join(timeout=2)
        store.close()

    app = FastAPI(title="Raumzaehler", lifespan=lifespan)
    if app_settings.auth_enabled and app_settings.auth_password_hash:
        app.add_middleware(
            BasicAuthMiddleware,
            username=app_settings.auth_username,
            password_hash=app_settings.auth_password_hash,
        )
    app.include_router(router)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        hub: WebSocketHub = websocket.app.state.hub
        await hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(websocket)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
