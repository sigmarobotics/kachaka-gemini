import asyncio
import traceback
import uuid
from datetime import datetime, timezone, timedelta

from google import genai
from google.genai import types

import base64

from robot_manager import robot_manager
import settings_service
import token_service
import file_service
from config import DEFAULT_FUNCTION_DECLARATIONS, _clamp


class GeminiTextSession:
    """Manages a Gemini Text API session using google-genai SDK."""

    def __init__(self, send_callback):
        self.send_callback = send_callback
        self._closed = False
        self._session_id = uuid.uuid4().hex[:12]
        self._client = None
        self._model = ""
        self._config = None
        self._history = []  # list of types.Content
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

        self._model = settings.get("text_model", "gemini-3-flash-preview")
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
        system_prompt = system_prompt.replace("{{CURRENT_TIME}}", current_time)
        print(f"[TextAPI] System instruction ({len(system_prompt)} chars):\n{system_prompt[:500]}")

        func_decls = list(settings.get("function_declarations", DEFAULT_FUNCTION_DECLARATIONS))
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

        tool_list = [types.Tool(function_declarations=func_decls)]

        # Generation parameters
        temperature = _clamp(settings.get("text_temperature", 1.0), 0.0, 2.0, 1.0)
        max_output_tokens = _clamp(settings.get("text_max_output_tokens", 8192), 1, 65536, 8192, int)
        top_p = _clamp(settings.get("text_top_p", 0.95), 0.0, 1.0, 0.95)
        top_k = _clamp(settings.get("text_top_k", 40), 1, 100, 40, int)
        raw_safety = settings.get("text_safety_settings", {})

        # Build safety settings list
        VALID_SAFETY_CATEGORIES = {
            "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
        }
        VALID_THRESHOLDS = {
            "BLOCK_NONE", "BLOCK_LOW_AND_ABOVE",
            "BLOCK_MEDIUM_AND_ABOVE", "BLOCK_ONLY_HIGH",
        }
        safety_settings = []
        for cat, thresh in raw_safety.items():
            if cat in VALID_SAFETY_CATEGORIES and thresh in VALID_THRESHOLDS:
                safety_settings.append(types.SafetySetting(category=cat, threshold=thresh))
            else:
                print(f"[TextAPI] Ignoring invalid safety setting: {cat}={thresh}")
        safety_settings = safety_settings or None

        self._config = types.GenerateContentConfig(
            system_instruction=system_prompt if system_prompt else None,
            tools=tool_list,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=top_p,
            top_k=top_k,
            safety_settings=safety_settings,
        )
        self._history = []

        await self._send_to_client({
            "type": "status",
            "message": "Connected to Gemini Text API",
            "api_mode": "text",
        })

        return True

    async def send_text(self, text: str):
        if self._closed:
            return

        parts = []

        # Inject enabled files on the first message (or after history clear)
        if not self._files_injected:
            enabled_files = file_service.get_enabled_files()
            for ef in enabled_files:
                parts.append(types.Part.from_uri(
                    file_uri=ef["uri"],
                    mime_type=ef.get("mime_type", "application/octet-stream"),
                ))
            if enabled_files:
                print(f"[TextAPI] Injected {len(enabled_files)} file(s)")
                self._files_injected = True

        parts.append(types.Part.from_text(text=text))

        self._history.append(
            types.Content(role="user", parts=parts)
        )

        await self._generate()

    async def send_audio(self, audio_b64: str):
        # Text API doesn't support audio input — no-op
        pass

    async def _generate(self):
        """Call generateContent in a loop to handle function calling."""
        while True:
            await self._send_to_client({"type": "thinking"})
            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=self._history,
                    config=self._config,
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

            # Track token usage
            usage = response.usage_metadata
            if usage:
                prompt_tokens = usage.prompt_token_count or 0
                response_tokens = usage.candidates_token_count or 0
                total_tokens = usage.total_token_count or 0
                if total_tokens > 0:
                    token_service.record(self._session_id, prompt_tokens, response_tokens, total_tokens)
                    await self._send_to_client({
                        "type": "token_usage",
                        "prompt": prompt_tokens,
                        "response": response_tokens,
                        "total": total_tokens,
                    })

            # Parse response
            if not response.candidates:
                await self._send_to_client({
                    "type": "error",
                    "message": "No response from Gemini",
                })
                return

            candidate = response.candidates[0]
            model_content = candidate.content

            # Append model content to history (SDK preserves thought signatures)
            self._history.append(model_content)

            # Check if Google Search grounding was used
            grounding = getattr(candidate, "grounding_metadata", None)
            used_google_search = bool(
                grounding and getattr(grounding, "search_entry_point", None)
            )

            # Separate function calls and text parts
            function_call_parts = [p for p in model_content.parts if p.function_call]
            text_parts = [p for p in model_content.parts if p.text is not None]

            # If Google Search and function calls both present, block function calls
            if used_google_search and function_call_parts:
                print(f"[TextAPI] Google Search + function call conflict — blocking function calls")

                # Notify frontend about the blocked function calls
                for part in function_call_parts:
                    fc = part.function_call
                    await self._send_to_client({
                        "type": "function_call_blocked",
                        "name": fc.name,
                        "args": dict(fc.args) if fc.args else {},
                    })

                # Send Google Search grounding info
                await self._send_google_search_info(grounding)

                # Send text response if available
                if text_parts:
                    full_text = "".join(p.text for p in text_parts)
                    await self._send_to_client({
                        "type": "text",
                        "content": full_text,
                    })

                await self._send_to_client({"type": "turn_complete"})
                return

            if function_call_parts:
                # Execute function calls and build responses
                fn_response_parts = []
                for part in function_call_parts:
                    fc = part.function_call
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}

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

                    fn_response_parts.append(
                        types.Part.from_function_response(
                            name=fn_name,
                            response=result,
                        )
                    )

                    # For capture_camera, attach the image alongside function response
                    if fn_name == "capture_camera" and result.get("ok"):
                        frame = robot_manager.get_camera_frame()
                        if frame and frame.get("ok") and frame.get("image_base64"):
                            fn_response_parts.append(
                                types.Part.from_bytes(
                                    data=base64.b64decode(frame["image_base64"]),
                                    mime_type="image/jpeg",
                                )
                            )

                # Append function responses (+ image if any) as user turn and loop
                self._history.append(
                    types.Content(role="user", parts=fn_response_parts)
                )
                continue  # Loop to call API again

            elif text_parts:
                # Send Google Search grounding info if present
                if used_google_search:
                    await self._send_google_search_info(grounding)

                full_text = "".join(p.text for p in text_parts)
                await self._send_to_client({
                    "type": "text",
                    "content": full_text,
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
            search_config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=search_query,
                config=search_config,
            )

            search_text = response.text or ""

            # Forward grounding metadata (sources) to the frontend
            if response.candidates:
                grounding = getattr(response.candidates[0], "grounding_metadata", None)
                if grounding:
                    await self._send_google_search_info(grounding)

            return {"result": search_text}
        except Exception as e:
            print(f"[TextAPI] Google Search error: {e}")
            traceback.print_exc()
            return {"error": f"Google Search failed: {e}"}

    async def _send_google_search_info(self, grounding):
        """Send Google Search grounding metadata to the frontend."""
        chunks = getattr(grounding, "grounding_chunks", None) or []
        sources = []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web:
                sources.append({
                    "title": getattr(web, "title", "") or "",
                    "uri": getattr(web, "uri", "") or "",
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
        self._history = []
        self._files_injected = False

    async def close(self):
        self._closed = True
