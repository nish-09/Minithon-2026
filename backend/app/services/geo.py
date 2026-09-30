import math

from ..config import get_settings


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def eta_minutes(distance_km: float) -> float:
    """Straight-line distance inflated by a road-network factor, at configured average speed."""
    road_km = distance_km * 1.3
    return max(1.0, round(road_km / get_settings().avg_speed_kmh * 60, 1))


def bbox(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Cheap pre-filter box (min_lat, max_lat, min_lng, max_lng) so SQL can use the geo index."""
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def fuzz(lat: float, lng: float, precision: int = 2) -> tuple[float, float]:
    """Approximate location (~1 km at precision=2) for users who are not assigned to the request."""
    return round(lat, precision), round(lng, precision)
