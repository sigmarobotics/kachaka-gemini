#!/usr/bin/env python3
"""
run_fc_eval_live.py — Run Gemini Live API function calling evaluation.

Tests FC routing through Gemini's Live API using text-mode send_client_content,
which exercises the same FC decision pipeline as voice sessions but with
deterministic text input for reproducible testing.

Usage:
    python scripts/run_fc_eval_live.py \
        --eval-set evals/eval_set.json \
        --system-prompt current_system_prompt.txt \
        --fc-schema fc_schema.json \
        --output results/live-baseline/ \
        --tag live-baseline \
        --workers 10

Requires:
    - GEMINI_API_KEY environment variable
    - pip install google-genai
"""

import argparse
import asyncio
import json
import os
import sys
import copy
from pathlib import Path
from datetime import datetime

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("ERROR: google-genai not installed.")
    print("Run: pip install google-genai")
    sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def save_json(data, path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Live API Interface ───────────────────────────────────────────────────────

async def _drain_for_tool_call(session, result: dict):
    """After turn_complete, keep receiving to catch tool_call from thinking models."""
    async for chunk in session.receive():
        if chunk.tool_call:
            for fc in chunk.tool_call.function_calls:
                result["function_call"] = {
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                }
            return
        elif chunk.server_content and chunk.server_content.turn_complete:
            return

async def call_live_api(
    client: genai.Client,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    model_name: str,
    max_retries: int = 3,
) -> dict:
    """Call Gemini Live API single-turn with text input."""
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
                await session.send_client_content(
                    turns={"parts": [{"text": user_message}]},
                    turn_complete=True,
                )

                async def _receive_response():
                    async for chunk in session.receive():
                        if chunk.tool_call:
                            for fc in chunk.tool_call.function_calls:
                                result["function_call"] = {
                                    "name": fc.name,
                                    "args": dict(fc.args) if fc.args else {},
                                }
                            return
                        elif chunk.server_content:
                            if chunk.server_content.model_turn:
                                for part in chunk.server_content.model_turn.parts:
                                    if hasattr(part, "text") and part.text:
                                        if result["text_response"] is None:
                                            result["text_response"] = ""
                                        result["text_response"] += part.text
                            elif chunk.text is not None:
                                if result["text_response"] is None:
                                    result["text_response"] = ""
                                result["text_response"] += chunk.text
                            if chunk.server_content.turn_complete:
                                try:
                                    await asyncio.wait_for(
                                        _drain_for_tool_call(session, result),
                                        timeout=5.0,
                                    )
                                except asyncio.TimeoutError:
                                    pass
                                return

                try:
                    await asyncio.wait_for(_receive_response(), timeout=30.0)
                except asyncio.TimeoutError:
                    result["error"] = "receive timeout (30s)"

            return result

        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                await asyncio.sleep(wait)
            else:
                return {"function_call": None, "text_response": None, "error": str(e)}


async def call_live_api_multiturn(
    client: genai.Client,
    system_prompt: str,
    turns: list[dict],
    tools: list[dict],
    model_name: str,
) -> list[dict]:
    """
    Run a multi-turn conversation through Live API.
    Sends each user turn, collects model response.
    Skips 'model' turns (those are just scoring checkpoints in our eval format).
    """
    config = {
        "tools": tools,
        "system_instruction": system_prompt,
        "response_modalities": ["AUDIO"],
    }

    responses = []
    try:
        async with client.aio.live.connect(
            model=model_name, config=config
        ) as session:
            for turn in turns:
                if turn["role"] == "user":
                    text = turn.get("content") or turn.get("text", "")
                    await session.send_client_content(
                        turns={"parts": [{"text": text}]},
                        turn_complete=True,
                    )

                    # Collect response
                    turn_result = {"function_call": None, "text_response": None, "error": None}

                    async def _recv_turn():
                        async for chunk in session.receive():
                            if chunk.tool_call:
                                for fc in chunk.tool_call.function_calls:
                                    turn_result["function_call"] = {
                                        "name": fc.name,
                                        "args": dict(fc.args) if fc.args else {},
                                    }
                                return
                            elif chunk.server_content:
                                if chunk.server_content.model_turn:
                                    for part in chunk.server_content.model_turn.parts:
                                        if hasattr(part, "text") and part.text:
                                            if turn_result["text_response"] is None:
                                                turn_result["text_response"] = ""
                                            turn_result["text_response"] += part.text
                                elif chunk.text is not None:
                                    if turn_result["text_response"] is None:
                                        turn_result["text_response"] = ""
                                    turn_result["text_response"] += chunk.text
                                if chunk.server_content.turn_complete:
                                    try:
                                        await asyncio.wait_for(
                                            _drain_for_tool_call(session, turn_result),
                                            timeout=5.0,
                                        )
                                    except asyncio.TimeoutError:
                                        pass
                                    return

                    try:
                        await asyncio.wait_for(_recv_turn(), timeout=30.0)
                    except asyncio.TimeoutError:
                        turn_result["error"] = "receive timeout (30s)"

                    responses.append(turn_result)

                elif turn["role"] == "model":
                    # Scoring checkpoint — skip (handled by scorer)
                    pass

    except Exception as e:
        responses.append({
            "function_call": None, "text_response": None, "error": str(e),
        })

    return responses


# ── Scoring ──────────────────────────────────────────────────────────────────

CLARIFY_SIGNALS = [
    "?", "？", "哪一", "哪個", "請問", "確認", "請告訴",
    "which", "could you specify", "do you mean", "clarify", "please tell",
]


def score_case(case: dict, response: dict) -> dict:
    """Score a single response against expected behavior."""
    expected = case["expected"]
    scores = {}
    details = {}

    actual_fn = (response["function_call"]["name"]
                 if response.get("function_call") else None)
    should_clarify = expected.get("should_clarify", False)
    expected_fn = expected.get("function")

    if should_clarify:
        scores["function_match"] = actual_fn is None
        is_clarifying = (
            response.get("text_response")
            and any(s in response["text_response"].lower() for s in CLARIFY_SIGNALS)
        )
        scores["clarify_match"] = actual_fn is None and is_clarifying
        details["expected"] = "should clarify"
        details["actual"] = (
            "clarified" if scores["clarify_match"]
            else f"called {actual_fn}" if actual_fn
            else "text without clarification"
        )
    else:
        scores["function_match"] = actual_fn == expected_fn
        scores["clarify_match"] = True
        details["expected_fn"] = expected_fn
        details["actual_fn"] = actual_fn

    if scores["function_match"] and expected_fn and response.get("function_call"):
        actual_args = response["function_call"]["args"]
        expected_params = expected.get("params_contain", {})
        param_checks = {}
        for key, want in expected_params.items():
            got = actual_args.get(key)
            if isinstance(want, list):
                param_checks[key] = isinstance(got, list) and all(
                    item in got for item in want
                )
            else:
                param_checks[key] = got == want
        scores["param_match"] = all(param_checks.values()) if param_checks else True
        details["param_checks"] = param_checks
        details["actual_args"] = actual_args
    else:
        scores["param_match"] = scores["function_match"]

    scores["overall"] = all(scores.values())

    return {
        "case_id": case["id"] if "id" in case else case.get("case_id", "?"),
        "category": case.get("category", "uncategorized"),
        "difficulty": case.get("difficulty", "unknown"),
        "input": case.get("input", ""),
        "scores": scores,
        "details": details,
        "response": {
            "function_called": actual_fn,
            "args": response["function_call"]["args"] if response.get("function_call") else None,
            "text": (response.get("text_response") or "")[:500],
        },
    }


def score_multiturn_case(case: dict, responses: list[dict]) -> dict:
    """Score a multi-turn conversation against expected per-turn behavior."""
    turns = case["turns"]
    model_turns = [t for t in turns if t["role"] == "model"]
    all_pass = True
    details = {"turns": []}

    for idx, (model_turn, response) in enumerate(zip(model_turns, responses)):
        turn_detail = {"turn": idx}

        if response.get("error"):
            turn_detail["error"] = response["error"]
            all_pass = False
            details["turns"].append(turn_detail)
            continue

        expected = model_turn.get("expected", {})
        should_clarify = expected.get("should_clarify", False)
        expected_fn = expected.get("function")
        actual_fn = (response["function_call"]["name"]
                     if response.get("function_call") else None)

        if should_clarify:
            is_clarifying = (
                response.get("text_response")
                and any(s in response["text_response"].lower() for s in CLARIFY_SIGNALS)
            )
            turn_pass = actual_fn is None and is_clarifying
            turn_detail["expected"] = "clarify"
            turn_detail["actual"] = (
                "clarified" if turn_pass
                else f"called {actual_fn}" if actual_fn
                else "text (no clarify signal)"
            )
        elif expected_fn:
            turn_pass = actual_fn == expected_fn
            if turn_pass and expected.get("params_contain") and response.get("function_call"):
                actual_args = response["function_call"]["args"]
                for key, want in expected["params_contain"].items():
                    if actual_args.get(key) != want:
                        turn_pass = False
                        break
            turn_detail["expected"] = f"{expected_fn}({expected.get('params_contain', {})})"
            turn_detail["actual"] = f"{actual_fn}({response['function_call']['args'] if response.get('function_call') else {}})"
        else:
            turn_pass = actual_fn is None
            turn_detail["expected"] = "no FC"
            turn_detail["actual"] = f"called {actual_fn}" if actual_fn else "text"

        turn_detail["pass"] = turn_pass
        if not turn_pass:
            all_pass = False
        details["turns"].append(turn_detail)

    scores = {
        "overall": all_pass,
        "function_match": all_pass,
        "param_match": all_pass,
        "clarify_match": all_pass,
    }

    user_inputs = [t.get("content", t.get("text", "")) for t in turns if t["role"] == "user"]

    return {
        "case_id": case.get("id", "?"),
        "category": case.get("category", "uncategorized"),
        "difficulty": case.get("difficulty", "unknown"),
        "input": " → ".join(user_inputs),
        "scores": scores,
        "details": details,
        "response": {
            "function_called": responses[-1]["function_call"]["name"] if responses and responses[-1].get("function_call") else None,
            "args": responses[-1]["function_call"]["args"] if responses and responses[-1].get("function_call") else None,
            "text": (responses[-1].get("text_response") or "")[:500] if responses else "",
        },
    }


# ── Summary ──────────────────────────────────────────────────────────────────

def compute_summary(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["scores"]["overall"])

    by_category = {}
    for r in results:
        cat = r["category"]
        by_category.setdefault(cat, {"total": 0, "passed": 0})
        by_category[cat]["total"] += 1
        if r["scores"]["overall"]:
            by_category[cat]["passed"] += 1
    for v in by_category.values():
        v["pass_rate"] = round(v["passed"] / v["total"] * 100, 1) if v["total"] else 0

    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "by_category": by_category,
        "api_mode": "live",
    }


def print_summary(summary: dict, tag: str):
    w = 60
    print(f"\n{'='*w}")
    print(f"  {tag} (Live API):  {summary['passed']}/{summary['total']}  ({summary['pass_rate']}%)")
    print(f"{'='*w}")

    print("\n  By Category:")
    for cat, d in sorted(summary["by_category"].items()):
        bar = "█" * d["passed"] + "░" * (d["total"] - d["passed"])
        print(f"    {cat:30s} {bar}  {d['passed']}/{d['total']}  ({d['pass_rate']}%)")
    print()


# ── Eval Runner ──────────────────────────────────────────────────────────────

def build_user_message(case: dict) -> str:
    """Build user message with optional context injection."""
    msg = case["input"]
    ctx = case.get("context")
    if ctx:
        ctx_str = json.dumps(ctx, ensure_ascii=False, indent=2)
        msg = f"[Available context]\n{ctx_str}\n\n[User request]\n{msg}"
    return msg


def _inject_location_enum(tools: list[dict], case: dict) -> list[dict]:
    """Populate location_name enum from case context."""
    ctx = case.get("context", {})
    locs_str = ctx.get("available_locations", "") if ctx else ""
    if not locs_str:
        return tools
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


async def _eval_single_case(
    client: genai.Client,
    case: dict,
    system_prompt: str,
    tools: list[dict],
    model_name: str,
) -> dict:
    """Evaluate one case (single or multi-turn) via Live API."""
    tools = _inject_location_enum(tools, case)
    is_multiturn = "turns" in case

    if is_multiturn:
        turns = case["turns"]
        ctx = case.get("context")
        if ctx:
            turns = copy.deepcopy(turns)
            ctx_str = json.dumps(ctx, ensure_ascii=False, indent=2)
            for t in turns:
                if t["role"] == "user":
                    content = t.get("content", t.get("text", ""))
                    t["content"] = f"[Available context]\n{ctx_str}\n\n[User request]\n{content}"
                    break

        responses = await call_live_api_multiturn(
            client, system_prompt, turns, tools, model_name
        )
        if any(r.get("error") for r in responses):
            err = next(r["error"] for r in responses if r.get("error"))
            return {
                "case_id": case.get("id", "?"),
                "category": case.get("category"),
                "input": " → ".join(
                    t.get("content", t.get("text", ""))
                    for t in case["turns"] if t["role"] == "user"
                ),
                "scores": {"overall": False, "error": True},
                "details": {"error": err},
                "response": None,
            }
        return score_multiturn_case(case, responses)
    else:
        user_msg = build_user_message(case)
        response = await call_live_api(
            client, system_prompt, user_msg, tools, model_name
        )
        if response.get("error"):
            return {
                "case_id": case.get("id", "?"),
                "category": case.get("category"),
                "input": case.get("input", ""),
                "scores": {"overall": False, "error": True},
                "details": {"error": response["error"]},
                "response": None,
            }
        return score_case(case, response)


async def run_eval_live(
    eval_set: dict,
    system_prompt: str,
    fc_schema: list,
    model_name: str,
    workers: int = 1,
) -> list[dict]:
    """Run Live API eval with optional concurrency."""
    client = genai.Client()
    tools = [{"function_declarations": fc_schema}]
    cases = eval_set.get("cases", [])
    total = len(cases)

    if workers <= 1:
        results = []
        for i, case in enumerate(cases):
            print(f"  [{i+1}/{total}] {case['id']}...", end=" ", flush=True)
            scored = await _eval_single_case(client, case, system_prompt, tools, model_name)
            mark = "✓" if scored["scores"]["overall"] else ("ERR" if scored["scores"].get("error") else "✗")
            print(mark)
            results.append(scored)
            await asyncio.sleep(0.3)
        return results

    # Parallel mode using asyncio semaphore
    print(f"  (parallel: {workers} workers)\n")
    sem = asyncio.Semaphore(workers)
    results_map = {}
    done_count = 0

    async def run_one(idx: int, case: dict):
        nonlocal done_count
        async with sem:
            scored = await _eval_single_case(client, case, system_prompt, tools, model_name)
            results_map[idx] = scored
            done_count += 1
            mark = "✓" if scored["scores"]["overall"] else ("ERR" if scored["scores"].get("error") else "✗")
            print(f"  [{done_count}/{total}] {scored['case_id']}... {mark}")

    tasks = [run_one(i, case) for i, case in enumerate(cases)]
    await asyncio.gather(*tasks)

    return [results_map[i] for i in range(total)]


def main():
    parser = argparse.ArgumentParser(description="Run Gemini Live API FC eval")
    parser.add_argument("--eval-set", required=True)
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--fc-schema", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tag", default="live-run")
    parser.add_argument("--model", default="gemini-3.1-flash-live-preview")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel workers (1=sequential, >1=concurrent)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    print(f"Loading eval set: {args.eval_set}")
    eval_set = load_json(args.eval_set)
    if isinstance(eval_set, list):
        eval_set = {"cases": eval_set}
    print(f"  {len(eval_set['cases'])} cases")

    print(f"Loading system prompt: {args.system_prompt}")
    system_prompt = load_text(args.system_prompt)

    print(f"Loading FC schema: {args.fc_schema}")
    fc_schema = load_json(args.fc_schema)
    if isinstance(fc_schema, dict):
        fc_schema = fc_schema.get("functions", fc_schema.get("tools", []))
    print(f"  {len(fc_schema)} functions")

    print(f"\nRunning Live API eval (model={args.model})...\n")

    results = asyncio.run(
        run_eval_live(eval_set, system_prompt, fc_schema, args.model, args.workers)
    )

    summary = compute_summary(results)
    print_summary(summary, args.tag)

    out_dir = Path(args.output)
    save_json({
        "tag": args.tag,
        "model": args.model,
        "api_mode": "live",
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "results": results,
    }, str(out_dir / "results.json"))

    print(f"Saved to {out_dir}/")


if __name__ == "__main__":
    main()
