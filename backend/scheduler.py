"""
ETA polling loop — background asyncio task.

M2 improvements:
  - Dynamic poll interval theo ETA bands → tiết kiệm ORS quota
      ETA > 30 min  → poll mỗi 5 phút
      ETA 10–30 min → poll mỗi 2 phút
      ETA < 10 min  → poll mỗi 30 giây
  - ETA smoothing: median của ETA_WINDOW_SIZE lần đo gần nhất
      → tránh false alarm khi GPS noise làm ETA nhảy loạn
      → cần ít nhất ⌈N/2⌉ lần đo liên tiếp < prep_time để trigger alert
  - Wake alert retry: nếu user không ack sau WAKE_RETRY_AFTER giây,
      gửi lại tối đa WAKE_MAX_RETRIES lần
  - Escalation spam khi người dùng không phản hồi:
      retry #0 → ntfy priority=high
      retry #1 → spam 3 tin ⏰ + ntfy priority=urgent (bypass DND)
      retry #2 → spam 5 tin 🚨 + voice TTS + ntfy priority=max (alarm toàn màn hình)
"""
import asyncio
import io
import logging
import statistics
import time

import httpx
from gtts import gTTS
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

import backend.session_store as store
from backend.session_store import TripStatus
from backend.ors_client import get_eta_async
from backend.config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ETA bands → poll interval
ETA_BAND_FAR_S   = 30 * 60    # 30 phút
ETA_BAND_NEAR_S  = 10 * 60    # 10 phút

POLL_FAR     = 5 * 60         # > 30 min ETA  → poll mỗi 5 phút
POLL_NEAR    = 2 * 60         # 10–30 min ETA → poll mỗi 2 phút
POLL_CLOSE   = 30             # < 10 min ETA  → poll mỗi 30 giây
POLL_NO_GPS  = 60             # chưa có GPS   → poll mỗi 1 phút

# ETA smoothing
ETA_WINDOW_SIZE = 3           # median của 3 lần đo gần nhất

# Wake alert retry
WAKE_RETRY_AFTER = 3 * 60    # retry nếu chưa ack sau 3 phút
WAKE_MAX_RETRIES = 3         # tối đa 3 lần retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_poll_interval(session: store.TripSession | None) -> int:
    """Tính poll interval dựa trên smoothed ETA hiện tại."""
    if session is None or session.last_eta_seconds is None:
        return POLL_NO_GPS
    eta = session.last_eta_seconds
    if eta > ETA_BAND_FAR_S:
        return POLL_FAR
    if eta > ETA_BAND_NEAR_S:
        return POLL_NEAR
    return POLL_CLOSE


# ---------------------------------------------------------------------------
# Wake alert message
# ---------------------------------------------------------------------------

def _wake_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tôi dậy rồi",       callback_data="wake_ack")],
        [InlineKeyboardButton("💤 Nhắc lại 5 phút",    callback_data="wake_snooze")],
        [InlineKeyboardButton("🛑 Dừng theo dõi",       callback_data="wake_stop")],
    ])


async def _spam_ping(bot_app: Application, count: int, emoji: str, delay: float) -> None:
    """Gửi liên tiếp `count` tin nhắn ngắn để kích notification nhiều lần."""
    for i in range(count):
        await bot_app.bot.send_message(
            chat_id=config.OWNER_CHAT_ID,
            text=emoji,
        )
        if i < count - 1:
            await asyncio.sleep(delay)


async def _send_voice_alert(bot_app: Application, destination_name: str, eta_min: int) -> None:
    """
    Tạo voice message TTS tiếng Việt và gửi đến OWNER_CHAT_ID.
    Telegram sẽ tự phát âm thanh — hiệu quả như một cuộc gọi.
    Chạy gTTS trong executor để không block event loop.
    """
    text = (
        f"Thức dậy! Thức dậy! "
        f"Còn khoảng {eta_min} phút nữa là đến {destination_name}. "
        f"Hãy chuẩn bị xuống xe ngay!"
    )

    loop = asyncio.get_event_loop()

    def _generate_mp3() -> bytes:
        buf = io.BytesIO()
        gTTS(text=text, lang="vi").write_to_fp(buf)
        buf.seek(0)
        return buf.read()

    try:
        mp3_bytes = await loop.run_in_executor(None, _generate_mp3)
        audio_buf = io.BytesIO(mp3_bytes)
        audio_buf.name = "wake_alert.mp3"
        await bot_app.bot.send_voice(
            chat_id=config.OWNER_CHAT_ID,
            voice=audio_buf,
            caption="🔊 <b>Tin nhắn thoại khẩn cấp</b>",
            parse_mode="HTML",
        )
        logger.info("Voice alert sent via gTTS — text: %s", text)
    except Exception as exc:
        logger.error("Failed to send voice alert: %s", exc)


async def _ntfy_post(title: str, body: str, priority: str, tags: str) -> None:
    """Gửi một ntfy notification, raise nếu lỗi."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://ntfy.sh/{config.NTFY_TOPIC}",
            content=body.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        resp.raise_for_status()


async def _send_ntfy_alert(destination_name: str, eta_min: int, retry: int) -> None:
    """
    Gửi push notification qua ntfy.sh — bypass chế độ im lặng / DND trên Android.

    Priority mapping:
      retry 0 → high    (notification bình thường, có âm thanh)
      retry 1 → urgent  (bypass DND)
      retry 2 → max x5  (5 ping cách nhau 4 giây → loop như báo thức ~20 giây)

    Yêu cầu: cài app ntfy trên điện thoại + subscribe đúng topic.
    Trong app ntfy: subscription settings → chọn âm thanh "alarm" + bật DND override.
    """
    if not config.NTFY_TOPIC:
        return

    if retry == 0:
        title = "Sap den tram roi!"
        tags = "alarm_clock"
        priority = "high"
    elif retry == 1:
        title = f"Sap den! (nhac lai #{retry})"
        tags = "alarm_clock,loudspeaker"
        priority = "urgent"
    else:
        title = f"KHAN CAP - THUC DAY NGAY! (lan {retry})"
        tags = "rotating_light,alarm_clock,sos"
        priority = "max"

    body = f"Con {eta_min} phut den {destination_name}. Chuan bi xuong xe!"

    try:
        if retry >= 2:
            # Gửi 5 ping liên tiếp, cách nhau 4 giây → ~20 giây kêu như báo thức
            ALARM_PINGS   = 5
            ALARM_INTERVAL = 4  # giây

            logger.info(
                "ntfy alarm loop: %d pings × %ds — topic=%s",
                ALARM_PINGS, ALARM_INTERVAL, config.NTFY_TOPIC,
            )
            for i in range(ALARM_PINGS):
                ping_title = f"{title} ({i + 1}/{ALARM_PINGS})"
                await _ntfy_post(ping_title, body, priority, tags)
                if i < ALARM_PINGS - 1:
                    await asyncio.sleep(ALARM_INTERVAL)
        else:
            await _ntfy_post(title, body, priority, tags)
            logger.info("ntfy alert sent (priority=%s) — topic=%s", priority, config.NTFY_TOPIC)
    except Exception as exc:
        logger.error("Failed to send ntfy alert: %s", exc)


async def send_wake_alert(bot_app: Application, session: store.TripSession) -> None:
    """
    Gửi tin nhắn cảnh báo đến OWNER_CHAT_ID, có leo thang theo retry:
      - retry 0: alert bình thường
      - retry 1: alert + spam 3 ⏰ (1 giây/tin) → nhiều notification hơn
      - retry 2+: alert + spam 5 🚨 (0.5 giây/tin) + nhắn gọi điện khẩn
    """
    eta_min = round((session.last_eta_seconds or 0) / 60)
    retry = session.wake_retry_count

    if retry == 0:
        header = "⏰ <b>SẮP ĐẾN TRẠM!</b>"
    elif retry == 1:
        header = "⏰⏰ <b>SẮP ĐẾN TRẠM! (nhắc lại #1)</b>"
    else:
        header = f"🚨🚨 <b>KHẨN CẤP — NHẮC LẦN {retry}!</b> 🚨🚨"

    text = (
        f"{header}\n\n"
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

    # ntfy push notification — mọi retry đều gửi, priority tăng dần
    await _send_ntfy_alert(session.destination_name, eta_min, retry)

    # Leo thang Telegram: spam thêm tin để trigger nhiều notification
    if retry == 1:
        await asyncio.sleep(0.5)
        await _spam_ping(bot_app, count=3, emoji="⏰", delay=1.0)
    elif retry >= 2:
        await asyncio.sleep(0.5)
        await _spam_ping(bot_app, count=5, emoji="🚨", delay=0.5)
        # Gửi voice message TTS — phát tiếng nói to qua loa điện thoại
        await _send_voice_alert(bot_app, session.destination_name, eta_min)

    logger.info(
        "Wake alert sent (retry=%d, ntfy=%s, escalation=%s) — eta=%.0fs",
        retry,
        "yes" if config.NTFY_TOPIC else "skip",
        "none" if retry == 0 else f"spam×{'3' if retry == 1 else '5'}",
        session.last_eta_seconds or 0,
    )


# ---------------------------------------------------------------------------
# Single poll tick
# ---------------------------------------------------------------------------

async def _tick(bot_app: Application) -> None:
    session = store.get_session()
    if not session:
        return

    # --- WAKING: kiểm tra có cần retry không ---
    if session.status == TripStatus.WAKING:
        if (
            session.wake_retry_count < WAKE_MAX_RETRIES
            and session.wake_sent_at is not None
            and time.time() - session.wake_sent_at >= WAKE_RETRY_AFTER
        ):
            session.wake_retry_count += 1
            session.wake_sent_at = time.time()
            logger.info("Retrying wake alert #%d", session.wake_retry_count)
            await send_wake_alert(bot_app, session)
        return

    # --- Chỉ process khi ACTIVE ---
    if session.status != TripStatus.ACTIVE:
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

    raw_eta = result["eta_seconds"]

    # --- ETA Smoothing: cập nhật sliding window, dùng median ---
    session.eta_window.append(raw_eta)
    if len(session.eta_window) > ETA_WINDOW_SIZE:
        session.eta_window.pop(0)

    smoothed_eta = statistics.median(session.eta_window)
    session.last_eta_seconds = smoothed_eta

    logger.info(
        "Scheduler tick — raw=%.0fs smooth=%.0fs dist=%.0fm prep=%ds window=%s",
        raw_eta, smoothed_eta, result["distance_meters"],
        session.prep_time_seconds,
        [round(e) for e in session.eta_window],
    )

    if smoothed_eta <= session.prep_time_seconds:
        session.status = TripStatus.WAKING
        session.wake_sent_at = time.time()
        await send_wake_alert(bot_app, session)


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------

async def _poll_loop(bot_app: Application) -> None:
    logger.info("Scheduler started — dynamic polling (ETA bands)")
    while True:
        try:
            await _tick(bot_app)
        except Exception as exc:
            logger.error("Scheduler: unexpected error in tick — %s", exc, exc_info=True)

        session = store.get_session()
        interval = _get_poll_interval(session)
        logger.debug("Next poll in %ds", interval)
        await asyncio.sleep(interval)


def start_scheduler(bot_app: Application) -> asyncio.Task:
    """
    Tạo background task cho polling loop.
    Gọi trong FastAPI lifespan sau khi bot đã start.
    Trả về Task để lifespan có thể cancel khi shutdown.
    """
    task = asyncio.create_task(_poll_loop(bot_app))
    return task
