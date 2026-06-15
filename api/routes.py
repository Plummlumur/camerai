from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import require_auth
from counter.preview import FrameBuffer
from timeutils import local_day_bounds_utc, utc_now_iso

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def _today_bounds(request: Request) -> tuple[str, str]:
    tz = ZoneInfo(request.app.state.settings.timezone)
    today = datetime.now(UTC).astimezone(tz).date()
    return local_day_bounds_utc(today, tz)


@router.get("/status")
def get_status(request: Request) -> dict:
    state = request.app.state
    counts = state.store.counts_between(*_today_bounds(request))
    return {
        "occupancy": state.occupancy.count,
        "today_in": counts["in"],
        "today_out": counts["out"],
        "sensor_id": state.settings.sensor_id,
        "source": state.settings.counter_source,
        "preview_enabled": state.frame_buffer is not None,
        "line_position": state.settings.line_position,
        "line_axis": state.settings.line_axis,
    }


class CorrectionRequest(BaseModel):
    value: int = Field(ge=0)


@router.get("/stats/today")
def get_today_stats(request: Request) -> dict:
    state = request.app.state
    tz = ZoneInfo(state.settings.timezone)
    today = datetime.now(UTC).astimezone(tz).date()
    start, end = _today_bounds(request)
    return {"date": today.isoformat(), "hours": state.store.hourly_counts(start, end, tz)}


@router.get("/stats/history")
def get_history(request: Request, days: int = Query(default=7, ge=1, le=366)) -> dict:
    state = request.app.state
    tz = ZoneInfo(state.settings.timezone)
    today = datetime.now(UTC).astimezone(tz).date()
    return {"days": state.store.daily_totals(days, tz, today)}


def _mjpeg_frames(buffer: FrameBuffer) -> Iterator[bytes]:
    last_seq = 0
    # Short wait so a disconnected client frees its threadpool slot promptly
    # (Starlette steps this sync generator in a worker thread per connection).
    while not buffer.closed:
        last_seq, frame = buffer.wait_for(last_seq, timeout=1.0)
        if frame is None:
            continue
        yield (
            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame)
            + frame
            + b"\r\n"
        )


@router.get("/camera/stream")
def camera_stream(request: Request) -> StreamingResponse:
    buffer = request.app.state.frame_buffer
    if buffer is None:
        raise HTTPException(status_code=404, detail="camera preview is disabled")
    return StreamingResponse(
        _mjpeg_frames(buffer),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/occupancy")
async def correct_occupancy(request: Request, correction: CorrectionRequest) -> dict:
    state = request.app.state
    occupancy = state.occupancy.set_count(correction.value)
    ts_utc = utc_now_iso()
    state.store.add_event(ts_utc, "correction", state.settings.sensor_id, value=occupancy)
    await state.hub.broadcast({"type": "correction", "occupancy": occupancy, "ts_utc": ts_utc})
    return {"occupancy": occupancy}
