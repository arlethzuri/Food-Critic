# Food Critic — Variants 1, 2 & 3

Streamlit dashboards over `db/food_health.duckdb`: a results list + filter bar
+ map (Explore tab), a chat box backed by a ReAct-style agent (LangChain
`create_agent`) that can query the DB via SQL/structured search and render
charts on request, and — variant 3 only — a Reasoning tab (strictness slider,
timeline scrubber, map-step and evidence-glyph visualizations).

- **Variant 1** (`dashboard.py`) — DB access only, no domain grounding. RQ1
  baseline condition.
- **Variant 2** (`dashboard_v2.py`) — same, plus RAG over Utah's R392-100
  Food Service Sanitation Rule and SLC county's inspection-process page,
  so the agent can ground *why* something is a violation / what a rule
  requires, not just query counts.
- **Variant 3** (`dashboard_v3.py`) — same as variant 2, plus an
  ontology-guided hypothesis/evidence pipeline (`semantic/ontology.json`):
  the agent's final answer is structured, not free text — it must
  classify itself into one of a fixed set of hypothesis types (`safe_bet`,
  `health_risk_concern`, `improving_compliance`, `declining_compliance`,
  `repeat_critical_violator`, `no_inspection_data_available`,
  `well_reviewed`, `reputation_inspection_mismatch`,
  `limited_track_record`, or `none` for a plain lookup) and back it with
  typed evidence tagged to ontology concepts, each item citing the actual
  tool call it came from. This is what completes the RQ1 3-condition
  comparison (data-only / +RAG / +ontology+evidence) and is the direct
  answer to RQ2 (can the agent explain its reasoning in a checkable way).

## How to run

Full path from a clean checkout, in order (see the root `README.md` for the
one-time data/env setup — this assumes that's already done):

1. Pick an LLM provider — copy `app/.env.example` to `app/.env` and fill
   in one of:
   - **Groq** (default, `LLM_PROVIDER=groq`) — free tier, fast, good
     tool-calling. Get a key at https://console.groq.com/keys and set
     `GROQ_API_KEY`.
   - **Google** (`LLM_PROVIDER=google`) — free tier via AI Studio. Get a
     key at https://aistudio.google.com/apikey and set `GOOGLE_API_KEY`.
   - **Ollama** (`LLM_PROVIDER=ollama`, no key needed) — install
     [Ollama](https://ollama.com/download), then:
     ```
     ollama pull qwen2.5:7b
     ollama serve
     ```
     Set `OLLAMA_MODEL` in `app/.env` if you use a different tag.
     Smaller/local models are noticeably weaker than large hosted models
     at native tool-calling, and variant 3 additionally asks the model to
     produce structured output on top of tool-calling — expect more
     failures there with a small local model than with Groq/Google.

   See `app/llm.py` for the full provider/model logic and defaults.

2. **Variants 2/3 only** — build the RAG index (downloads the PDF +
   county page, chunks, embeds locally, persists to `data/RAG/chroma/` —
   gitignored, so this is a real step even on a fresh checkout):
   ```
   python3 app/rag/ingest.py
   ```
   This does not need the chat LLM at all — embeddings are local
   sentence-transformers (first run downloads the ~80MB `all-MiniLM-L6-v2`
   model). Re-run any time the sources change; it rebuilds the index from
   scratch (~1-2 min, no API costs).

3. Run whichever variant you want:
   ```
   streamlit run app/dashboard.py       # Variant 1: DB + ReAct only
   streamlit run app/dashboard_v2.py    # Variant 2: + RAG over regulations
   streamlit run app/dashboard_v3.py    # Variant 3: + ontology hypothesis/evidence
   ```
   Each opens in your browser (Streamlit defaults to `localhost:8501`, and
   picks the next free port automatically if you run more than one at
   once — e.g. `8502`, `8503`). The Explore tab (results/filters/map/chat)
   loads immediately; variants 2/3 disable `st.chat_input` instead of
   crashing if step 2 (RAG index) wasn't run.

   If a chat message errors out, the error text itself usually says
   whether it's a missing/invalid API key vs. `ollama serve` not running —
   that's the most common failure point on first run. Re-check `app/.env`
   against `app/.env.example` and step 1 above.

`semantic/violation_map.csv` (violation → normalized `ViolationType`,
variant 3) is already committed — only regenerate it with
`python3 semantic/build_violation_map.py` if you want to refresh the
keyword-rule classification after editing the rules in that script; hand
corrections to the CSV itself are otherwise preserved as-is.

## Files

- `data_layer.py` — read-only connection to `db/food_health.duckdb`.
- `overview.py` — the 4 fixed overview charts, shown in the Data overview tab.
- `tools.py` — DB tools: `get_schema`, `get_column_glossary`, `run_sql`, `search_establishments`, `get_inspection_history`, `plot_chart`.
- `llm.py` — picks the chat model (Groq / Google / Ollama) from `app/.env`.
- `agent.py` / `agent_v2.py` / `agent_v3.py` — build the agent (LangChain `create_agent`) for each variant.
- `dashboard.py` / `dashboard_v2.py` / `dashboard_v3.py` — Streamlit entrypoints (tabs: Explore, Reasoning [v3 only], Data overview).
- `components/` — `filters.py`, `map_view.py`, `results_list.py`, `baseline_search.py` (Explore tab), `reasoning_view.py` (v3 Reasoning tab), `restaurant_card.py` (detail card).
- `chat_utils.py` — shared helpers to invoke an agent and extract the answer + reasoning trace (`run_agent`), or the structured hypothesis/evidence response + timeline (`run_structured_agent`, variant 3).
- `rag_tool.py` — wraps the RAG retriever as a `retrieve_regulation` tool (variants 2/3).
- `rag/ingest.py` — builds the Chroma index from the two regulatory sources.
- `rag/retriever.py` — loads the persisted index at query time.
- `ontology.py` — loads `semantic/ontology.json` + `semantic/violation_map.csv`; exposes the hypothesis guidance text (system prompt) and the `classify_violation` tool (variant 3).
- `schemas.py` — `HypothesisResponse`/`EvidenceItem`/`CandidatePoolItem` Pydantic models — variant 3's structured output shape, mirroring the ontology's Hypothesis/Evidence classes.

## Known limitations

- Only 139/8,592 establishments have a matched SLCHD inspection history —
  review/rating data covers all of them, safety data doesn't. The agent is
  prompted to say so explicitly rather than imply a clean record.
- Variant 1 has no regulatory grounding — can't cite rule text, only what's in the DB.
- Variants 2/3's RAG corpus is 2 sources (SLC county page + the R392-100
  PDF). `adminrules.utah.gov`'s own hosting of the same rule was skipped —
  it's a JS-rendered SPA that 404s on direct fetch, and its content
  duplicates the PDF. See `data/RAG/sources.txt`.
- `semantic/violation_map.csv` is a keyword-rule first pass — expect some
  misclassified `ViolationType` buckets until it's hand-corrected.
- Variant 3's structured output (`response_format`) can fail to validate
  for a weaker/local model — `chat_utils.run_structured_agent` recovers a
  plain-text narrative from the model's raw attempt when that happens, and
  still surfaces the real tool-call trace in the Reasoning tab (candidate
  pool/timeline don't depend on the final structured-output step
  succeeding), but confidence is forced to `low` and hypothesis to `none`
  in that case.
- Smaller/local models (Ollama tags like `qwen2.5:3b`, or Groq/Google's
  smallest free tiers) are noticeably weaker than large hosted models at
  native tool-calling — expect occasional malformed tool calls, a tool
  called with the wrong arguments, or an agent that loops without
  converging on a complex multi-step question.
