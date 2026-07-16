import asyncio
import json
import traceback
import uuid
from datetime import datetime, timezone, timedelta

from google import genai

from robot_manager import robot_manager
from location_service import location_service
import settings_service
import token_service
import file_service
from config import DEFAULT_FUNCTION_DECLARATIONS, _clamp


def _content_type_for_mime(mime_type: str) -> str:
    """Map a mime type to an Interactions API input content "type"."""
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "document"


class GeminiTextSession:
    """Manages a Gemini Text API session using google-genai SDK."""

    def __init__(self, send_callback):
        self.send_callback = send_callback
        self._closed = False
        self._session_id = uuid.uuid4().hex[:12]
        self._client = None
        self._model = ""
        self._system_instruction = None
        self._tools = None
        self._generation_config = None
        self._safety_settings = None
        self._previous_interaction_id = None  # server-side state (Interactions API)
        self._enable_google_search = False
        self._files_injected = False

    async def connect(self):
        settings = settings_service.get_all()
        api_key = settings.get("gemini_api_key", "")
        if not api_key:
            await self._send_to_client({
                "type": "error",
                "message": "Gemini API key not configured. Please set it in Settings.",
            })
            return False

        self._model = settings.get("text_model", "gemini-3.5-flash")
        self._client = genai.Client(api_key=api_key)

        # Build system instruction (same logic as Live session)
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
        print(f"[TextAPI] System instruction ({len(system_prompt)} chars)")

        all_decls = settings.get("function_declarations", DEFAULT_FUNCTION_DECLARATIONS)
        func_decls = [
            {k: v for k, v in f.items() if k != "enabled"}
            for f in all_decls if f.get("enabled", True)
        ]

        # Dynamically populate inspect_location.location_name.enum
        patrol_point_ids = set(settings.get("patrol_points", []))
        location_names = []
        for loc in location_enum:
            # If patrol_points is configured, only include those locations
            if patrol_point_ids and loc["id"] not in patrol_point_ids:
                continue
            location_names.append(loc["name"])
        if not location_names:
            # Fallback: include all locations
            location_names = [loc["name"] for loc in location_enum]
        _location_enum_fcs = {"inspect_location", "guide_to_booth"}
        for fd in func_decls:
            if fd.get("name") in _location_enum_fcs:
                props = fd.get("parameters", {}).get("properties", {})
                if "location_name" in props:
                    props["location_name"]["enum"] = location_names

        self._enable_google_search = settings.get("text_enable_google_search", False)

        # Google Search + function calling can't coexist in the same request
        # for some models (e.g. gemini-3-flash-preview returns 400).
        # Instead, we inject a google_search function declaration so the model
        # can emit a google_search call, which we intercept and handle via a
        # separate API call in _handle_google_search().
        if self._enable_google_search:
            has_gs = any(f.get("name") == "google_search" for f in func_decls)
            if not has_gs:
                func_decls.append({
                    "name": "google_search",
                    "description": (
                        "搜尋 Google 以取得即時資訊。當知識庫無法回答、"
                        "或使用者詢問即時新聞、天氣、時事等需要最新資料的問題時調用。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "queries": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "搜尋關鍵字列表",
                            }
                        },
                        "required": ["queries"],
                    },
                })
                print("[TextAPI] Injected google_search function declaration")

        # Interactions API: each function tool dict needs a top-level "type": "function"
        # (the old SDK's types.Tool(function_declarations=...) wrapper is gone).
        self._tools = [{**fd, "type": "function"} for fd in func_decls]

        # Generation parameters
        temperature = _clamp(settings.get("text_temperature", 1.0), 0.0, 2.0, 1.0)
        max_output_tokens = _clamp(settings.get("text_max_output_tokens", 8192), 1, 65536, 8192, int)
        top_p = _clamp(settings.get("text_top_p", 0.95), 0.0, 1.0, 0.95)
        # NOTE: top_k has no equivalent in the Interactions API's generation_config
        # (confirmed against the API reference — only temperature/max_output_tokens/top_p/
        # thinking_level/seed/stop_sequences/speech_config/tool_choice/video_config exist).
        # text_top_k is still read from settings so the field stays valid, but it is not sent.
        _ = _clamp(settings.get("text_top_k", 40), 1, 100, 40, int)
        raw_safety = settings.get("text_safety_settings", {})

        # Build safety settings list — Interactions API renamed the category enum
        # (HARM_CATEGORY_* -> lowercase HarmCategory values) and moved threshold to
        # lowercase too; "method" is optional and defaults to probability-based blocking,
        # matching the old API's default behavior.
        CATEGORY_MAP = {
            "HARM_CATEGORY_HARASSMENT": "harassment",
            "HARM_CATEGORY_HATE_SPEECH": "hate_speech",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "sexually_explicit",
            "HARM_CATEGORY_DANGEROUS_CONTENT": "dangerous_content",
        }
        THRESHOLD_MAP = {
            "BLOCK_NONE": "block_none",
            "BLOCK_LOW_AND_ABOVE": "block_low_and_above",
            "BLOCK_MEDIUM_AND_ABOVE": "block_medium_and_above",
            "BLOCK_ONLY_HIGH": "block_only_high",
        }
        safety_settings = []
        for cat, thresh in raw_safety.items():
            if cat in CATEGORY_MAP and thresh in THRESHOLD_MAP:
                safety_settings.append({"type": CATEGORY_MAP[cat], "threshold": THRESHOLD_MAP[thresh]})
            else:
                print(f"[TextAPI] Ignoring invalid safety setting: {cat}={thresh}")
        self._safety_settings = safety_settings or None

        self._system_instruction = system_prompt if system_prompt else None
        self._generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "top_p": top_p,
        }
        self._previous_interaction_id = None

        await self._send_to_client({
            "type": "status",
            "message": "Connected to Gemini Text API",
            "api_mode": "text",
        })

        return True

    async def send_text(self, text: str):
        if self._closed:
            return

        input_items = []

        # Inject enabled files on the first message (or after history clear)
        if not self._files_injected:
            enabled_files = file_service.get_enabled_files()
            for ef in enabled_files:
                mime_type = ef.get("mime_type", "application/octet-stream")
                input_items.append({
                    "type": _content_type_for_mime(mime_type),
                    "uri": ef["uri"],
                    "mime_type": mime_type,
                })
            if enabled_files:
                print(f"[TextAPI] Injected {len(enabled_files)} file(s)")
                self._files_injected = True

        input_items.append({"type": "text", "text": text})

        await self._generate(input_items)

    async def send_audio(self, audio_b64: str):
        # Text API doesn't support audio input — no-op
        pass

    async def _generate(self, input_data):
        """Call interactions.create in a loop to handle function calling."""
        while True:
            await self._send_to_client({"type": "thinking"})
            try:
                kwargs = dict(
                    model=self._model,
                    input=input_data,
                    tools=self._tools,
                    system_instruction=self._system_instruction,
                    generation_config=self._generation_config,
                )
                # NOTE: safety_settings is NOT sent — confirmed via live test that the
                # standard Gemini API (genai.Client(api_key=...)) rejects this top-level
                # param with a 400 ("not available on the Gemini API but it is available
                # on the Gemini Enterprise Agent Platform"). Sending it would break every
                # turn for any user with custom safety settings configured. self._safety_settings
                # is still computed in connect() (see below) in case this becomes available later.
                if self._previous_interaction_id:
                    kwargs["previous_interaction_id"] = self._previous_interaction_id
                interaction = await asyncio.to_thread(
                    self._client.interactions.create,
                    **kwargs,
                )
            except Exception as e:
                print(f"[TextAPI] API call error: {e}")
                traceback.print_exc()
                await self._send_to_client({
                    "type": "error",
                    "message": f"Gemini API error: {e}",
                })
                return

            if self._closed:
                return

            # Server-side state — carry this interaction forward as history.
            self._previous_interaction_id = interaction.id

            # Track token usage
            usage = getattr(interaction, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "total_input_tokens", 0) or 0
                response_tokens = getattr(usage, "total_output_tokens", 0) or 0
                total_tokens = getattr(usage, "total_tokens", 0) or 0
                if total_tokens > 0:
                    token_service.record(self._session_id, prompt_tokens, response_tokens, total_tokens)
                    await self._send_to_client({
                        "type": "token_usage",
                        "prompt": prompt_tokens,
                        "response": response_tokens,
                        "total": total_tokens,
                    })

            steps = interaction.steps or []
            function_call_steps = [s for s in steps if s.type == "function_call"]
            model_output_steps = [s for s in steps if s.type == "model_output"]

            # Check if Google Search grounding was used (url_citation annotations
            # on model_output text content blocks)
            used_google_search = False
            for s in model_output_steps:
                for block in (s.content or []):
                    if getattr(block, "type", None) == "text":
                        for ann in (getattr(block, "annotations", None) or []):
                            if getattr(ann, "type", None) == "url_citation":
                                used_google_search = True

            # If Google Search and function calls both present, block function calls
            if used_google_search and function_call_steps:
                print(f"[TextAPI] Google Search + function call conflict — blocking function calls")

                # Notify frontend about the blocked function calls
                for step in function_call_steps:
                    await self._send_to_client({
                        "type": "function_call_blocked",
                        "name": step.name,
                        "args": step.arguments or {},
                    })

                # Send Google Search grounding info
                await self._send_google_search_info(model_output_steps)

                # Send text response if available
                if interaction.output_text:
                    await self._send_to_client({
                        "type": "text",
                        "content": interaction.output_text,
                    })

                await self._send_to_client({"type": "turn_complete"})
                return

            if function_call_steps:
                # Execute function calls and build responses
                fn_response_items = []
                for step in function_call_steps:
                    fn_name = step.name
                    fn_args = step.arguments or {}

                    await self._send_to_client({
                        "type": "function_call",
                        "name": fn_name,
                        "args": fn_args,
                    })

                    if fn_name == "google_search":
                        # Handle via separate API call with Google Search grounding
                        result = await self._handle_google_search(fn_args)
                    else:
                        result = await asyncio.to_thread(robot_manager.execute_function_call, fn_name, fn_args)

                    await self._send_to_client({
                        "type": "function_result",
                        "name": fn_name,
                        "result": result,
                    })

                    fn_response_items.append({
                        "type": "function_result",
                        "call_id": step.id,
                        "name": fn_name,
                        "result": [{"type": "text", "text": json.dumps(result)}],
                    })

                    # For capture_camera, attach the image alongside function response
                    if fn_name == "capture_camera" and result.get("ok"):
                        frame = robot_manager.get_camera_frame()
                        if frame and frame.get("ok") and frame.get("image_base64"):
                            fn_response_items.append({
                                "type": "image",
                                "mime_type": "image/jpeg",
                                "data": frame["image_base64"],
                            })

                # Send function responses (+ image if any) back and loop
                input_data = fn_response_items
                continue  # Loop to call API again

            elif interaction.output_text:
                # Send Google Search grounding info if present
                if used_google_search:
                    await self._send_google_search_info(model_output_steps)

                await self._send_to_client({
                    "type": "text",
                    "content": interaction.output_text,
                })
                await self._send_to_client({"type": "turn_complete"})
                return

            else:
                await self._send_to_client({"type": "turn_complete"})
                return

    async def _handle_google_search(self, args: dict) -> dict:
        """Handle google_search function call via a separate API call with Google Search grounding.

        Some models (e.g. gemini-3-flash-preview) don't support Google Search
        and function calling in the same request. The model still emits a
        google_search function call based on the system instruction, so we
        intercept it and perform the search in a dedicated API call.
        """
        if not self._enable_google_search:
            return {"error": "Google Search is not enabled in settings."}

        queries = args.get("queries", [])
        search_query = " ".join(queries) if isinstance(queries, list) else str(queries)
        if not search_query:
            return {"error": "No search queries provided"}

        try:
            interaction = await asyncio.to_thread(
                self._client.interactions.create,
                model=self._model,
                input=search_query,
                tools=[{"type": "google_search"}],
            )

            search_text = interaction.output_text or ""

            # Forward grounding metadata (sources) to the frontend
            model_output_steps = [s for s in (interaction.steps or []) if s.type == "model_output"]
            if model_output_steps:
                await self._send_google_search_info(model_output_steps)

            return {"result": search_text}
        except Exception as e:
            print(f"[TextAPI] Google Search error: {e}")
            traceback.print_exc()
            return {"error": f"Google Search failed: {e}"}

    async def _send_google_search_info(self, model_output_steps):
        """Send Google Search grounding metadata (url_citation annotations) to the frontend."""
        sources = []
        for s in model_output_steps:
            for block in (s.content or []):
                if getattr(block, "type", None) == "text":
                    for ann in (getattr(block, "annotations", None) or []):
                        if getattr(ann, "type", None) == "url_citation":
                            sources.append({
                                "title": getattr(ann, "title", "") or "",
                                "uri": getattr(ann, "url", "") or "",
                            })
        await self._send_to_client({
            "type": "google_search",
            "sources": sources,
        })

    async def _send_to_client(self, msg: dict):
        if self._closed:
            return
        try:
            await self.send_callback(msg)
        except Exception:
            pass

    async def send_text_and_collect(self, text: str) -> list:
        """Send text and return all response messages as a list."""
        collected = []
        async def collector(msg):
            collected.append(msg)
        original_cb = self.send_callback
        self.send_callback = collector
        try:
            await self.send_text(text)
        finally:
            self.send_callback = original_cb
        return collected

    async def clear_history(self):
        """Clear the conversation history."""
        self._previous_interaction_id = None
        self._files_injected = False

    async def close(self):
        self._closed = True
