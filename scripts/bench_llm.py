"""
Benchmark Ollama models for token throughput (eval tok/s).
Tests: qwen3.5:4b-mlx, qwen3.5:4b-q4_K_M

No thinking mode — enforced via system prompt + options where supported.
Run: .venv/bin/python scripts/bench_llm.py
"""

import json
import time
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434"

MODELS = [
    "qwen3.5:4b-mlx",
    "qwen3.5:4b-q4_K_M",
]

# Prompt designed to produce a consistent medium-length response (≈80-120 tokens)
SYSTEM = (
    "You are a concise assistant. Do NOT use any thinking, reasoning steps, "
    "or <think> blocks. Respond directly and immediately."
)
PROMPTS = [
    "Describe the colour blue in exactly two sentences.",
    "What makes a robot feel alive? Answer in two sentences.",
    "Explain gravity to a five-year-old in two sentences.",
    "What is the speed of light and why does it matter? Two sentences only.",
    "Name three emotions and describe each in one word.",
]

RUNS = 5   # iterations per model


def generate(model: str, prompt: str) -> dict:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 200,
            # Disable thinking for models that support it (qwen3, gemma4 with thinking)
            "think": False,
        },
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def bench_model(model: str) -> list[dict]:
    results = []
    print(f"\n  {'─'*52}")
    for i, prompt in enumerate(PROMPTS[:RUNS]):
        try:
            t0 = time.time()
            r = generate(model, prompt)
            wall = time.time() - t0

            eval_count    = r.get("eval_count", 0)
            eval_ns       = r.get("eval_duration", 1)
            prompt_count  = r.get("prompt_eval_count", 0)
            prompt_ns     = r.get("prompt_eval_duration", 1)

            tok_s  = eval_count / (eval_ns / 1e9)
            prompt_tok_s = prompt_count / (prompt_ns / 1e9) if prompt_ns else 0

            # Grab first 60 chars of reply for a sanity check
            reply = r.get("message", {}).get("content", "")[:60].replace("\n", " ")

            results.append({
                "run": i + 1,
                "eval_tokens": eval_count,
                "tok_s": tok_s,
                "prompt_tok_s": prompt_tok_s,
                "wall_s": wall,
                "reply": reply,
            })
            print(f"  run {i+1}  {eval_count:>3} tok  {tok_s:>6.1f} tok/s  "
                  f"wall {wall:>5.1f}s  -> \"{reply}...\"")
        except Exception as e:
            print(f"  run {i+1}  ERROR: {e}")

    return results


def main():
    print("\n" + "═" * 62)
    print("  LLM BENCHMARK — eval tok/s (no thinking mode)")
    print("═" * 62)

    summary = {}
    for model in MODELS:
        print(f"\n▶ {model}")
        # Warm-up: one silent call so the model is loaded into VRAM
        print("  [warming up…]")
        try:
            generate(model, "Hi")
        except Exception as e:
            print(f"  SKIP — model not available: {e}")
            continue

        results = bench_model(model)
        if not results:
            continue

        tok_s_vals = [r["tok_s"] for r in results]
        avg = sum(tok_s_vals) / len(tok_s_vals)
        mn  = min(tok_s_vals)
        mx  = max(tok_s_vals)
        summary[model] = {"avg": avg, "min": mn, "max": mx}

    print("\n\n" + "═" * 62)
    print("  RESULTS SUMMARY")
    print("═" * 62)
    print(f"  {'Model':<40}  {'avg':>7}  {'min':>7}  {'max':>7}")
    print(f"  {'─'*40}  {'─'*7}  {'─'*7}  {'─'*7}")
    for model, s in sorted(summary.items(), key=lambda x: -x[1]["avg"]):
        flag = " ◀ fastest" if s["avg"] == max(v["avg"] for v in summary.values()) else ""
        print(f"  {model:<40}  {s['avg']:>6.1f}  {s['min']:>6.1f}  {s['max']:>6.1f}  tok/s{flag}")

    print()
    if summary:
        fastest = max(summary, key=lambda m: summary[m]["avg"])
        print(f"  Winner: {fastest}")
        print(f"  Near-realtime threshold: ≥30 tok/s feels instant; 15–30 perceptible but OK.")
    print("═" * 62 + "\n")


if __name__ == "__main__":
    main()
