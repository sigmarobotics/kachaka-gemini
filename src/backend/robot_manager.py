"""Robot Manager — singleton facade over kachaka_core components.

Replaces robot_service.py with production-ready connection management,
command execution, and camera streaming via kachaka_core.
"""

import asyncio
import base64
import logging
import threading

from kachaka_core import KachakaConnection, RobotController, KachakaQueries, CameraStreamer

import settings_service

logger = logging.getLogger(__name__)


class RobotManager:
    """Singleton facade wrapping kachaka_core components for the web app."""

    def __init__(self):
        self._conn: KachakaConnection | None = None
        self._ctrl: RobotController | None = None
        self._queries: KachakaQueries | None = None
        self._camera: CameraStreamer | None = None
        self._ip: str = ""
        self._serial: str = ""
        self._map_cache: dict | None = None
        self._lock = threading.Lock()

    # ── Properties ────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._conn is not None

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def serial(self) -> str:
        return self._serial

    # ── Connection lifecycle ──────────────────────────────────────

    def connect(self, ip: str) -> dict:
        """Connect to robot at given IP. Returns {"ok": bool, ...}."""
        with self._lock:
            # Disconnect existing if any
            if self._conn is not None:
                self._shutdown_components()

            try:
                self._conn = KachakaConnection.get(ip)
                ping = self._conn.ping()
                if not ping["ok"]:
                    self._conn = None
                    KachakaConnection.remove(ip)
                    return {"ok": False, "error": ping.get("error", "Ping failed")}

                self._ip = ip
                self._serial = ping.get("serial", "")

                # Start components
                self._ctrl = RobotController(self._conn, fast_interval=1.0)
                self._ctrl.start()

                self._queries = KachakaQueries(self._conn)

                self._camera = CameraStreamer(self._conn, interval=1.0, camera="front")
                self._camera.start()

                # Reset map cache on new connection
                self._map_cache = None

                # Save IP to settings
                settings_service.save({"robot_ip": ip})

                logger.info("Connected to robot at %s (serial: %s)", ip, self._serial)
                return {"ok": True, "serial": self._serial, "ip": ip}

            except Exception as e:
                logger.error("Failed to connect to %s: %s", ip, e)
                self._conn = None
                KachakaConnection.remove(ip)
                return {"ok": False, "error": str(e)}

    def disconnect(self) -> dict:
        """Disconnect from current robot."""
        with self._lock:
            if self._conn is None:
                return {"ok": True, "message": "Not connected"}
            ip = self._ip
            self._shutdown_components()
            logger.info("Disconnected from robot at %s", ip)
            return {"ok": True}

    def reconnect(self, new_ip: str) -> dict:
        """Disconnect current and connect to new IP."""
        return self.connect(new_ip)  # connect() already handles disconnect

    def get_connection_status(self) -> dict:
        """Return current connection status."""
        return {
            "connected": self.connected,
            "ip": self._ip,
            "serial": self._serial,
        }

    def _shutdown_components(self):
        """Stop all kachaka_core components. Must be called under self._lock."""
        if self._camera:
            self._camera.stop()
            self._camera = None
        if self._ctrl:
            self._ctrl.stop()
            self._ctrl = None
        self._queries = None
        if self._conn and self._ip:
            KachakaConnection.remove(self._ip)
        self._conn = None
        self._ip = ""
        self._serial = ""
        self._map_cache = None

    # ── State queries ─────────────────────────────────────────────

    def get_state(self) -> dict:
        """Return robot state for /api/state endpoint."""
        if not self._ctrl:
            return {
                "battery": 0,
                "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
                "map_info": {
                    "resolution": 0.05, "width": 0, "height": 0,
                    "origin_x": 0.0, "origin_y": 0.0,
                },
            }
        s = self._ctrl.state
        # Fetch map info if cached
        map_info = {
            "resolution": 0.05, "width": 0, "height": 0,
            "origin_x": 0.0, "origin_y": 0.0,
        }
        if self._map_cache:
            map_info = self._map_cache["info"]
        return {
            "battery": s.battery_pct,
            "pose": {"x": s.pose_x, "y": s.pose_y, "theta": s.pose_theta},
            "map_info": map_info,
        }

    def get_map_bytes(self) -> bytes | None:
        """Return cached PNG map bytes, fetching on first call."""
        if not self._queries:
            return None
        if self._map_cache is None:
            try:
                result = self._queries.get_map()
                if result["ok"]:
                    self._map_cache = {
                        "bytes": base64.b64decode(result["image_base64"]),
                        "info": {
                            "resolution": result["resolution"],
                            "width": result["width"],
                            "height": result["height"],
                            "origin_x": 0.0,
                            "origin_y": 0.0,
                        },
                    }
            except Exception as e:
                logger.error("Failed to fetch map: %s", e)
                return None
        return self._map_cache["bytes"] if self._map_cache else None

    def get_locations(self) -> list:
        """Return list of registered locations."""
        if not self._queries:
            return []
        try:
            result = self._queries.list_locations()
            if result["ok"]:
                return [
                    {
                        "id": loc["id"],
                        "name": loc["name"],
                        "x": loc["pose"]["x"],
                        "y": loc["pose"]["y"],
                        "theta": loc["pose"]["theta"],
                    }
                    for loc in result["locations"]
                ]
        except Exception as e:
            logger.error("Failed to get locations: %s", e)
        return []

    def get_shelves(self) -> list:
        """Return list of registered shelves."""
        if not self._queries:
            return []
        try:
            result = self._queries.list_shelves()
            if result["ok"]:
                return [
                    {
                        "id": s["id"],
                        "name": s["name"],
                        "home_location_id": s.get("home_location_id", ""),
                    }
                    for s in result["shelves"]
                ]
        except Exception as e:
            logger.error("Failed to get shelves: %s", e)
        return []

    def get_command_state(self) -> dict:
        """Return current command state."""
        if not self._queries:
            return {"state": "disconnected"}
        try:
            result = self._queries.get_command_state()
            if result["ok"]:
                return {"state": result["state"]}
        except Exception as e:
            return {"state": "unknown", "error": str(e)}
        return {"state": "unknown"}

    # ── Camera ────────────────────────────────────────────────────

    def get_camera_frame(self) -> dict | None:
        """Return latest camera frame dict from CameraStreamer."""
        if not self._camera:
            return None
        return self._camera.latest_frame

    def get_camera_jpeg_bytes(self) -> bytes | None:
        """Return raw JPEG bytes for MJPEG streaming."""
        frame = self.get_camera_frame()
        if frame and frame.get("ok") and frame.get("image_base64"):
            return base64.b64decode(frame["image_base64"])
        return None

    # ── Direct control (REST endpoints) ───────────────────────────

    def move_to_pose(self, x: float, y: float, theta: float):
        """Move robot to a specific coordinate (non-blocking, fire-and-forget)."""
        if not self._conn:
            return
        try:
            self._conn.client.move_to_pose(x, y, theta, wait_for_completion=False)
        except Exception as e:
            logger.error("move_to_pose error: %s", e)

    def cancel_command(self):
        """Cancel the currently running command."""
        if not self._conn:
            return
        try:
            self._conn.client.cancel_command()
        except Exception as e:
            logger.error("cancel_command error: %s", e)

    def return_home(self):
        """Send robot to charger (fire-and-forget)."""
        if not self._conn:
            return
        try:
            self._conn.client.return_home(wait_for_completion=False)
        except Exception as e:
            logger.error("return_home error: %s", e)

    def move_forward(self, distance: float, speed: float = 0.1):
        """Move forward/backward by distance meters."""
        if not self._conn:
            return
        try:
            self._conn.client.move_forward(distance_meter=distance, speed=speed)
        except Exception as e:
            logger.error("move_forward error: %s", e)

    def rotate(self, angle: float):
        """Rotate in place by angle radians."""
        if not self._conn:
            return
        try:
            self._conn.client.rotate_in_place(angle_radian=angle)
        except Exception as e:
            logger.error("rotate error: %s", e)

    def speak(self, text: str) -> dict:
        """Speak text via robot TTS."""
        if not self._conn:
            return {"ok": False, "error": "Robot not connected"}
        try:
            self._conn.client.speak(text)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Function call dispatch (used by Gemini sessions) ──────────

    def execute_function_call(self, name: str, args: dict) -> dict:
        """Execute a Gemini function call and return the result.

        Uses RobotController for movement commands (waits for completion,
        enriched errors, command_id verification).
        """
        try:
            if name == "move_to_location":
                location_id = args.get("location_id", "")
                if not location_id:
                    return {"ok": False, "error": "location_id is required"}
                if not self._ctrl:
                    return {"ok": False, "error": "Robot not connected"}
                return self._ctrl.move_to_location(location_id, timeout=120)

            elif name == "move_shelf":
                shelf_id = args.get("shelf_id", "")
                destination_id = args.get("destination_id", "")
                if not shelf_id or not destination_id:
                    return {"ok": False, "error": "shelf_id and destination_id are required"}
                if not self._ctrl:
                    return {"ok": False, "error": "Robot not connected"}
                return self._ctrl.move_shelf(shelf_id, destination_id, timeout=120)

            elif name == "return_shelf":
                shelf_id = args.get("shelf_id", "")
                if not shelf_id:
                    return {"ok": False, "error": "shelf_id is required"}
                if not self._ctrl:
                    return {"ok": False, "error": "Robot not connected"}
                return self._ctrl.return_shelf(shelf_id, timeout=60)

            elif name == "get_robot_status":
                state = self.get_state()
                cmd_state = self.get_command_state()
                return {
                    "ok": True,
                    "battery": state["battery"],
                    "pose": state["pose"],
                    "command_state": cmd_state.get("state", "unknown"),
                }

            elif name == "cancel_command":
                self.cancel_command()
                return {"ok": True, "message": "Command cancelled"}

            elif name == "capture_camera":
                frame = self.get_camera_frame()
                if frame and frame.get("ok"):
                    return {"ok": True, "message": "Camera frame captured, image attached"}
                return {"ok": False, "error": "Camera not available"}

            else:
                return {"ok": False, "error": f"Unknown function: {name}"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Auto-connect on startup ───────────────────────────────────

    def auto_connect(self):
        """Try to connect using saved IP from settings. Non-blocking."""
        from config import ROBOT_IP as ENV_ROBOT_IP
        saved_ip = settings_service.get("robot_ip", "")
        ip = saved_ip or ENV_ROBOT_IP
        if ip:
            logger.info("Auto-connecting to robot at %s ...", ip)
            result = self.connect(ip)
            if result["ok"]:
                logger.info("Auto-connect succeeded: %s", ip)
            else:
                logger.warning("Auto-connect failed: %s", result.get("error", ""))


# Module-level singleton
robot_manager = RobotManager()
