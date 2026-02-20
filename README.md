# Kachaka + Gemini Live

A web interface that connects a [Kachaka](https://kachaka.life/) robot to Google's Gemini API, enabling voice and text conversations with function-calling capabilities for robot control.

## Features

- **Dual API modes** — Text API (stateless, multi-turn REST) and Live API (real-time bidirectional WebSocket with audio)
- **Voice interaction** — PCM audio capture (16 kHz) via AudioWorklet, gapless playback at 24 kHz, configurable TTS voice
- **Robot control via function calling** — Gemini autonomously calls functions to move the robot, transport shelves, query status, and capture camera images
- **Google Search grounding** — Optional web search integration for up-to-date answers; handles model-level incompatibilities (e.g. `gemini-3-flash-preview` Google Search + function calling conflict) via dedicated API fallback
- **Interactive map** — Canvas-rendered floor map with click-to-move and drag-to-set-pose, real-time pose tracking
- **Front camera** — MJPEG streaming endpoint; optional continuous camera-to-AI feed (Live API)
- **Settings UI** — Three-tab settings panel (General / Text API / Live API) with graphical function declaration editor, system instruction accordion, generation parameter sliders, and safety settings
- **Chat management** — Clear conversation history and export chat as JSON
- **Interim response** — Pre-generated TTS audio clips played during function call execution for seamless UX
- **Token tracking** — SQLite-backed per-session and daily token usage statistics

## Architecture

```
Browser (ES modules)
  +-- app.js           Entry point, tab switching
  +-- chat.js          WebSocket client, audio capture/playback, interim response
  +-- map.js           Canvas map rendering, coordinate transforms, click-to-move
  +-- settings.js      Settings UI bindings, function editor, import/export
  +-- state.js         Shared reactive state (robot pose, map info)
  +-- pcm-processor.js AudioWorklet processor (16 kHz PCM capture)

         | WebSocket /ws/chat
         v

FastAPI backend (uvicorn)
  +-- main.py                 Routes, WebSocket handler, MJPEG camera stream
  +-- gemini_live_service.py  Gemini Live API (BidiGenerateContent) WebSocket session
  +-- gemini_text_service.py  Gemini Text API (generateContent) multi-turn session
  +-- robot_service.py        Kachaka gRPC client with background state polling
  +-- settings_service.py     JSON file-based settings persistence (data/settings.json)
  +-- token_service.py        SQLite token usage tracking (data/tokens.db)
  +-- config.py               Default settings, function declarations, persona, knowledge base

         | gRPC :26400
         v

Kachaka Robot
```

### Data Flow

1. User opens the web UI and enters a Gemini API key in **Settings > General**
2. Clicking **Connect** in the Chat tab opens a WebSocket to `/ws/chat`
3. The backend creates either a `GeminiTextSession` or `GeminiLiveSession` based on the configured API mode
4. User messages (text or audio) are forwarded to the Gemini API
5. Gemini responses (text, audio, function calls) are relayed back to the browser
6. Function calls (e.g. `move_to_location`) are executed on the Kachaka robot via gRPC and results returned to Gemini for follow-up

## Quick Start

### Prerequisites

- Docker & Docker Compose
- A Gemini API key ([Google AI Studio](https://aistudio.google.com/apikey))
- A Kachaka robot on the same network (optional -- the app runs without one)

### Run

```bash
# Set your robot's IP (default: 192.168.50.133)
export ROBOT_IP=192.168.50.133:26400

docker compose up -d
```

Open **http://localhost:9000** in a browser.

Enter your Gemini API key in **Settings > General**, then click **Connect** in the Chat tab.

### Development

Source code is volume-mounted into the container with `--reload` enabled, so edits to `src/` are picked up automatically.

```bash
# Rebuild after changing requirements.txt or Dockerfile
docker compose up -d --build
```

### Multi-arch Build

```bash
./build-multiarch.sh            # builds for amd64 + arm64
./build-multiarch.sh myimage v2 # custom image name and tag
```

## Project Structure

```
kachaka-gemini/
+-- docker-compose.yml
+-- Dockerfile
+-- build-multiarch.sh
+-- data/                      # Runtime data (gitignored)
|   +-- settings.json          # Persisted settings
|   +-- tokens.db              # Token usage database
+-- docs/
|   +-- google-search-function-calling.md
|   +-- plans/                 # Design docs and implementation plans
+-- src/
    +-- backend/
    |   +-- main.py            # FastAPI routes + WebSocket handler
    |   +-- config.py          # Defaults, function declarations, persona
    |   +-- gemini_live_service.py   # Live API (BidiGenerateContent) session
    |   +-- gemini_text_service.py   # Text API (generateContent) session
    |   +-- robot_service.py   # Kachaka gRPC client + background polling
    |   +-- settings_service.py      # JSON settings persistence
    |   +-- token_service.py   # SQLite token tracking
    |   +-- requirements.txt
    +-- frontend/
        +-- templates/
        |   +-- index.html     # Single-page app template
        +-- static/
            +-- css/style.css
            +-- js/
            |   +-- app.js           # Entry point, tab switching
            |   +-- chat.js          # WebSocket chat + audio
            |   +-- map.js           # Canvas map rendering
            |   +-- settings.js      # Settings UI logic
            |   +-- state.js         # Shared state
            |   +-- pcm-processor.js # AudioWorklet processor
            +-- favicon.png
```

## API Endpoints

### REST

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/api/state` | Robot state (battery, pose, map info) |
| `GET` | `/api/map` | Floor map PNG |
| `GET` | `/api/camera/front` | MJPEG camera stream |
| `GET` | `/api/locations` | Registered locations |
| `GET` | `/api/shelves` | Registered shelves |
| `GET` | `/api/settings` | Current settings (API key masked) |
| `GET` | `/api/settings/defaults` | Default settings |
| `POST` | `/api/settings` | Update settings |
| `GET` | `/api/models?mode=live\|text` | Query available Gemini models |
| `GET` | `/api/token_usage` | Token usage summary |
| `POST` | `/api/token_usage/reset` | Reset token counters |
| `POST` | `/api/move` | Move robot to coordinates `{x, y, theta}` |
| `POST` | `/api/cancel_command` | Cancel current robot command |
| `POST` | `/api/return_home` | Return robot to charging dock |
| `POST` | `/api/manual_control` | Manual drive `{direction: forward\|backward\|left\|right}` |
| `POST` | `/api/generate_interim_audio` | Pre-generate TTS clips for interim responses |
| `GET` | `/api/interim_audio` | Retrieve generated interim audio data |

### WebSocket `/ws/chat`

| Client -> Server | Description |
|------------------|-------------|
| `{type: "connect"}` | Open Gemini session (mode determined by `api_mode` setting) |
| `{type: "disconnect"}` | Close Gemini session |
| `{type: "text", content: "..."}` | Send text message |
| `{type: "audio", data: "<base64>"}` | Send PCM audio chunk (Live API only) |
| `{type: "clear_history"}` | Clear conversation history (Text API resets history array; Live API reconnects fresh session) |

| Server -> Client | Description |
|------------------|-------------|
| `{type: "status", message: "...", api_mode?: "text"\|"live"}` | Connection status (includes `api_mode` on connect) |
| `{type: "text", content: "..."}` | Model text response (streamed incrementally) |
| `{type: "audio", data: "<base64>"}` | Model audio response (PCM 24 kHz, Live API only) |
| `{type: "turn_complete"}` | Model turn finished |
| `{type: "function_call", name, args}` | Function call initiated |
| `{type: "function_result", name, result}` | Function call result |
| `{type: "function_call_blocked", name, args}` | Function call skipped due to Google Search conflict |
| `{type: "google_search", sources: [...]}` | Search grounding sources `[{title, uri}]` |
| `{type: "token_usage", prompt, response, total}` | Token counts for this turn |
| `{type: "error", message: "..."}` | Error |
| `{type: "gemini_disconnected", code, reason}` | Server-side Gemini disconnect (triggers auto-reconnect) |
| `{type: "history_cleared"}` | Confirmation that history was cleared |

## Dual API Mode

### Text API (`api_mode: "text"`)

- Uses `google-genai` SDK's `generate_content` method
- Maintains conversation history client-side (`_history` list of `types.Content`)
- Supports multi-turn conversations with function calling
- Sends camera images as inline `image/jpeg` parts alongside function responses
- Handles Google Search via a **separate API call** when the model emits a `google_search` function call (workaround for models like `gemini-3-flash-preview` that don't support Google Search + function calling in the same request)
- Supports safety settings (harassment, hate speech, sexually explicit, dangerous content)
- Clear history resets the in-memory conversation array

### Live API (`api_mode: "live"`)

- Uses raw WebSocket connection to Gemini's `BidiGenerateContent` endpoint
- Always returns audio responses (configurable voice)
- Supports real-time audio input via AudioWorklet (16 kHz PCM)
- Gapless audio playback scheduling at 24 kHz
- Optional camera-to-AI streaming (sends JPEG frames every 2 seconds)
- Supports Google Search as a separate tool alongside function declarations
- Clear history closes and reopens the Gemini WebSocket session (server-side state is not directly resettable)

## Function Declarations

The default function declarations (editable in Settings via graphical card editor) expose these robot capabilities to Gemini:

| Function | Description | Parameters |
|----------|-------------|------------|
| `move_to_location` | Navigate to a registered location | `location_id` (enum: L01-L05, S01_home, home) |
| `move_shelf` | Transport a shelf to a destination | `shelf_id` (enum: S01), `destination_id` (enum) |
| `return_shelf` | Return a shelf to its home position | `shelf_id` (enum: S01) |
| `get_robot_status` | Query battery level, pose, and command state | (none) |
| `cancel_command` | Stop the current robot task | (none) |
| `capture_camera` | Capture and analyze a front camera image | (none) |

### Graphical Function Editor

The Settings > General tab provides a card-based editor for function declarations:

- **Add/delete functions** with named cards
- **Parameter table** per function with columns: Name, Type, Description, Enum, Required
- **Import/export** as JSON files
- **Reset to default** restores built-in declarations
- Uses monotonic counter for card indices to prevent collisions after delete-then-add operations

## System Instruction

The system instruction is composed of four configurable sections, concatenated at connect time:

| Section | Setting Key | Description |
|---------|------------|-------------|
| **Persona** | `persona` | AI assistant's role, tone, and behavioral rules |
| **Function Usage Rules** | `static_knowledge` | Function calling decision logic and constraints |
| **Knowledge Base** | `knowledge_base` | Background knowledge (JSON or text), uploadable from `.json`/`.txt`/`.md` files |
| **Robot Background Info** | `robot_background_info` | Location/shelf data (can be auto-fetched from robot) |

A `{{CURRENT_TIME}}` placeholder in the persona is replaced with the current UTC+8 timestamp at connection time.

If interim response is enabled (Live API), an additional note is appended instructing the model to call functions silently.

## Configuration

All settings are persisted to `data/settings.json` and editable through the web UI.

### General Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `gemini_api_key` | `""` | Google Gemini API key |
| `api_mode` | `"text"` | `"text"` or `"live"` |
| `voice_name` | `"Aoede"` | TTS voice for Live API (Puck, Charon, Kore, Fenrir, Aoede) |
| `persona` | *(built-in)* | AI persona and behavioral rules |
| `static_knowledge` | *(built-in)* | Function calling constraints |
| `knowledge_base` | *(built-in JSON)* | Background knowledge document |
| `robot_background_info` | *(built-in)* | Location/shelf listing for the robot |
| `function_declarations` | *(6 built-in)* | Editable function declarations array |
| `shelf_ids` | `[]` | Comma-separated shelf IDs |

### Text API Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `text_model` | `"gemini-3-flash-preview"` | Model for Text API |
| `text_enable_google_search` | `true` | Enable Google Search in Text mode |
| `text_temperature` | `1.0` | Sampling temperature (0.0 - 2.0) |
| `text_max_output_tokens` | `8192` | Maximum output tokens (1 - 65536) |
| `text_top_p` | `0.95` | Nucleus sampling threshold (0.0 - 1.0) |
| `text_top_k` | `40` | Top-K sampling (1 - 100) |
| `text_safety_settings` | `{}` | Per-category safety thresholds |

### Live API Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `live_model` | `"gemini-2.5-flash-native-audio-preview-12-2025"` | Model for Live API |
| `live_enable_google_search` | `false` | Enable Google Search in Live mode |
| `live_temperature` | `1.0` | Sampling temperature (0.0 - 2.0) |
| `live_max_output_tokens` | `8192` | Maximum output tokens (1 - 65536) |
| `live_top_p` | `0.95` | Nucleus sampling threshold (0.0 - 1.0) |
| `live_top_k` | `40` | Top-K sampling (1 - 100) |
| `enable_camera_to_ai` | `false` | Stream camera frames to Gemini every 2s |
| `enable_interim_response` | `false` | Play pre-generated audio during function execution |
| `interim_phrases` | *(built-in map)* | Function name -> spoken text for interim audio |
| `interim_audio` | `{}` | Pre-generated PCM audio data (base64, generated via Live API) |

### Safety Settings (Text API)

Four harm categories with configurable thresholds:

| Category | Values |
|----------|--------|
| `HARM_CATEGORY_HARASSMENT` | `BLOCK_NONE`, `BLOCK_LOW_AND_ABOVE`, `BLOCK_MEDIUM_AND_ABOVE`, `BLOCK_ONLY_HIGH` |
| `HARM_CATEGORY_HATE_SPEECH` | *(same)* |
| `HARM_CATEGORY_SEXUALLY_EXPLICIT` | *(same)* |
| `HARM_CATEGORY_DANGEROUS_CONTENT` | *(same)* |

## Audio Pipeline

### Capture (Browser -> Backend -> Gemini)

1. `navigator.mediaDevices.getUserMedia` captures mono audio at 16 kHz
2. **AudioWorklet** (`pcm-processor.js`) extracts raw Float32 samples in 128-sample render quanta
3. Samples are buffered to ~4096 samples (~256 ms) before encoding
4. Float32 -> PCM16 conversion, then base64 encoding
5. Sent as `{type: "audio", data: "<base64>"}` over WebSocket
6. Backend forwards to Gemini Live API as `realtimeInput.mediaChunks`

Falls back to deprecated `ScriptProcessorNode` for browsers without AudioWorklet support.

### Playback (Gemini -> Backend -> Browser)

1. Gemini returns audio as base64 PCM16 at 24 kHz
2. Backend forwards as `{type: "audio", data: "<base64>"}` to the browser
3. Browser decodes base64 -> Int16Array -> Float32Array
4. Creates `AudioBuffer` and schedules on a single `AudioContext` timeline
5. Gapless playback: each chunk is scheduled at `max(now, nextPlayTime)`, preventing gaps between chunks
6. Playback timeline resets on `turn_complete`

### Interim Response

When enabled, pre-generated audio clips play immediately during function call execution:

1. Configure phrases in **Settings > Live API > Interim Response**
2. Click **Generate Audio with Live API** to create TTS clips using the same Gemini voice
3. On function call, the matching clip plays instantly (or falls back to Web Speech API)
4. `nextPlayTime` is updated so subsequent Gemini audio starts after the interim clip

## Interactive Map

- Canvas-based rendering with real-time robot pose updates (100ms polling)
- **Click** to move the robot to a point (preserving current heading)
- **Drag** to set both position and orientation (heading = drag direction)
- Ghost robot preview shows the target pose during drag
- Coordinate transform: world coordinates (meters) <-> pixel coordinates using map resolution and origin

## Settings Migration

The settings service automatically migrates old single-mode keys to per-mode keys:

- `gemini_model` -> `text_model` / `live_model` (based on active `api_mode`)
- `enable_google_search` -> `text_enable_google_search` / `live_enable_google_search`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROBOT_IP` | `192.168.50.133:26400` | Kachaka robot IP and gRPC port |

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| [FastAPI](https://fastapi.tiangolo.com/) | >= 0.115 | Web framework |
| [Uvicorn](https://www.uvicorn.org/) | >= 0.34 | ASGI server |
| [websockets](https://websockets.readthedocs.io/) | >= 14.0 | Gemini Live API WebSocket client |
| [kachaka-api](https://github.com/pf-robotics/kachaka-api) | >= 3.14 | Kachaka robot gRPC client |
| [google-genai](https://github.com/googleapis/python-genai) | >= 1.0 | Gemini Text API SDK |
| [Pillow](https://python-pillow.org/) | >= 10.0 | Image processing |
| [Jinja2](https://jinja.palletsprojects.com/) | >= 3.1 | HTML templating |

## Known Limitations

- **Google Search + Function Calling conflict**: `gemini-3-flash-preview` returns `400 INVALID_ARGUMENT` when both are sent in the same request. The Text API works around this by intercepting `google_search` function calls and executing them via a dedicated API call with only the `GoogleSearch` tool.
- **Live API safety settings**: `BidiGenerateContent` does not currently support safety settings; the `live_safety_settings` field is reserved for future use.
- **Live API history**: Server-side conversation state cannot be selectively cleared; clearing history requires reconnecting the entire WebSocket session.
- **Camera dependency**: Camera features require a connected Kachaka robot; without one, camera endpoints return empty responses.

## License

Private project -- not open source.
