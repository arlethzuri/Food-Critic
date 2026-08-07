# Food Critic — Variants 1, 2 & 3

Streamlit dashboards: fixed safety-overview charts computed directly from
`data/processed/merged_food_inspections.csv`, plus a chat box backed by a
ReAct-style agent (LangChain `create_agent`: native tool-calling reason/act
loop) that can query the same data via SQL and render charts on request.

- **Variant 1** (`dashboard.py`) — CSV only, no domain grounding. RQ1
  baseline condition.
- **Variant 2** (`dashboard_v2.py`) — same, plus RAG over Utah's R392-100
  Food Service Sanitation Rule and SLC county's inspection-process page,
  so the agent can ground *why* something is a violation / what a rule
  requires, not just query counts.
- **Variant 3** (`dashboard_v3.py`) — same as variant 2, plus an
  ontology-guided hypothesis/evidence pipeline
  (`semantic/gen_ontology.json`): the agent's final answer is structured,
  not free text — it must classify itself into one of a fixed set of
  hypothesis types (`safe_bet`, `health_risk_concern`,
  `improving_compliance`, `declining_compliance`,
  `repeat_critical_violator`, or `none` for a plain lookup) and back it
  with typed evidence tagged to ontology concepts
  (`Violation.critical`, `InspectionTrend.worsening`,
  `ViolationType.temperature_control`, ...), each item citing the actual
  tool call it came from. This is what completes the RQ1 3-condition
  comparison (data-only / +RAG / +ontology+evidence) and is the direct
  answer to RQ2 (can the agent explain its reasoning in a checkable way).

None of the three variants have review data yet (Yelp is currently blocked).

## How to run

Full path from a clean checkout, in order:

1. Install Python deps:
   ```
   pip install -r app/requirements.txt
   ```
   (or `conda env update -f environment.yml --prune` if using the conda env)

   Variants 2/3 additionally install `sentence-transformers` (pulls in
   `torch` — a few hundred MB) for local embeddings; the embedding model
   itself (`all-MiniLM-L6-v2`, ~80MB) downloads once on first use.

2. Pick an LLM provider — copy `app/.env.example` to `app/.env` and fill
   in one of:
   - **Groq** (default, `LLM_PROVIDER=groq`) — free tier, fast, good
     tool-calling. Get a key at https://console.groq.com/keys and set
     `GROQ_API_KEY`.
   - **Google** (`LLM_PROVIDER=google`) — free tier via AI Studio. Get a
     key at https://aistudio.google.com/apikey and set `GOOGLE_API_KEY`.
   - **Ollama** (`LLM_PROVIDER=ollama`, no key needed) — the original
     local setup. Install [Ollama](https://ollama.com/download), then:
     ```
     ollama pull qwen2.5:7b
     ollama serve
     ```
     `llama3.1:8b` is a solid alternative; set `OLLAMA_MODEL` in
     `app/.env` if you use a different tag. Smaller/local models are
     noticeably weaker than large hosted models at native tool-calling,
     and variant 3 additionally asks the model to produce structured
     output on top of tool-calling — expect more failures there with a
     small local model than with Groq/Google.

   See `app/llm.py` for the full provider/model logic and defaults.

3. Make sure the merged data exists:
   ```
   python3 scripts/merge_food_inspections.py
   ```

4. **Variants 2/3 only** — build the RAG index (downloads the PDF +
   county page, chunks, embeds locally, persists to `data/RAG/chroma/`):
   ```
   python3 app/rag/ingest.py
   ```
   This does not need the chat LLM at all — embeddings are local
   sentence-transformers. Re-run any time the sources change; it rebuilds
   the index from scratch (~1-2 min, no API costs).

5. **Variant 3 only** — build the violation-type map the ontology needs
   (`semantic/gen_ontology.json`'s `ViolationType` class calls for a
   hand-curated `semantic/violation_map.csv`, generated here via keyword
   rules over the actual data):
   ```
   python3 semantic/build_violation_map.py
   ```
   This is a first-pass heuristic (231 raw violation labels bucketed into
   6 ontology categories + `other`), not a final hand-curation — the
   output is plain CSV, edit it directly to correct misclassifications
   (sorted by frequency descending, so fixing the top rows covers the
   most inspections).

6. Run whichever variant you want:
   ```
   streamlit run app/dashboard.py       # Variant 1: CSV + ReAct only
   streamlit run app/dashboard_v2.py    # Variant 2: + RAG over regulations
   streamlit run app/dashboard_v3.py    # Variant 3: + ontology hypothesis/evidence
   ```
   Each opens in your browser (Streamlit defaults to `localhost:8501`, and
   picks the next free port automatically if you run more than one at
   once — e.g. `8502`, `8503`). You'll see the fixed safety-overview
   charts immediately; the chat box is below them. Variants 2/3 will show
   an error in place of the chat box instead of crashing if step 4 (RAG
   index) wasn't run — `st.chat_input` is disabled until the index loads.

   If a chat message errors out, the error text itself usually says
   whether it's a missing/invalid API key vs. `ollama serve` not running —
   that's the most common failure point on first run. Re-check `app/.env`
   against `app/.env.example` and step 2 above.

## Files

- `data_layer.py` — loads the merged CSV into an in-memory DuckDB view (`inspections`).
- `overview.py` — the 4 fixed overview charts, shared by all three dashboards.
- `tools.py` — CSV tools: `get_schema`, `run_sql`, `plot_chart`.
- `llm.py` — picks the chat model (Groq / Google / Ollama) from `app/.env`.
- `agent.py` / `agent_v2.py` / `agent_v3.py` — build the agent (LangChain `create_agent`) for each variant.
- `dashboard.py` / `dashboard_v2.py` / `dashboard_v3.py` — Streamlit entrypoints.
- `chat_utils.py` — shared helpers to invoke an agent and extract the answer + reasoning trace (`run_agent`), or the structured hypothesis/evidence response (`run_structured_agent`, variant 3).
- `rag_tool.py` — wraps the RAG retriever as a `retrieve_regulation` tool (variants 2/3).
- `rag/ingest.py` — builds the Chroma index from the two regulatory sources.
- `rag/retriever.py` — loads the persisted index at query time.
- `ontology.py` — loads `semantic/gen_ontology.json` + `semantic/violation_map.csv`; exposes the hypothesis guidance text (system prompt) and the `classify_violation` tool (variant 3).
- `schemas.py` — `HypothesisResponse`/`EvidenceItem` Pydantic models — variant 3's structured output shape, mirroring the ontology's Hypothesis/Evidence classes.

## Known limitations

- No review/sentiment data — safety signal only, in all three variants.
- Variant 1 has no regulatory grounding — can't cite rule text, only what's in the CSV.
- Variants 2/3's RAG corpus is 2 sources (SLC county page + the R392-100
  PDF). `adminrules.utah.gov`'s own hosting of the same rule was skipped —
  it's a JS-rendered SPA that 404s on direct fetch, and its content
  duplicates the PDF. See `data/RAG/sources.txt`.
- `semantic/violation_map.csv` is a keyword-rule first pass (see setup
  step 5) — expect some misclassified ViolationType buckets until it's
  hand-corrected.
- Variant 3's structured output (`response_format`) adds another way for
  a weak model to fail beyond tool-calling itself — if it can't produce a
  valid `HypothesisResponse`, `chat_utils.run_structured_agent` falls
  back to showing the last message as plain text with no hypothesis panel.
- Smaller/local models (Ollama tags like `qwen2.5:3b`, or Groq/Google's
  smallest free tiers) are noticeably weaker than large hosted models at
  native tool-calling — expect occasional malformed tool calls, a tool
  called with the wrong arguments, or an agent that loops without
  converging on a complex multi-step question.
