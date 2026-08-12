"""Curated model lists for the sidebar picker (model_picker.py), plus
per-model pricing used by chat_utils.py to cost out every logged run.

Tiers reflect actual behavior against this project's own free API keys
(checked 2026-08), not vendor marketing copy — vendor "free tier" docs
were sometimes stale or inconsistent with what the key could actually
call:

- Groq's whole general-purpose catalog works on a free key. The
  exceptions are `groq/compound` and `groq/compound-mini`, which bill
  extra for their built-in tools (web search, code exec) even on an
  otherwise-free key — tagged "paid" here.
- Google's Gemini API doesn't hard-block "pro"/preview models on a free
  key (they responded fine when tested), but their free-tier request
  quotas are far tighter than the flash tier's, to the point of being
  impractical for a chat UI without billing enabled — tagged "paid" here
  as a practical warning, not a hard access limit.
- Narrow non-chat models (Whisper, TTS, prompt-guard classifiers) are
  left out entirely; they can't back a tool-calling chat agent.
- OpenAI's API has no free tier at all (unlike the ChatGPT web app) — a
  fresh API key still bills a funded account from the first token. Every
  OpenAI model is tagged "paid" here. All three GPT-5.6 tiers were
  checked against a live key and work for tool-calling, but only with
  `reasoning_effort="none"` (see llm.py) — omit that and every one of
  them 400s on any request with tools attached.

`price` is USD per 1M tokens, {"input": x, "output": y}, from each
provider's published pricing page (2026-08) — omitted (not $0) when not
looked up, so chat_utils.py's cost estimate can tell "confirmed free"
(Ollama, always $0 — local, no API) apart from "unknown, don't guess"
(e.g. groq/compound's tool-use surcharge, qwen/qwen3.6-27b — not priced
here, cost logs as null rather than a made-up number). Gemini's Pro-tier
prices are the <=200k-token-prompt rate; ignores the higher long-context
tier for simplicity.
"""

PROVIDER_LABELS = {
    "groq": "Groq",
    "google": "Google (Gemini)",
    "openai": "OpenAI",
    "ollama": "Ollama (local)",
}

PROVIDER_MODELS = {
    "groq": [
        {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B Versatile", "tier": "free",
         "price": {"input": 0.59, "output": 0.79}},
        {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B Instant (faster, weaker)", "tier": "free",
         "price": {"input": 0.05, "output": 0.08}},
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B", "tier": "free",
         "price": {"input": 0.15, "output": 0.60}},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B (faster, weaker)", "tier": "free",
         "price": {"input": 0.075, "output": 0.30}},
        {"id": "qwen/qwen3.6-27b", "label": "Qwen 3.6 27B", "tier": "free"},
        {"id": "groq/compound", "label": "Groq Compound (built-in tools — bills extra)", "tier": "paid"},
        {"id": "groq/compound-mini", "label": "Groq Compound Mini (built-in tools — bills extra)", "tier": "paid"},
    ],
    "google": [
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "tier": "free",
         "price": {"input": 0.30, "output": 2.50}},
        {"id": "gemini-flash-latest", "label": "Gemini Flash (latest)", "tier": "free",
         "price": {"input": 0.30, "output": 2.50}},
        {"id": "gemini-flash-lite-latest", "label": "Gemini Flash Lite (latest, faster/weaker)", "tier": "free",
         "price": {"input": 0.10, "output": 0.40}},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "tier": "free",
         "price": {"input": 1.50, "output": 9.00}},
        {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash (newest)", "tier": "free",
         "price": {"input": 1.50, "output": 7.50}},
        {"id": "gemini-pro-latest", "label": "Gemini Pro (latest, tight free quota)", "tier": "paid",
         "price": {"input": 2.00, "output": 12.00}},
        {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (preview, tight free quota)", "tier": "paid",
         "price": {"input": 2.00, "output": 12.00}},
    ],
    "openai": [
        {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna (cheapest, high-volume)", "tier": "paid",
         "price": {"input": 0.20, "output": 1.20}},
        {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra (balanced cost/quality)", "tier": "paid",
         "price": {"input": 2.00, "output": 12.00}},
        {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol (flagship, most expensive)", "tier": "paid",
         "price": {"input": 5.00, "output": 30.00}},
    ],
    "ollama": [
        {"id": "gemma4:26b", "label": "Gemma 4 26B", "tier": "free", "price": {"input": 0.0, "output": 0.0}},
        {"id": "qwen2.5:7b", "label": "Qwen2.5 7B", "tier": "free", "price": {"input": 0.0, "output": 0.0}},
        {"id": "llama3.1:8b", "label": "Llama 3.1 8B", "tier": "free", "price": {"input": 0.0, "output": 0.0}},
        {"id": "qwen2.5:3b", "label": "Qwen2.5 3B (smaller, less reliable)", "tier": "free", "price": {"input": 0.0, "output": 0.0}},
        {"id": "llama3.2:3b", "label": "Llama 3.2 3B (smaller, less reliable)", "tier": "free", "price": {"input": 0.0, "output": 0.0}},
    ],
}


def get_price(provider: str, model: str) -> dict | None:
    """{"input": $/1M tokens, "output": $/1M tokens} for a known model, or
    None if not priced here (don't silently treat unknown as free)."""
    for entry in PROVIDER_MODELS.get(provider, []):
        if entry["id"] == model:
            return entry.get("price")
    return None
