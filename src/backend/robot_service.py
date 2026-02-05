import threading
import time
import kachaka_api
from config import ROBOT_IP


class RobotService:
    def __init__(self):
        self.client = None
        self.client_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.robot_state = {
            "battery": 0,
            "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
            "map_info": {
                "resolution": 0.05,
                "width": 0,
                "height": 0,
                "origin_x": 0.0,
                "origin_y": 0.0,
            },
        }
        self.map_image_bytes = None

        self.polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self.polling_thread.start()

    def connect(self):
        try:
            new_client = kachaka_api.KachakaApiClient(ROBOT_IP)
            new_client.get_robot_serial_number()
            with self.client_lock:
                self.client = new_client
            print(f"Connected to Kachaka at {ROBOT_IP}")
            return True
        except Exception as e:
            print(f"Failed to connect to Kachaka at {ROBOT_IP}: {e}")
            with self.client_lock:
                self.client = None
            return False

    def get_client(self):
        with self.client_lock:
            return self.client

    def _polling_loop(self):
        while True:
            with self.client_lock:
                current_client = self.client

            if not current_client:
                self.connect()
                with self.client_lock:
                    current_client = self.client
                if not current_client:
                    time.sleep(2)
                    continue

            # Fetch map if missing
            with self.state_lock:
                map_missing = self.map_image_bytes is None

            if map_missing:
                try:
                    png_map = current_client.get_png_map()
                    with self.state_lock:
                        self.map_image_bytes = png_map.data
                        self.robot_state["map_info"].update({
                            "resolution": png_map.resolution,
                            "width": png_map.width,
                            "height": png_map.height,
                            "origin_x": png_map.origin.x,
                            "origin_y": png_map.origin.y,
                        })
                except Exception as e:
                    print(f"Error fetching map: {e}")

            # Poll status
            try:
                pose = current_client.get_robot_pose()
                battery = current_client.get_battery_info()

                with self.state_lock:
                    actual_pose = getattr(pose, "pose", pose)
                    self.robot_state["pose"].update({
                        "x": actual_pose.x,
                        "y": actual_pose.y,
                        "theta": actual_pose.theta,
                    })

                    if isinstance(battery, tuple) and len(battery) > 0:
                        self.robot_state["battery"] = int(battery[0])
                    elif hasattr(battery, "percentage"):
                        self.robot_state["battery"] = int(battery.percentage)
                    else:
                        self.robot_state["battery"] = (
                            int(battery) if isinstance(battery, (int, float)) else 0
                        )

            except Exception as e:
                print(f"Error polling robot state: {e}")
                with self.client_lock:
                    self.client = None

            time.sleep(0.1)

    def get_state(self):
        with self.state_lock:
            return self.robot_state.copy()

    def get_map_bytes(self):
        with self.state_lock:
            return self.map_image_bytes

    def move_to(self, x, y, theta, wait=True):
        client = self.get_client()
        if client:
            return client.move_to_pose(x, y, theta, wait_for_completion=wait)
        return None

    def move_forward(self, distance, speed=0.1):
        client = self.get_client()
        if client:
            client.move_forward(distance_meter=distance, speed=speed)

    def rotate(self, angle):
        client = self.get_client()
        if client:
            client.rotate_in_place(angle_radian=angle)

    def return_home(self):
        client = self.get_client()
        if client:
            return client.return_home()

    def cancel_command(self):
        client = self.get_client()
        if client:
            client.cancel_command()

    def get_front_camera_image(self):
        client = self.get_client()
        if client:
            return client.get_front_camera_ros_compressed_image()
        return None

    def get_locations(self):
        client = self.get_client()
        if client:
            try:
                locations = client.get_locations()
                result = []
                for loc in locations:
                    result.append({
                        "id": loc.id,
                        "name": loc.name,
                        "x": loc.pose.x,
                        "y": loc.pose.y,
                        "theta": loc.pose.theta,
                    })
                return result
            except Exception as e:
                print(f"Error getting locations: {e}")
                return []
        return []

    def get_shelves(self):
        client = self.get_client()
        if client:
            try:
                shelves = client.get_shelves()
                result = []
                for shelf in shelves:
                    result.append({
                        "id": shelf.id,
                        "name": shelf.name,
                        "home_location_id": getattr(shelf, "home_location_id", ""),
                    })
                return result
            except Exception as e:
                print(f"Error getting shelves: {e}")
                return []
        return []

    def move_to_location(self, location_id, wait=False):
        client = self.get_client()
        if client:
            try:
                result = client.move_to_location(
                    location_id, wait_for_completion=wait
                )
                return {"success": True, "result": str(result)}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Robot not connected"}

    def move_shelf(self, shelf_id, location_id, wait=False):
        client = self.get_client()
        if client:
            try:
                result = client.move_shelf(
                    shelf_id, location_id, wait_for_completion=wait
                )
                return {"success": True, "result": str(result)}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Robot not connected"}

    def return_shelf(self, shelf_id, wait=False):
        client = self.get_client()
        if client:
            try:
                result = client.return_shelf(shelf_id, wait_for_completion=wait)
                return {"success": True, "result": str(result)}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Robot not connected"}

    def speak(self, text):
        client = self.get_client()
        if client:
            try:
                result = client.speak(text)
                return {"success": True, "result": str(result)}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Robot not connected"}

    def get_command_state(self):
        client = self.get_client()
        if client:
            try:
                state = client.get_command_state()
                return {"state": str(state)}
            except Exception as e:
                return {"state": "unknown", "error": str(e)}
        return {"state": "disconnected"}

    def get_serial(self):
        client = self.get_client()
        if client:
            return client.get_robot_serial_number()
        return "unknown"


robot_service = RobotService()
