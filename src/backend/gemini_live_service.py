import asyncio
import json
import traceback
import uuid
from datetime import datetime, timezone, timedelta
import websockets
from robot_manager import robot_manager
from location_service import location_service
import settings_service
import token_service
from config import DEFAULT_FUNCTION_DECLARATIONS, _clamp

GEMINI_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


class GeminiLiveSession:
    """Manages a single Gemini Live API WebSocket session."""

    def __init__(self, client_ws):
        self.client_ws = client_ws
        self.gemini_ws = None
        self._receive_task = None
        self._closed = False
        self._session_id = uuid.uuid4().hex[:12]
        self._cancelled_fc_ids: set = set()  # Track cancelled tool call IDs

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
        # Note: interim_response suppression removed — let the model speak
        # naturally before/after function calls (guided by FC descriptions).
        system_prompt = "\n\n".join(sections)
        # Inject local time (UTC+8) into {{CURRENT_TIME}} placeholder
        utc8 = timezone(timedelta(hours=8))
        current_time = datetime.now(utc8).strftime("%Y-%m-%d %H:%M:%S")
        # Inject available locations into system prompt
        location_enum = location_service.get_location_enum_with_distances()
        if location_enum:
            loc_lines = ["可用地點（依距離排序）："]
            for loc in location_enum:
                dist_str = f" ({loc['distance_m']}m)" if loc.get("distance_m") is not None else ""
                loc_lines.append(f"- {loc['name']}{dist_str}")
            locations_text = "\n".join(loc_lines)
        else:
            locations_text = "可用地點：（機器人未連線，無法取得地點資訊）"
        system_prompt = system_prompt.replace("{{AVAILABLE_LOCATIONS}}", locations_text)

        system_prompt = system_prompt.replace("{{CURRENT_TIME}}", current_time)
        print(f"System instruction ({len(system_prompt)} chars):\n{system_prompt[:500]}")

        voice_name = settings.get("voice_name", "Aoede")
        all_decls = settings.get("function_declarations", DEFAULT_FUNCTION_DECLARATIONS)
        func_decls = [
            {k: v for k, v in f.items() if k != "enabled"}
            for f in all_decls if f.get("enabled", True)
        ]

        # Dynamically populate inspect_location.location_name.enum
        patrol_point_ids = set(settings.get("patrol_points", []))
        location_names = []
        for loc in location_enum:
            if patrol_point_ids and loc["id"] not in patrol_point_ids:
                continue
            location_names.append(loc["name"])
        if not location_names:
            location_names = [loc["name"] for loc in location_enum]
        _location_enum_fcs = {"inspect_location", "guide_to_booth"}
        for fd in func_decls:
            if fd.get("name") in _location_enum_fcs:
                props = fd.get("parameters", {}).get("properties", {})
                if "location_name" in props:
                    props["location_name"]["enum"] = location_names
        enable_google_search = settings.get("live_enable_google_search", False)
        auto_interrupt = settings.get("live_auto_interrupt", True)

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

            setup_config = {
                "model": f"models/{model}",
                "generationConfig": generation_config,
                "systemInstruction": {
                    "parts": [{"text": system_prompt}]
                },
                "tools": tools,
                "contextWindowCompression": {
                    "slidingWindow": {},
                    "triggerTokens": 25600,
                },
            }

            # When auto-interrupt is off (exhibition/noisy environment),
            # tell Gemini server to NOT interrupt model output on detected speech.
            if not auto_interrupt:
                setup_config["realtimeInputConfig"] = {
                    "activityHandling": "NO_INTERRUPTION",
                }

            setup_msg = {"setup": setup_config}

            await self.gemini_ws.send(json.dumps(setup_msg))

            # Wait for setup complete
            raw = await self.gemini_ws.recv()
            setup_response = json.loads(raw)
            print(f"Gemini setup response: {json.dumps(setup_response)[:200]}")
            print(f"  model={model}, tools={len(func_decls)} FCs, voice={voice_name}")
            print(f"  setup_config keys: {list(setup_config.keys())}")

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

        return True

    async def send_text(self, text: str):
        if not self.gemini_ws:
            return
        print(f"[Live] Sending text: {text[:80]}")
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

            # VAD interruption — user started speaking while model was generating
            if content.get("interrupted", False):
                print(f"[Live] >>> INTERRUPTED by VAD")
                await self._send_to_client({"type": "interrupted"})

            if content.get("turnComplete", False):
                print(f"[Live] >>> turnComplete")
                await self._send_to_client({"type": "turn_complete"})

        # Handle toolCall
        elif "toolCall" in msg:
            import time
            tool_call = msg["toolCall"]
            function_calls = tool_call.get("functionCalls", [])

            for fc in function_calls:
                fn_name = fc.get("name", "")
                fn_args = fc.get("args", {})
                fn_id = fc.get("id", "")
                t_start = time.monotonic()

                # Notify client about the function call
                await self._send_to_client({
                    "type": "function_call",
                    "name": fn_name,
                    "args": fn_args,
                })

                # Movement commands are blocking (RobotController waits for completion),
                # so run in thread pool to avoid blocking the event loop
                result = await asyncio.to_thread(robot_manager.execute_function_call, fn_name, fn_args)
                print(f"[Live] FC {fn_name} execute: {time.monotonic()-t_start:.1f}s")

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
                if fn_id in self._cancelled_fc_ids:
                    self._cancelled_fc_ids.discard(fn_id)
                    print(f"[Live] FC {fn_name} total: {time.monotonic()-t_start:.1f}s, SKIPPED — cancelled")
                elif self.gemini_ws and not self._closed:
                    await self.gemini_ws.send(json.dumps(tool_response))
                    print(f"[Live] FC {fn_name} total: {time.monotonic()-t_start:.1f}s, toolResponse sent")
                else:
                    print(f"[Live] FC {fn_name} total: {time.monotonic()-t_start:.1f}s, SKIPPED — ws closed")

        # Handle toolCallCancellation
        elif "toolCallCancellation" in msg:
            raw_ids = msg["toolCallCancellation"].get("ids", [])
            # ids can be a list of strings or a list of dicts
            ids = [
                (i.get("id", "?") if isinstance(i, dict) else str(i))
                for i in raw_ids
            ]
            self._cancelled_fc_ids.update(ids)
            print(f"[Live] toolCallCancellation: ids={ids}")
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
        if self.gemini_ws:
            try:
                await self.gemini_ws.close()
            except Exception:
                pass
