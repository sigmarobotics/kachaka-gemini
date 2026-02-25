"""Frame Hub — centralized camera frame access for patrol and video recording."""

import base64
import io
import time
from PIL import Image
from robot_manager import robot_manager


class FrameHub:
    def __init__(self):
        self._last_fetch_time = 0.0

    def get_latest_frame_bytes(self) -> bytes | None:
        return robot_manager.get_camera_jpeg_bytes()

    def get_latest_frame_pil(self) -> Image.Image | None:
        jpeg = self.get_latest_frame_bytes()
        if not jpeg:
            return None
        return Image.open(io.BytesIO(jpeg))

    def get_latest_frame_base64(self) -> str | None:
        frame = robot_manager.get_camera_frame()
        if frame and frame.get("ok") and frame.get("image_base64"):
            return frame["image_base64"]
        return None

    def wait_for_fresh_frame(self, timeout: float = 10.0) -> bytes | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jpeg = self.get_latest_frame_bytes()
            if jpeg:
                self._last_fetch_time = time.monotonic()
                return jpeg
            time.sleep(0.2)
        return None

    def save_frame(self, path: str) -> bool:
        jpeg = self.wait_for_fresh_frame(timeout=10.0)
        if not jpeg:
            return False
        with open(path, "wb") as f:
            f.write(jpeg)
        return True


frame_hub = FrameHub()
