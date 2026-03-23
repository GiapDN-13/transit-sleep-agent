"""
Telegram Bot — handlers và application factory.

Luồng chính:
  /start
    → [🗺️ Chọn trên bản đồ] (web_app, mode=pick)  ← MỚI
    → HOẶC chọn điểm từ danh sách (callback: dest:<id>)
    → chọn prep time (callback: prep:<seconds>)
    → [📍 Bắt đầu theo dõi] (web_app, mode=track)

  /help  — hướng dẫn sử dụng
  /status — trạng thái hành trình hiện tại
"""
import json
import logging
import time

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.config import config
from backend.destinations import DESTINATION_MAP, DESTINATIONS, PREP_TIME_OPTIONS
from backend.session_store import TripStatus
import backend.session_store as store
from backend.trip_logger import record_trip

SNOOZE_SECONDS = 5 * 60

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dest_name(dest) -> str:
    """Lấy tên điểm — dest có thể là Destination dataclass hoặc dict từ Mini App."""
    return dest.name if hasattr(dest, "name") else dest["name"]


def _dest_coords(dest) -> tuple[float, float]:
    """Lấy (lon, lat) — dest có thể là Destination dataclass hoặc dict từ Mini App."""
    if hasattr(dest, "coords"):
        return dest.coords
    return (dest["lon"], dest["lat"])


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------

def _map_pick_keyboard() -> ReplyKeyboardMarkup:
    """
    Reply keyboard với nút mở Mini App (pick mode).
    Dùng KeyboardButton thay vì InlineKeyboardButton vì Telegram.WebApp.sendData()
    chỉ hoạt động khi Mini App được mở từ KeyboardButton (reply keyboard),
    KHÔNG phải InlineKeyboardButton.
    """
    return ReplyKeyboardMarkup(
        [[
            KeyboardButton(
                text="🗺️ Chọn điểm trên bản đồ",
                web_app=WebAppInfo(url=f"{config.MINI_APP_URL}?mode=pick"),
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _preset_inline_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard chỉ với danh sách preset destinations."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text=d.name, callback_data=f"dest:{d.id}")]
        for d in DESTINATIONS
    ])


def _prep_time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text=label, callback_data=f"prep:{seconds}")]
        for label, seconds in PREP_TIME_OPTIONS
    ])


def _open_miniapp_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="📍 Bắt đầu theo dõi hành trình",
                web_app=WebAppInfo(url=f"{config.MINI_APP_URL}?mode=track"),
            )
        ],
        [InlineKeyboardButton(text="↩️ Chọn lại", callback_data="restart")],
    ])


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    store.clear_session()
    # Gửi reply keyboard trước để hiện nút mở bản đồ
    # (KeyboardButton.web_app mới hỗ trợ sendData() từ Mini App)
    await update.message.reply_text(
        text=(
            "🚌 <b>Transit Sleep Agent</b>\n\n"
            "Nhấn nút bên dưới để chọn điểm xuống trên bản đồ:"
        ),
        reply_markup=_map_pick_keyboard(),
        parse_mode="HTML",
    )
    await update.message.reply_text(
        text="📍 Hoặc chọn nhanh từ danh sách có sẵn:",
        reply_markup=_preset_inline_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        text=(
            "🚌 <b>Transit Sleep Agent — Hướng dẫn</b>\n\n"
            "<b>Cách dùng:</b>\n"
            "1. Gõ /start\n"
            "2. Chọn điểm xuống <i>(từ danh sách hoặc nhấn 🗺️ để chọn trên bản đồ)</i>\n"
            "3. Chọn thời gian báo thức trước khi đến\n"
            "4. Nhấn <b>Bắt đầu theo dõi</b> → Mini App lấy GPS\n"
            "5. Khoá màn hình — bot sẽ nhắn khi sắp đến trạm\n\n"
            "<b>Lệnh:</b>\n"
            "/start — Bắt đầu chuyến đi mới\n"
            "/status — Xem trạng thái hành trình đang chạy\n"
            "/help — Hướng dẫn này\n\n"
            "<b>Khi nhận cảnh báo:</b>\n"
            "✅ <b>Tôi dậy rồi</b> — Xác nhận, kết thúc theo dõi\n"
            "💤 <b>Nhắc lại 5 phút</b> — Snooze, báo lại sau 5 phút\n"
            "🛑 <b>Dừng</b> — Hủy theo dõi hoàn toàn"
        ),
        parse_mode="HTML",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = store.get_session()
    if not session:
        await update.message.reply_text(
            "ℹ️ Không có hành trình nào đang chạy.\nGõ /start để bắt đầu."
        )
        return

    eta_text = "Chưa có dữ liệu GPS"
    if session.last_eta_seconds is not None:
        m = round(session.last_eta_seconds / 60)
        eta_text = f"~{m} phút"

    gps_text = "Chưa có" if session.last_lat is None else f"{session.last_lat:.5f}, {session.last_lon:.5f}"

    status_emoji = {
        TripStatus.ACTIVE:  "🟢",
        TripStatus.WAKING:  "🔔",
        TripStatus.DONE:    "✅",
        TripStatus.IDLE:    "⏸️",
    }.get(session.status, "❓")

    prep_min = session.prep_time_seconds // 60
    await update.message.reply_text(
        text=(
            f"<b>Trạng thái hành trình</b>\n\n"
            f"{status_emoji} Trạng thái: <b>{session.status.value}</b>\n"
            f"📍 Điểm xuống: <b>{session.destination_name}</b>\n"
            f"⏰ Báo thức trước: <b>{prep_min} phút</b>\n"
            f"🛰️ GPS hiện tại: <code>{gps_text}</code>\n"
            f"🕐 ETA: <b>{eta_text}</b>"
        ),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------

async def cb_destination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User chọn điểm từ danh sách preset → hỏi prep time."""
    query = update.callback_query
    await query.answer()

    dest_id = query.data.split(":", 1)[1]
    dest = DESTINATION_MAP.get(dest_id)
    if not dest:
        await query.edit_message_text("❌ Điểm xuống không hợp lệ. Gõ /start để thử lại.")
        return

    context.user_data["destination"] = dest
    await query.edit_message_text(
        text=f"📍 Điểm xuống: <b>{dest.name}</b>\n\nBạn muốn được báo thức trước bao lâu?",
        reply_markup=_prep_time_keyboard(),
        parse_mode="HTML",
    )


async def cb_prep_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User chọn prep time → tạo session + hiện nút mở Mini App (track mode)."""
    query = update.callback_query
    await query.answer()

    dest = context.user_data.get("destination")
    if not dest:
        await query.edit_message_text("❌ Phiên đã hết hạn. Gõ /start để bắt đầu lại.")
        return

    prep_seconds = int(query.data.split(":", 1)[1])
    prep_label = next(
        (label for label, sec in PREP_TIME_OPTIONS if sec == prep_seconds),
        f"{prep_seconds // 60} phút",
    )

    dest_name   = _dest_name(dest)
    dest_coords = _dest_coords(dest)

    store.create_session(
        destination_name=dest_name,
        destination_coords=dest_coords,
        prep_time_seconds=prep_seconds,
    )
    logger.info("Session created — dest=%s prep=%ds", dest_name, prep_seconds)

    await query.edit_message_text(
        text=(
            f"✅ <b>Đã lưu hành trình</b>\n\n"
            f"📍 Điểm xuống: <b>{dest_name}</b>\n"
            f"⏰ Báo thức trước: <b>{prep_label}</b>\n\n"
            "Bấm nút bên dưới, Mini App sẽ lấy GPS và bắt đầu theo dõi."
        ),
        reply_markup=_open_miniapp_keyboard(),
        parse_mode="HTML",
    )


async def cb_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    store.clear_session()
    # Xoá inline keyboard của message cũ
    await query.edit_message_text(text="↩️ Đã reset. Bắt đầu chuyến mới:")
    # Gửi lại cả hai keyboard (reply + inline) như cmd_start
    await query.message.reply_text(
        text=(
            "🚌 <b>Transit Sleep Agent</b>\n\n"
            "Nhấn nút bên dưới để chọn điểm xuống trên bản đồ:"
        ),
        reply_markup=_map_pick_keyboard(),
        parse_mode="HTML",
    )
    await query.message.reply_text(
        text="📍 Hoặc chọn nhanh từ danh sách có sẵn:",
        reply_markup=_preset_inline_keyboard(),
    )


async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Nhận dữ liệu từ Mini App (mode=pick) khi user xác nhận điểm xuống trên bản đồ.
    Payload: { "name": str, "lat": float, "lon": float }
    Lưu ý: sendData() chỉ hoạt động khi Mini App được mở từ KeyboardButton.
    """
    raw = update.message.web_app_data.data
    try:
        data = json.loads(raw)
        name = data["name"]
        lat  = float(data["lat"])
        lon  = float(data["lon"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Invalid WebApp data: %s — %s", raw, e)
        await update.message.reply_text("❌ Dữ liệu từ bản đồ không hợp lệ. Thử lại nhé.")
        return

    context.user_data["destination"] = {"name": name, "lat": lat, "lon": lon}
    logger.info("Destination from map: %s (%.5f, %.5f)", name, lat, lon)

    # Xoá reply keyboard (bản đồ) rồi hỏi prep time bằng inline keyboard
    await update.message.reply_text(
        text=f"📍 Điểm xuống: <b>{name}</b>\n\nBạn muốn được báo thức trước bao lâu?",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    await update.message.reply_text(
        text="⏰ Chọn thời gian báo thức trước:",
        reply_markup=_prep_time_keyboard(),
    )


# ---------------------------------------------------------------------------
# Wake alert handlers
# ---------------------------------------------------------------------------

async def cb_wake_ack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("✅ Chúc bạn xuống xe an toàn!")
    session = store.get_session()
    dest_name = session.destination_name if session else "điểm đến"
    if session:
        record_trip(session, "ack")
    store.clear_session()
    await query.edit_message_text(
        text=f"✅ <b>Đã ghi nhận!</b>\n\nChúc bạn xuống xe an toàn tại <b>{dest_name}</b>. 🚶",
        parse_mode="HTML",
    )
    logger.info("Trip ACK'd — session cleared")


async def cb_wake_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("💤 Nhắc lại sau 5 phút")
    session = store.get_session()
    if not session:
        await query.edit_message_text("❌ Hành trình đã kết thúc. Gõ /start để bắt đầu lại.")
        return
    session.status       = TripStatus.ACTIVE
    session.snooze_until = time.time() + SNOOZE_SECONDS
    session.wake_sent_at = None
    session.eta_window   = []   # Reset smoothing window — bắt đầu đo lại sau snooze
    await query.edit_message_text(
        text="💤 <b>Đã snooze 5 phút.</b>\nSẽ báo lại khi gần đến trạm.",
        parse_mode="HTML",
    )
    logger.info("Trip snoozed for %ds", SNOOZE_SECONDS)


async def cb_wake_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("🛑 Đã dừng theo dõi")
    session = store.get_session()
    if session:
        record_trip(session, "stop")
    store.clear_session()
    await query.edit_message_text(
        text="🛑 <b>Đã dừng theo dõi hành trình.</b>\nGõ /start để bắt đầu lại khi cần.",
        parse_mode="HTML",
    )
    logger.info("Trip STOPPED — session cleared")


async def cb_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer("Chức năng này chưa sẵn sàng.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception", exc_info=context.error)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def build_application() -> Application:
    app = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))

    # WebApp data từ Mini App pick mode
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    # Callback handlers — specific trước, catch-all sau
    app.add_handler(CallbackQueryHandler(cb_destination,  pattern=r"^dest:"))
    app.add_handler(CallbackQueryHandler(cb_prep_time,    pattern=r"^prep:"))
    app.add_handler(CallbackQueryHandler(cb_restart,      pattern=r"^restart$"))
    app.add_handler(CallbackQueryHandler(cb_wake_ack,     pattern=r"^wake_ack$"))
    app.add_handler(CallbackQueryHandler(cb_wake_snooze,  pattern=r"^wake_snooze$"))
    app.add_handler(CallbackQueryHandler(cb_wake_stop,    pattern=r"^wake_stop$"))
    app.add_handler(CallbackQueryHandler(cb_unknown))

    app.add_error_handler(error_handler)
    return app
