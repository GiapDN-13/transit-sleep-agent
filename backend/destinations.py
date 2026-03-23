"""
Hard-coded danh sách điểm xuống.
Thêm/bớt tại đây theo tuyến thực tế của bạn.

Tọa độ: (longitude, latitude) — chuẩn của ORS.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    lon: float
    lat: float

    @property
    def coords(self) -> tuple[float, float]:
        return (self.lon, self.lat)


DESTINATIONS: list[Destination] = [
    Destination(
        id="ben_thanh",
        name="Chợ Bến Thành",
        lon=106.6980,
        lat=10.7725,
    ),
    Destination(
        id="landmark81",
        name="Landmark 81 (Vinhomes)",
        lon=106.7218,
        lat=10.7950,
    ),
    Destination(
        id="thu_duc_station",
        name="Ga Thủ Đức",
        lon=106.7614,
        lat=10.8502,
    ),
    Destination(
        id="suoi_tien",
        name="Bến xe Suối Tiên",
        lon=106.8361,
        lat=10.8754,
    ),
    Destination(
        id="mien_dong",
        name="Bến xe Miền Đông",
        lon=106.7148,
        lat=10.8165,
    ),
]

# Lookup nhanh theo id
DESTINATION_MAP: dict[str, Destination] = {d.id: d for d in DESTINATIONS}


PREP_TIME_OPTIONS: list[tuple[str, int]] = [
    ("2 phút", 2 * 60),
    ("5 phút", 5 * 60),
    ("10 phút", 10 * 60),
]
