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
    Đảm bảo URL có https:// scheme.
    Tránh lỗi 'only https links are allowed' khi user quên điền scheme
    trong Koyeb / .env (ví dụ: điền 'xxx.koyeb.app' thay vì 'https://xxx.koyeb.app').
    """
    if not value.startswith(("https://", "http://")):
        fixed = f"https://{value}"
        _log.warning("'%s' thiếu scheme — tự động thêm https://: %s → %s", key, value, fixed)
        return fixed
    return value


class Config:
    TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
    ORS_API_KEY: str = _require("ORS_API_KEY")
    BACKEND_URL: str = _ensure_https("BACKEND_URL", _require("BACKEND_URL"))
    MINI_APP_URL: str = _ensure_https("MINI_APP_URL", _require("MINI_APP_URL"))
    OWNER_CHAT_ID: int = int(_require("OWNER_CHAT_ID"))


config = Config()
