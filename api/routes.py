from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from api.auth import require_auth
from timeutils import local_day_bounds_utc

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
