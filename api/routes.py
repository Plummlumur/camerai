from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.auth import require_auth
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
def get_history(request: Request, days: int = 7) -> dict:
    state = request.app.state
    tz = ZoneInfo(state.settings.timezone)
    today = datetime.now(UTC).astimezone(tz).date()
    return {"days": state.store.daily_totals(days, tz, today)}


@router.post("/occupancy")
async def correct_occupancy(request: Request, correction: CorrectionRequest) -> dict:
    state = request.app.state
    occupancy = state.occupancy.set_count(correction.value)
    ts_utc = utc_now_iso()
    state.store.add_event(ts_utc, "correction", state.settings.sensor_id, value=occupancy)
    await state.hub.broadcast({"type": "correction", "occupancy": occupancy, "ts_utc": ts_utc})
    return {"occupancy": occupancy}
