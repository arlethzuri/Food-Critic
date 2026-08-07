"""Curated model lists for the sidebar picker (model_picker.py).

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
"""

PROVIDER_LABELS = {
    "groq": "Groq",
    "google": "Google (Gemini)",
    "ollama": "Ollama (local)",
}

PROVIDER_MODELS = {
    "groq": [
        {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B Versatile", "tier": "free"},
        {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B Instant (faster, weaker)", "tier": "free"},
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B", "tier": "free"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B (faster, weaker)", "tier": "free"},
        {"id": "qwen/qwen3.6-27b", "label": "Qwen 3.6 27B", "tier": "free"},
        {"id": "groq/compound", "label": "Groq Compound (built-in tools — bills extra)", "tier": "paid"},
        {"id": "groq/compound-mini", "label": "Groq Compound Mini (built-in tools — bills extra)", "tier": "paid"},
    ],
    "google": [
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "tier": "free"},
        {"id": "gemini-flash-latest", "label": "Gemini Flash (latest)", "tier": "free"},
        {"id": "gemini-flash-lite-latest", "label": "Gemini Flash Lite (latest, faster/weaker)", "tier": "free"},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "tier": "free"},
        {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash (newest)", "tier": "free"},
        {"id": "gemini-pro-latest", "label": "Gemini Pro (latest, tight free quota)", "tier": "paid"},
        {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (preview, tight free quota)", "tier": "paid"},
    ],
    "ollama": [
        {"id": "qwen2.5:7b", "label": "Qwen2.5 7B", "tier": "free"},
        {"id": "llama3.1:8b", "label": "Llama 3.1 8B", "tier": "free"},
        {"id": "qwen2.5:3b", "label": "Qwen2.5 3B (smaller, less reliable)", "tier": "free"},
        {"id": "llama3.2:3b", "label": "Llama 3.2 3B (smaller, less reliable)", "tier": "free"},
    ],
}
