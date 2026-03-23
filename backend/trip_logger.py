"""
Trip history logger.

Ghi lại kết quả mỗi chuyến đi khi kết thúc (ack / stop).
- Local dev: ghi vào trip_history.jsonl tại project root
- Production (Koyeb): filesystem ephemeral → chỉ log ra stdout,
  nhưng Koyeb log viewer hiển thị đầy đủ

Format mỗi entry (JSONL):
  {"ts": "...", "destination": "...", "prep_time_s": 300,
   "duration_s": 1800, "last_eta_s": 120, "wake_retries": 0, "outcome": "ack"}
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.session_store import TripSession

logger = logging.getLogger(__name__)

_HISTORY_FILE = Path(__file__).parent.parent / "trip_history.jsonl"


def record_trip(session: "TripSession", outcome: str) -> None:
    """
    Ghi lại trip outcome trước khi session bị clear.

    Args:
        session: TripSession hiện tại
        outcome: "ack" | "stop"
    """
    entry = {
        "ts":           datetime.now(timezone.utc).isoformat(),
        "destination":  session.destination_name,
        "prep_time_s":  session.prep_time_seconds,
        "duration_s":   round(time.time() - session.started_at),
        "last_eta_s":   round(session.last_eta_seconds) if session.last_eta_seconds is not None else None,
        "wake_retries": session.wake_retry_count,
        "outcome":      outcome,
    }

    # Luôn log ra stdout → visible trong Koyeb log viewer
    logger.info("TRIP_END | %s", json.dumps(entry, ensure_ascii=False))

    # Ghi file (local dev) — bỏ qua nếu không thể (ephemeral fs trên Koyeb)
    try:
        with _HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
