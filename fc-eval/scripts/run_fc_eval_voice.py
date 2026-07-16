#!/usr/bin/env python3
"""
run_fc_eval_voice.py — Voice E2E evaluation for Gemini Live API FC routing.

Synthesizes speech from eval cases via TTS, optionally mixes background noise,
and sends raw audio to Gemini Live API via send_realtime_input.
Only evaluates FC trigger correctness (TP/TN/FP/FN).

Usage:
    # Clean audio
    python scripts/run_fc_eval_voice.py \
        --eval-set evals/eval_set.json \
        --system-prompt current_system_prompt.txt \
        --fc-schema fc_schema.json \
        --output results/voice-clean/ \
        --tag voice-clean

    # With background noise
    python scripts/run_fc_eval_voice.py ... --noise low,mid,high

    # Multiple voices + noise + repeats
    python scripts/run_fc_eval_voice.py ... \
        --voices "zh-TW-HsiaoChenNeural,zh-TW-YunJheNeural" \
        --noise clean,low,mid,high \
        --repeats 2

Requires:
    - GEMINI_API_KEY environment variable
    - pip install google-genai edge-tts
    - ffmpeg (system)
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("ERROR: pip install google-genai")
    sys.exit(1)

try:
    import edge_tts
except ImportError:
    print("ERROR: pip install edge-tts")
    sys.exit(1)


# ── Noise SNR levels ────────────────────────────────────────────────────────

NOISE_LEVELS = {
    "clean": None,   # no noise
    "low":   20,     # quiet office (20 dB SNR)
    "mid":   10,     # normal office (10 dB SNR)
    "high":   5,     # noisy corridor (5 dB SNR)
}


# ── TTS ─────────────────────────────────────────────────────────────────────

LANG_VOICE_FALLBACKS = {
    "ja": "ja-JP-NanamiNeural",
    "en": "en-US-JennyNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
}


def _detect_lang(text: str) -> str:
    """Simple language detection based on character ranges."""
    for ch in text:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
            return "ja"  # hiragana/katakana
    # Check if mostly ASCII (English)
    ascii_count = sum(1 for c in text if ord(c) < 128)
    if ascii_count > len(text) * 0.7:
        return "en"
    return "zh"


async def tts_to_pcm(text: str, voice: str, cache_dir: Path) -> Path:
    """Synthesize text to 16kHz mono PCM via edge-tts + ffmpeg."""
    # Auto-select voice for non-matching languages
    lang = _detect_lang(text)
    effective_voice = voice
    if lang == "ja" and "ja-JP" not in voice:
        effective_voice = LANG_VOICE_FALLBACKS["ja"]
    elif lang == "en" and "en-" not in voice:
        effective_voice = LANG_VOICE_FALLBACKS["en"]

    key = hashlib.md5(f"{effective_voice}:{text}".encode()).hexdigest()[:12]
    pcm_path = cache_dir / f"{key}_clean.pcm"
    if pcm_path.exists() and pcm_path.stat().st_size > 0:
        return pcm_path

    mp3_path = cache_dir / f"{key}.mp3"
    try:
        communicate = edge_tts.Communicate(text, effective_voice)
        await communicate.save(str(mp3_path))
    except Exception:
        # Try language-specific fallback
        fallback = LANG_VOICE_FALLBACKS.get(lang, "zh-CN-XiaoxiaoNeural")
        try:
            communicate = edge_tts.Communicate(text, fallback)
            await communicate.save(str(mp3_path))
        except Exception as e:
            raise RuntimeError(f"TTS failed for '{text[:50]}': {e}")

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path),
         "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
         str(pcm_path)],
        capture_output=True, check=True,
    )
    mp3_path.unlink(missing_ok=True)
    return pcm_path


def mix_noise(clean_pcm: Path, noise_level: str, cache_dir: Path) -> Path:
    """Mix synthetic noise into clean PCM at given SNR."""
    snr_db = NOISE_LEVELS.get(noise_level)
    if snr_db is None:
        return clean_pcm

    noisy_path = clean_pcm.with_suffix(f".{noise_level}.pcm")
    if noisy_path.exists() and noisy_path.stat().st_size > 0:
        return noisy_path

    file_size = clean_pcm.stat().st_size
    duration = file_size / (16000 * 2)
    noise_vol = math.pow(10, -snr_db / 20)

    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", str(clean_pcm),
         "-filter_complex",
         f"anoisesrc=d={duration}:c=white:r=16000:a=0.3[w];"
         f"anoisesrc=d={duration}:c=pink:r=16000:a=0.5[p];"
         f"anoisesrc=d={duration}:c=brown:r=16000:a=0.2[b];"
         f"[w][p][b]amix=inputs=3:duration=shortest[noise];"
         f"[noise]volume={noise_vol}[nv];"
         f"[0:a][nv]amix=inputs=2:duration=first:dropout_transition=0[out]",
         "-map", "[out]",
         "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
         str(noisy_path)],
        capture_output=True, check=True,
    )
    return noisy_path


# ── Gemini Live API ─────────────────────────────────────────────────────────

async def _drain_for_tool_call(session, result: dict):
    """After turn_complete, keep receiving to catch tool_call from thinking models."""
    async for chunk in session.receive():
        if chunk.tool_call:
            for fc in chunk.tool_call.function_calls:
                result["function_call"] = {
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                    "id": getattr(fc, "id", None),
                }
            return
        elif chunk.server_content and chunk.server_content.turn_complete:
            return


async def call_voice_api(
    client: genai.Client,
    system_prompt: str,
    pcm_bytes: bytes,
    tools: list[dict],
    model_name: str,
    max_retries: int = 3,
) -> dict:
    """Send audio to Gemini Live API, return FC result."""
    config = {
        "tools": tools,
        "system_instruction": system_prompt,
        "response_modalities": ["AUDIO"],
    }

    for attempt in range(max_retries):
        try:
            result = {"function_call": None, "text_response": None, "error": None}

            async with client.aio.live.connect(
                model=model_name, config=config
            ) as session:
                # Stream audio in 1-second chunks
                chunk_size = 16000 * 2  # 1 sec of 16kHz 16-bit mono
                for offset in range(0, len(pcm_bytes), chunk_size):
                    chunk = pcm_bytes[offset:offset + chunk_size]
                    await session.send_realtime_input(
                        audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                    )
                    await asyncio.sleep(0.05)

                # Signal end of audio
                await session.send_realtime_input(audio_stream_end=True)

                # Receive response — only care about tool_call
                async for chunk in session.receive():
                    if chunk.tool_call:
                        for fc in chunk.tool_call.function_calls:
                            result["function_call"] = {
                                "name": fc.name,
                                "args": dict(fc.args) if fc.args else {},
                                "id": getattr(fc, "id", None),
                            }
                        break
                    elif chunk.server_content:
                        if chunk.server_content.model_turn:
                            for part in chunk.server_content.model_turn.parts:
                                if hasattr(part, "text") and part.text:
                                    if result["text_response"] is None:
                                        result["text_response"] = ""
                                    result["text_response"] += part.text
                        if chunk.server_content.turn_complete:
                            # Thinking models may emit tool_call after turn_complete
                            try:
                                await asyncio.wait_for(
                                    _drain_for_tool_call(session, result),
                                    timeout=5.0,
                                )
                            except asyncio.TimeoutError:
                                pass
                            break

            return result

        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** (attempt + 1))
            else:
                return {"function_call": None, "text_response": None, "error": str(e)}


# ── Classification ──────────────────────────────────────────────────────────

def classify(case: dict, fc_result: dict | None) -> str:
    """Classify result as TP/TN/FP/FN."""
    expected = case["expected"]
    expected_fn = expected.get("function")
    should_clarify = expected.get("should_clarify", False)
    actual_fn = fc_result["name"] if fc_result else None

    if should_clarify or expected_fn is None:
        # No FC should be triggered (clarify or pure chat)
        return "TN" if actual_fn is None else "FP"
    else:
        # A specific FC should be triggered
        if actual_fn is None:
            return "FN"
        elif actual_fn == expected_fn and params_match(expected, fc_result):
            return "TP"
        else:
            return "FP"


def params_match(expected: dict, fc_result: dict) -> bool:
    expected_params = expected.get("params_contain", {})
    if not expected_params:
        return True
    # patrol_all and inspect_location: implementation incomplete, skip param check
    fn_name = fc_result.get("name", "")
    if fn_name in ("patrol_all", "inspect_location"):
        return True
    actual_args = fc_result.get("args", {})
    for key, want in expected_params.items():
        got = actual_args.get(key)
        if key in ("prompt", "message"):
            if not got or not isinstance(got, str) or not got.strip():
                return False
        elif key == "angle":
            if got is None:
                return False
            try:
                if (float(want) > 0) != (float(got) > 0):
                    return False
            except (TypeError, ValueError):
                return False
        elif isinstance(want, list):
            if not (isinstance(got, list) and all(item in got for item in want)):
                return False
        elif got != want:
            return False
    return True


def compute_metrics(classifications: list[str]) -> dict:
    tp = classifications.count("TP")
    tn = classifications.count("TN")
    fp = classifications.count("FP")
    fn = classifications.count("FN")

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    accuracy = (tp + tn) / len(classifications) if classifications else 0

    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }


# ── Eval Runner ─────────────────────────────────────────────────────────────

def _inject_location_enum(tools: list[dict], case: dict) -> list[dict]:
    """Populate location_name enum from case context."""
    ctx = case.get("context", {})
    locs_str = ctx.get("available_locations", "") if ctx else ""
    if not locs_str:
        return tools

    # Parse "廁所1 (1.9m), 辦公室101 (0.4m)" → ["廁所1", "辦公室101"]
    names = []
    for part in locs_str.split(","):
        part = part.strip()
        paren = part.find("(")
        name = part[:paren].strip() if paren > 0 else part
        if name:
            names.append(name)

    if not names:
        return tools

    import copy
    tools = copy.deepcopy(tools)
    for tool in tools:
        for fd in tool.get("function_declarations", []):
            props = fd.get("parameters", {}).get("properties", {})
            if "location_name" in props and "enum" in props["location_name"]:
                props["location_name"]["enum"] = names
    return tools


def _inject_locations_into_prompt(system_prompt: str, locs_str: str) -> str:
    """Inject available locations into system prompt."""
    if not locs_str:
        return system_prompt
    section = f"\n\n[Available Locations (sorted by distance)]\n{locs_str}"
    if "{{AVAILABLE_LOCATIONS}}" in system_prompt:
        return system_prompt.replace("{{AVAILABLE_LOCATIONS}}", section)
    return system_prompt + section


async def _eval_one(
    client: genai.Client,
    case: dict,
    system_prompt: str,
    tools: list[dict],
    model_name: str,
    voice: str,
    noise_level: str,
    cache_dir: Path,
    repeat_idx: int,
) -> dict:
    """Evaluate a single case with given voice/noise/repeat combination."""
    text = case["input"]
    ctx = case.get("context", {}) or {}
    locs_str = ctx.get("available_locations", "")

    # Inject locations into system prompt (not user message)
    case_prompt = _inject_locations_into_prompt(system_prompt, locs_str)
    tools = _inject_location_enum(tools, case)

    # TTS → PCM
    try:
        clean_pcm = await tts_to_pcm(text, voice, cache_dir)
    except RuntimeError as e:
        return {
            "case_id": case.get("id", "?"),
            "category": case.get("category", ""),
            "classification": "ERR",
            "noise_level": noise_level,
            "voice": voice,
            "repeat": repeat_idx,
            "error": str(e),
        }

    # Mix noise
    pcm_path = mix_noise(clean_pcm, noise_level, cache_dir)
    pcm_bytes = pcm_path.read_bytes()

    # Call API (locations are in system prompt, no separate context)
    response = await call_voice_api(
        client, case_prompt, pcm_bytes, tools, model_name
    )

    if response.get("error"):
        return {
            "case_id": case.get("id", "?"),
            "category": case.get("category", ""),
            "classification": "ERR",
            "noise_level": noise_level,
            "voice": voice,
            "repeat": repeat_idx,
            "error": response["error"],
        }

    fc_result = response.get("function_call")
    cls = classify(case, fc_result)

    expected = case["expected"]
    return {
        "case_id": case.get("id", "?"),
        "category": case.get("category", ""),
        "classification": cls,
        "noise_level": noise_level,
        "voice": voice,
        "repeat": repeat_idx,
        "expected_fn": expected.get("function"),
        "should_clarify": expected.get("should_clarify", False),
        "actual_fn": fc_result["name"] if fc_result else None,
        "actual_args": fc_result["args"] if fc_result else None,
        "params_correct": params_match(expected, fc_result) if fc_result else False,
    }


async def _recv_model_response(session, timeout: float = 30.0) -> dict:
    """Receive model response from Live API session. Returns {function_call, text_response, error}."""
    result = {"function_call": None, "text_response": None, "error": None}

    async def _receive_loop():
        async for chunk in session.receive():
            if chunk.tool_call:
                for fc in chunk.tool_call.function_calls:
                    result["function_call"] = {
                        "name": fc.name,
                        "args": dict(fc.args) if fc.args else {},
                        "id": getattr(fc, "id", None),
                    }
                return
            elif chunk.server_content:
                if chunk.server_content.model_turn:
                    for part in chunk.server_content.model_turn.parts:
                        if hasattr(part, "text") and part.text:
                            if result["text_response"] is None:
                                result["text_response"] = ""
                            result["text_response"] += part.text
                if chunk.server_content.turn_complete:
                    # Thinking models may emit tool_call after turn_complete
                    try:
                        await asyncio.wait_for(
                            _drain_for_tool_call(session, result),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        pass
                    return

    try:
        await asyncio.wait_for(_receive_loop(), timeout=timeout)
    except asyncio.TimeoutError:
        result["error"] = "timeout waiting for model response"
    return result


async def _send_audio_turn(session, pcm_bytes: bytes):
    """Stream audio to Live API session in 1-second chunks."""
    chunk_size = 16000 * 2  # 1 sec of 16kHz 16-bit mono
    for offset in range(0, len(pcm_bytes), chunk_size):
        chunk = pcm_bytes[offset:offset + chunk_size]
        await session.send_realtime_input(
            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
        )
        await asyncio.sleep(0.05)
    await session.send_realtime_input(audio_stream_end=True)


# Fake FC results for tool_response so session can continue
FAKE_FC_RESULTS = {
    "guide_to_booth": {"ok": True, "message": "已帶領前往目的地"},
    "capture_camera": {"ok": True, "description": "照片已拍攝"},
    "inspect_location": {"ok": True, "analysis": "檢查完成，一切正常"},
    "patrol_all": {"ok": True, "analysis": "巡邏完成"},
    "rotate": {"ok": True, "message": "已旋轉"},
    "notify_staff": {"ok": True, "message": "已通知工作人員"},
    "deliver_drink": {"ok": True, "message": "飲料已送達"},
    "return_drink": {"ok": True, "message": "飲料已回收"},
}


async def _eval_multi_turn(
    client: genai.Client,
    case: dict,
    system_prompt: str,
    tools: list[dict],
    model_name: str,
    voice: str,
    noise_level: str,
    cache_dir: Path,
    repeat_idx: int,
    max_retries: int = 3,
) -> list[dict]:
    """Evaluate a multi-turn case within a single Live API session.
    Returns a list of per-turn result dicts."""
    turns = case["turns"]
    ctx = case.get("context", {}) or {}
    locs_str = ctx.get("available_locations", "")
    case_prompt = _inject_locations_into_prompt(system_prompt, locs_str)
    case_tools = _inject_location_enum(tools, case)
    case_id = case.get("id", "?")
    category = case.get("category", "")

    config = {
        "tools": case_tools,
        "system_instruction": case_prompt,
        "response_modalities": ["AUDIO"],
    }

    for attempt in range(max_retries):
        try:
            turn_results = []
            async with client.aio.live.connect(
                model=model_name, config=config
            ) as session:
                turn_idx = 0
                while turn_idx < len(turns):
                    turn = turns[turn_idx]

                    if turn["role"] == "user":
                        # TTS → PCM → send audio
                        try:
                            clean_pcm = await tts_to_pcm(turn["content"], voice, cache_dir)
                        except RuntimeError as e:
                            # TTS failed — mark remaining turns as ERR
                            for j in range(turn_idx, len(turns)):
                                if turns[j]["role"] == "model":
                                    turn_results.append({
                                        "case_id": case_id,
                                        "turn_idx": j,
                                        "category": category,
                                        "classification": "ERR",
                                        "noise_level": noise_level,
                                        "voice": voice,
                                        "repeat": repeat_idx,
                                        "error": f"TTS failed: {e}",
                                    })
                            return turn_results

                        pcm_path = mix_noise(clean_pcm, noise_level, cache_dir)
                        pcm_bytes = pcm_path.read_bytes()
                        await _send_audio_turn(session, pcm_bytes)
                        turn_idx += 1

                    elif turn["role"] == "model":
                        # Receive model response and classify
                        expected = turn.get("expected", {})
                        response = await _recv_model_response(session, timeout=30.0)

                        if response.get("error"):
                            turn_results.append({
                                "case_id": case_id,
                                "turn_idx": turn_idx,
                                "category": category,
                                "classification": "ERR",
                                "noise_level": noise_level,
                                "voice": voice,
                                "repeat": repeat_idx,
                                "error": response["error"],
                            })
                            turn_idx += 1
                            continue

                        fc_result = response.get("function_call")
                        expected_fn = expected.get("function")
                        should_clarify = expected.get("should_clarify", False)
                        actual_fn = fc_result["name"] if fc_result else None

                        if should_clarify or expected_fn is None:
                            cls = "TN" if actual_fn is None else "FP"
                        else:
                            if actual_fn is None:
                                cls = "FN"
                            elif actual_fn == expected_fn and params_match(expected, fc_result):
                                cls = "TP"
                            else:
                                cls = "FP"

                        turn_results.append({
                            "case_id": case_id,
                            "turn_idx": turn_idx,
                            "category": category,
                            "classification": cls,
                            "noise_level": noise_level,
                            "voice": voice,
                            "repeat": repeat_idx,
                            "expected_fn": expected_fn,
                            "should_clarify": should_clarify,
                            "actual_fn": actual_fn,
                            "actual_args": fc_result["args"] if fc_result else None,
                            "params_correct": params_match(expected, fc_result) if fc_result else False,
                        })

                        # If model returned FC, send tool_response so session continues
                        if fc_result:
                            fake_result = FAKE_FC_RESULTS.get(
                                fc_result["name"],
                                {"ok": True, "message": "完成"}
                            )
                            tool_resp = types.FunctionResponse(
                                name=fc_result["name"],
                                response=fake_result,
                            )
                            if fc_result.get("id"):
                                tool_resp.id = fc_result["id"]
                            await session.send_tool_response(
                                function_responses=[tool_resp]
                            )
                            # Receive model's follow-up response after tool result
                            await _recv_model_response(session, timeout=15.0)

                        turn_idx += 1
                    else:
                        turn_idx += 1

            return turn_results

        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** (attempt + 1))
            else:
                # Return ERR for all model turns
                return [{
                    "case_id": case_id,
                    "turn_idx": i,
                    "category": category,
                    "classification": "ERR",
                    "noise_level": noise_level,
                    "voice": voice,
                    "repeat": repeat_idx,
                    "error": str(e),
                } for i, t in enumerate(turns) if t["role"] == "model"]


async def run_eval(
    eval_set: dict,
    system_prompt: str,
    fc_schema: list,
    model_name: str,
    voices: list[str],
    noise_levels: list[str],
    repeats: int,
    cache_dir: Path,
    workers: int,
    skip_langs: set[str] | None = None,
) -> list[dict]:
    """Run voice eval across all combinations (single-turn + multi-turn)."""
    client = genai.Client()
    tools = [{"function_declarations": fc_schema}]

    all_cases = eval_set.get("cases", [])
    st_cases = [c for c in all_cases if "turns" not in c]
    mt_cases = [c for c in all_cases if "turns" in c]

    # Filter by language
    if skip_langs:
        def _skip(c):
            return any(c.get("id", "").endswith(f"-{lang}") or
                      c.get("id", "").endswith(f"-{lang}-1") or
                      c.get("id", "").endswith(f"-{lang}-2") or
                      c.get("id", "").endswith(f"-{lang}-3")
                      for lang in skip_langs)
        before_st, before_mt = len(st_cases), len(mt_cases)
        st_cases = [c for c in st_cases if not _skip(c)]
        mt_cases = [c for c in mt_cases if not _skip(c)]
        skipped = (before_st - len(st_cases)) + (before_mt - len(mt_cases))
        if skipped:
            print(f"  Skipping {skipped} cases for languages: {skip_langs}")

    print(f"  Single-turn: {len(st_cases)} cases")
    print(f"  Multi-turn:  {len(mt_cases)} cases")

    # Build single-turn combos
    st_combos = []
    for case in st_cases:
        for voice in voices:
            for noise in noise_levels:
                for rep in range(repeats):
                    st_combos.append((case, voice, noise, rep))

    # Build multi-turn combos
    mt_combos = []
    for case in mt_cases:
        for voice in voices:
            for noise in noise_levels:
                for rep in range(repeats):
                    mt_combos.append((case, voice, noise, rep))

    total_combos = len(st_combos) + len(mt_combos)
    print(f"  Total eval combos: {total_combos} ({len(st_combos)} ST + {len(mt_combos)} MT)")

    sem = asyncio.Semaphore(workers)
    all_results = []
    done_count = 0
    lock = asyncio.Lock()

    async def run_single(case, voice, noise, rep):
        nonlocal done_count
        async with sem:
            scored = await _eval_one(
                client, case, system_prompt, tools, model_name,
                voice, noise, cache_dir, rep,
            )
            async with lock:
                all_results.append(scored)
                done_count += 1
                cls = scored["classification"]
                mark = {"TP": "✓", "TN": "✓", "FP": "✗", "FN": "✗", "ERR": "ERR"}[cls]
                label = f"{scored['case_id']}"
                if noise != "clean":
                    label += f"/{noise}"
                print(f"  [{done_count}/{total_combos}] {label}... {cls} {mark}", flush=True)
            await asyncio.sleep(0.5)

    async def run_multi(case, voice, noise, rep):
        nonlocal done_count
        async with sem:
            turn_results = await _eval_multi_turn(
                client, case, system_prompt, tools, model_name,
                voice, noise, cache_dir, rep,
            )
            async with lock:
                all_results.extend(turn_results)
                done_count += 1
                # Summarize: count TP/TN/FP/FN/ERR for this case
                cls_counts = {}
                for r in turn_results:
                    cls_counts[r["classification"]] = cls_counts.get(r["classification"], 0) + 1
                summary_str = " ".join(f"{k}={v}" for k, v in sorted(cls_counts.items()))
                has_err = any(r["classification"] in ("FP", "FN", "ERR") for r in turn_results)
                mark = "✗" if has_err else "✓"
                print(f"  [{done_count}/{total_combos}] {case['id']} (MT {len(turn_results)}t)... {summary_str} {mark}", flush=True)
            await asyncio.sleep(0.5)

    tasks = []
    for combo in st_combos:
        tasks.append(run_single(*combo))
    for combo in mt_combos:
        tasks.append(run_multi(*combo))

    await asyncio.gather(*tasks)

    return all_results


# ── Summary & Output ────────────────────────────────────────────────────────

def compute_summary(results: list[dict]) -> dict:
    valid = [r for r in results if r["classification"] != "ERR"]
    errors = len(results) - len(valid)
    cls_list = [r["classification"] for r in valid]
    overall = compute_metrics(cls_list)
    overall["errors"] = errors

    # By noise level
    by_noise = {}
    for nl in sorted(set(r["noise_level"] for r in results)):
        nl_cls = [r["classification"] for r in valid if r["noise_level"] == nl]
        if nl_cls:
            by_noise[nl] = compute_metrics(nl_cls)

    # By category
    by_category = {}
    for cat in sorted(set(r["category"] for r in results)):
        cat_cls = [r["classification"] for r in valid if r["category"] == cat]
        if cat_cls:
            by_category[cat] = compute_metrics(cat_cls)

    return {
        "total": len(results),
        "metrics": overall,
        "by_noise_level": by_noise,
        "by_category": by_category,
    }


def compute_stability(results: list[dict]) -> list[dict]:
    """Compute per-case stability across voices/noise/repeats."""
    from collections import defaultdict
    by_case = defaultdict(list)
    for r in results:
        if r["classification"] != "ERR":
            by_case[r["case_id"]].append(r)

    stability = []
    for cid, runs in sorted(by_case.items()):
        cls_list = [r["classification"] for r in runs]
        tp_count = sum(1 for c in cls_list if c in ("TP", "TN"))
        error_cls = [r for r in runs if r["classification"] in ("FP", "FN")]

        # Find noise level where errors start
        degrades_at = None
        noise_order = ["clean", "low", "mid", "high"]
        for nl in noise_order:
            nl_cls = [r["classification"] for r in runs if r["noise_level"] == nl]
            if any(c in ("FP", "FN") for c in nl_cls):
                degrades_at = nl
                break

        stability.append({
            "case_id": cid,
            "total_runs": len(runs),
            "classifications": cls_list,
            "correct_rate": round(tp_count / len(runs), 3) if runs else 0,
            "error_rate": round(len(error_cls) / len(runs), 3) if runs else 0,
            "is_stable": len(error_cls) == 0,
            "degrades_at": degrades_at,
        })
    return stability


def print_summary(summary: dict, tag: str):
    m = summary["metrics"]
    w = 60
    print(f"\n{'='*w}")
    print(f"  {tag} (Voice E2E)")
    print(f"{'='*w}")
    print(f"\n  Overall:  Accuracy={m['accuracy']:.1%}  Precision={m['precision']:.1%}  Recall={m['recall']:.1%}  F1={m['f1']:.3f}")
    if m["errors"]:
        print(f"  Errors: {m['errors']}")

    print(f"\n  Confusion Matrix:")
    print(f"  {'':14s} Triggered    Not-triggered")
    print(f"  {'Should':14s}  TP={m['tp']:<8d}  FN={m['fn']}")
    shouldnt = "Shouldn't"
    print(f"  {shouldnt:14s}  FP={m['fp']:<8d}  TN={m['tn']}")

    if summary["by_noise_level"]:
        print(f"\n  By Noise Level:")
        for nl, nm in summary["by_noise_level"].items():
            print(f"    {nl:8s} Acc={nm['accuracy']:.0%}  P={nm['precision']:.2f}  R={nm['recall']:.2f}  F1={nm['f1']:.3f}")

    print(f"\n  By Category:")
    for cat, cm in summary["by_category"].items():
        print(f"    {cat:30s} TP={cm['tp']}  FP={cm['fp']}  FN={cm['fn']}  TN={cm['tn']}  F1={cm['f1']:.3f}")
    print()


def print_errors(results: list[dict]):
    errors = [r for r in results if r["classification"] in ("FP", "FN")]
    if not errors:
        return
    print("  Errors (FP + FN):")
    for r in errors:
        turn_str = f"/t{r['turn_idx']}" if "turn_idx" in r else ""
        if r["classification"] == "FP":
            print(f"    ✗ FP {r['case_id']}{turn_str} ({r['noise_level']}): "
                  f"want={'clarify' if r.get('should_clarify') else r.get('expected_fn')} "
                  f"got={r.get('actual_fn')}")
        else:
            print(f"    ✗ FN {r['case_id']}{turn_str} ({r['noise_level']}): "
                  f"want={r.get('expected_fn')} got=no_fc")
    print()


def save_results(results: list[dict], summary: dict, stability: list[dict],
                 tag: str, model: str, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    data = {
        "tag": tag,
        "model": model,
        "api_mode": "voice",
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "stability": [s for s in stability if not s["is_stable"]],
        "results": results,
    }
    with open(output / "results.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Saved to {output}/")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Voice E2E FC eval for Gemini Live API")
    parser.add_argument("--eval-set", required=True)
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--fc-schema", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tag", default="voice-run")
    parser.add_argument("--model", default="gemini-3.1-flash-live-preview")
    parser.add_argument("--voices", default="zh-TW-HsiaoChenNeural",
                        help="Comma-separated TTS voices")
    parser.add_argument("--noise", default="clean",
                        help="Comma-separated noise levels: clean,low,mid,high")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--audio-cache", default=".audio_cache",
                        help="Directory for cached TTS audio")
    parser.add_argument("--skip-lang", default="ja",
                        help="Comma-separated language suffixes to skip (default: ja)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    # Parse lists
    voices = [v.strip() for v in args.voices.split(",")]
    noise_levels = [n.strip() for n in args.noise.split(",")]
    for nl in noise_levels:
        if nl not in NOISE_LEVELS:
            print(f"ERROR: Unknown noise level '{nl}'. Choose from: {list(NOISE_LEVELS.keys())}")
            sys.exit(1)

    # Load inputs
    print(f"Loading eval set: {args.eval_set}")
    with open(args.eval_set, "r", encoding="utf-8") as f:
        eval_set = json.load(f)
    if isinstance(eval_set, list):
        eval_set = {"cases": eval_set}

    print(f"Loading system prompt: {args.system_prompt}")
    with open(args.system_prompt, "r", encoding="utf-8") as f:
        system_prompt = f.read().strip()

    print(f"Loading FC schema: {args.fc_schema}")
    with open(args.fc_schema, "r", encoding="utf-8") as f:
        fc_schema = json.load(f)
    if isinstance(fc_schema, dict):
        fc_schema = fc_schema.get("functions", fc_schema.get("tools", []))

    cache_dir = Path(args.audio_cache)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nVoice E2E eval (model={args.model})")
    print(f"  Voices: {voices}")
    print(f"  Noise:  {noise_levels}")
    print(f"  Repeats: {args.repeats}")
    print(f"  Workers: {args.workers}\n")

    skip_langs = set(l.strip() for l in args.skip_lang.split(",")) if args.skip_lang else None

    results = asyncio.run(run_eval(
        eval_set, system_prompt, fc_schema, args.model,
        voices, noise_levels, args.repeats,
        cache_dir, args.workers, skip_langs,
    ))

    summary = compute_summary(results)
    stability = compute_stability(results)
    print_summary(summary, args.tag)
    print_errors(results)

    save_results(results, summary, stability, args.tag, args.model, Path(args.output))


if __name__ == "__main__":
    main()
