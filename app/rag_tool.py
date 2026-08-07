"""Tool wrapping the RAG retriever (app/rag/retriever.py) so the agent can
ground claims about *why* something is a violation or what a regulation
requires, separate from run_sql/plot_chart which ground claims about the
actual inspection data."""
from langchain_core.tools import tool


def make_rag_tool(retriever):
    @tool
    def retrieve_regulation(query: str) -> str:
        """Search Utah's R392-100 Food Service Sanitation Rule (FDA Food Code 2013 + Utah amendments) and the SLC county inspection-process page for regulatory text relevant to `query`. Use this to explain why a violation matters, what a code section requires, or how scoring/risk levels work — not for anything about specific restaurants (use run_sql for that)."""
        docs = retriever.invoke(query)
        if not docs:
            return "No relevant regulatory text found."
        parts = []
        for d in docs:
            meta = d.metadata
            cite = meta.get("source", "unknown source")
            heading = meta.get("nearest_heading")
            page = meta.get("page")
            loc = cite + (f", near {heading}" if heading else "") + (f", p.{page}" if page else "")
            parts.append(f"[{loc}]\n{d.page_content.strip()}")
        return "\n\n---\n\n".join(parts)

    return retrieve_regulation
