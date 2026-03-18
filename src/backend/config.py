import os

# Fallback robot IP from env var. Primary source is settings.json "robot_ip" field.
ROBOT_IP = os.environ.get("ROBOT_IP", "192.168.50.133:26400")


def _clamp(value, lo, hi, default, cast=float):
    """Clamp a settings value to [lo, hi] with type coercion."""
    try:
        v = cast(value)
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return default

# Data dir - support both local dev and Docker
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(BASE_DIR, "data")):
    DATA_DIR = os.path.join(BASE_DIR, "data")
else:
    DATA_DIR = os.path.join(BASE_DIR, "..", "..", "data")

DEFAULT_FUNCTION_DECLARATIONS = [
    {
        "name": "capture_camera",
        "description": (
            "從目前位置拍照並進行視覺分析，不移動。"
            "僅在用戶明確要求你「看」、「拍」目前眼前的東西時調用。"
            "例如：『你前面有什麼？』『幫我拍一張』『看看這是什麼』。"
            "注意：用戶詢問你的相機規格、能不能拍照、展覽內容等問題時，"
            "不要調用此功能，直接口頭回答即可。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "使用者的原始需求或問題，例如：'前面有什麼障礙物？'、'幫我看看這是什麼'",
                },
            },
        },
    },
    {
        "name": "inspect_location",
        "description": (
            "前往指定地點拍照分析後自動返回。"
            "僅在用戶明確要求你「去」某個地點「看」或「檢查」時調用。"
            "例如：『去辦公室101看有沒有人』『幫我去餐廳檢查一下』。"
            "注意：用戶只是提到或評論某地點"
            "（如『廁所好像有人排隊』『辦公室101好酷』）時不要調用，直接回應即可。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location_name": {
                    "type": "string",
                    "description": "目標地點的名稱（從可用地點列表中選擇）",
                    "enum": [],  # Dynamically populated at connect time
                },
                "prompt": {
                    "type": "string",
                    "description": "分析指示，例如：'看看有沒有人'、'檢查是否有異常'",
                },
            },
            "required": ["location_name"],
        },
    },
    {
        "name": "patrol_all",
        "description": (
            "啟動全域巡檢，依序前往所有巡邏點後返回。"
            "僅在用戶明確要求「去巡邏」或「開始巡檢」時調用。"
            "注意：用戶詢問巡邏相關問題（如『巡邏要多久？』『上次巡邏結果如何？』）"
            "時不要調用，直接回答即可。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "rotate",
        "description": (
            "原地旋轉指定角度。正值=左轉，負值=右轉，預設15度。"
            "僅在用戶明確要求「轉」的時候調用，"
            "例如：『左轉』『往右轉30度』。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "angle": {
                    "type": "number",
                    "description": "旋轉角度（度），正值=左轉，負值=右轉。預設15度。",
                },
            },
        },
    },
    {
        "name": "guide_to_booth",
        "description": (
            "帶領訪客前往指定地點。"
            "僅在用戶明確要求你「帶路」或「帶我去」某地時調用。"
            "例如：『帶我去餐廳』『我要去辦公室101』『take me to the warehouse』。"
            "注意：以下情況不要調用——用戶只是問路（『出口在哪？』『停車場怎麼走？』）、"
            "提到地點但沒有要求前往（『我朋友在辦公室102』『餐廳好多人』）、"
            "或詢問地點資訊（『辦公室101展什麼？』）。這些情況請直接口頭回答。"
            "location_name 必須從 enum 中選擇，不可使用列表外的地點名稱。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location_name": {
                    "type": "string",
                    "description": "目標攤位或地點名稱（從可用地點列表中選擇）",
                    "enum": [],  # Dynamically populated at connect time
                },
            },
            "required": ["location_name"],
        },
    },
    {
        "name": "notify_staff",
        "description": (
            "通知工作人員（透過 Telegram）。"
            "僅在用戶明確要求你「通知」或「叫」工作人員時調用。"
            "例如：『幫我叫工作人員來』『通知一下staff』。"
            "注意：用戶只是描述問題（如『地上有水』）但沒有明確要求通知時，"
            "先詢問是否需要通知工作人員。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "要通知的訊息內容",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "deliver_drink",
        "description": (
            "搬運飲料架到指定地點。"
            "僅在用戶明確要求「送飲料」時調用。"
            "用戶詢問飲料服務相關問題（如『你會送飲料嗎？』）時不要調用，直接回答。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "return_drink",
        "description": (
            "將飲料架搬回原位並返回充電站。"
            "僅在用戶明確要求「收回」飲料架時調用。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_patrol_history",
        "description": "查詢巡檢歷史紀錄。適合『上次巡檢結果』、『巡檢紀錄』等需求。",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "查詢最近幾筆紀錄（預設 5）",
                },
            },
        },
    },
    # Low-level FCs — disabled by default, for testing/advanced use
    {
        "name": "move_to_location",
        "description": (
            "低階移動指令。指定 location_id 直接移動機器人。"
            "一般情況請使用 inspect_location。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location_id": {
                    "type": "string",
                    "description": "目標地點的 ID",
                }
            },
            "required": ["location_id"],
        },
        "enabled": False,
    },
    {
        "name": "move_shelf",
        "description": (
            "搬運層架指令。必須同時具備層架 ID 與目標地點 ID。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "shelf_id": {
                    "type": "string",
                    "description": "要搬運的層架 ID。",
                },
                "destination_id": {
                    "type": "string",
                    "description": "目標送達地點的 ID。",
                },
            },
            "required": ["shelf_id", "destination_id"],
        },
        "enabled": False,
    },
    {
        "name": "return_shelf",
        "description": "層架歸位指令。",
        "parameters": {
            "type": "object",
            "properties": {
                "shelf_id": {
                    "type": "string",
                    "description": "要歸位的層架 ID。",
                }
            },
            "required": ["shelf_id"],
        },
        "enabled": False,
    },
    {
        "name": "get_robot_status",
        "description": "狀態查詢指令。查詢電量、位置等資訊。",
        "parameters": {"type": "object", "properties": {}},
        "enabled": False,
    },
    {
        "name": "cancel_command",
        "description": "終止當前任務。",
        "parameters": {"type": "object", "properties": {}},
        "enabled": False,
    },
]

DEFAULT_PERSONA = (
    "## Role\n"
    "你是由 Sigma Robotics 開發的「物理 AI (Physical AI) 導覽大使」。"
    "你目前在 2026 智慧城市展現場，代表「台南市政府經發局」與「SIG 聯盟」"
    "展示一套已在沙崙綠能科技示範場域成功落地的「物理AI方案」。\n\n"
    "## Persona\n"
    "* **專業背景**：你不是單一廠商的封閉系統，而是代表一個「通用平台」，"
    "強調透過 MCP (Model Context Protocol) 整合多家專精廠商"
    "（如：Preferred Robotics 的底盤、CUPOLA 的 360 相機、Google 的雲端大模型 Gemini 3）。\n"
    "* **說話風格**：科技感十足且專業。由於展場吵雜，每段回覆請控制在 50 字內。"
    "另外，你可以執行多語系的對話，包含中文，英文，日文。用使用者提問的語言回覆他。\n"
    "* **核心使命**：向訪客證明透過「水平分工」與「雲端 VLM 判讀」，"
    "能以極低成本達成不間斷的精準導覽與巡檢。"
)

DEFAULT_STATIC_KNOWLEDGE = (
    "[Function Calling Decision Rules]\n\n"
    "IMPORTANT: 你是一個對話型機器人。大多數使用者訊息是閒聊 — 直接回答即可。\n"
    "只有當使用者發出明確的行動指令時，才觸發 function_call。\n\n"
    "1. 以下情況「不要」觸發任何 function_call：\n"
    "   - 使用者在「問問題」（即使提到地點）：「出口在哪？」「廁所乾淨嗎？」「office 103展示什麼？」\n"
    "   - 使用者在「評論或觀察」：「廁所好像有人排隊」「餐廳好多人」「辦公室101好酷」\n"
    "   - 使用者在詢問你的「功能或規格」：「你可以拍照嗎？」「你會送飲料嗎？」「巡邏要多久？」\n"
    "   - 使用者在講「假設性」的話：「如果我想去辦公室101...」「要是去巡邏的話...」\n"
    "   - 使用者在打招呼、聊天、或問一般常識問題\n"
    "   - 使用者提到了某個地點，但並沒有要求你「去」那裡或「做」什麼\n"
    "   → 這些情況都直接用文字回答，不觸發 function_call。\n\n"
    "2. 以下情況才觸發 function_call：\n"
    "   - 使用者發出「明確指令」要求你執行動作：\n"
    "     * 「帶我去餐廳」→ guide_to_booth（明確要求帶路）\n"
    "     * 「去辦公室101看有沒有人」→ inspect_location（明確要求去檢查）\n"
    "     * 「拍一張照片」/「你前面有什麼」→ capture_camera（明確要求看/拍）\n"
    "     * 「去巡一下」→ patrol_all（明確要求巡邏）\n"
    "     * 「左轉30度」→ rotate（明確要求旋轉）\n"
    "     * 「通知工作人員」→ notify_staff（明確要求通知）\n"
    "     * 「送飲料到餐廳」→ deliver_drink（明確要求送飲料）\n\n"
    "3. 多語言語意對應：\n"
    "   - [辦公室]：「辦公室」「Office」「事務室」「オフィス」\n"
    "   - [廁所]：「廁所」「Toilet」「Restroom」「トイレ」「お手洗い」\n"
    "   - [倉庫]：「倉庫」「Warehouse」「ストレージ」\n\n"
    "4. 釐清與確認規則：\n"
    "   - 若用戶要求導覽到一個存在多個選項的類別（例：「帶我去辦公室」但有辦公室101和辦公室102）："
    "你必須先問是哪一個，不觸發 function_call。\n"
    "   - 例外（廁所）：用戶說「帶我去廁所」但沒指定哪一間，自動選距離最近的。\n"
    "   - 若用戶要求的地點不在可用列表中：告知不存在並列出可用選項，不觸發 function_call。\n"
    "   - location_name 參數必須是可用地點列表中的精確名稱，絕不可自行編造。\n\n"
    "5. 執行協議：\n"
    "   - 觸發 function_call 時，可以簡短確認（如「好的，馬上去」），但嚴禁預測或描述尚未收到的執行結果。\n"
    "   - 收到 function_response 後，再回報實際結果。\n"
    "   - 若必填參數不明確，嚴禁擅自預測，必須先詢問使用者。"
)

DEFAULT_ROBOT_BACKGROUND_INFO = (
    "{{AVAILABLE_LOCATIONS}}"
)


DEFAULT_KNOWLEDGE_BASE = (
    "## 沙崙綠能科技示範場域 (SGETDS)\n"
    "- **身分**：國內首座完整綠能驗證場域，工研院營運。"
    "獲得 2022 全球卓越建設獎金獎、鑽石級綠建築認證。\n"
    "- **亮點**：20米高太陽能樹、風之使者 (梅花鹿發電裝置)、SPINLab 節能測試。\n\n"
    "## 交通指南\n"
    "- **高鐵轉乘**：台南高鐵站 2 樓通廊直通台鐵沙崙站。步行至 SGETDS 約 10-15 分鐘。\n"
    "- **智慧接駁**：高鐵 4 號出口可搭乘「電動接駁小巴」前往園區各點。\n\n"
    "## 周邊美食\n"
    "- **三井 Outlet**：高鐵站對面，推薦合點壽司、NARA Thai。\n"
    "- **在地必吃**：長榮大學蒜頭飯、阿裕牛肉涮涮鍋 (車程10分)、卜卜角餃子店。"
)

DEFAULT_SETTINGS = {
    "gemini_api_key": "",
    "telegram_bot_token": "",
    "api_mode": "text",
    "text_model": "gemini-3-flash-preview",
    "live_model": "gemini-2.5-flash-native-audio-preview-12-2025",
    "text_enable_google_search": True,
    "live_enable_google_search": False,
    # Generation parameters (per-mode)
    "text_temperature": 1.0,
    "text_max_output_tokens": 8192,
    "text_top_p": 0.95,
    "text_top_k": 40,
    "text_safety_settings": {},
    "live_temperature": 1.0,
    "live_max_output_tokens": 8192,
    "live_top_p": 0.95,
    "live_top_k": 40,
    "live_safety_settings": {},
    "persona": DEFAULT_PERSONA,
    "static_knowledge": DEFAULT_STATIC_KNOWLEDGE,
    "knowledge_base": DEFAULT_KNOWLEDGE_BASE,
    "robot_background_info": DEFAULT_ROBOT_BACKGROUND_INFO,
    "function_declarations": DEFAULT_FUNCTION_DECLARATIONS,
    "voice_name": "Aoede",
    "live_auto_interrupt": True,
    "mute_buffer_s": 1.5,
    "show_camera": True,
    "robot_ip": ROBOT_IP,
    # Patrol settings
    "patrol_points": [],              # list of location IDs, e.g. ["L01", "L03"]
    "patrol_system_prompt": "你是一個巡檢機器人，使用一般標準進行檢查就好，不用太嚴格",
    "video_analysis_prompt": "請分析這段巡檢影片，描述觀察到的環境狀況、異常事項及建議。使用繁體中文。",
    "patrol_image_prompt": "請分析這張照片中的環境狀況。回答：大約人數、擁擠程度、簡短描述。繁體中文。",
    "patrol_telegram_notify": True,
    # Inspect / guide settings
    "inspect_dwell_time": 10,         # seconds to wait at inspection location
    "guide_dwell_time": 30,           # seconds to wait at guide destination
    # Drink delivery settings
    "drink_shelf_id": "S01",          # shelf ID for drink delivery
    # Exhibition settings
    "exhibition_title": "AI 機器人互動展示",
    "exhibition_quick_actions": [
        {"label": "巡檢", "command": "開始巡檢"},
        {"label": "查看報告", "action": "show_history"},
    ],
    "kiosk_location": "",
    # Telegram
    "telegram_chat_ids": [],          # list of chat IDs for notifications
}
