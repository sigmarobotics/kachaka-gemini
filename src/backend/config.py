import os

ROBOT_IP = os.environ.get("ROBOT_IP", "192.168.50.133:26400")

# Data dir - support both local dev and Docker
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(BASE_DIR, "data")):
    DATA_DIR = os.path.join(BASE_DIR, "data")
else:
    DATA_DIR = os.path.join(BASE_DIR, "..", "..", "data")

DEFAULT_FUNCTION_DECLARATIONS = [
    {
        "name": "move_to_location",
        "description": "Move the robot to a specific location. Use the location ID from the background info.",
        "parameters": {
            "type": "object",
            "properties": {
                "location_id": {
                    "type": "string",
                    "description": "ID of the target location (e.g. 'L01', 'home')",
                }
            },
            "required": ["location_id"],
        },
    },
    {
        "name": "move_shelf",
        "description": "Pick up a shelf and deliver it to a location. Use IDs from the background info.",
        "parameters": {
            "type": "object",
            "properties": {
                "shelf_id": {
                    "type": "string",
                    "description": "ID of the shelf to move",
                },
                "destination_id": {
                    "type": "string",
                    "description": "ID of the destination location",
                },
            },
            "required": ["shelf_id", "destination_id"],
        },
    },
    {
        "name": "return_shelf",
        "description": "Return a shelf to its home location. Use the shelf ID from the background info.",
        "parameters": {
            "type": "object",
            "properties": {
                "shelf_id": {
                    "type": "string",
                    "description": "ID of the shelf to return",
                }
            },
            "required": ["shelf_id"],
        },
    },
    {
        "name": "get_robot_status",
        "description": "Get the current robot status including battery level and position.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_command",
        "description": "Cancel the currently running robot command. Use this if the user wants to stop the robot.",
        "parameters": {"type": "object", "properties": {}},
    },
]

DEFAULT_INTERIM_PHRASES = {
    "move_to_location": "好的，正在前往目的地",
    "move_shelf": "好的，正在搬運貨架",
    "return_shelf": "好的，正在歸還貨架",
    "get_robot_status": "正在查詢機器人狀態",
    "cancel_command": "正在取消目前的指令",
}

DEFAULT_SETTINGS = {
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash-native-audio-latest",
    "response_mode": "audio",          # "audio" or "text"
    "enable_google_search": False,
    "persona": (
        "你是一個智能機器人助手，控制著一台 Kachaka 機器人。"
        "你可以幫助使用者導航到不同地點、搬運貨架、查詢機器人狀態等。"
        "請用繁體中文回答，語氣友善且簡潔。"
    ),
    "static_knowledge": (
        "呼叫功能時，一律使用背景資訊中的 ID（而非名稱）作為參數。"
        "當使用者要求移動到某個地方時，根據背景資訊找到對應的 location_id 執行 move_to_location。"
        "當使用者要求送貨時，使用 move_shelf 功能，傳入 shelf_id 和 destination_id。"
    ),
    "knowledge_base": "",
    "robot_background_info": "",
    "function_declarations": DEFAULT_FUNCTION_DECLARATIONS,
    "voice_name": "Aoede",
    "shelf_ids": [],
    "enable_camera_to_ai": False,
    "enable_interim_response": False,
    "interim_phrases": DEFAULT_INTERIM_PHRASES,
    "interim_audio": {},
    "robot_ip": ROBOT_IP,
}
