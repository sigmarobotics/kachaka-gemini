#!/usr/bin/env python3
"""
run_fc_eval.py — Gemini Text API function calling evaluation.

Scores FC routing correctness using TP/TN/FP/FN classification.
Control variable: system prompt + FC schema.
Expected outcome: correct FC trigger decisions.

Usage:
    python scripts/run_fc_eval.py \
        --eval-set evals/eval_set.json \
        --system-prompt current_system_prompt.txt \
        --fc-schema fc_schema.json \
        --output results/text-baseline/ \
        --tag text-baseline \
        --model gemini-3.5-flash \
        --workers 10

Requires:
    - GEMINI_API_KEY environment variable
    - pip install google-genai
"""

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from google import genai
except ImportError:
    print("ERROR: pip install google-genai")
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


# ── Location Injection ──────────────────────────────────────────────────────

def parse_locations(locs_str: str) -> list[str]:
    """Parse 'name1 (1.2m), name2 (3.4m)' → ['name1', 'name2']."""
    names = []
    for part in locs_str.split(","):
        part = part.strip()
        paren = part.find("(")
        name = part[:paren].strip() if paren > 0 else part
        if name:
            names.append(name)
    return names


def inject_locations_into_prompt(system_prompt: str, locs_str: str) -> str:
    """Inject available locations into system prompt."""
    if not locs_str:
        return system_prompt
    section = f"\n\n[Available Locations (sorted by distance)]\n{locs_str}"
    if "{{AVAILABLE_LOCATIONS}}" in system_prompt:
        return system_prompt.replace("{{AVAILABLE_LOCATIONS}}", section)
    return system_prompt + section


def inject_location_enum(fc_schema: list[dict], location_names: list[str]) -> list[dict]:
    """Populate location_name enum in FC schema."""
    if not location_names:
        return fc_schema
    schema = copy.deepcopy(fc_schema)
    for fn in schema:
        props = fn.get("parameters", {}).get("properties", {})
        if "location_name" in props and "enum" in props["location_name"]:
            props["location_name"]["enum"] = location_names
    return schema


# ── Gemini Interface ─────────────────────────────────────────────────────────

def build_gemini_tools(schema: list[dict]) -> list:
    # Interactions API: each function tool is a plain dict with a top-level
    # "type": "function" (no types.Tool(function_declarations=...) wrapper).
    tools = []
    for fn in schema:
        tool = {"type": "function", "name": fn["name"], "description": fn.get("description", "")}
        if "parameters" in fn:
            tool["parameters"] = fn["parameters"]
        tools.append(tool)
    return tools


def call_gemini(client: "genai.Client", system_prompt: str, user_message: str, tools: list,
                model_name: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            interaction = client.interactions.create(
                model=model_name,
                input=user_message,
                system_instruction=system_prompt,
                tools=tools,
            )
            return _parse_response(interaction)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
            else:
                return {"error": str(e), "function_call": None, "text_response": None}


def call_gemini_multiturn(client: "genai.Client", system_prompt: str, turns: list[dict], tools: list,
                          model_name: str, max_retries: int = 3) -> list[dict]:
    # Interactions API has no client-side chat object — multi-turn state is
    # carried server-side via previous_interaction_id (see gemini_text_service.py).
    responses = []
    previous_interaction_id = None

    for turn in turns:
        if turn["role"] != "user":
            continue
        msg = turn["content"]
        for attempt in range(max_retries):
            try:
                kwargs = dict(
                    model=model_name,
                    input=msg,
                    system_instruction=system_prompt,
                    tools=tools,
                )
                if previous_interaction_id:
                    kwargs["previous_interaction_id"] = previous_interaction_id
                interaction = client.interactions.create(**kwargs)
                previous_interaction_id = interaction.id
                responses.append(_parse_response(interaction))
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                else:
                    responses.append({"error": str(e), "function_call": None, "text_response": None})
        time.sleep(0.1)

    return responses


def _parse_response(interaction) -> dict:
    result = {"function_call": None, "text_response": None, "error": None}
    try:
        steps = interaction.steps or []
        for step in steps:
            if step.type == "function_call":
                result["function_call"] = {
                    "name": step.name,
                    "args": step.arguments or {},
                }
        result["text_response"] = interaction.output_text
    except Exception as e:
        result["error"] = f"Parse error: {e}"
    return result


# ── Classification (TP/TN/FP/FN) ────────────────────────────────────────────

CLARIFY_SIGNALS = [
    "?", "？", "哪一", "哪個", "請問", "確認", "請告訴",
    "which", "could you specify", "do you mean", "clarify", "please tell",
]


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
            # prompt/message: only check that the model provided a non-empty string
            if not got or not isinstance(got, str) or not got.strip():
                return False
        elif key == "angle":
            # angle: check sign matches (direction) — exact value not required
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


def classify_single(expected: dict, response: dict) -> str:
    """Classify a single-turn response as TP/TN/FP/FN."""
    expected_fn = expected.get("function")
    should_clarify = expected.get("should_clarify", False)
    fc = response.get("function_call")
    actual_fn = fc["name"] if fc else None

    if should_clarify or expected_fn is None:
        # No FC should be triggered
        return "TN" if actual_fn is None else "FP"
    else:
        # A specific FC should be triggered
        if actual_fn is None:
            return "FN"
        elif actual_fn == expected_fn and params_match(expected, fc):
            return "TP"
        else:
            return "FP"


def classify_multiturn(case: dict, responses: list[dict]) -> tuple[str, list[dict]]:
    """Classify multi-turn conversation. Returns (worst_class, turn_details)."""
    turns = case["turns"]
    model_turns = [t for t in turns if t["role"] == "model"]
    turn_details = []
    worst = "TP"  # best case
    rank = {"TP": 0, "TN": 0, "FP": 2, "FN": 1}  # FP is worst

    for idx, (model_turn, response) in enumerate(zip(model_turns, responses)):
        detail = {"turn": idx}

        if response.get("error"):
            detail["classification"] = "ERR"
            detail["error"] = response["error"]
            worst = "FP"
            turn_details.append(detail)
            continue

        expected = model_turn.get("expected", {})
        cls = classify_single(expected, response)
        detail["classification"] = cls
        detail["expected_fn"] = expected.get("function")
        detail["should_clarify"] = expected.get("should_clarify", False)
        detail["actual_fn"] = response["function_call"]["name"] if response.get("function_call") else None
        detail["actual_args"] = response["function_call"]["args"] if response.get("function_call") else None

        if rank.get(cls, 0) > rank.get(worst, 0):
            worst = cls

        turn_details.append(detail)

    # For multi-turn: if any turn is FP/FN, overall is FP/FN (worst)
    # If all turns are TP/TN, overall follows the last FC turn
    has_fp = any(t["classification"] == "FP" for t in turn_details)
    has_fn = any(t["classification"] == "FN" for t in turn_details)
    if has_fp:
        overall = "FP"
    elif has_fn:
        overall = "FN"
    else:
        # All correct — use last turn's classification
        overall = turn_details[-1]["classification"] if turn_details else "TN"

    return overall, turn_details


def score_case(case: dict, response: dict) -> dict:
    """Score a single case with TP/TN/FP/FN classification."""
    expected = case["expected"]
    fc = response.get("function_call")
    actual_fn = fc["name"] if fc else None
    cls = classify_single(expected, response)

    return {
        "case_id": case["id"],
        "category": case.get("category", ""),
        "difficulty": case.get("difficulty", ""),
        "input": case["input"],
        "classification": cls,
        "expected_fn": expected.get("function"),
        "should_clarify": expected.get("should_clarify", False),
        "actual_fn": actual_fn,
        "actual_args": fc["args"] if fc else None,
        "params_correct": params_match(expected, fc) if fc and expected.get("function") else None,
        "response_text": (response.get("text_response") or "")[:300],
    }


def score_multiturn_case(case: dict, responses: list[dict]) -> dict:
    """Score a multi-turn case with TP/TN/FP/FN classification."""
    cls, turn_details = classify_multiturn(case, responses)
    user_inputs = [t["content"] for t in case["turns"] if t["role"] == "user"]

    last_resp = responses[-1] if responses else {}
    last_fc = last_resp.get("function_call")

    return {
        "case_id": case["id"],
        "category": case.get("category", ""),
        "difficulty": case.get("difficulty", ""),
        "input": " → ".join(user_inputs),
        "classification": cls,
        "turn_details": turn_details,
        "expected_fn": None,  # multi-turn has per-turn expectations
        "should_clarify": None,
        "actual_fn": last_fc["name"] if last_fc else None,
        "actual_args": last_fc["args"] if last_fc else None,
        "params_correct": None,
        "response_text": (last_resp.get("text_response") or "")[:300],
    }


# ── Metrics ─────────────────────────────────────────────────────────────────

def compute_metrics(classifications: list[str]) -> dict:
    tp = classifications.count("TP")
    tn = classifications.count("TN")
    fp = classifications.count("FP")
    fn = classifications.count("FN")
    err = classifications.count("ERR")

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    accuracy = (tp + tn) / len(classifications) if classifications else 0

    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn, "errors": err,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }


def compute_summary(results: list[dict]) -> dict:
    cls_list = [r["classification"] for r in results]
    overall = compute_metrics(cls_list)

    by_category = {}
    for cat in sorted(set(r["category"] for r in results)):
        cat_cls = [r["classification"] for r in results if r["category"] == cat]
        by_category[cat] = compute_metrics(cat_cls)

    return {
        "total": len(results),
        "metrics": overall,
        "by_category": by_category,
    }


def print_summary(summary: dict, tag: str):
    m = summary["metrics"]
    w = 60
    print(f"\n{'='*w}")
    print(f"  {tag} (Text API)")
    print(f"{'='*w}")
    print(f"\n  Overall:  Accuracy={m['accuracy']:.1%}  Precision={m['precision']:.1%}  Recall={m['recall']:.1%}  F1={m['f1']:.3f}")
    if m["errors"]:
        print(f"  Errors: {m['errors']}")

    print(f"\n  Confusion Matrix:")
    print(f"  {'':14s} Triggered    Not-triggered")
    print(f"  {'Should':14s}  TP={m['tp']:<8d}  FN={m['fn']}")
    shouldnt = "Shouldn't"
    print(f"  {shouldnt:14s}  FP={m['fp']:<8d}  TN={m['tn']}")

    print(f"\n  By Category:")
    for cat, cm in summary["by_category"].items():
        print(f"    {cat:30s} TP={cm['tp']}  FP={cm['fp']}  FN={cm['fn']}  TN={cm['tn']}  F1={cm['f1']:.3f}  Acc={cm['accuracy']:.0%}")
    print()


def print_errors(results: list[dict]):
    errors = [r for r in results if r["classification"] in ("FP", "FN")]
    if not errors:
        return
    print("  Errors (FP + FN):")
    for r in errors:
        if r["classification"] == "FP":
            exp = "clarify" if r["should_clarify"] else (r["expected_fn"] or "None")
            print(f"    FP {r['case_id']}: want={exp} got={r['actual_fn']}")
        else:
            print(f"    FN {r['case_id']}: want={r['expected_fn']} got=no_fc")
    print()


# ── Eval Runner ─────────────────────────────────────────────────────────────

def _prepare_case(case: dict, base_system_prompt: str, base_fc_schema: list[dict]):
    """Prepare system prompt and tools for a specific case."""
    ctx = case.get("context", {}) or {}
    locs_str = ctx.get("available_locations", "")

    # Inject locations into system prompt
    system_prompt = inject_locations_into_prompt(base_system_prompt, locs_str)

    # Inject location enum into FC schema
    location_names = parse_locations(locs_str)
    fc_schema = inject_location_enum(base_fc_schema, location_names)
    tools = build_gemini_tools(fc_schema)

    return system_prompt, tools


def _eval_single_case(client: "genai.Client", case: dict, base_system_prompt: str,
                      base_fc_schema: list[dict], model_name: str) -> dict:
    """Evaluate one case (single or multi-turn). Thread-safe."""
    system_prompt, tools = _prepare_case(case, base_system_prompt, base_fc_schema)
    is_multiturn = "turns" in case

    if is_multiturn:
        turns = case["turns"]
        responses = call_gemini_multiturn(client, system_prompt, turns, tools, model_name)
        if any(r.get("error") for r in responses):
            err = next(r["error"] for r in responses if r.get("error"))
            return {
                "case_id": case["id"],
                "category": case.get("category", ""),
                "classification": "ERR",
                "input": " → ".join(t["content"] for t in case["turns"] if t["role"] == "user"),
                "error": err,
            }
        return score_multiturn_case(case, responses)
    else:
        user_msg = case["input"]
        response = call_gemini(client, system_prompt, user_msg, tools, model_name)
        if response.get("error"):
            return {
                "case_id": case["id"],
                "category": case.get("category", ""),
                "classification": "ERR",
                "input": case["input"],
                "error": response["error"],
            }
        return score_case(case, response)


def run_eval(client: "genai.Client", eval_set: dict, system_prompt: str, fc_schema: list[dict],
             model_name: str, workers: int = 1) -> list[dict]:
    cases = eval_set["cases"]
    total = len(cases)

    if workers <= 1:
        results = []
        for i, case in enumerate(cases):
            print(f"  [{i+1}/{total}] {case['id']}...", end=" ", flush=True)
            scored = _eval_single_case(client, case, system_prompt, fc_schema, model_name)
            cls = scored.get("classification", "ERR")
            mark = {"TP": "✓", "TN": "✓", "FP": "✗", "FN": "✗", "ERR": "ERR"}.get(cls, "?")
            print(f"{cls} {mark}")
            results.append(scored)
            time.sleep(1.0)
        return results

    print(f"  (parallel: {workers} workers)\n")
    results_map = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {}
        for i, case in enumerate(cases):
            future = executor.submit(
                _eval_single_case, client, case, system_prompt, fc_schema, model_name)
            future_to_idx[future] = i

        done_count = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            case = cases[idx]
            try:
                scored = future.result()
            except Exception as e:
                scored = {
                    "case_id": case.get("id", f"case-{idx}"),
                    "category": case.get("category", ""),
                    "classification": "ERR",
                    "input": case.get("input", ""),
                    "error": str(e),
                }
            results_map[idx] = scored
            done_count += 1
            cls = scored.get("classification", "ERR")
            mark = {"TP": "✓", "TN": "✓", "FP": "✗", "FN": "✗", "ERR": "ERR"}.get(cls, "?")
            print(f"  [{done_count}/{total}] {scored['case_id']}... {cls} {mark}")

    return [results_map[i] for i in range(total)]


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gemini Text API FC eval")
    parser.add_argument("--eval-set", required=True)
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--fc-schema", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tag", default="text-run")
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        sys.exit(1)
    client = genai.Client(api_key=api_key)

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

    print(f"\nText API eval (model={args.model})...\n")
    results = run_eval(client, eval_set, system_prompt, fc_schema, args.model, args.workers)

    summary = compute_summary(results)
    print_summary(summary, args.tag)
    print_errors(results)

    out_dir = Path(args.output)
    save_json({
        "tag": args.tag,
        "model": args.model,
        "api_mode": "text",
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "results": results,
    }, str(out_dir / "results.json"))

    print(f"  Saved to {out_dir}/")


if __name__ == "__main__":
    main()
