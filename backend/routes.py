"""
FastAPI route handlers.

Endpoints:
  POST /telegram/webhook — nhận Telegram updates (webhook mode, thay polling)
  GET  /session/current  — trả thông tin session hiện tại (Mini App dùng khi load)
  POST /trips/start      — nhận GPS đầu tiên, kích hoạt session
  POST /gps/update       — Mini App push GPS định kỳ (mỗi 30s)
  GET  /eta/current      — ETA hiện tại (debug / Mini App hiển thị)
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from telegram import Update

import backend.session_store as store
from backend.session_store import TripStatus
from backend.ors_client import get_eta_async

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    destination_name: str
    prep_time_seconds: int
    status: str


class GpsPayload(BaseModel):
    lat: float = Field(..., description="Latitude từ GPS điện thoại")
    lon: float = Field(..., description="Longitude từ GPS điện thoại")


class StartTripResponse(BaseModel):
    ok: bool
    message: str


class GpsUpdateResponse(BaseModel):
    ok: bool
    eta_seconds: float | None = None
    distance_meters: float | None = None


class EtaResponse(BaseModel):
    eta_seconds: float
    distance_meters: float
    prep_time_seconds: int
    should_wake: bool


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_active_session() -> store.TripSession:
    session = store.get_session()
    if not session:
        raise HTTPException(
            status_code=404,
            detail="Chua co hanh trinh nao. Hay chon diem xuong trong bot truoc.",
        )
    if session.status == TripStatus.DONE:
        raise HTTPException(
            status_code=409,
            detail="Hanh trinh da ket thuc. Got /start de bat dau lai.",
        )
    return session


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """
    Nhận Telegram updates qua webhook (production mode).
    Telegram POST json payload đến đây mỗi khi có message / callback.
    Lazy import backend.main để tránh circular import.
    """
    import backend.main as m  # noqa: PLC0415

    data = await request.json()
    update = Update.de_json(data, m.bot_app.bot)
    await m.bot_app.process_update(update)
    return {"ok": True}


@router.get("/session/current", response_model=SessionResponse)
async def get_current_session():
    """Mini App gọi khi load để hiển thị destination + prep time."""
    session = store.get_session()
    if not session:
        raise HTTPException(
            status_code=404,
            detail="Chua co hanh trinh nao. Hay chon diem xuong trong bot truoc.",
        )
    return SessionResponse(
        destination_name=session.destination_name,
        prep_time_seconds=session.prep_time_seconds,
        status=session.status.value,
    )


@router.post("/trips/start", response_model=StartTripResponse)
async def start_trip(body: GpsPayload):
    """
    Mini App gửi GPS đầu tiên.
    Cập nhật session với GPS và đánh dấu ACTIVE.
    Polling loop (T1.6) sẽ pick up session và bắt đầu tính ETA.
    """
    session = _require_active_session()
    session.last_lat = body.lat
    session.last_lon = body.lon
    session.status = TripStatus.ACTIVE
    logger.info("Trip started — gps=(%.5f, %.5f)", body.lat, body.lon)
    return StartTripResponse(
        ok=True,
        message=f"Dang theo doi hanh trinh den {session.destination_name}. Ban co the khoa man hinh.",
    )


@router.post("/gps/update", response_model=GpsUpdateResponse)
async def update_gps(body: GpsPayload):
    """
    Mini App push GPS định kỳ (mỗi 30s).
    Tính ETA ngay lập tức và trả về — Mini App có thể hiển thị ETA live.
    Polling loop (T1.6) cũng đọc GPS từ session này.
    """
    session = _require_active_session()
    session.last_lat = body.lat
    session.last_lon = body.lon
    logger.debug("GPS updated — (%.5f, %.5f)", body.lat, body.lon)

    try:
        result = await get_eta_async(
            current_coords=(body.lon, body.lat),
            destination_coords=session.destination_coords,
        )
        session.last_eta_seconds = result["eta_seconds"]
        return GpsUpdateResponse(
            ok=True,
            eta_seconds=result["eta_seconds"],
            distance_meters=result["distance_meters"],
        )
    except Exception as exc:
        logger.warning("ORS call failed on gps/update: %s", exc)
        # Không raise — GPS đã được lưu, ETA sẽ retry ở lần sau
        return GpsUpdateResponse(ok=True, eta_seconds=None)


@router.get("/eta/current", response_model=EtaResponse)
async def get_current_eta():
    """
    Tính ETA on-demand dùng GPS cuối cùng đã lưu trong session.
    Dùng để debug hoặc Mini App hiển thị countdown.
    """
    session = _require_active_session()
    if session.last_lat is None or session.last_lon is None:
        raise HTTPException(
            status_code=425,
            detail="Chua co GPS. Hay mo Mini App va cho phep vi tri.",
        )

    result = await get_eta_async(
        current_coords=(session.last_lon, session.last_lat),
        destination_coords=session.destination_coords,
    )
    session.last_eta_seconds = result["eta_seconds"]

    return EtaResponse(
        eta_seconds=result["eta_seconds"],
        distance_meters=result["distance_meters"],
        prep_time_seconds=session.prep_time_seconds,
        should_wake=result["eta_seconds"] <= session.prep_time_seconds,
    )
