"""Robot Manager — singleton facade over kachaka_core components.

Replaces robot_service.py with production-ready connection management,
command execution, and camera streaming via kachaka_core.
"""

import base64
import json
import logging
import math
import threading
import time

from kachaka_core import KachakaConnection, RobotController, KachakaQueries, CameraStreamer

import settings_service

logger = logging.getLogger(__name__)


# ── Telegram helpers ──────────────────────────────────────────────────────────

def _get_telegram_chat_ids() -> list[str]:
    """Return list of chat IDs for Telegram notifications."""
    ids = settings_service.get("telegram_chat_ids", [])
    if isinstance(ids, str):
        return [ids] if ids else []
    return [str(i) for i in ids if i]


def _send_telegram_text(text: str, chat_ids: list[str] | None = None,
                        token: str | None = None):
    """Send a text message to all configured Telegram chat IDs."""
    import urllib.request
    if token is None:
        token = settings_service.get("telegram_bot_token", "")
    if chat_ids is None:
        chat_ids = _get_telegram_chat_ids()
    if not token or not chat_ids:
        return
    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = json.dumps({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
            req = urllib.request.Request(
                url, data=payload.encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            logger.warning("Telegram text send failed (chat_id=%s): %s", chat_id, e)


def _send_telegram_photo(jpeg_bytes: bytes, caption: str,
                         chat_ids: list[str] | None = None,
                         token: str | None = None):
    """Send a photo with caption to all configured Telegram chat IDs."""
    import urllib.request
    import uuid as _uuid
    if token is None:
        token = settings_service.get("telegram_bot_token", "")
    if chat_ids is None:
        chat_ids = _get_telegram_chat_ids()
    if not token or not chat_ids:
        return
    for chat_id in chat_ids:
        try:
            boundary = _uuid.uuid4().hex
            body_parts = []
            body_parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}'.encode()
            )
            body_parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption[:1024]}'.encode()
            )
            body_parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="photo.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
                + jpeg_bytes
            )
            body_parts.append(f'--{boundary}--\r\n'.encode())
            body = b'\r\n'.join(body_parts)
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            logger.warning("Telegram photo send failed (chat_id=%s): %s", chat_id, e)


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

                # Invalidate location service cache
                try:
                    from location_service import location_service
                    location_service.invalidate()
                except ImportError:
                    pass

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
        if not self._conn:
            return None
        if self._map_cache is None:
            try:
                png_map = self._conn.client.get_png_map()
                self._map_cache = {
                    "bytes": png_map.data,
                    "info": {
                        "resolution": png_map.resolution,
                        "width": png_map.width,
                        "height": png_map.height,
                        "origin_x": png_map.origin.x,
                        "origin_y": png_map.origin.y,
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
        """Execute a Gemini function call and return the result."""
        dispatch = {
            "move_to_location": self._fc_move_to_location,
            "move_shelf": self._fc_move_shelf,
            "return_shelf": self._fc_return_shelf,
            "get_robot_status": self._fc_get_robot_status,
            "cancel_command": self._fc_cancel_command,
            "capture_camera": self._fc_capture_camera,
            "inspect_location": self._fc_inspect_location,
            "patrol_all": self._fc_patrol_all,
            "rotate": self._fc_rotate,
            "guide_to_booth": self._fc_guide_to_booth,
            "notify_staff": self._fc_notify_staff,
            "deliver_drink": self._fc_deliver_drink,
            "return_drink": self._fc_return_drink,
            "get_patrol_history": self._fc_get_patrol_history,
        }
        handler = dispatch.get(name)
        if not handler:
            return {"ok": False, "error": f"Unknown function: {name}"}
        try:
            return handler(args)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── FC handlers ────────────────────────────────────────────────

    def _fc_move_to_location(self, args: dict) -> dict:
        location_id = args.get("location_id", "")
        if not location_id:
            return {"ok": False, "error": "location_id is required"}
        if not self._ctrl:
            return {"ok": False, "error": "Robot not connected"}
        return self._ctrl.move_to_location(location_id, timeout=120)

    def _fc_move_shelf(self, args: dict) -> dict:
        shelf_id = args.get("shelf_id", "")
        destination_id = args.get("destination_id", "")
        if not shelf_id or not destination_id:
            return {"ok": False, "error": "shelf_id and destination_id are required"}
        if not self._ctrl:
            return {"ok": False, "error": "Robot not connected"}
        return self._ctrl.move_shelf(shelf_id, destination_id, timeout=120)

    def _fc_return_shelf(self, args: dict) -> dict:
        shelf_id = args.get("shelf_id", "")
        if not shelf_id:
            return {"ok": False, "error": "shelf_id is required"}
        if not self._ctrl:
            return {"ok": False, "error": "Robot not connected"}
        return self._ctrl.return_shelf(shelf_id, timeout=60)

    def _fc_get_robot_status(self, args: dict) -> dict:
        state = self.get_state()
        cmd_state = self.get_command_state()
        return {
            "ok": True,
            "battery": state["battery"],
            "pose": state["pose"],
            "command_state": cmd_state.get("state", "unknown"),
        }

    def _fc_cancel_command(self, args: dict) -> dict:
        self.cancel_command()
        return {"ok": True, "message": "Command cancelled"}

    def _fc_capture_camera(self, args: dict) -> dict:
        """Capture camera frame and analyze with Gemini."""
        from frame_hub import frame_hub
        jpeg = frame_hub.wait_for_fresh_frame(timeout=10)
        if not jpeg:
            return {"ok": False, "error": "Camera not available"}

        prompt = args.get("prompt", "") or args.get("query", "")

        # Analyze with Gemini
        from google import genai
        from google.genai import types
        api_key = settings_service.get("gemini_api_key", "")
        model = settings_service.get("text_model", "gemini-3-flash-preview")

        user_prompt = prompt.strip() if prompt else "請詳細描述這張照片中你看到的所有內容。"

        sys_instruction = (
            "你是一個影像分析助手。請根據使用者的問題分析照片內容。"
            "用簡潔的口語化中文回答（2-3句話），不要使用 markdown 格式、"
            "列表符號或特殊字元。直接描述你看到的內容。"
        )

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Content(role="user", parts=[
                        types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                        types.Part.from_text(text=user_prompt),
                    ])
                ],
                config=types.GenerateContentConfig(
                    system_instruction=sys_instruction,
                ),
            )
            analysis = response.text or "No analysis available"
        except Exception as e:
            logger.error("Camera analysis error: %s", e)
            analysis = f"Image analysis failed: {e}"

        # Send to Telegram
        if settings_service.get("patrol_telegram_notify", True):
            _send_telegram_photo(jpeg, f"📷 視覺檢測\n\n{analysis}")

        return {
            "ok": True,
            "image_analysis": analysis,
            "message": "Camera frame captured and analyzed",
        }

    def _fc_inspect_location(self, args: dict) -> dict:
        """Move to a named location, capture and analyze photo, then return home."""
        location_name = args.get("location_name", "")
        if not location_name:
            return {"ok": False, "error": "location_name is required"}
        if not self._ctrl:
            return {"ok": False, "error": "Robot not connected"}

        # Exact match via location_service
        from location_service import location_service
        matched = location_service.resolve_location_name(location_name)
        if not matched:
            all_locs = location_service.get_all_locations()
            return {
                "ok": False,
                "error": f"找不到地點: {location_name}",
                "available": [loc["name"] for loc in all_locs],
            }

        # Move to location
        move_result = self._ctrl.move_to_location(matched["id"], timeout=120)
        if not move_result.get("ok"):
            return move_result

        # Dwell
        dwell = settings_service.get("inspect_dwell_time", 10)
        time.sleep(dwell)

        # Capture frame
        from frame_hub import frame_hub
        jpeg = frame_hub.wait_for_fresh_frame(timeout=10)
        if not jpeg:
            self._ctrl.return_home(timeout=120)
            return {"ok": False, "error": "Camera not available at location"}

        # Analyze with Gemini
        prompt = args.get("prompt", "") or "請分析這張照片中的環境狀況。繁體中文。"
        from google import genai
        from google.genai import types
        api_key = settings_service.get("gemini_api_key", "")
        model = settings_service.get("text_model", "gemini-3-flash-preview")

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Content(role="user", parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                    ]),
                ],
            )
            analysis = response.text or "No analysis available"
        except Exception as e:
            logger.error("Inspect location analysis error: %s", e)
            analysis = f"Analysis failed: {e}"

        # Send to Telegram
        caption = f"🔍 定點巡查 — {matched['name']}\n\n{analysis}"
        _send_telegram_photo(jpeg, caption)

        # Return home
        self._ctrl.return_home(timeout=120)

        return {
            "ok": True,
            "analysis": analysis,
            "location": matched["name"],
        }

    def _fc_patrol_all(self, args: dict) -> dict:
        """Start a patrol run via patrol_service."""
        from patrol_service import patrol_service
        return patrol_service.start_patrol()

    def _fc_rotate(self, args: dict) -> dict:
        """Rotate in place by specified degrees."""
        angle_deg = args.get("angle", 15)
        try:
            angle_deg = float(angle_deg)
        except (TypeError, ValueError):
            angle_deg = 15.0
        angle_rad = math.radians(angle_deg)
        self.rotate(angle_rad)
        return {"ok": True, "message": f"Rotated {angle_deg}°"}

    def _fc_guide_to_booth(self, args: dict) -> dict:
        """Guide a visitor to a named location, wait, then return home."""
        location_name = args.get("location_name", "")
        if not location_name:
            return {"ok": False, "error": "location_name is required"}
        if not self._ctrl:
            return {"ok": False, "error": "Robot not connected"}

        from location_service import location_service
        matched = location_service.resolve_location_name(location_name)
        if not matched:
            all_locs = location_service.get_all_locations()
            return {"ok": False, "error": f"找不到地點: {location_name}",
                    "available": [loc["name"] for loc in all_locs]}

        result = self._ctrl.move_to_location(matched["id"], timeout=120)
        if not result.get("ok"):
            return result

        dwell_time = settings_service.get("guide_dwell_time", 30)
        time.sleep(dwell_time)

        self._ctrl.return_home(timeout=120)
        return {"ok": True, "message": f"已完成 {matched['name']} 導覽並返回"}


    def _fc_notify_staff(self, args: dict) -> dict:
        """Send a notification message to staff via Telegram."""
        message = args.get("message", "")
        if not message:
            return {"ok": False, "error": "message is required"}
        chat_ids = _get_telegram_chat_ids()
        token = settings_service.get("telegram_bot_token", "")
        if not chat_ids or not token:
            return {"ok": False, "error": "Telegram not configured"}
        _send_telegram_text(f"📢 通知\n\n{message}", chat_ids, token)
        return {"ok": True, "message": "Notification sent to staff"}

    def _fc_deliver_drink(self, args: dict) -> dict:
        """Deliver the drink shelf to the configured destination."""
        if not self._ctrl:
            return {"ok": False, "error": "Robot not connected"}
        shelf_id = settings_service.get("drink_shelf_id", "S01")
        destination_id = settings_service.get("kiosk_location", "")
        if not destination_id:
            return {"ok": False, "error": "kiosk_location not configured in settings"}
        return self._ctrl.move_shelf(shelf_id, destination_id, timeout=120)

    def _fc_return_drink(self, args: dict) -> dict:
        """Return the drink shelf to its home location."""
        if not self._ctrl:
            return {"ok": False, "error": "Robot not connected"}
        shelf_id = settings_service.get("drink_shelf_id", "S01")
        result = self._ctrl.return_shelf(shelf_id, timeout=60)
        if not result.get("ok"):
            return result
        self._ctrl.return_home(timeout=120)
        return {"ok": True, "message": "飲料架已歸位，機器人返回充電座"}

    def _fc_get_patrol_history(self, args: dict) -> dict:
        """Return recent patrol run summaries."""
        import patrol_db
        patrol_db.init_db()
        count = args.get("count", 5)
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 5
        runs = patrol_db.get_runs(limit=count)
        summaries = []
        for r in runs:
            summaries.append({
                "run_id": r["id"],
                "time": r["start_time"],
                "status": r["status"],
                "summary": (r.get("report_content") or "")[:200],
            })
        return {"ok": True, "history": summaries}

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
