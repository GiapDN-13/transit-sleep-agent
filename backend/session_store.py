"""
In-memory trip session store.
Single-user app — one active trip at a time is enough for V1.

Session lifecycle:
  IDLE → ACTIVE → WAKING → (cleared)
          ↑___snooze___↗

M2 changes:
  - IDLE là trạng thái mặc định khi session mới tạo (chờ GPS đầu tiên)
  - ACTIVE khi Mini App gửi GPS đầu tiên qua /trips/start
  - eta_window: sliding window raw ETAs cho smoothing (tránh false alarm)
  - wake_retry_count: đếm số lần retry wake alert
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class TripStatus(str, Enum):
    IDLE = "IDLE"       # Session tạo xong, chờ GPS đầu tiên từ Mini App
    ACTIVE = "ACTIVE"   # GPS nhận được, đang đếm ETA
    WAKING = "WAKING"   # Wake alert đã gửi, chờ user ack
    DONE = "DONE"       # Reserved — không dùng (session được clear thay vì set DONE)


@dataclass
class TripSession:
    destination_name: str
    destination_coords: tuple[float, float]  # (lon, lat)
    prep_time_seconds: int
    status: TripStatus = TripStatus.IDLE   # Bắt đầu IDLE, chờ GPS
    last_lat: Optional[float] = None
    last_lon: Optional[float] = None
    last_eta_seconds: Optional[float] = None   # Smoothed ETA (dùng cho display)
    started_at: float = field(default_factory=time.time)
    wake_sent_at: Optional[float] = None
    wake_retry_count: int = 0              # Số lần retry wake alert đã gửi
    snooze_until: Optional[float] = None   # epoch — scheduler bỏ qua cho đến khi hết snooze
    eta_window: list = field(default_factory=list)  # Raw ETAs gần nhất (cho ETA smoothing)


# Global single-session store (1 user, 1 active trip)
_session: Optional[TripSession] = None


def create_session(
    destination_name: str,
    destination_coords: tuple[float, float],
    prep_time_seconds: int,
) -> TripSession:
    global _session
    _session = TripSession(
        destination_name=destination_name,
        destination_coords=destination_coords,
        prep_time_seconds=prep_time_seconds,
    )
    return _session


def get_session() -> Optional[TripSession]:
    return _session


def clear_session() -> None:
    global _session
    _session = None
