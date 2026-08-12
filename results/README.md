# Results

Saved agent runs for the v1/v2/v3 comparison — from the live dashboards
(`frontend/`) and the batch script (`comparison/`, see
`scripts/run_comparison.py`). Both write the same record schema (a
`source: "frontend"|"batch"` field is the only structural difference),
so they load together.

## Files per run

Three files share a name stem (batch: `{question_id}_{variant}`;
frontend: `{timestamp}_{variant}_{run_id}`):

| File | Format | Contents |
|---|---|---|
| `{stem}.json` | JSON | full record (see table below) |
| `{stem}.txt` | plain text | question, answer, reasoning trace, token usage/cost — readable without any tooling |
| `{stem}_chart{N}.png` | PNG | each chart rendered standalone (also embedded as a re-renderable Plotly JSON spec inside the `.json`) |
| `all_runs.jsonl` | JSON Lines | one line per run, all runs in that folder — `pandas.read_json("all_runs.jsonl", lines=True)` |

## Record fields (`.json` / each `.jsonl` line)

| Field | Meaning |
|---|---|
| `source` | `"frontend"` or `"batch"` |
| `id`, `category`, `predicted_winner` | batch only — see `scripts/comparison_questions.py` |
| `run_id`, `timestamp` | frontend only |
| `variant`, `provider`, `model` | which dashboard, which LLM served it |
| `question` | the prompt asked |
| `output_text` | final answer text (v1/v2), or v3's narrative |
| `structured_response` | v3's full `HypothesisResponse` (hypothesis, confidence, supporting/undermining evidence, candidate_pool); `null` for v1/v2 |
| `trace_text` | human-readable Action/Observation trace |
| `timeline` | v3's Reasoning-tab step data |
| `messages` | every raw message, incl. every tool call + its full result and per-call token usage |
| `charts` | every chart as a Plotly JSON spec |
| `chart_image_files` | filenames of the matching `{stem}_chart{N}.png` sidecars |
| `candidate_pool_raw` | raw `search_establishments` rows collected |
| `duration_seconds`, `tokens_per_minute` | timing |
| `usage` | `{available, per_call: [...], input_tokens, output_tokens, total_tokens}` — summed across every LLM call in the turn (one question = several ReAct steps) |
| `estimated_cost_usd` | from real per-token pricing (`app/model_registry.py`); `null` when the model isn't priced there, never a guessed `$0` |
| `success`, `error` | failed runs (rate limits, bad keys, etc.) are logged too, not dropped |

## Regenerating

- Frontend: runs are logged automatically on every chat turn in any of the three dashboards (`app/chat_utils.py`'s `log_run`/`log_failed_run`) — nothing to trigger manually.
- Batch: `.venv/bin/python scripts/run_comparison.py` — resumable, skips runs already saved successfully unless `--force`.
