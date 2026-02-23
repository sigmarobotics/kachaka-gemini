import asyncio
import base64
import json
import math
import os
import urllib.request
import urllib.error

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import websockets

from robot_manager import robot_manager
import settings_service
import token_service
from config import DEFAULT_SETTINGS
from gemini_live_service import GeminiLiveSession, GEMINI_WS_URL
from gemini_text_service import GeminiTextSession
from telegram_service import telegram_manager

# Paths - support both local dev and Docker
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Check if running in Docker (frontend is at /app/frontend)
if os.path.exists(os.path.join(BASE_DIR, "frontend")):
    FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
else:
    FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, "templates")

app = FastAPI(title="Kachaka + Gemini Live")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)


@app.on_event("startup")
async def startup_event():
    # Auto-connect to robot from saved settings (in thread to avoid blocking event loop)
    await asyncio.to_thread(robot_manager.auto_connect)
    # Start Telegram bot
    token = settings_service.get("telegram_bot_token", "")
    if token:
        try:
            await telegram_manager.start(token)
        except Exception as e:
            print(f"[Telegram] Failed to start bot: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    await telegram_manager.stop()
    await asyncio.to_thread(robot_manager.disconnect)


# ─── Pages ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ─── Robot REST endpoints ─────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state():
    return robot_manager.get_state()


@app.get("/api/map")
async def get_map():
    data = robot_manager.get_map_bytes()
    if data:
        return Response(content=data, media_type="image/png")
    return Response(status_code=404)


@app.get("/api/camera/front")
async def camera_front():
    """MJPEG streaming endpoint for the front camera."""
    async def generate():
        try:
            while True:
                jpeg_bytes = robot_manager.get_camera_jpeg_bytes()
                if jpeg_bytes:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + jpeg_bytes
                        + b"\r\n"
                    )
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/locations")
async def get_locations():
    return robot_manager.get_locations()


@app.get("/api/shelves")
async def get_shelves():
    return robot_manager.get_shelves()


@app.get("/api/settings")
async def get_settings(request: Request):
    settings = settings_service.get_all()
    safe = settings.copy()
    # Mask API key for display
    if safe.get("gemini_api_key"):
        key = safe["gemini_api_key"]
        safe["gemini_api_key_masked"] = key[:4] + "..." + key[-4:] if len(key) > 8 else "****"
    else:
        safe["gemini_api_key_masked"] = ""
    # Mask Telegram bot token for display
    if safe.get("telegram_bot_token"):
        key = safe["telegram_bot_token"]
        safe["telegram_bot_token_masked"] = key[:4] + "..." + key[-4:] if len(key) > 8 else "****"
    else:
        safe["telegram_bot_token_masked"] = ""
    safe.pop("telegram_bot_token", None)
    # Replace interim_audio with just key list (audio data is large)
    if safe.get("interim_audio"):
        safe["interim_audio_keys"] = list(safe["interim_audio"].keys())
    else:
        safe["interim_audio_keys"] = []
    safe.pop("interim_audio", None)
    return safe


@app.get("/api/interim_audio")
async def get_interim_audio():
    """Return the pre-generated interim audio data (large payload)."""
    settings = settings_service.get_all()
    return {
        "enabled": settings.get("enable_interim_response", False),
        "audio": settings.get("interim_audio", {}),
        "phrases": settings.get("interim_phrases", {}),
    }


@app.get("/api/settings/defaults")
async def get_default_settings():
    safe = {k: v for k, v in DEFAULT_SETTINGS.items() if k != "gemini_api_key"}
    return safe


@app.post("/api/settings")
async def save_settings(request: Request):
    body = await request.json()
    old_token = settings_service.get("telegram_bot_token", "")
    updated = settings_service.save(body)
    new_token = updated.get("telegram_bot_token", "")
    # Hot-reload Telegram bot on token change
    if new_token != old_token:
        await telegram_manager.stop()
        if new_token:
            try:
                await telegram_manager.start(new_token)
            except Exception as e:
                print(f"[Telegram] Failed to start bot: {e}")
    return {"status": "ok", "settings": updated}


@app.get("/api/token_usage")
async def get_token_usage():
    return token_service.get_summary()


@app.post("/api/token_usage/reset")
async def reset_token_usage():
    token_service.reset()
    return {"status": "ok"}


MODELS_LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models"


@app.get("/api/models")
def list_models(mode: str = "live"):
    """Query available Gemini models filtered by API mode.

    Args:
        mode: 'live' filters by bidiGenerateContent, 'text' filters by generateContent.
    """
    api_key = settings_service.get("gemini_api_key", "")
    if not api_key:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    try:
        url = f"{MODELS_LIST_URL}?key={api_key}&pageSize=1000"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return JSONResponse({"error": f"Google API error: {e.code} {body[:200]}"}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    required_method = "generateContent" if mode == "text" else "bidiGenerateContent"

    matched_models = []
    for m in data.get("models", []):
        methods = m.get("supportedGenerationMethods", [])
        if required_method not in methods:
            continue
        # Strip "models/" prefix for display
        name = m.get("name", "")
        model_id = name.removeprefix("models/")
        matched_models.append({
            "id": model_id,
            "displayName": m.get("displayName", model_id),
            "description": m.get("description", ""),
            "inputTokenLimit": m.get("inputTokenLimit"),
            "outputTokenLimit": m.get("outputTokenLimit"),
        })

    return {"models": matched_models}


@app.post("/api/generate_interim_audio")
async def generate_interim_audio(request: Request):
    """Generate interim response audio clips using Gemini Live API."""
    body = await request.json()
    phrases = body.get("phrases", {})
    if not phrases:
        return JSONResponse({"error": "No phrases provided"}, status_code=400)

    settings = settings_service.get_all()
    api_key = settings.get("gemini_api_key", "")
    if not api_key:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    model = settings.get("live_model", "gemini-2.5-flash-native-audio-latest")
    voice_name = settings.get("voice_name", "Aoede")

    url = f"{GEMINI_WS_URL}?key={api_key}"

    try:
        ws = await websockets.connect(url, max_size=None, close_timeout=5)

        # Setup: simple TTS session — instruct model to just speak the given text
        setup_msg = {
            "setup": {
                "model": f"models/{model}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": voice_name}
                        }
                    },
                },
                "systemInstruction": {
                    "parts": [{"text": (
                        "你是一個語音助手。請直接朗讀用戶提供的文字，不要添加任何額外的內容、解釋或問候。"
                        "只需要自然地唸出文字即可。"
                    )}]
                },
            }
        }
        await ws.send(json.dumps(setup_msg))
        await ws.recv()  # setup complete

        result = {}
        for func_name, phrase in phrases.items():
            # Send the phrase as a text turn
            turn_msg = {
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": phrase}]}],
                    "turnComplete": True,
                }
            }
            await ws.send(json.dumps(turn_msg))

            # Collect audio response chunks
            audio_chunks = []
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(raw)
                if "serverContent" in data:
                    content = data["serverContent"]
                    parts = content.get("modelTurn", {}).get("parts", [])
                    for part in parts:
                        if "inlineData" in part:
                            audio_chunks.append(part["inlineData"]["data"])
                    if content.get("turnComplete", False):
                        break

            # Concatenate PCM chunks into single base64 string
            if audio_chunks:
                all_pcm = b""
                for chunk_b64 in audio_chunks:
                    all_pcm += base64.b64decode(chunk_b64)
                result[func_name] = base64.b64encode(all_pcm).decode("utf-8")

        await ws.close()

        # Save to settings
        settings_service.save({"interim_audio": result})

        return {"status": "ok", "generated": list(result.keys())}

    except asyncio.TimeoutError:
        return JSONResponse({"error": "Gemini response timed out"}, status_code=504)
    except Exception as e:
        print(f"Interim audio generation error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/move")
async def move_robot(request: Request):
    body = await request.json()
    x = body.get("x", 0)
    y = body.get("y", 0)
    theta = body.get("theta", 0)
    robot_manager.move_to_pose(x, y, theta)
    return {"status": "ok"}


@app.post("/api/cancel_command")
async def cancel_command():
    robot_manager.cancel_command()
    return {"status": "ok"}


@app.post("/api/return_home")
async def return_home():
    robot_manager.return_home()
    return {"status": "ok"}


@app.post("/api/manual_control")
async def manual_control(request: Request):
    body = await request.json()
    direction = body.get("direction", "")
    if direction == "forward":
        robot_manager.move_forward(0.1)
    elif direction == "backward":
        robot_manager.move_forward(-0.1)
    elif direction == "left":
        robot_manager.rotate(math.radians(10))
    elif direction == "right":
        robot_manager.rotate(math.radians(-10))
    return {"status": "ok"}


# ─── Robot connection management ─────────────────────────────────────────────

@app.post("/api/robot/connect")
async def robot_connect(request: Request):
    body = await request.json()
    ip = body.get("ip", "").strip()
    if not ip:
        return JSONResponse({"ok": False, "error": "IP address is required"}, status_code=400)
    result = await asyncio.to_thread(robot_manager.connect, ip)
    return result


@app.post("/api/robot/disconnect")
async def robot_disconnect():
    result = await asyncio.to_thread(robot_manager.disconnect)
    return result


@app.get("/api/robot/status")
async def robot_status():
    return robot_manager.get_connection_status()


# ─── WebSocket: Gemini Live API proxy ─────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    session = None

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "connect":
                try:
                    if session:
                        await session.close()
                    api_mode = settings_service.get("api_mode", "live")
                    if api_mode == "text":
                        session = GeminiTextSession(websocket.send_json)
                    else:
                        session = GeminiLiveSession(websocket)
                    ok = await session.connect()
                    if not ok:
                        session = None
                except Exception as e:
                    print(f"Gemini session connect error: {e}")
                    import traceback
                    traceback.print_exc()
                    session = None
                    try:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Failed to start Gemini session: {e}",
                        })
                    except Exception:
                        pass

            elif msg_type == "disconnect":
                if session:
                    await session.close()
                    session = None
                await websocket.send_json({
                    "type": "status",
                    "message": "Disconnected from Gemini",
                })

            elif msg_type == "text":
                if session:
                    try:
                        await session.send_text(data.get("content", ""))
                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Send error: {e}",
                        })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Not connected. Click Connect first.",
                    })

            elif msg_type == "audio":
                if session:
                    try:
                        await session.send_audio(data.get("data", ""))
                    except Exception:
                        pass

            elif msg_type == "clear_history":
                if session and hasattr(session, 'clear_history'):
                    await session.clear_history()
                await websocket.send_json({
                    "type": "history_cleared",
                    "message": "Chat history cleared",
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if session:
            await session.close()
