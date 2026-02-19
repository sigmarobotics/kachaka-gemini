# Google Search + Function Calling Workaround

## Problem

`gemini-3-flash-preview` does not support Google Search and Function Calling in the same API request. Sending both tools results in:

```
400 INVALID_ARGUMENT: Tool use with function calling is unsupported by the model.
```

All tested combinations fail:

| Approach | Result |
|----------|--------|
| `google_search` + `function_declarations` (separate Tool objects) | 400 |
| `google_search_retrieval` + `function_declarations` | 400: "google_search_retrieval is not supported" |
| Both tools + `tool_config.function_calling_config.mode = "AUTO"` | 400 |
| Both in same `types.Tool()` | SDK silently drops `google_search`; model hallucinates function call |

## Solution: Separate API Calls

Since the two tools cannot coexist in one request, we intercept the model's `google_search` function call and execute it via a dedicated API call.

### Flow

```
User message
    │
    ▼
generateContent(tools=[functionDeclarations])
    │
    ▼
Model response contains functionCall?
    │
    ├─ name == "google_search"
    │       │
    │       ▼
    │   Separate API call: generateContent(tools=[GoogleSearch])
    │       │
    │       ▼
    │   Return search text + grounding sources as functionResponse
    │       │
    │       ▼
    │   Loop: call generateContent again with search results
    │
    ├─ name == other function (move_to_location, etc.)
    │       │
    │       ▼
    │   Execute locally via execute_function_call()
    │
    └─ No function call → return text response
```

### Implementation (`gemini_text_service.py`)

1. **Connect**: Only send `functionDeclarations` as tools (no Google Search):
   ```python
   tool_list = [types.Tool(function_declarations=func_decls)]
   # Google Search is NOT added here — conflicts with function calling.
   ```

2. **Intercept**: In `_generate()`, check for `google_search` function calls:
   ```python
   if fn_name == "google_search":
       result = await self._handle_google_search(fn_args)
   else:
       result = execute_function_call(fn_name, fn_args)
   ```

3. **Search**: `_handle_google_search()` makes a standalone API call:
   ```python
   search_config = types.GenerateContentConfig(
       tools=[types.Tool(google_search=types.GoogleSearch())],
   )
   response = await asyncio.to_thread(
       self._client.models.generate_content,
       model=self._model,
       contents=search_query,
       config=search_config,
   )
   ```

4. **Return**: Search text is returned as a function response; grounding metadata (source URLs) is forwarded to the frontend.

### Why the Model Calls `google_search`

The system instruction includes phrases like "必須調用 Google Search" which causes the model to emit a `functionCall` with `name: "google_search"` even though it's not declared in `functionDeclarations`. This is expected behavior — the model treats it as an implicit tool.

### Settings

- `text_enable_google_search` (bool): Controls whether `_handle_google_search()` processes the call or returns an error.
- The setting toggle is in the Settings page under the Text API tab.

## Affected Models

- `gemini-3-flash-preview` — confirmed incompatible (2026-02-19)
- Other models (e.g. `gemini-2.5-flash`) may support both tools natively. If Google upgrades model support, the workaround can be replaced with the standard approach (both tools in one request).

## Live API

The Live API (`gemini_live_service.py`) uses `{"googleSearch": {}}` as a separate WebSocket tool and has its own conflict handling (blocking function calls when Google Search grounding is detected). This workaround is specific to the Text API.
