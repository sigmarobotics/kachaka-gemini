import asyncio
import json
import base64
import traceback
import uuid
from datetime import datetime, timezone, timedelta
import websockets
from robot_service import robot_service
import settings_service
import token_service
from config import DEFAULT_FUNCTION_DECLARATIONS, _clamp

GEMINI_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


def execute_function_call(name: str, args: dict) -> dict:
    """Execute a function call from Gemini and return the result."""
    try:
        if name == "move_to_location":
            location_id = args.get("location_id", "")
            if not location_id:
                return {"success": False, "error": "location_id is required"}
            result = robot_service.move_to_location(location_id)
            return result

        elif name == "move_shelf":
            shelf_id = args.get("shelf_id", "")
            destination_id = args.get("destination_id", "")
            if not shelf_id or not destination_id:
                return {"success": False, "error": "shelf_id and destination_id are required"}
            result = robot_service.move_shelf(shelf_id, destination_id)
            return result

        elif name == "return_shelf":
            shelf_id = args.get("shelf_id", "")
            if not shelf_id:
                return {"success": False, "error": "shelf_id is required"}
            result = robot_service.return_shelf(shelf_id)
            return result

        elif name == "get_robot_status":
            state = robot_service.get_state()
            cmd_state = robot_service.get_command_state()
            return {
                "battery": state["battery"],
                "pose": state["pose"],
                "command_state": cmd_state.get("state", "unknown"),
            }

        elif name == "cancel_command":
            robot_service.cancel_command()
            return {"success": True, "message": "Command cancelled"}

        elif name == "capture_camera":
            img = robot_service.get_front_camera_image()
            if img and hasattr(img, "data") and img.data:
                return {"success": True, "message": "Camera frame captured, image attached"}
            else:
                return {"success": False, "error": "Camera not available"}

        else:
            return {"error": f"Unknown function: {name}"}

    except Exception as e:
        return {"error": str(e)}


class GeminiLiveSession:
    """Manages a single Gemini Live API WebSocket session."""

    def __init__(self, client_ws):
        self.client_ws = client_ws
        self.gemini_ws = None
        self._receive_task = None
        self._camera_task = None
        self._closed = False
        self._session_id = uuid.uuid4().hex[:12]

    async def connect(self):
        settings = settings_service.get_all()
        api_key = settings.get("gemini_api_key", "")
        if not api_key:
            await self._send_to_client({
                "type": "error",
                "message": "Gemini API key not configured. Please set it in Settings.",
            })
            return False

        model = settings.get("live_model", "gemini-2.5-flash-native-audio-preview-12-2025")

        # Build system instruction from sections
        sections = []
        persona = settings.get("persona", "")
        if persona:
            sections.append(f"[Persona]\n{persona}")
        static_knowledge = settings.get("static_knowledge", "")
        if static_knowledge:
            sections.append(f"[Function Usage Rules]\n{static_knowledge}")
        knowledge_base = settings.get("knowledge_base", "")
        if knowledge_base:
            sections.append(f"[Knowledge Base]\n{knowledge_base}")
        robot_info = settings.get("robot_background_info", "")
        if robot_info:
            sections.append(f"[Robot Background Info]\n{robot_info}")
        if settings.get("enable_interim_response", False):
            sections.append(
                "[Note]\n"
                "當你要呼叫功能時，請不要先產生任何語音回覆，直接呼叫功能即可。"
                "系統會自動播放過渡語音通知使用者。"
            )
        system_prompt = "\n\n".join(sections)
        # Inject local time (UTC+8) into {{CURRENT_TIME}} placeholder
        utc8 = timezone(timedelta(hours=8))
        current_time = datetime.now(utc8).strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = system_prompt.replace("{{CURRENT_TIME}}", current_time)
        print(f"System instruction ({len(system_prompt)} chars):\n{system_prompt[:500]}")

        voice_name = settings.get("voice_name", "Aoede")
        func_decls = settings.get("function_declarations", DEFAULT_FUNCTION_DECLARATIONS)
        enable_google_search = settings.get("live_enable_google_search", False)

        live_temperature = _clamp(settings.get("live_temperature", 1.0), 0.0, 2.0, 1.0)
        live_max_output_tokens = _clamp(settings.get("live_max_output_tokens", 8192), 1, 65536, 8192, int)
        live_top_p = _clamp(settings.get("live_top_p", 0.95), 0.0, 1.0, 0.95)
        live_top_k = _clamp(settings.get("live_top_k", 40), 1, 100, 40, int)

        url = f"{GEMINI_WS_URL}?key={api_key}"

        try:
            self.gemini_ws = await websockets.connect(
                url, max_size=None, close_timeout=5
            )

            # Build generation config based on response mode
            gen_params = {
                "temperature": live_temperature,
                "maxOutputTokens": live_max_output_tokens,
                "topP": live_top_p,
                "topK": live_top_k,
            }

            generation_config = {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice_name}
                    }
                },
                **gen_params,
            }

            # Build tools list
            tools = [{"functionDeclarations": func_decls}]
            if enable_google_search:
                tools.append({"googleSearch": {}})

            setup_msg = {
                "setup": {
                    "model": f"models/{model}",
                    "generationConfig": generation_config,
                    "systemInstruction": {
                        "parts": [{"text": system_prompt}]
                    },
                    "tools": tools,
                }
            }

            await self.gemini_ws.send(json.dumps(setup_msg))

            # Wait for setup complete
            raw = await self.gemini_ws.recv()
            setup_response = json.loads(raw)
            print(f"Gemini setup response: {json.dumps(setup_response)[:200]}")

        except Exception as e:
            print(f"Gemini connect/setup error: {e}")
            traceback.print_exc()
            await self._send_to_client({
                "type": "error",
                "message": f"Failed to connect to Gemini: {e}",
            })
            if self.gemini_ws:
                try:
                    await self.gemini_ws.close()
                except Exception:
                    pass
                self.gemini_ws = None
            return False

        await self._send_to_client({
            "type": "status",
            "message": "Connected to Gemini Live API",
        })

        # Start receiving from Gemini
        self._receive_task = asyncio.create_task(self._receive_from_gemini())

        # Start camera streaming if enabled
        if settings.get("enable_camera_to_ai", False):
            self._camera_task = asyncio.create_task(self._stream_camera())

        return True

    async def send_text(self, text: str):
        if not self.gemini_ws:
            return
        msg = {
            "clientContent": {
                "turns": [{"role": "user", "parts": [{"text": text}]}],
                "turnComplete": True,
            }
        }
        await self.gemini_ws.send(json.dumps(msg))

    async def send_audio(self, audio_b64: str):
        if not self.gemini_ws:
            return
        msg = {
            "realtimeInput": {
                "audio": {
                    "mimeType": "audio/pcm;rate=16000",
                    "data": audio_b64,
                }
            }
        }
        await self.gemini_ws.send(json.dumps(msg))

    async def _stream_camera(self):
        """Periodically send camera frames to Gemini."""
        try:
            while not self._closed and self.gemini_ws:
                try:
                    img = robot_service.get_front_camera_image()
                    if img and hasattr(img, "data") and img.data:
                        b64_data = base64.b64encode(img.data).decode("utf-8")
                        msg = {
                            "realtimeInput": {
                                "video": {
                                    "mimeType": "image/jpeg",
                                    "data": b64_data,
                                }
                            }
                        }
                        await self.gemini_ws.send(json.dumps(msg))
                except Exception as e:
                    print(f"Camera stream error: {e}")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass

    async def _receive_from_gemini(self):
        """Receive messages from Gemini and forward/process them."""
        try:
            async for raw in self.gemini_ws:
                if self._closed:
                    break
                try:
                    msg = json.loads(raw)
                    await self._handle_gemini_message(msg)
                except json.JSONDecodeError:
                    print(f"Non-JSON from Gemini: {raw[:100]}")
        except websockets.ConnectionClosed as e:
            if not self._closed:
                print(f"Gemini connection closed: code={e.code} reason={e.reason}")
                await self._send_to_client({
                    "type": "gemini_disconnected",
                    "code": e.code,
                    "reason": e.reason or "Session ended by server",
                })
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Gemini receive error: {e}")
            traceback.print_exc()
            if not self._closed:
                await self._send_to_client({
                    "type": "error",
                    "message": f"Gemini error: {e}",
                })

    async def _handle_gemini_message(self, msg: dict):
        """Process a single message from Gemini."""
        # Handle serverContent (text/audio responses)
        if "serverContent" in msg:
            content = msg["serverContent"]
            model_turn = content.get("modelTurn", {})
            parts = model_turn.get("parts", [])

            for part in parts:
                if "text" in part:
                    await self._send_to_client({
                        "type": "text",
                        "content": part["text"],
                    })
                elif "inlineData" in part:
                    inline = part["inlineData"]
                    mime = inline.get("mimeType", "")
                    if "audio" in mime:
                        await self._send_to_client({
                            "type": "audio",
                            "data": inline["data"],
                        })

            if content.get("turnComplete", False):
                await self._send_to_client({"type": "turn_complete"})

        # Handle toolCall
        elif "toolCall" in msg:
            tool_call = msg["toolCall"]
            function_calls = tool_call.get("functionCalls", [])

            for fc in function_calls:
                fn_name = fc.get("name", "")
                fn_args = fc.get("args", {})
                fn_id = fc.get("id", "")

                # Notify client about the function call
                await self._send_to_client({
                    "type": "function_call",
                    "name": fn_name,
                    "args": fn_args,
                })

                # Execute function
                result = execute_function_call(fn_name, fn_args)

                # Notify client about result
                await self._send_to_client({
                    "type": "function_result",
                    "name": fn_name,
                    "result": result,
                })

                # Send tool response back to Gemini
                tool_response = {
                    "toolResponse": {
                        "functionResponses": [
                            {
                                "id": fn_id,
                                "name": fn_name,
                                "response": result,
                            }
                        ]
                    }
                }
                if self.gemini_ws:
                    await self.gemini_ws.send(json.dumps(tool_response))

                    # For capture_camera, also send the image as realtime input
                    if fn_name == "capture_camera" and result.get("success"):
                        img = robot_service.get_front_camera_image()
                        if img and hasattr(img, "data") and img.data:
                            b64_data = base64.b64encode(img.data).decode("utf-8")
                            img_msg = {
                                "realtimeInput": {
                                    "mediaChunks": [{
                                        "mimeType": "image/jpeg",
                                        "data": b64_data,
                                    }]
                                }
                            }
                            await self.gemini_ws.send(json.dumps(img_msg))

        # Handle toolCallCancellation
        elif "toolCallCancellation" in msg:
            await self._send_to_client({
                "type": "status",
                "message": "Tool call cancelled by Gemini",
            })

        # Handle setupComplete or other messages
        elif "setupComplete" in msg:
            pass  # Already handled during connect

        # Track token usage from usageMetadata (can appear on any server message)
        if "usageMetadata" in msg:
            um = msg["usageMetadata"]
            prompt = um.get("promptTokenCount", 0)
            response = um.get("responseTokenCount", 0)
            total = um.get("totalTokenCount", 0)
            if total > 0:
                token_service.record(self._session_id, prompt, response, total)
                await self._send_to_client({
                    "type": "token_usage",
                    "prompt": prompt,
                    "response": response,
                    "total": total,
                })

    async def _send_to_client(self, msg: dict):
        """Send a message to the browser client."""
        if self._closed:
            return
        try:
            await self.client_ws.send_json(msg)
        except Exception:
            pass

    async def clear_history(self):
        """Clear conversation history by reconnecting with a fresh Gemini session.

        The Live API maintains history server-side; the only way to clear it
        is to close the current connection and start a new one.
        """
        if self._receive_task:
            self._receive_task.cancel()
            self._receive_task = None
        if self._camera_task:
            self._camera_task.cancel()
            self._camera_task = None
        if self.gemini_ws:
            try:
                await self.gemini_ws.close()
            except Exception:
                pass
            self.gemini_ws = None

        self._closed = False
        await self.connect()

    async def close(self):
        self._closed = True
        if self._receive_task:
            self._receive_task.cancel()
        if self._camera_task:
            self._camera_task.cancel()
        if self.gemini_ws:
            try:
                await self.gemini_ws.close()
            except Exception:
                pass
