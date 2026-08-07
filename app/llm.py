"""Shared LLM factory for both agent variants.

Picks a chat model from `app/.env` so the agents don't require a local
Ollama install. Set LLM_PROVIDER to "groq" (default), "google", or
"ollama", plus the matching API key — see `.env.example`.
"""
import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "google": "gemini-2.5-flash",
    "ollama": "qwen2.5:7b",
}


def get_llm(model: str | None = None, provider: str | None = None, temperature: float = 0):
    """Build a chat model for the given (or env-configured) provider.

    `model` overrides the provider's default tag; leave it None to use
    `<PROVIDER>_MODEL` from the environment, falling back to
    `DEFAULT_MODELS`. `provider` overrides `LLM_PROVIDER` from the
    environment — pass it explicitly (e.g. from a per-session UI widget)
    rather than mutating `os.environ`, since a Streamlit server can hold
    multiple sessions in one process and env vars are process-global.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "groq")).lower()

    if provider == "groq":
        from langchain_groq import ChatGroq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is not set. Add it to "
                "app/.env — get a free key at https://console.groq.com/keys"
            )
        return ChatGroq(
            model=model or os.getenv("GROQ_MODEL", DEFAULT_MODELS["groq"]),
            temperature=temperature,
            api_key=api_key,
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER=google but GOOGLE_API_KEY is not set. Add it "
                "to app/.env — get a free key at https://aistudio.google.com/apikey"
            )
        return ChatGoogleGenerativeAI(
            model=model or os.getenv("GOOGLE_MODEL", DEFAULT_MODELS["google"]),
            temperature=temperature,
            google_api_key=api_key,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model or os.getenv("OLLAMA_MODEL", DEFAULT_MODELS["ollama"]),
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}; expected 'groq', 'google', or 'ollama'."
    )
