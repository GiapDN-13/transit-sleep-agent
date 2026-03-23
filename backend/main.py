"""
FastAPI application entrypoint.
Run with: uvicorn backend.main:app --reload --port 8000

Lifespan:
  - startup  → khởi động Telegram bot polling
  - shutdown → dừng bot gracefully
"""
import json
import logging
import multiprocessing
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# Đường dẫn tuyệt đối đến project root — hoạt động đúng bất kể CWD (local / Docker)
_PROJECT_ROOT = Path(__file__).parent.parent
_MINIAPP_HTML = _PROJECT_ROOT / "miniapp" / "index.html"

from backend.config import config
from backend.bot import build_application
from backend.routes import router
from backend.scheduler import start_scheduler
from backend.destinations import DESTINATIONS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level bot application (accessible from other modules for sending alerts)
bot_app = build_application()


def _is_reloader_process() -> bool:
    """
    Uvicorn --reload tạo parent "reloader" (MainProcess) và child worker (SpawnProcess-N / Process-N).
    Chỉ start bot ở worker process để tránh duplicate polling.

    Phân biệt bằng cách:
    - Nếu là MainProcess VÀ có child process đang chạy → đây là reloader → skip bot.
    - Nếu là MainProcess nhưng KHÔNG có child → đây là chế độ no-reload → start bot.
    - Nếu là Process-N / SpawnProcess-N → đây là worker → start bot.

    Trong thực tế, khi uvicorn dùng watchfiles (uvicorn[standard]) để reload,
    child worker sẽ có tên khác MainProcess. Ta dùng active_children() để phát hiện.
    """
    proc = multiprocessing.current_process()
    if proc.name != "MainProcess":
        # Đây là worker process (SpawnProcess-N, Process-N...) → start bot
        return False
    # Là MainProcess: chỉ là reloader nếu đã spawn ít nhất 1 child worker
    return len(multiprocessing.active_children()) > 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _is_reloader_process():
        # Reloader parent — không start bot, chỉ pass through
        logger.info("Reloader process detected — skipping bot startup.")
        yield
        return

    logger.info("Starting Telegram bot polling...")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot is polling. Send /start to your bot on Telegram.")

    scheduler_task = start_scheduler(bot_app)

    yield  # App runs here

    scheduler_task.cancel()
    logger.info("Stopping Telegram bot...")
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()
    logger.info("Bot stopped.")


app = FastAPI(title="Transit Sleep Agent", version="0.1.0", lifespan=lifespan)

app.include_router(router)


@app.get("/miniapp", response_class=HTMLResponse)
async def serve_miniapp():
    """
    Serve Mini App với config được inject:
      - window.BACKEND_URL
      - window.PRESET_DESTINATIONS  (danh sách điểm xuống cho map picker)
    """
    presets = [
        {"id": d.id, "name": d.name, "lat": d.lat, "lon": d.lon}
        for d in DESTINATIONS
    ]
    html = _MINIAPP_HTML.read_text(encoding="utf-8")
    injection = (
        f'<script>'
        f'window.BACKEND_URL = "{config.BACKEND_URL}";'
        f'window.PRESET_DESTINATIONS = {json.dumps(presets, ensure_ascii=False)};'
        f'</script>'
    )
    html = html.replace("</head>", f"{injection}\n</head>", 1)
    return HTMLResponse(content=html)


@app.get("/health")
async def health():
    try:
        username = bot_app.bot.username
    except RuntimeError:
        username = None
    return {"status": "ok", "bot_username": username}
