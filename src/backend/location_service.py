"""Location Service — location enum with A* distances and name resolution.

Provides sorted location lists with distances from the kiosk position,
and exact-match name resolution (no fuzzy matching).
"""

import logging
import threading

from robot_manager import robot_manager
import settings_service
from pathfinding import compute_distances

logger = logging.getLogger(__name__)


class LocationService:
    """Caches location-to-distance mappings; invalidated on reconnect."""

    def __init__(self):
        self._cache: list[dict] | None = None
        self._locations: list[dict] = []
        self._lock = threading.Lock()

    def invalidate(self):
        """Clear the distance cache (call on robot reconnect)."""
        with self._lock:
            self._cache = None
            self._locations = []

    def _ensure_locations(self):
        """Fetch locations from robot if not cached."""
        if not self._locations:
            self._locations = robot_manager.get_locations()

    def _compute(self) -> list[dict]:
        """Compute distances from kiosk to all locations via A*."""
        self._ensure_locations()
        if not self._locations:
            return []

        map_bytes = robot_manager.get_map_bytes()
        state = robot_manager.get_state()
        map_info = state.get("map_info", {})

        # Determine starting point: kiosk location or current robot pose
        kiosk_id = settings_service.get("kiosk_location", "")
        from_world = None
        if kiosk_id:
            for loc in self._locations:
                if loc["id"] == kiosk_id:
                    from_world = (loc["x"], loc["y"])
                    break

        if from_world is None:
            # Fall back to current robot position
            pose = state.get("pose", {})
            from_world = (pose.get("x", 0.0), pose.get("y", 0.0))

        # If we have a map, compute A* distances
        distances = {}
        if map_bytes and map_info.get("width", 0) > 0:
            try:
                distances = compute_distances(map_bytes, map_info,
                                              from_world, self._locations)
            except Exception as e:
                logger.error("A* distance computation failed: %s", e)

        # Build result list
        result = []
        for loc in self._locations:
            dist = distances.get(loc["id"], float("inf"))
            result.append({
                "id": loc["id"],
                "name": loc["name"],
                "x": loc["x"],
                "y": loc["y"],
                "theta": loc.get("theta", 0.0),
                "distance_m": round(dist, 1) if dist != float("inf") else None,
            })

        # Sort by distance (None/inf last)
        result.sort(key=lambda r: r["distance_m"] if r["distance_m"] is not None else float("inf"))
        return result

    def get_location_enum_with_distances(self) -> list[dict]:
        """Return [{name, id, distance_m}, ...] sorted by distance.

        Results are cached until invalidate() is called.
        """
        with self._lock:
            if self._cache is not None:
                return self._cache
            result = self._compute()
            # Only cache non-empty results so we retry when robot connects
            if result:
                self._cache = result
            return result

    def resolve_location_name(self, name: str) -> dict | None:
        """Exact match on name -> return {id, name, x, y, theta}. No fuzzy."""
        self._ensure_locations()
        for loc in self._locations:
            if loc["name"] == name:
                return loc
        return None

    def get_all_locations(self) -> list[dict]:
        """Return raw location list (no distance computation)."""
        self._ensure_locations()
        return self._locations


# Module-level singleton
location_service = LocationService()
