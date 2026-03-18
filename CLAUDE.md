# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kachaka + Gemini: A web interface connecting a [Kachaka](https://kachaka.life/) robot to Google's Gemini API. Supports voice (Live API) and text (Text API) conversations with function-calling for robot control. Includes a Telegram bot bridge.

**Language**: Backend is Python (FastAPI), frontend is vanilla JS (ES modules, no build step). All UI text and system prompts are in Traditional Chinese (繁體中文).

## Running the App

```bash
# Development (hot-reload via volume mount + --reload)
export ROBOT_IP=<YOUR_ROBOT_IP>:26400
docker compose up -d

# Rebuild after requirements.txt or Dockerfile changes
docker compose up -d --build

# Multi-arch build (amd64 + arm64)
./build-multiarch.sh
```

The app runs at **http://localhost:9000**. Source in `src/` is volume-mounted so edits are picked up automatically.

There are **no tests, no linter, and no type checker** configured in this project.

## Architecture

### Dual API Mode

The app has two Gemini API modes, selected via settings:

- **Text API** (`GeminiTextSession`): Uses `google-genai` SDK's `generate_content`. Maintains conversation history in-memory (`_history` list). Google Search is handled via a **separate API call** workaround (some models can't combine Google Search + function calling in one request).
- **Live API** (`GeminiLiveSession`): Raw WebSocket to `BidiGenerateContent`. Returns audio responses. Supports real-time audio input/output and camera-to-AI streaming.

Both modes share `execute_function_call()` (defined in `gemini_live_service.py`) for robot function dispatch.

### Key Data Flow

```
Browser <--WebSocket /ws/chat--> main.py <--WebSocket/REST--> Gemini API
                                    |
                                    +--gRPC :26400--> Kachaka Robot

Telegram <--polling--> telegram_service.py --> GeminiTextSession (reuses Text API)
```

### Backend Modules (`src/backend/`)

| Module | Role |
|--------|------|
| `main.py` | FastAPI app, REST routes, WebSocket `/ws/chat` handler, MJPEG camera stream |
| `gemini_live_service.py` | Live API session + `execute_function_call()` dispatcher |
| `gemini_text_service.py` | Text API session with function calling loop and Google Search workaround |
| `robot_manager.py` | Singleton facade over `kachaka_core` (from `kachaka-sdk-toolkit`) — connection, commands, queries, camera streaming |
| `telegram_service.py` | Telegram bot manager — per-chat `GeminiTextSession` instances |
| `settings_service.py` | JSON file-based settings persistence (`data/settings.json`) with migration |
| `token_service.py` | SQLite token usage tracking (`data/tokens.db`) |
| `config.py` | Default settings, function declarations, persona, knowledge base, `ROBOT_IP` env var |

### Frontend (`src/frontend/`)

Vanilla JS single-page app, no build tools. ES modules loaded directly by the browser.

| File | Role |
|------|------|
| `app.js` | Entry point, tab switching |
| `chat.js` | WebSocket client, audio capture (AudioWorklet 16kHz) / playback (24kHz), interim response |
| `map.js` | Canvas map rendering, coordinate transforms, click-to-move, drag-to-set-pose |
| `settings.js` | Settings UI, graphical function declaration editor, import/export |
| `state.js` | Shared reactive state (robot pose, map info) |
| `pcm-processor.js` | AudioWorklet processor for PCM capture |

### Persistence

- **Settings**: `data/settings.json` — merged with `DEFAULT_SETTINGS` from `config.py` on load
- **Token usage**: `data/tokens.db` — SQLite with WAL mode
- Both are gitignored and volume-mounted in Docker

## Important Patterns

### Function Calling

Gemini function calls are dispatched through `execute_function_call()` in `gemini_live_service.py`. This is shared by both API modes. To add a new function:
1. Add declaration to `DEFAULT_FUNCTION_DECLARATIONS` in `config.py`
2. Add handler case in `execute_function_call()`
3. Add interim phrase to `DEFAULT_INTERIM_PHRASES` in `config.py` (for Live API)

### Robot Manager Singleton

`robot_manager` is a module-level singleton (`RobotManager`) that wraps `kachaka_core` components from `kachaka-sdk-toolkit`. It uses `KachakaConnection` for pooled connections, `RobotController` for command execution, `KachakaQueries` for state queries, and `CameraStreamer` for camera feeds. Thread-safe via internal lock.

### System Instruction Assembly

Both API modes build the system prompt from 4 concatenated sections: Persona, Function Usage Rules, Knowledge Base, Robot Background Info. A `{{CURRENT_TIME}}` placeholder is replaced with UTC+8 timestamp at connect time.

### Google Search + Function Calling Conflict

Models like `gemini-3-flash-preview` return 400 when both Google Search and function declarations are in the same request. The Text API works around this by only sending function declarations, then intercepting `google_search` function calls and executing them via a separate API call with `GoogleSearch` tool only.

### Settings Migration

`settings_service._migrate()` auto-converts old single-mode keys (`gemini_model`, `enable_google_search`) to per-mode keys (`text_model`/`live_model`, `text_enable_google_search`/`live_enable_google_search`).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROBOT_IP` | `<YOUR_ROBOT_IP>:26400` | Kachaka robot gRPC address |

## Docker Layout

In the container, backend is at `/app/` and frontend at `/app/frontend/`. The code detects this layout vs local dev (`src/backend/` + `src/frontend/`) automatically in `main.py` and `config.py`.
