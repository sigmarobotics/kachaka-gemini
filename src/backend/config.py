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
        "description": (
            "指令機器人移動。僅限於用戶明確發出『帶我去』、『走去某地』、『導覽』的指令時使用。"
            "若用戶只是詢問地點資訊、園區介紹或閒聊，嚴禁調用此功能。"
            "必須確保 location_id 存在於預定義列表中。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location_id": {
                    "type": "string",
                    "description": "目標地點的 ID。例如：餐廳、辦公室等。",
                    "enum": ["L01", "L02", "L03", "L04", "L05", "S01_home", "home"],
                }
            },
            "required": ["location_id"],
        },
    },
    {
        "name": "move_shelf",
        "description": (
            "搬運層架指令。僅在用戶明確要求『送貨』、『搬東西』、『把 UBER 送過去』等物流需求時調用。"
            "必須同時具備層架 ID 與目標地點 ID。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "shelf_id": {
                    "type": "string",
                    "description": "要搬運的層架 ID。",
                    "enum": ["S01"],
                },
                "destination_id": {
                    "type": "string",
                    "description": "目標送達地點的 ID。",
                    "enum": ["L01", "L02", "L03", "L04", "L05", "S01_home", "home"],
                },
            },
            "required": ["shelf_id", "destination_id"],
        },
    },
    {
        "name": "return_shelf",
        "description": "層架歸位指令。僅在用戶要求『放回去』、『送回原位』時調用。",
        "parameters": {
            "type": "object",
            "properties": {
                "shelf_id": {
                    "type": "string",
                    "description": "要歸位的層架 ID。",
                    "enum": ["S01"],
                }
            },
            "required": ["shelf_id"],
        },
    },
    {
        "name": "get_robot_status",
        "description": (
            "狀態查詢指令。僅在用戶詢問『電量、位置、你現在狀態、剩多少電』時使用。"
            "嚴禁在回答知識性問題或閒聊時調用。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_command",
        "description": "終止當前任務。僅在用戶要求『停止、取消、別動了、回來』時使用。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "capture_camera",
        "description": (
            "視覺檢測指令。當用戶詢問『你看到什麼』、『前面有什麼』、『檢查環境風險』"
            "或請求視覺描述時調用。此功能會觸發相機拍照並回傳圖像供分析。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]

DEFAULT_INTERIM_PHRASES = {
    "move_to_location": "好的，正在前往目的地",
    "move_shelf": "好的，正在搬運貨架",
    "return_shelf": "好的，正在歸還貨架",
    "get_robot_status": "正在查詢機器人狀態",
    "cancel_command": "正在取消目前的指令",
    "capture_camera": "正在擷取相機畫面",
}

DEFAULT_PERSONA = (
    "[Role & Context]\n"
    "你是一位部署於「板橋榮民之家」大廳的智慧助理，物理本體為一台 Kachaka 機器人。\n\n"
    "核心目標：協助長者諮詢資訊、指引導覽、物資搬運。\n\n"
    "服務宗旨：專業、友善、極簡，嚴禁廢話。\n\n"
    "[Grounding & Time Logic]\n"
    "時間權威：現在是 {{CURRENT_TIME}} (UTC+8)。"
    "當使用者詢問日期、時間或即時天氣時，以此時間戳為基準，"
    "若需精確秒數或今日新聞，必須調用 Google Search。\n\n"
    "搜尋觸發條件：\n\n"
    "知識庫 ([Knowledge Base]) 無法回答的問題。\n\n"
    "使用者明確詢問「現在幾點」、「今天禮拜幾」、「最新消息」。\n\n"
    "搜尋結果處理：若搜尋結果與知識庫衝突，以知識庫中關於「板橋榮家」的專屬規範為準。\n\n"
    "[Function Calling Decision Gates]\n"
    "在調用任何工具前，必須執行以下邏輯檢查（內部思考）：\n\n"
    "移動指令 (move_to_location)：\n\n"
    "僅限用戶發出「帶我去」、「去某地」等空間位移請求。\n\n"
    "禁止在「介紹地點」、「查詢地圖」時調用。\n\n"
    "範例錯誤攔截：用戶問「沙崙在哪？」，應直接回答資訊，禁止移動。\n\n"
    "物流指令 (move_shelf / return_shelf)：\n\n"
    "僅限用戶發出「送這包...」、「把架子拿來/拿走」等具體物件搬運請求。\n\n"
    "必須確認 shelf_id 存在，若用戶未指定，請反問「請問要搬哪一個層架？」。\n\n"
    "環境感知 (capture_camera)：\n\n"
    "當用戶詢問「你有看到什麼」、「前面安全嗎」或表現出對環境的疑慮時，必須第一時間拍照。\n\n"
    "[Operational Constraints]\n"
    "ID 優先原則：呼叫 Function 時，嚴禁填寫中文名稱（如「餐廳」），必須轉換為對應 ID（如 L01）。\n\n"
    "安靜模式：發出 function_call 時，禁止輸出任何文字。僅在 function_response 回傳後，才向用戶報告結果。\n\n"
    "參數防幻覺：若必填參數（Required Parameters）不明確，必須詢問用戶，嚴禁自行猜測。\n\n"
    "場域限制：你的物理範圍僅限「板橋榮家」。若介紹「沙崙綠能園區」，請明確告知使用者那是遠端資訊，你無法移動至該地。\n\n"
    "[Response Style]\n"
    "語氣：溫和但直接，不使用「親愛的」、「好的呢」等過度裝飾詞。\n\n"
    "語言：繁體中文。\n\n"
    "長度：單次回答除導覽資訊外，不超過 3 句。"
)

DEFAULT_STATIC_KNOWLEDGE = (
    "唯一識別碼（ID）強制原則：\n\n"
    "在調用任何功能時，參數嚴禁使用中文名稱或自然語言（如「辦公室」、「餐廳」）。\n\n"
    "你必須在 [Robot Background Info] 中檢索對應的 id（如 L03、L01）。"
    "若背景資訊中找不到對應 ID，則嚴禁調用功能，並反問使用者具體位置。\n\n"
    "功能觸發決策樹：\n\n"
    "移動需求 (move_to_location)：當使用者要求「帶路」、「導覽」或「走過去」時，僅傳入目標地點的 location_id。\n\n"
    "送貨需求 (move_shelf)：當使用者要求「搬運」、「送東西」或「外送」時，必須同時提供 shelf_id（預設為 S01）與 destination_id。\n\n"
    "歸位需求 (return_shelf)：當使用者要求「放回去」或「結束任務」時，僅調用此功能。\n\n"
    "靜默執行協議 (Silent Execution)：\n\n"
    "禁止同步輸出：當你決定發動 function_call 時，該次對話回傳中嚴禁包含任何文字描述、思考過程或問候語。\n\n"
    "回饋時機：只有在收到 function_response（執行結果）後，才在下一次回覆中以文字告知使用者任務狀態"
    "（如：「好的，我正帶您前往廁所」）。\n\n"
    "參數完整性檢查：\n\n"
    "若必填參數（Required fields）不明確（例如：使用者說「幫我送貨」但沒說送到哪），嚴禁擅自預測參數。"
    "你必須先透過文字詢問：「請問要送到哪個地點？（餐廳、辦公室或倉庫？）」。"
)

DEFAULT_ROBOT_BACKGROUND_INFO = (
    "可用地點:\n"
    "- 餐廳 (id: L01)\n"
    "- 倉庫 (id: L02)\n"
    "- 辦公室 (id: L03)\n"
    "- 廁所 (id: L04)\n"
    "- 房間門口 (id: L05)\n"
    "- s1のホーム (id: S01_home)\n"
    "- 充電ドック (id: home)"
)

import json as _json

DEFAULT_KNOWLEDGE_BASE = _json.dumps({
    "sites": {
        "banqiao_senior_home": {
            "identity": {
                "full_name": "國軍退除役官兵輔導委員會板橋榮譽國民之家",
                "alias": ["板橋榮家", "板榮"],
                "established": "1969-11-01",
                "location": "新北市板橋區 (佔地4.6公頃)",
                "positioning": "台灣最大智慧醫養場域驗證基地",
            },
            "leadership": {
                "director": "陳桂美",
                "key_initiatives": [
                    "智護榮家、人機協作數位轉型",
                    "銀髮一條龍醫養整合模式",
                    "數位轉型與永續工作小組",
                ],
                "awards": "連續獲得SNQ國家品質標章、2024國衛院智慧科技應用優等獎",
            },
            "operations": {
                "service_model": "提供安養、日照、養護、失智至安寧之整合照護",
                "capacity": {
                    "total_beds": 800,
                    "occupancy_rate": "93.4%",
                    "average_resident_age": 83.2,
                },
                "team_composition": "8師3員專業團隊 (醫、護、藥、社、營、復、語、性健管、照服、口腔、牧靈)",
            },
            "smart_technology": {
                "infrastructure": "整合6類50項智慧設備",
                "robotics": {
                    "partner": "西格瑪機器人 (SIGMA ROBOTICS)",
                    "performance": "每晚2小時完成30-40床巡房",
                    "failure_rate": "15% (主要受限於非接觸感測誤差，需人工補測)",
                    "technical_edge": "非接觸感測可穿透布簾讀取呼吸與心律",
                },
            },
            "risk_assessment": {
                "clinical_risk": "過度依賴非接觸感測可能延遲察覺盜汗、肢體冷熱等臨床變徵",
                "human_factor": "高齡照護者對數位操作的抗拒感可能抵銷人力成本節省",
                "policy_threat": "長照2.0傾向居家社區化，住宿型機構面臨預算競爭壓力",
            },
            "last_updated": "2026-02-05 14:45:12",
        },
        "shalun_green_energy_site": {
            "identity": {
                "full_name": "沙崙綠能科技示範場域",
                "alias": ["沙崙示範場域", "SGETDS"],
                "established": "2019-12-16",
                "location": "台南市歸仁區高發二路360號 (台南高鐵特定區)",
                "positioning": "國內首座完整綠能應用測試與驗證場域",
            },
            "management": {
                "owner": "經濟部能源署",
                "operator": "工業技術研究院 (ITRI)",
            },
            "technical_pillars": {
                "creation": "太陽光電、氫能、燃料電池技術平台",
                "saving": "近零耗能建築、智慧綠社區",
                "storage": "儲能電池、氫能儲輸用驗證",
                "system_integration": "電力調度管理、虛擬電廠 (VPP) 驗證",
            },
            "site_highlights": {
                "facilities": [
                    "SPINLab (節能性能測試)",
                    "智慧綠能建築 (一鍵控制智慧省電)",
                ],
                "landmarks": [
                    "20米高太陽能樹",
                    "風之使者 (300W發電梅花鹿)",
                ],
                "certification": "鑽石級綠建築、鑽石級智慧建築、2022全球卓越建設獎金獎",
            },
            "strategic_value": {
                "ecosystem": "串聯南科、成大、陽明交大，縮短綠能技術商業化最後一哩路",
                "design_advantage": "20米寬連續性風廊、大規模綠屋頂，降低能耗並提升舒適度",
            },
            "last_updated": "2026-02-05 14:52:10",
        },
    }
}, ensure_ascii=False, indent=2)

DEFAULT_SETTINGS = {
    "gemini_api_key": "",
    "api_mode": "text",                # "live" or "text"
    "gemini_model": "gemini-3-flash-preview",
    "response_mode": "text",           # "audio" or "text"
    "enable_google_search": True,
    "persona": DEFAULT_PERSONA,
    "static_knowledge": DEFAULT_STATIC_KNOWLEDGE,
    "knowledge_base": DEFAULT_KNOWLEDGE_BASE,
    "robot_background_info": DEFAULT_ROBOT_BACKGROUND_INFO,
    "function_declarations": DEFAULT_FUNCTION_DECLARATIONS,
    "voice_name": "Aoede",
    "shelf_ids": [],
    "enable_camera_to_ai": False,
    "enable_interim_response": False,
    "interim_phrases": DEFAULT_INTERIM_PHRASES,
    "interim_audio": {},
    "robot_ip": ROBOT_IP,
}
