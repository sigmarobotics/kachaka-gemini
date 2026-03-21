# 系統架構文件

本文件詳細描述 Kachaka + Gemini 系統的內部架構，重點涵蓋 Text API / Live API 雙模式切換機制、Google Search 多層次呼叫策略、以及元件間的資料流。

---

## 目錄

- [系統總覽](#系統總覽)
- [高層架構圖](#高層架構圖)
- [雙 API 模式架構](#雙-api-模式架構)
  - [模式切換機制](#模式切換機制)
  - [Text API 模式詳解](#text-api-模式詳解)
  - [Live API 模式詳解](#live-api-模式詳解)
  - [雙模式差異對照](#雙模式差異對照)
- [Google Search 多層次呼叫架構](#google-search-多層次呼叫架構)
  - [問題背景](#問題背景)
  - [Text API 的分離式呼叫策略](#text-api-的分離式呼叫策略)
  - [Grounding 衝突處理](#grounding-衝突處理)
  - [Live API 的原生支援](#live-api-的原生支援)
  - [Google Search 完整流程圖](#google-search-完整流程圖)
- [函式呼叫架構](#函式呼叫架構)
- [對話資料流](#對話資料流)
  - [Text API 對話流程](#text-api-對話流程)
  - [Live API 對話流程](#live-api-對話流程)
  - [巡檢流程](#巡檢流程)
  - [Telegram 橋接流程](#telegram-橋接流程)
- [系統指令組裝](#系統指令組裝)
- [設定系統](#設定系統)
- [部署架構](#部署架構)

---

## 系統總覽

Kachaka + Gemini 是一個網頁應用程式，將 [Kachaka](https://kachaka.life/) 移動機器人橋接至 Google Gemini AI API。系統支援三種互動管道：

1. **網頁文字聊天** — 透過 Text API（REST `generateContent`）
2. **即時語音對話** — 透過 Live API（WebSocket `BidiGenerateContent`）
3. **Telegram 機器人** — 橋接至 Text API 會話

後端為 Python FastAPI 應用程式，同時提供 REST API 與 WebSocket 代理。前端為原生 JavaScript 單頁應用，無建置步驟。

---

## 高層架構圖

```mermaid
graph TB
    subgraph Browser["瀏覽器客戶端"]
        direction TB
        APP["app.js<br/>進入點 + 頁籤切換"]
        CHAT["demo-chat.js<br/>WebSocket + 音訊 I/O"]
        VOICE["demo-voice.js<br/>波形覆蓋層"]
        MAP["map.js<br/>Canvas 地圖 + 點擊移動"]
        SETTINGS_UI["settings.js<br/>設定介面 + FC 編輯器"]
        FILES_UI["files.js<br/>檔案管理"]
        STATUS["demo-status.js<br/>機器人狀態"]
        PATROL_UI["demo-patrol.js<br/>巡檢介面"]
        PCM["pcm-processor.js<br/>AudioWorklet 16kHz"]
        STATE["state.js<br/>共用狀態"]
    end

    subgraph Backend["FastAPI 後端"]
        MAIN["main.py<br/>路由 + WS + MJPEG"]

        subgraph GeminiLayer["Gemini 會話層"]
            LIVE["GeminiLiveSession<br/>BidiGenerateContent WS"]
            TEXT["GeminiTextSession<br/>generateContent REST"]
        end

        subgraph RobotLayer["機器人層"]
            RMGR["RobotManager<br/>kachaka_core 封裝"]
            FHUB["FrameHub<br/>相機存取"]
        end

        subgraph Services["應用服務"]
            PATROL["PatrolService<br/>背景巡檢"]
            TELEGRAM["TelegramBotManager<br/>每聊天室獨立會話"]
            REPORT["ReportService<br/>PDF + 影片分析"]
            FSVC["FileService<br/>Gemini Files API"]
        end

        subgraph Persistence["持久化層"]
            SETTINGS_SVC["settings_service<br/>JSON"]
            TOKEN_SVC["token_service<br/>SQLite"]
            PATROL_DB["patrol_db<br/>SQLite"]
            PROFILE_SVC["profile_service<br/>JSON"]
        end

        CONFIG["config.py<br/>預設值 + FC 宣告"]
    end

    subgraph External["外部服務"]
        GEMINI_TEXT_API["Gemini Text API<br/>generateContent"]
        GEMINI_LIVE_API["Gemini Live API<br/>BidiGenerateContent"]
        GEMINI_FILES_API["Gemini Files API"]
        TG_API["Telegram Bot API"]
    end

    ROBOT["Kachaka 機器人<br/>gRPC :26400"]

    %% 瀏覽器內部
    APP --> CHAT & MAP & SETTINGS_UI & FILES_UI & VOICE & STATUS & PATROL_UI
    CHAT --> PCM
    CHAT --> STATE
    MAP --> STATE

    %% 瀏覽器到後端
    Browser -- "WebSocket /ws/chat" --> MAIN
    Browser -- "REST /api/*" --> MAIN

    %% 後端路由
    MAIN --> LIVE & TEXT
    MAIN --> RMGR & PATROL & FSVC
    MAIN --> SETTINGS_SVC & TOKEN_SVC & PATROL_DB & PROFILE_SVC

    %% Gemini 會話
    LIVE -- "原始 WebSocket" --> GEMINI_LIVE_API
    LIVE -- "兩階段相機分析" --> GEMINI_TEXT_API
    TEXT -- "generateContent" --> GEMINI_TEXT_API
    LIVE --> RMGR
    TEXT --> RMGR

    %% 機器人
    RMGR -- "gRPC" --> ROBOT
    FHUB --> RMGR

    %% 服務
    PATROL --> RMGR & FHUB & PATROL_DB
    PATROL -- "VLM 巡檢分析" --> GEMINI_TEXT_API
    TELEGRAM -- "polling" --> TG_API
    TELEGRAM --> TEXT
    REPORT --> PATROL_DB
    FSVC --> GEMINI_FILES_API

    %% 設定
    LIVE --> SETTINGS_SVC & CONFIG
    TEXT --> SETTINGS_SVC & CONFIG

    style Browser fill:#1a1a2e,stroke:#b8860b,color:#e0e0e0
    style Backend fill:#16213e,stroke:#b8860b,color:#e0e0e0
    style External fill:#0f3460,stroke:#b8860b,color:#e0e0e0
    style GeminiLayer fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style RobotLayer fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style Services fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style Persistence fill:#1a2744,stroke:#b8860b,color:#e0e0e0
```

---

## 雙 API 模式架構

系統支援兩種根本不同的 Gemini API 模式，可在運行時透過介面切換。

### 模式切換機制

```mermaid
sequenceDiagram
    participant U as 使用者
    participant H as 頂部狀態列
    participant WS as /ws/chat
    participant M as main.py
    participant T as GeminiTextSession
    participant L as GeminiLiveSession

    U->>H: 切換 文字↔語音 開關
    H->>H: 更新 api_mode 設定<br/>POST /api/settings

    Note over H: 若已有連線，先斷開

    H->>WS: {type: "disconnect"}
    WS->>M: 關閉現有 session

    H->>WS: {type: "connect"}
    WS->>M: 建立新 session

    alt api_mode == "text"
        M->>T: new GeminiTextSession()
        T->>T: 建立 google-genai 客戶端
        T->>T: 組裝 system instruction
        T->>T: 篩選已啟用的函式宣告
        T-->>WS: {type: "status", message: "Connected", api_mode: "text"}
    else api_mode == "live"
        M->>L: new GeminiLiveSession()
        L->>L: 建立 WebSocket 至 Gemini
        L->>L: 發送 setup 訊息（模型、語音、工具、壓縮）
        L-->>WS: {type: "status", message: "Connected", api_mode: "live"}
    end

    WS-->>U: 顯示連線成功
```

**關鍵程式碼**（`main.py` WebSocket handler）：

```python
if msg_type == "connect":
    settings = settings_service.get_all()
    if settings.get("api_mode") == "live":
        session = GeminiLiveSession(send_to_client, settings)
    else:
        session = GeminiTextSession(send_to_client, settings)
    await session.connect()
```

### Text API 模式詳解

```mermaid
graph TD
    subgraph TextMode["Text API 模式"]
        direction TB
        CLIENT["google-genai SDK<br/>Client"]
        HISTORY["_history: list[Content]<br/>客戶端管理的對話歷史"]
        LOOP["函式呼叫迴圈<br/>call → execute → respond → repeat"]
        GS_WORKAROUND["Google Search 繞過<br/>（分離式 API 呼叫）"]
        FILE_INJECT["檔案注入<br/>Part.from_uri"]
        CAMERA_ATTACH["相機影像附加<br/>Part.from_bytes"]
        SAFETY["Safety Settings<br/>（4 類有害內容過濾）"]
    end

    style TextMode fill:#16213e,stroke:#b8860b,color:#e0e0e0
```

**特點：**

| 面向 | 說明 |
|------|------|
| 傳輸方式 | REST `generateContent` — 每次發送完整對話歷史 |
| 歷史管理 | 客戶端 `_history` 列表（`list[Content]`），完整保留所有對話 |
| 音訊 | 不支援 |
| 清除歷史 | 直接重設 `_history` 列表 |
| Google Search | 需使用分離式 API 呼叫（見下方詳解） |
| 相機分析 | 影像直接以 `Part.from_bytes` 附加在函式回應中 |
| 檔案注入 | 首則訊息時注入已啟用檔案的 `Part.from_uri` |
| Safety Settings | 支援（4 類 × 4 等級） |

### Live API 模式詳解

```mermaid
graph TD
    subgraph LiveMode["Live API 模式"]
        direction TB
        WS_CONN["原始 WebSocket<br/>BidiGenerateContent"]
        AUDIO_IO["音訊 I/O<br/>PCM 16kHz 輸入 / 24kHz 輸出"]
        CWC["上下文壓縮<br/>滑動視窗 25600 tokens"]
        NO_INT["NO_INTERRUPTION<br/>展覽模式（關閉 VAD）"]
        CANCEL["toolCallCancellation<br/>處理被取消的函式呼叫"]
        TWO_STAGE["兩階段相機分析<br/>Live → Text API → Live"]
        SETUP["setup 訊息<br/>模型 + 語音 + 工具 + 壓縮"]
    end

    style LiveMode fill:#16213e,stroke:#b8860b,color:#e0e0e0
```

**特點：**

| 面向 | 說明 |
|------|------|
| 傳輸方式 | WebSocket `BidiGenerateContent` — 持久雙向連線 |
| 歷史管理 | 伺服器端（Gemini）管理，搭配滑動視窗壓縮（25600 tokens 觸發） |
| 音訊 | 原生支援（16 kHz PCM 輸入 / 24 kHz PCM 輸出） |
| 清除歷史 | 需重新連線 WebSocket |
| Google Search | 原生支援（兩工具同時存在於 setup 訊息） |
| 相機分析 | 兩階段 — `toolResponse` 不支援多模態資料，需透過 Text API 分析後回傳文字 |
| Safety Settings | 目前不支援 |
| 展覽模式 | `activityHandling: NO_INTERRUPTION` 防止 VAD 打斷回應 |

### 雙模式差異對照

```mermaid
graph LR
    subgraph TextAPI["Text API 模式"]
        T_SDK["google-genai SDK"]
        T_HIST["客戶端歷史<br/>list[Content]"]
        T_LOOP["FC 迴圈<br/>call → execute → respond"]
        T_GS["Google Search<br/>分離式 API 呼叫"]
        T_CAM["相機分析<br/>Part.from_bytes"]
    end

    subgraph LiveAPI["Live API 模式"]
        L_WS["原始 WebSocket<br/>BidiGenerateContent"]
        L_AUDIO["音訊 I/O<br/>PCM 16k/24k"]
        L_CWC["上下文壓縮<br/>滑動視窗"]
        L_GS["Google Search<br/>原生支援"]
        L_CAM["相機分析<br/>兩階段（Text API 代理）"]
    end

    SHARED["共用：execute_function_call()<br/>透過 robot_manager"]

    TextAPI --> SHARED
    LiveAPI --> SHARED

    style TextAPI fill:#16213e,stroke:#b8860b,color:#e0e0e0
    style LiveAPI fill:#16213e,stroke:#b8860b,color:#e0e0e0
```

| 面向 | Text API | Live API |
|------|----------|----------|
| 傳輸 | REST (`generateContent`) | WebSocket (`BidiGenerateContent`) |
| 歷史 | 客戶端管理 (`_history`) | 伺服器端管理（Gemini） |
| 音訊 | 不支援 | 原生（PCM 16kHz 輸入 / 24kHz 輸出） |
| Google Search | 分離式 API 呼叫繞過 | 原生（兩工具共存於 setup） |
| 相機分析 | 影像直接附加至回應 | 兩階段（先 Text API 分析，再文字回傳） |
| 清除歷史 | 重設 `_history` 列表 | 重新連線 WebSocket |
| 上下文管理 | 每次發送完整歷史 | 滑動視窗壓縮（25600 tokens） |
| Safety Settings | 支援 | 不支援 |

---

## Google Search 多層次呼叫架構

### 問題背景

部分 Gemini 模型（如 `gemini-3-flash-preview`）**無法在同一個 API 請求中同時使用 Google Search 與 Function Calling**。發送兩者會收到：

```
400 INVALID_ARGUMENT: Tool use with function calling is unsupported by the model.
```

所有嘗試的組合方式均失敗：

| 嘗試方式 | 結果 |
|---------|------|
| `google_search` + `function_declarations`（分開的 Tool 物件） | 400 |
| `google_search_retrieval` + `function_declarations` | 400: "google_search_retrieval is not supported" |
| 兩工具 + `tool_config.function_calling_config.mode = "AUTO"` | 400 |
| 兩者放在同一個 `types.Tool()` | SDK 靜默丟棄 `google_search`，模型產生幻覺 |

### Text API 的分離式呼叫策略

核心思路：**將 Google Search 偽裝成一般函式宣告**，當模型嘗試呼叫時攔截並以獨立 API 呼叫執行搜尋。

```mermaid
flowchart TD
    START["使用者訊息"] --> GEN["generateContent<br/>tools = [functionDeclarations]<br/>（不含 GoogleSearch）"]
    GEN --> CHECK{"回應含有<br/>functionCall？"}

    CHECK -->|"name == google_search"| INTERCEPT["攔截！"]
    INTERCEPT --> EXTRACT["擷取搜尋查詢<br/>fn_args['queries']"]
    EXTRACT --> SEARCH_CALL["獨立 API 呼叫<br/>generateContent<br/>tools = [GoogleSearch]<br/>contents = 查詢文字"]
    SEARCH_CALL --> PARSE["解析搜尋結果<br/>+ grounding metadata"]
    PARSE --> SOURCES["提取來源連結<br/>{title, uri}"]
    SOURCES --> SEND_SOURCES["傳送至前端<br/>{type: 'google_search', sources}"]
    PARSE --> FUNC_RESP["組裝 functionResponse<br/>搜尋結果文字"]
    FUNC_RESP --> LOOP["回到 generateContent<br/>繼續對話迴圈"]
    LOOP --> GEN

    CHECK -->|"name == 其他函式"| EXEC["執行函式<br/>execute_function_call()"]
    EXEC --> RESULT["回傳 functionResponse"]
    RESULT --> LOOP

    CHECK -->|"無 functionCall"| RESPONSE["回傳文字回應"]

    style INTERCEPT fill:#8b0000,stroke:#b8860b,color:#e0e0e0
    style SEARCH_CALL fill:#006400,stroke:#b8860b,color:#e0e0e0
    style GEN fill:#1a2744,stroke:#b8860b,color:#e0e0e0
```

#### 第 1 層：函式宣告注入

在 `connect()` 階段，只將 `functionDeclarations` 作為工具發送（**不含 GoogleSearch**）。同時，將 `google_search` 注入為一般函式宣告：

```python
# gemini_text_service.py — connect()
if enable_google_search:
    func_decls.append({
        "name": "google_search",
        "description": "搜尋 Google 以取得即時資訊...",
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["queries"]
        }
    })
tool_list = [types.Tool(function_declarations=func_decls)]
# ↑ 注意：沒有加入 GoogleSearch 工具
```

#### 第 2 層：函式呼叫攔截

在 `_generate()` 迴圈中，檢查模型回傳的函式呼叫名稱：

```python
# gemini_text_service.py — _generate()
if fn_name == "google_search":
    result = await self._handle_google_search(fn_args)
else:
    result = await asyncio.to_thread(
        execute_function_call, fn_name, fn_args
    )
```

#### 第 3 層：獨立搜尋 API 呼叫

`_handle_google_search()` 使用**完全獨立的 `generateContent` 呼叫**，僅攜帶 `GoogleSearch` 工具：

```python
# gemini_text_service.py — _handle_google_search()
search_config = types.GenerateContentConfig(
    tools=[types.Tool(google_search=types.GoogleSearch())],
)
response = await asyncio.to_thread(
    self._client.models.generate_content,
    model=self._model,
    contents=search_query,
    config=search_config,
)
# 解析搜尋結果 + grounding metadata
```

#### 第 4 層：結果回傳與繼續對話

搜尋結果以 `functionResponse` 的形式加入對話歷史，然後繼續呼叫 `generateContent` 讓模型根據搜尋結果產生最終回應。

### Grounding 衝突處理

當 Text API 回應中**同時包含 Google Search grounding metadata 與函式呼叫**時，會發生衝突。系統的處理策略：

```mermaid
flowchart TD
    RESP["API 回應"] --> CHECK{"同時包含<br/>grounding + functionCall？"}

    CHECK -->|"是"| BLOCK["阻擋所有函式呼叫"]
    BLOCK --> NOTIFY["通知前端<br/>{type: 'function_call_blocked',<br/>name, args}"]
    BLOCK --> FORWARD_GS["轉發 grounding 來源<br/>{type: 'google_search', sources}"]
    BLOCK --> FORWARD_TEXT["轉發文字回應<br/>（如果有的話）"]

    CHECK -->|"否"| NORMAL["正常處理"]
    NORMAL --> HANDLE_FC["執行函式呼叫"]
    NORMAL --> HANDLE_GS["處理搜尋結果"]
    NORMAL --> HANDLE_TEXT["回傳文字"]

    style BLOCK fill:#8b0000,stroke:#b8860b,color:#e0e0e0
```

```python
if used_google_search and function_call_parts:
    # 同時有 grounding + FC → 阻擋函式呼叫，避免重複執行
    for part in function_call_parts:
        await self._send_to_client({
            "type": "function_call_blocked",
            "name": fc.name,
            "args": dict(fc.args) if fc.args else {},
        })
```

### Live API 的原生支援

Live API **原生支援同時使用 Google Search 與 Function Calling**，兩者作為 `tools` 陣列中的獨立項目：

```mermaid
graph LR
    SETUP["WebSocket setup 訊息"]
    TOOLS["tools 陣列"]
    FD["{functionDeclarations: [...]}"]
    GS["{googleSearch: {}}"]

    SETUP --> TOOLS
    TOOLS --> FD
    TOOLS --> GS

    style SETUP fill:#16213e,stroke:#b8860b,color:#e0e0e0
    style FD fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style GS fill:#006400,stroke:#b8860b,color:#e0e0e0
```

```python
# gemini_live_service.py — connect()
tools = [{"functionDeclarations": func_decls}]
if enable_google_search:
    tools.append({"googleSearch": {}})  # 獨立的工具項目
```

**不需要任何繞過機制**。Live API 的 `BidiGenerateContent` 協定原生支援兩種工具共存。

### Google Search 完整流程圖

以下是完整的 Google Search 呼叫流程，涵蓋 Text API 與 Live API 兩種模式：

```mermaid
flowchart TB
    USER["使用者：台南明天天氣如何？"] --> MODE{"目前模式？"}

    MODE -->|"Text API"| TEXT_FLOW
    MODE -->|"Live API"| LIVE_FLOW

    subgraph TEXT_FLOW["Text API — 分離式呼叫"]
        direction TB
        T1["generateContent<br/>tools = [functionDeclarations]<br/>含偽裝的 google_search 函式"]
        T2{"模型回應"}
        T3["模型呼叫 google_search<br/>args: {queries: ['台南明天天氣']}"]
        T4["攔截！不送往 robot_manager"]
        T5["獨立 API 呼叫<br/>generateContent<br/>tools = [GoogleSearch]"]
        T6["收到搜尋結果<br/>+ grounding sources"]
        T7["組裝 functionResponse<br/>搜尋結果文字"]
        T8["再次 generateContent<br/>模型根據搜尋結果回答"]
        T9["最終回應：<br/>台南明天晴天，28°C"]

        T1 --> T2
        T2 --> T3
        T3 --> T4
        T4 --> T5
        T5 --> T6
        T6 --> T7
        T7 --> T8
        T8 --> T9
    end

    subgraph LIVE_FLOW["Live API — 原生支援"]
        direction TB
        L1["WebSocket setup<br/>tools = [<br/>  {functionDeclarations},<br/>  {googleSearch: {}}<br/>]"]
        L2["使用者語音輸入<br/>PCM 16kHz"]
        L3["Gemini 內部搜尋<br/>（自動觸發）"]
        L4["搜尋結果 + 語音回應<br/>PCM 24kHz"]
        L5["使用者聽到回答"]

        L1 --> L2
        L2 --> L3
        L3 --> L4
        L4 --> L5
    end

    style TEXT_FLOW fill:#16213e,stroke:#b8860b,color:#e0e0e0
    style LIVE_FLOW fill:#16213e,stroke:#b8860b,color:#e0e0e0
    style T4 fill:#8b0000,stroke:#b8860b,color:#e0e0e0
    style T5 fill:#006400,stroke:#b8860b,color:#e0e0e0
```

---

## 函式呼叫架構

函式呼叫是 Gemini 自然語言理解與實體機器人控制之間的橋樑。兩種 API 模式共用同一個函式分派器。

```mermaid
graph TD
    subgraph Declaration["函式宣告（config.py）"]
        FD["14 個預設函式<br/>（繁體中文描述）<br/>每個可獨立啟用/停用"]
    end

    subgraph Dispatch["分派（robot_manager.py）"]
        EFC["execute_function_call(name, args)"]
        D["dispatch dict<br/>{name: handler}"]
        EFC --> D
    end

    subgraph Handlers["函式處理器"]
        NAV["導航<br/>move_to_location<br/>guide_to_booth"]
        SHELF["貨架搬運<br/>move_shelf / return_shelf<br/>deliver_drink / return_drink"]
        QUERY["查詢<br/>get_robot_status<br/>get_patrol_history"]
        CAMERA["相機<br/>capture_camera"]
        CONTROL["控制<br/>cancel_command<br/>patrol_all<br/>rotate<br/>notify_staff"]
    end

    subgraph Execution["執行層"]
        CTRL["RobotController<br/>（阻塞，等待完成）"]
        QUERIES["KachakaQueries<br/>（即時查詢）"]
        CAM["CameraStreamer<br/>（背景擷取畫面）"]
        VLM["Gemini VLM<br/>（影像分析）"]
        TG_SEND["Telegram Bot API<br/>（工作人員通知）"]
    end

    Declaration --> EFC
    D --> NAV & SHELF & QUERY & CAMERA & CONTROL
    NAV --> CTRL
    SHELF --> CTRL
    QUERY --> QUERIES
    CAMERA --> CAM & VLM
    CONTROL --> CTRL & TG_SEND

    style Declaration fill:#1a1a2e,stroke:#b8860b,color:#e0e0e0
    style Dispatch fill:#16213e,stroke:#b8860b,color:#e0e0e0
    style Handlers fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style Execution fill:#0f3460,stroke:#b8860b,color:#e0e0e0
```

### 相機分析的模式差異

相機拍照分析在兩種模式下的處理方式不同：

```mermaid
sequenceDiagram
    participant AI as Gemini
    participant SRV as 後端
    participant CAM as CameraStreamer
    participant TEXT_API as Text API (generateContent)

    Note over AI,TEXT_API: === Text API 模式 ===
    AI->>SRV: functionCall: capture_camera
    SRV->>CAM: 取得 JPEG 畫面
    CAM-->>SRV: JPEG bytes
    SRV->>AI: functionResponse<br/>+ Part.from_bytes(JPEG)<br/>AI 直接看到影像

    Note over AI,TEXT_API: === Live API 模式 ===
    AI->>SRV: toolCall: capture_camera
    SRV->>CAM: 取得 JPEG 畫面
    CAM-->>SRV: JPEG bytes
    Note over SRV: toolResponse 不支援影像！
    SRV->>TEXT_API: generateContent(JPEG + prompt)
    TEXT_API-->>SRV: "照片中可以看到走廊..."
    SRV->>AI: toolResponse({analysis: "照片中可以看到走廊..."})
    Note over AI: 模型以語音朗讀分析結果
```

---

## 對話資料流

### Text API 對話流程

```mermaid
sequenceDiagram
    participant B as 瀏覽器
    participant WS as /ws/chat
    participant TXT as GeminiTextSession
    participant GEMINI as Gemini Text API
    participant RM as RobotManager
    participant ROBOT as Kachaka 機器人

    B->>WS: {type: "connect"}
    WS->>TXT: new GeminiTextSession()
    TXT->>TXT: 組裝 system instruction
    TXT-->>B: {type: "status", message: "Connected"}

    B->>WS: {type: "text", content: "帶我去餐廳"}
    WS->>TXT: send_text("帶我去餐廳")
    TXT-->>B: {type: "thinking"}
    TXT->>GEMINI: generateContent(history + user msg)
    GEMINI-->>TXT: functionCall: guide_to_booth({location_name: "餐廳"})

    TXT-->>B: {type: "function_call", name: "guide_to_booth"}
    TXT->>RM: execute_function_call("guide_to_booth", {location_name: "餐廳"})
    RM->>ROBOT: gRPC move_to_location("L01")
    ROBOT-->>RM: 到達
    RM-->>TXT: {ok: true}
    TXT-->>B: {type: "function_result", ...}

    TXT->>GEMINI: generateContent(history + function response)
    GEMINI-->>TXT: "好的，已帶您到餐廳了"
    TXT-->>B: {type: "text", content: "好的，已帶您到餐廳了"}
    TXT-->>B: {type: "turn_complete"}
```

### Live API 對話流程

```mermaid
sequenceDiagram
    participant B as 瀏覽器
    participant WS as /ws/chat
    participant LIVE as GeminiLiveSession
    participant GEMINI as Gemini Live API
    participant RM as RobotManager

    B->>WS: {type: "connect"}
    WS->>LIVE: new GeminiLiveSession()
    LIVE->>GEMINI: WebSocket setup（模型、工具、語音、壓縮）
    GEMINI-->>LIVE: setupComplete
    LIVE-->>B: {type: "status", message: "Connected"}

    Note over B: 使用者對著麥克風說話
    B->>WS: {type: "audio", data: "<PCM base64>"}
    WS->>LIVE: send_audio(data)
    LIVE->>GEMINI: realtimeInput.audio

    GEMINI-->>LIVE: serverContent.modelTurn（音訊片段）
    LIVE-->>B: {type: "audio", data: "<PCM base64>"}
    Note over B: 以 24kHz 播放音訊

    GEMINI-->>LIVE: toolCall: capture_camera
    LIVE-->>B: {type: "function_call", name: "capture_camera"}
    LIVE->>RM: execute_function_call("capture_camera", ...)
    RM-->>LIVE: JPEG bytes

    Note over LIVE: 兩階段相機分析
    LIVE->>GEMINI: generateContent(影像 + 查詢) via Text API
    GEMINI-->>LIVE: "照片中可以看到一個走廊..."

    LIVE->>GEMINI: toolResponse({image_analysis: "照片中..."})
    GEMINI-->>LIVE: serverContent.modelTurn（朗讀分析結果）
    LIVE-->>B: {type: "audio", data: "..."}
    GEMINI-->>LIVE: turnComplete
    LIVE-->>B: {type: "turn_complete"}
```

### 巡檢流程

```mermaid
sequenceDiagram
    participant API as POST /api/patrol/start
    participant PS as PatrolService
    participant RM as RobotManager
    participant FH as FrameHub
    participant GEMINI as Gemini Text API
    participant DB as patrol_db
    participant TG as Telegram

    API->>PS: start_patrol(points)
    PS->>DB: create_run()
    PS->>PS: 產生背景執行緒

    loop 每個巡檢點位
        PS->>RM: move_to_location(point_id)
        RM-->>PS: {ok: true}
        PS->>PS: 等待 inspect_dwell_time 秒
        PS->>FH: wait_for_fresh_frame(timeout=10)
        FH-->>PS: JPEG bytes
        PS->>PS: 儲存影像至磁碟
        PS->>GEMINI: generateContent(影像 + 分析提示, schema=InspectionResult)
        GEMINI-->>PS: {is_NG: false, Description: "環境正常"}
        PS->>DB: insert_inspection(run_id, OK, description, image, tokens)
    end

    PS->>GEMINI: generateContent(摘要提示 + 所有結果)
    GEMINI-->>PS: 摘要報告文字
    PS->>DB: update_run(Completed, summary, tokens)
    PS->>TG: send_patrol_notification(摘要, PDF)
```

### Telegram 橋接流程

```mermaid
sequenceDiagram
    participant User as Telegram 使用者
    participant TG as Telegram API
    participant BOT as TelegramBotManager
    participant TXT as GeminiTextSession
    participant GEMINI as Gemini Text API
    participant RM as RobotManager

    User->>TG: "機器人電量多少？"
    TG->>BOT: on_message(update)
    BOT->>TXT: get_session(chat_id)
    Note over BOT,TXT: 首次訊息時建立新會話
    BOT->>TXT: send_text_and_collect("機器人電量多少？")
    TXT->>GEMINI: generateContent(...)
    GEMINI-->>TXT: functionCall: get_robot_status
    TXT->>RM: execute_function_call("get_robot_status", {})
    RM-->>TXT: {ok: true, battery: 85, ...}
    TXT->>GEMINI: generateContent(... + function response)
    GEMINI-->>TXT: "目前電量為 85%"
    TXT-->>BOT: 收集的回應訊息
    BOT->>TG: reply_text("目前電量為 85%")
    TG-->>User: "目前電量為 85%"
```

---

## 系統指令組裝

兩種 API 模式使用相同的方式組裝系統提示詞，由 4 個可設定的區段串接而成：

```mermaid
graph LR
    P["[Persona]<br/>角色、語氣、回應風格"] --> JOIN
    FK["[Function Usage Rules]<br/>函式呼叫決策規則"] --> JOIN
    KB["[Knowledge Base]<br/>場地資訊（JSON/文字）"] --> JOIN
    RBI["[Robot Background Info]<br/>可用地點列表 + A* 距離"] --> JOIN
    JOIN["以 \\n\\n 串接"] --> REPLACE["替換 {{CURRENT_TIME}}<br/>為 UTC+8 時間戳記"]
    REPLACE --> LOC["替換 {{AVAILABLE_LOCATIONS}}<br/>為機器人地點列表"]
    LOC --> PROMPT["最終系統指令"]

    style P fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style FK fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style KB fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style RBI fill:#1a2744,stroke:#b8860b,color:#e0e0e0
```

所有 4 個區段皆可透過 Settings > Prompt 頁籤的文字編輯器修改。

---

## 設定系統

```mermaid
graph TD
    ENV["環境變數<br/>ROBOT_IP"] --> CONFIG["config.py<br/>DEFAULT_SETTINGS"]
    CONFIG --> MERGE["settings_service.get_all()<br/>合併 DEFAULT + 已儲存"]
    SAVED["data/settings.json"] --> MIGRATE["_migrate()<br/>自動轉換舊版金鑰"]
    MIGRATE --> MERGE
    MERGE --> SETTINGS["最終設定 dict"]

    WEB_UI["Web UI<br/>POST /api/settings"] --> SAVE["settings_service.save()"]
    SAVE --> SAVED

    PROFILES["data/profiles/*.json"] --> LOAD["profile_service.load_profile()"]
    LOAD --> SAVE

    style CONFIG fill:#1a2744,stroke:#b8860b,color:#e0e0e0
    style MERGE fill:#16213e,stroke:#b8860b,color:#e0e0e0
```

### 設定遷移

`settings_service._migrate()` 自動處理向下相容：

| 舊金鑰 | 新金鑰 | 說明 |
|--------|--------|------|
| `gemini_model` | `text_model` / `live_model` | 分離為雙模式各自的模型設定 |
| `enable_google_search` | `text_enable_google_search` + `live_enable_google_search` | 分離為雙模式各自的搜尋開關 |
| `drink_shelf_home` | `kiosk_location` | 更名 |
| `telegram_chat_id`（字串） | `telegram_chat_ids`（陣列） | 支援多個 Chat ID |
| `patrol_points`（物件陣列） | `patrol_points`（字串陣列） | 簡化為地點 ID 字串 |

---

## 部署架構

```mermaid
graph TB
    subgraph Docker["Docker 容器（python:3.12-slim）"]
        UV["uvicorn main:app<br/>:9000"]
        BACKEND["後端 (/app/)"]
        FRONTEND["前端 (/app/frontend/)"]
        DATA["/app/data/<br/>（volume mount）"]
    end

    HOST["主機<br/>Port 9000"]
    BROWSER["瀏覽器"]
    KACHAKA["Kachaka 機器人<br/>gRPC :26400"]
    GOOGLE["Google Gemini API<br/>（HTTPS + WSS）"]
    TELEGRAM["Telegram API<br/>（HTTPS）"]

    HOST -- "port mapping" --> Docker
    BROWSER -- "HTTP/WS :9000" --> HOST
    Docker -- "gRPC" --> KACHAKA
    Docker -- "HTTPS/WSS" --> GOOGLE
    Docker -- "HTTPS（polling）" --> TELEGRAM

    style Docker fill:#16213e,stroke:#b8860b,color:#e0e0e0
```

### 開發模式

```yaml
# docker-compose.yml
volumes:
  - ./src/backend:/app          # 即時程式碼重載
  - ./src/frontend:/app/frontend
  - ./data:/app/data            # 持久化資料
command: uvicorn main:app --host 0.0.0.0 --port 9000 --reload
```

### 生產模式

```yaml
# docker-compose.prod.yml
image: ghcr.io/sigmarobotics/kachaka-gemini:latest
volumes:
  - ./data:/app/data            # 僅掛載資料
# 不掛載原始碼，不使用 --reload
```

### 多架構建置

`build-multiarch.sh` 使用 `docker buildx` 建置 `linux/amd64` 與 `linux/arm64`，支援 x86-64 伺服器與 ARM 設備（Raspberry Pi、Jetson 等）。
