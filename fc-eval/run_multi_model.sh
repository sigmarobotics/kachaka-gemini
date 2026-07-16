#!/bin/bash
# Run FC eval across Text API (zh/en/ja) + Voice E2E (zh/en, noise levels)
# Usage: ./run_multi_model.sh <system-prompt-file> <tag-prefix> <workers>
#
# All results use TP/TN/FP/FN classification.
# Control variable: system prompt + FC schema
# Expected outcome: correct FC trigger decisions

set -e
cd "$(dirname "$0")"

PROMPT="${1:-current_system_prompt.txt}"
TAG_PREFIX="${2:-baseline}"
WORKERS="${3:-10}"
EVAL_SET="evals/eval_set.json"
FC_SCHEMA="fc_schema.json"

# Text API models (zh/en/ja)
TEXT_MODELS=(
  "gemini-3.5-flash"
  "gemini-3.1-flash-lite-preview"
)

# Voice E2E model (zh/en only, with noise)
VOICE_MODEL="gemini-3.1-flash-live-preview"
VOICE_NOISE="clean,low,mid,high"

# Read API key from project settings
API_KEY=$(python3 -c "import json; print(json.load(open('../data/settings.json')).get('gemini_api_key',''))")
export GEMINI_API_KEY="$API_KEY"

CASES=$(python3 -c "import json; print(len(json.load(open('${EVAL_SET}')).get('cases',[])))")

echo "============================================"
echo "  FC Eval: ${TAG_PREFIX}"
echo "  Prompt:  ${PROMPT}"
echo "  Workers: ${WORKERS}"
echo "  Cases:   ${CASES}"
echo "  Text:    ${TEXT_MODELS[*]} (zh/en/ja)"
echo "  Voice:   ${VOICE_MODEL} (zh/en, noise=${VOICE_NOISE})"
echo "============================================"
echo

# ── Text API (zh/en/ja) ──
for model in "${TEXT_MODELS[@]}"; do
  tag="${TAG_PREFIX}-text-${model}"
  output="results/${TAG_PREFIX}/text-${model}/"
  echo ">>> [Text API] ${model}"
  python3 scripts/run_fc_eval.py \
    --eval-set "$EVAL_SET" \
    --system-prompt "$PROMPT" \
    --fc-schema "$FC_SCHEMA" \
    --output "$output" \
    --tag "$tag" \
    --model "$model" \
    --workers "$WORKERS"
  echo
done

# ── Voice E2E (zh/en, noise) ──
tag="${TAG_PREFIX}-voice"
output="results/${TAG_PREFIX}/voice/"
echo ">>> [Voice E2E] ${VOICE_MODEL}"
python3 scripts/run_fc_eval_voice.py \
  --eval-set "$EVAL_SET" \
  --system-prompt "$PROMPT" \
  --fc-schema "$FC_SCHEMA" \
  --output "$output" \
  --tag "$tag" \
  --model "$VOICE_MODEL" \
  --noise "$VOICE_NOISE" \
  --skip-lang ja \
  --workers "$WORKERS"
echo

echo ">>> Comparing results..."
python3 scripts/compare_results.py "results/${TAG_PREFIX}/" 2>/dev/null || true
echo
echo "Done. Results in results/${TAG_PREFIX}/"
