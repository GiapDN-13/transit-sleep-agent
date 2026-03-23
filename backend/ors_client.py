"""
Wrapper quanh OpenRouteService Directions API.

openrouteservice-py là thư viện đồng bộ.
get_eta_async() chạy nó trong thread pool để không block event loop của FastAPI.
"""
import asyncio
import logging

import openrouteservice
from openrouteservice.exceptions import ApiError

from backend.config import config

logger = logging.getLogger(__name__)

_client = openrouteservice.Client(key=config.ORS_API_KEY)


def _call_ors(
    current_coords: tuple[float, float],
    destination_coords: tuple[float, float],
) -> dict:
    """
    Đồng bộ — chạy trong thread pool, không gọi trực tiếp từ async code.
    Cả hai coords theo chuẩn ORS: (longitude, latitude).
    """
    route = _client.directions(
        coordinates=[list(current_coords), list(destination_coords)],
        profile="driving-car",
        format="geojson",
    )
    summary = route["features"][0]["properties"]["summary"]
    return {
        "eta_seconds": summary["duration"],
        "distance_meters": summary["distance"],
    }


async def get_eta_async(
    current_coords: tuple[float, float],
    destination_coords: tuple[float, float],
) -> dict:
    """
    Async wrapper.
    Raises ApiError nếu ORS trả về lỗi.
    Raises Exception nếu timeout hoặc network issue.
    """
    logger.debug(
        "ORS request: from=%s to=%s", current_coords, destination_coords
    )
    result = await asyncio.to_thread(_call_ors, current_coords, destination_coords)
    logger.debug(
        "ORS result: eta=%.0fs dist=%.0fm",
        result["eta_seconds"],
        result["distance_meters"],
    )
    return result
