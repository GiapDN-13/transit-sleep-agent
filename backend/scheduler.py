"""
ETA polling loop — background asyncio task.

Chạy mỗi POLL_INTERVAL giây:
  1. Đọc session hiện tại
  2. Nếu ACTIVE và có GPS → gọi ORS lấy ETA
  3. Nếu ETA ≤ prep_time → gửi wake alert qua Telegram, chuyển status → WAKING

Không re-send nếu đã WAKING (T1.7 sẽ reset về ACTIVE khi user snooze).
Tự dừng khi session DONE hoặc không có session.
"""
import asyncio
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

import backend.session_store as store
from backend.session_store import TripStatus
from backend.ors_client import get_eta_async
from backend.config import config

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30  # giây


# ---------------------------------------------------------------------------
# Wake alert message
# ---------------------------------------------------------------------------

def _wake_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tôi dậy rồi",       callback_data="wake_ack")],
        [InlineKeyboardButton("💤 Nhắc lại 5 phút",    callback_data="wake_snooze")],
        [InlineKeyboardButton("🛑 Dừng theo dõi",       callback_data="wake_stop")],
    ])


async def send_wake_alert(bot_app: Application, session: store.TripSession) -> None:
    """Gửi tin nhắn cảnh báo đến OWNER_CHAT_ID."""
    eta_min = round((session.last_eta_seconds or 0) / 60)
    dist_m  = ""
    text = (
        f"⏰ <b>SẮP ĐẾN TRẠM!</b>\n\n"
        f"📍 Điểm xuống: <b>{session.destination_name}</b>\n"
        f"🕐 ETA còn khoảng: <b>{eta_min} phút</b>\n\n"
        f"Bạn muốn làm gì?"
    )
    await bot_app.bot.send_message(
        chat_id=config.OWNER_CHAT_ID,
        text=text,
        reply_markup=_wake_keyboard(),
        parse_mode="HTML",
    )
    logger.info("Wake alert sent — eta=%.0fs", session.last_eta_seconds or 0)


# ---------------------------------------------------------------------------
# Single poll tick
# ---------------------------------------------------------------------------

async def _tick(bot_app: Application) -> None:
    session = store.get_session()

    if not session:
        return

    if session.status not in (TripStatus.ACTIVE,):
        return

    # Snooze: bỏ qua cho đến khi hết thời gian snooze
    if session.snooze_until and time.time() < session.snooze_until:
        remaining = round(session.snooze_until - time.time())
        logger.debug("Scheduler: snoozed for %ds more", remaining)
        return

    if session.last_lat is None or session.last_lon is None:
        logger.debug("Scheduler tick: no GPS yet, skipping")
        return

    try:
        result = await get_eta_async(
            current_coords=(session.last_lon, session.last_lat),
            destination_coords=session.destination_coords,
        )
    except Exception as exc:
        logger.warning("Scheduler: ORS call failed — %s", exc)
        return

    session.last_eta_seconds = result["eta_seconds"]
    eta = result["eta_seconds"]
    logger.info(
        "Scheduler tick — eta=%.0fs (%.0fm), prep=%ds",
        eta, result["distance_meters"], session.prep_time_seconds,
    )

    if eta <= session.prep_time_seconds:
        session.status = TripStatus.WAKING
        session.wake_sent_at = time.time()
        await send_wake_alert(bot_app, session)


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------

async def _poll_loop(bot_app: Application) -> None:
    logger.info("Scheduler started — polling every %ds", POLL_INTERVAL)
    while True:
        try:
            await _tick(bot_app)
        except Exception as exc:
            logger.error("Scheduler: unexpected error in tick — %s", exc, exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)


def start_scheduler(bot_app: Application) -> asyncio.Task:
    """
    Tạo background task cho polling loop.
    Gọi trong FastAPI lifespan sau khi bot đã start.
    Trả về Task để lifespan có thể cancel khi shutdown.
    """
    task = asyncio.create_task(_poll_loop(bot_app))
    return task
