"""Shared helper for both dashboards: runs a create_agent()-built agent
and turns its message-list result into the final answer text plus a
human-readable Action/Observation trace for the reasoning-trace expander.
"""
from langchain_core.messages import AIMessage, ToolMessage


def _as_text(content) -> str:
    """Normalize a message's `.content` to plain text.

    Most providers (Groq, Ollama) return a plain string. Some (Gemini)
    return a list of content blocks (`{"type": "text", "text": ...}`,
    plus non-text blocks like thought signatures) — pull just the text
    parts out of those.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _build_trace(messages) -> str:
    trace_lines = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                trace_lines.append(f"Action: {call['name']}({call['args']})")
        elif isinstance(msg, ToolMessage):
            trace_lines.append(f"Observation: {_as_text(msg.content)}")
    return "\n\n".join(trace_lines)


def run_agent(agent, prompt: str) -> tuple[str, str]:
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    messages = result["messages"]
    output = _as_text(messages[-1].content)
    return output, _build_trace(messages)


def run_structured_agent(agent, prompt: str):
    """For agents built with response_format= (Variant 3). Returns
    (structured_response, trace_text); structured_response is None if the
    model failed to produce one (falls back to plain text messages)."""
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    messages = result["messages"]
    structured = result.get("structured_response")
    if structured is None:
        # Fall back so the caller always has something to show.
        structured = _as_text(messages[-1].content)
    return structured, _build_trace(messages)
