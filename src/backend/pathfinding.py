"""A* pathfinding on the Kachaka PNG map.

Parses the robot's PNG map into an occupancy grid, inflates obstacles,
and computes shortest-path distances between world coordinates.
"""

import heapq
import io
import math

import numpy as np
from PIL import Image


# Obstacle inflation in world meters (0.15m ≈ tight margin for Kachaka)
INFLATE_RADIUS_M = 0.15


def _world_to_pixel(wx: float, wy: float, origin_x: float, origin_y: float,
                    resolution: float, height: int) -> tuple[int, int]:
    """Convert world coordinates (meters) to pixel coordinates."""
    px = int((wx - origin_x) / resolution)
    py = height - 1 - int((wy - origin_y) / resolution)
    return px, py


def _build_occupancy_grid(map_bytes: bytes) -> np.ndarray:
    """Parse PNG map bytes into a boolean occupancy grid.

    Returns an array where True = walkable, False = blocked.
    The lightest pixel value in the map represents walkable space.
    Kachaka maps typically use ~253 for walkable, ~234 for unknown,
    and ~175 for obstacles.  We threshold at 250 to be safe.
    """
    img = Image.open(io.BytesIO(map_bytes)).convert("L")
    arr = np.array(img, dtype=np.uint8)
    return arr >= 250


def _inflate_obstacles(grid: np.ndarray, radius: int) -> np.ndarray:
    """Inflate blocked cells by `radius` pixels using a circular kernel.

    Uses manual dilation (no scipy dependency).
    """
    if radius <= 0:
        return grid.copy()

    blocked = ~grid  # True where blocked
    inflated_blocked = blocked.copy()

    # Build circular kernel offsets
    offsets = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                offsets.append((dy, dx))

    h, w = grid.shape
    # Find all blocked cells and expand them
    blocked_ys, blocked_xs = np.where(blocked)
    for by, bx in zip(blocked_ys, blocked_xs):
        for dy, dx in offsets:
            ny, nx = by + dy, bx + dx
            if 0 <= ny < h and 0 <= nx < w:
                inflated_blocked[ny, nx] = True

    return ~inflated_blocked  # True = walkable


def _snap_to_walkable(grid: np.ndarray, px: int, py: int, max_radius: int = 20) -> tuple[int, int]:
    """Find nearest walkable cell via expanding square search."""
    h, w = grid.shape
    if 0 <= px < w and 0 <= py < h and grid[py, px]:
        return px, py
    for r in range(1, max_radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if abs(dy) != r and abs(dx) != r:
                    continue  # only check perimeter
                nx, ny = px + dx, py + dy
                if 0 <= nx < w and 0 <= ny < h and grid[ny, nx]:
                    return nx, ny
    return px, py  # give up


def _astar(grid: np.ndarray, start: tuple[int, int], goal: tuple[int, int]) -> float:
    """A* search on an 8-directional grid.

    Returns the path cost in pixels, or float('inf') if unreachable.
    """
    h, w = grid.shape
    sx, sy = start
    gx, gy = goal

    # Bounds check
    if not (0 <= sx < w and 0 <= sy < h and 0 <= gx < w and 0 <= gy < h):
        return float("inf")
    if not grid[sy, sx] or not grid[gy, gx]:
        return float("inf")

    SQRT2 = math.sqrt(2)
    # 8 directions: (dy, dx, cost)
    DIRS = [
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, SQRT2), (-1, 1, SQRT2), (1, -1, SQRT2), (1, 1, SQRT2),
    ]

    def heuristic(x, y):
        dx = abs(x - gx)
        dy = abs(y - gy)
        return max(dx, dy) + (SQRT2 - 1) * min(dx, dy)  # Octile distance

    # (f, g, x, y)
    open_set = [(heuristic(sx, sy), 0.0, sx, sy)]
    g_score = {(sx, sy): 0.0}

    while open_set:
        f, g, cx, cy = heapq.heappop(open_set)

        if cx == gx and cy == gy:
            return g

        if g > g_score.get((cx, cy), float("inf")):
            continue

        for dy, dx, cost in DIRS:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if not grid[ny, nx]:
                continue
            ng = g + cost
            if ng < g_score.get((nx, ny), float("inf")):
                g_score[(nx, ny)] = ng
                heapq.heappush(open_set, (ng + heuristic(nx, ny), ng, nx, ny))

    return float("inf")


def compute_distances(
    map_bytes: bytes,
    map_info: dict,
    from_world: tuple[float, float],
    to_locations: list[dict],
) -> dict[str, float]:
    """Compute A* distances from a world point to each location.

    Args:
        map_bytes: PNG map image bytes.
        map_info: dict with keys: resolution, width, height, origin_x, origin_y.
        from_world: (x, y) in world meters.
        to_locations: list of dicts with keys: id, name, x, y.

    Returns:
        {location_id: distance_in_meters} for each location.
        Unreachable locations get float('inf').
    """
    resolution = map_info.get("resolution", 0.05)
    origin_x = map_info.get("origin_x", 0.0)
    origin_y = map_info.get("origin_y", 0.0)

    raw_grid = _build_occupancy_grid(map_bytes)
    inflate_px = max(1, int(INFLATE_RADIUS_M / resolution))
    grid = _inflate_obstacles(raw_grid, inflate_px)
    height = raw_grid.shape[0]

    raw_start = _world_to_pixel(from_world[0], from_world[1],
                               origin_x, origin_y, resolution, height)
    start_px = _snap_to_walkable(grid, raw_start[0], raw_start[1])

    results = {}
    for loc in to_locations:
        loc_id = loc.get("id", "")
        lx, ly = loc.get("x", 0.0), loc.get("y", 0.0)
        raw_goal = _world_to_pixel(lx, ly, origin_x, origin_y, resolution, height)
        goal_px = _snap_to_walkable(grid, raw_goal[0], raw_goal[1])
        cost_px = _astar(grid, start_px, goal_px)
        results[loc_id] = cost_px * resolution if cost_px != float("inf") else float("inf")

    return results
