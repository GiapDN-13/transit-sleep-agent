"""
Central config loader.
Reads from environment variables (populated via .env file in dev).
Raises clearly if required keys are missing so the app fails fast.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

_log = logging.getLogger(__name__)


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is missing or empty. "
            f"Check your .env file against .env.example."
        )
    return value


def _ensure_https(key: str, value: str) -> str:
    """
    Chuẩn hoá URL:
      1. Tự động thêm https:// nếu thiếu scheme
         (tránh lỗi 'only https links are allowed')
      2. Xoá trailing slash
         (tránh double-slash khi nối path, ví dụ: 'xxx.koyeb.app/' + '/webhook' → '//webhook')
    """
    if not value.startswith(("https://", "http://")):
        value = f"https://{value}"
        _log.warning("'%s' thiếu scheme — tự động thêm https://", key)
    value = value.rstrip("/")
    return value


class Config:
    TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
    ORS_API_KEY: str = _require("ORS_API_KEY")
    BACKEND_URL: str = _ensure_https("BACKEND_URL", _require("BACKEND_URL"))
    MINI_APP_URL: str = _ensure_https("MINI_APP_URL", _require("MINI_APP_URL"))
    OWNER_CHAT_ID: int = int(_require("OWNER_CHAT_ID"))
    # ntfy.sh push notification (tuỳ chọn — để trống thì bỏ qua)
    # Cài app ntfy trên điện thoại, subscribe topic này để nhận alarm
    NTFY_TOPIC: str | None = os.getenv("NTFY_TOPIC") or None


config = Config()
