"""
Central config loader.
Reads from environment variables (populated via .env file in dev).
Raises clearly if required keys are missing so the app fails fast.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is missing or empty. "
            f"Check your .env file against .env.example."
        )
    return value


class Config:
    TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
    ORS_API_KEY: str = _require("ORS_API_KEY")
    BACKEND_URL: str = _require("BACKEND_URL")
    MINI_APP_URL: str = _require("MINI_APP_URL")
    OWNER_CHAT_ID: int = int(_require("OWNER_CHAT_ID"))


config = Config()
