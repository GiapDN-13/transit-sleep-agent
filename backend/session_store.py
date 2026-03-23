"""
In-memory trip session store.
Single-user app — one active trip at a time is enough for V1.

Session lifecycle:
  IDLE → ACTIVE → WAKING → DONE
         ↑___snooze___↗
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class TripStatus(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"      # GPS polling, ETA counting down
    WAKING = "WAKING"      # Wake alert sent, waiting for ack
    DONE = "DONE"          # Ack'd, snoozed-out, or stopped


@dataclass
class TripSession:
    destination_name: str
    destination_coords: tuple[float, float]  # (lon, lat)
    prep_time_seconds: int
    status: TripStatus = TripStatus.ACTIVE
    last_lat: Optional[float] = None
    last_lon: Optional[float] = None
    last_eta_seconds: Optional[float] = None
    started_at: float = field(default_factory=time.time)
    wake_sent_at: Optional[float] = None
    snooze_until: Optional[float] = None  # epoch — scheduler bỏ qua cho đến khi hết snooze


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
