#!/usr/bin/env python3
"""Batch-runs comparison_questions.QUESTIONS against all three agent
variants and saves everything — final answer, full message list (every
tool call + its raw result), human-readable trace, V3's structured
HypothesisResponse, the Reasoning-tab timeline, and every chart as a
re-renderable Plotly JSON spec — for offline analysis. No frontend
involved; this drives the agents directly.

One JSON file per (question, variant) run in --out-dir, plus a single
all_runs.jsonl manifest (one line per run, easy to load with
pandas.read_json(..., lines=True)). Resumable: a run already saved
successfully is skipped unless --force is passed, so a rate-limit crash
partway through doesn't lose completed work — just rerun the same
command.

Usage:
  .venv/bin/python scripts/run_comparison.py
  .venv/bin/python scripts/run_comparison.py --provider groq --model llama-3.3-70b-versatile
  .venv/bin/python scripts/run_comparison.py --only-ids A1,A2,C1 --only-variants v1,v2
  .venv/bin/python scripts/run_comparison.py --limit 3   # smoke test
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from comparison_questions import QUESTIONS  # noqa: E402 (needs sys.path set up first)

VARIANTS = ["v1", "v2", "v3"]


def _run_and_capture(agent, prompt: str, chart_sink: list, candidate_sink: list, structured_mode: bool,
                      provider: str, model: str) -> dict:
    """Invokes the agent exactly once and derives everything from that one
    result — deliberately not calling chat_utils.run_agent/
    run_structured_agent (which would need a second invoke to also expose
    raw messages), to avoid double-billing/double-calling the LLM per run.
    Mirrors their logic (and reuses their serialization/usage/cost
    helpers directly) — keep in sync with app/chat_utils.py if that changes.
    """
    from chat_utils import (
        _as_text, _build_timeline, _build_trace, _ensure_visualization, _estimate_cost,
        _extract_usage, _recover_narrative, _serialize_charts, _serialize_messages,
    )

    start = time.time()
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    duration = time.time() - start
    messages = result["messages"]

    structured_dict = None
    if structured_mode:
        from schemas import CandidatePoolItem, HypothesisResponse

        structured = result.get("structured_response")
        pool = [
            CandidatePoolItem(
                gmap_id=row["gmap_id"], name=row.get("name"), address=row.get("address"),
                latitude=row.get("latitude"), longitude=row.get("longitude"),
                avg_rating=row.get("avg_rating"), num_of_reviews=row.get("num_of_reviews"),
                price=row.get("price"), distance_mi=row.get("distance_mi"),
                slchd_establishment_key=row.get("slchd_establishment_key"),
                inspection_score=row.get("most_recent_inspection_score"),
                critical_violation_count=row.get("critical_violation_count"),
                total_violation_count=row.get("total_violation_count"),
            )
            for row in candidate_sink if row.get("gmap_id")
        ]
        if structured is None:
            structured = HypothesisResponse(
                narrative_answer=_recover_narrative(_as_text(messages[-1].content)),
                hypothesis="none", confidence="low", candidate_pool=pool,
            )
        else:
            structured.candidate_pool = pool
        output_text = structured.narrative_answer
        structured_dict = structured.model_dump()
    else:
        output_text = _as_text(messages[-1].content)

    _ensure_visualization(chart_sink, candidate_sink, messages)
    timeline = _build_timeline(messages) if structured_mode else []
    usage = _extract_usage(messages)

    return {
        "output_text": output_text,
        "structured_response": structured_dict,
        "trace_text": _build_trace(messages),
        "timeline": [dataclasses.asdict(step) for step in timeline],
        "messages": _serialize_messages(messages),
        "charts": _serialize_charts(chart_sink),
        "candidate_pool_raw": candidate_sink,
        "usage": usage,
        "tokens_per_minute": round(usage["total_tokens"] / (duration / 60), 1) if usage.get("available") and duration > 0 else None,
        "estimated_cost_usd": _estimate_cost(provider, model, usage),
    }


def _build_agent(variant: str, con, retriever, chart_sink, candidate_sink, model, provider):
    import agent, agent_v2, agent_v3

    if variant == "v1":
        return agent.build_agent(con, chart_sink, candidate_sink, model=model, provider=provider)
    if variant == "v2":
        return agent_v2.build_agent(con, chart_sink, candidate_sink, retriever, model=model, provider=provider)
    if variant == "v3":
        return agent_v3.build_agent(con, chart_sink, candidate_sink, retriever, model=model, provider=provider)
    raise ValueError(variant)


def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in (
        "rate_limit", "429", "413", "resource has been exhausted",
        "quota", "tokens per minute", "too many requests",
    ))


def _resolve_model(provider: str, model: str | None) -> str:
    """Mirrors app/llm.py's get_llm() model resolution exactly, so the
    record always logs the real model string that was actually used —
    never None — and cost lookups (keyed on the concrete model id) work
    even when --model was left to the provider default."""
    import os

    from llm import DEFAULT_MODELS

    return model or os.getenv(f"{provider.upper()}_MODEL", DEFAULT_MODELS[provider])


def run_one(variant: str, q: dict, con, retriever, model: str | None, provider: str,
            max_retries: int, retry_wait: float, out_dir: Path) -> dict:
    from datetime import datetime, timezone

    resolved_model = _resolve_model(provider, model)
    record = {
        "source": "batch", "id": q["id"], "category": q["category"], "predicted_winner": q["predicted_winner"],
        "question": q["question"], "variant": variant, "provider": provider, "model": resolved_model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    chart_sink: list = []
    candidate_sink: list = []
    start = time.time()
    attempt = 0
    while True:
        attempt += 1
        try:
            agent_obj = _build_agent(variant, con, retriever, chart_sink, candidate_sink, resolved_model, provider)
            captured = _run_and_capture(agent_obj, q["question"], chart_sink, candidate_sink,
                                         structured_mode=(variant == "v3"), provider=provider, model=resolved_model)
            record.update(captured)
            record["success"] = True
            record["error"] = None
            record["attempts"] = attempt
            from chat_utils import _export_chart_images
            record["chart_image_files"] = _export_chart_images(out_dir / f"{q['id']}_{variant}", chart_sink)
            break
        except Exception as e:
            if _is_rate_limit_error(e) and attempt <= max_retries:
                print(f"    rate-limited (attempt {attempt}/{max_retries}), waiting {retry_wait:.0f}s: {str(e)[:150]}")
                time.sleep(retry_wait)
                chart_sink, candidate_sink = [], []  # fresh sinks for the retry
                continue
            record["success"] = False
            record["error"] = f"{type(e).__name__}: {e}"
            record["error_traceback"] = traceback.format_exc()
            record["attempts"] = attempt
            break
    record["duration_seconds"] = round(time.time() - start, 2)
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="groq")
    ap.add_argument("--model", default=None, help="Defaults to the provider's DEFAULT_MODELS entry (see app/llm.py).")
    ap.add_argument("--out-dir", default=str(ROOT / "results" / "comparison"))
    ap.add_argument("--only-ids", default=None, help="Comma-separated question ids, e.g. A1,A2,C1")
    ap.add_argument("--only-variants", default=None, help="Comma-separated subset of v1,v2,v3")
    ap.add_argument("--limit", type=int, default=None, help="Only run the first N (question,variant) pairs — smoke test.")
    ap.add_argument("--sleep", type=float, default=3.0, help="Seconds to sleep between calls (be nice to rate limits).")
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--retry-wait", type=float, default=65.0, help="Seconds to wait on a rate-limit error before retrying (Groq's free tier TPM window is 60s).")
    ap.add_argument("--force", action="store_true", help="Rerun even if a successful result already exists.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "all_runs.jsonl"

    questions = QUESTIONS
    if args.only_ids:
        wanted = set(args.only_ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    variants = args.only_variants.split(",") if args.only_variants else VARIANTS

    pairs = [(q, v) for q in questions for v in variants]
    if args.limit:
        pairs = pairs[: args.limit]

    print(f"Provider={args.provider} model={args.model or '(default)'} — {len(pairs)} runs, out_dir={out_dir}")

    from data_layer import get_connection
    from rag.retriever import load_retriever

    con = get_connection()
    retriever = load_retriever() if any(v in ("v2", "v3") for _, v in pairs) else None

    done = failed = skipped = 0
    for i, (q, variant) in enumerate(pairs, 1):
        run_path = out_dir / f"{q['id']}_{variant}.json"
        tag = f"[{i}/{len(pairs)}] {q['id']} {variant}"

        if run_path.exists() and not args.force:
            try:
                existing = json.loads(run_path.read_text())
                if existing.get("success"):
                    print(f"{tag} — already done, skipping (--force to rerun)")
                    skipped += 1
                    continue
            except Exception:
                pass  # corrupt/partial file — rerun it

        print(f"{tag} — running: {q['question'][:80]}...")
        record = run_one(variant, q, con, retriever, args.model, args.provider, args.max_retries, args.retry_wait, out_dir)

        run_path.write_text(json.dumps(record, indent=2, default=str))
        with open(manifest_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        from chat_utils import _format_transcript
        (out_dir / f"{q['id']}_{variant}.txt").write_text(_format_transcript(record))

        if record["success"]:
            done += 1
            n_msgs = len(record["messages"])
            n_charts = len(record["charts"])
            print(f"    ok in {record['duration_seconds']}s — {n_msgs} messages, {n_charts} chart(s)")
        else:
            failed += 1
            print(f"    FAILED: {record['error']}")

        time.sleep(args.sleep)

    print(f"\nDone. {done} succeeded, {failed} failed, {skipped} skipped (already done). Results in {out_dir}")


if __name__ == "__main__":
    main()
