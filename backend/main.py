"""
FastAPI application entrypoint.
Run with: uvicorn backend.main:app --reload --port 8000

Lifespan:
  - startup  → đăng ký Telegram webhook, khởi động scheduler
  - shutdown → xoá webhook, dừng bot gracefully

Webhook mode (thay vì polling):
  - Telegram push update đến POST /telegram/webhook
  - Không conflict khi nhiều instance / redeploy
  - Yêu cầu BACKEND_URL là HTTPS (ngrok local, Koyeb production)
"""
import json
import logging
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

# Module-level bot application (accessible from routes for webhook processing)
bot_app = build_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Webhook mode — không cần phân biệt reloader/worker vì không có polling.
    Telegram tự push update đến /telegram/webhook → không conflict.
    """
    logger.info("Initializing Telegram bot (webhook mode)...")
    await bot_app.initialize()
    await bot_app.start()

    # rstrip("/") phòng trường hợp BACKEND_URL có trailing slash trong env vars
    webhook_url = f"{config.BACKEND_URL.rstrip('/')}/telegram/webhook"
    await bot_app.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
    )
    logger.info("Webhook registered: %s", webhook_url)

    scheduler_task = start_scheduler(bot_app)

    yield  # App runs here

    scheduler_task.cancel()
    logger.info("Removing Telegram webhook...")
    await bot_app.bot.delete_webhook()
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
