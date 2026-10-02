# Food Critic — an agentic visualization system for auditable restaurant-safety reasoning

Code for the paper **"Food Critic: An Agentic Visualization System for Auditable
Restaurant-Safety Reasoning"** (Arleth Salinas, Ishrat Jahan Eliza — University of Utah;
VisXGenAI workshop). Repo name: `food-health-viz`.

Food Critic pairs Salt Lake County Health Department (SLCHD) inspection records with Google
Local reviews and an LLM agent, and turns the agent's tool calls, retrieved regulation, and
typed evidence into an inspectable visual state, so users can audit claims instead of
accepting a fluent narrative.

## Grounding conditions (the experimental variable)

All three share the same core tools (schema lookup, read-only SQL, structured establishment
search, per-restaurant inspection history, chart rendering) and differ only in added grounding:

| Variant | Grounding | Entry point |
|---|---|---|
| **V1** | Database only (ReAct agent) | `app/dashboard.py` |
| **V2** | + regulatory retrieval (RAG over Utah R392-100 and SLCHD inspection docs) | `app/dashboard_v2.py` |
| **V3** | + ontology-guided structured output (hypothesis, confidence, typed supporting/undermining evidence) and the Reasoning view | `app/dashboard_v3.py` |

## Data

- **SLCHD inspections:** 1,341 establishment listings (dates, scores, critical/non-critical violations).
- **Google Local (Utah subset, UCSD):** 8,592 food-related places (metadata, ratings, reviews).
- Matched by name/address similarity + geographic distance (U.S. Census geocoder, OSM fallback)
  and loaded into a normalized DuckDB database. **Only 139 of 8,592 places (1.6%) have a matched
  inspection history** — a known coverage limit that bounds what the agent can safely claim.

## Interface

Streamlit app matching `frontend/sketches/`: an Explore view (filterable list + map, works
without the agent), a Data Overview tab (4 fixed charts computed from the DB), a chat panel,
and — V3 only — a Reasoning view with a tool-call timeline, candidate-set map, and evidence
glyphs per restaurant.

## Evaluation (summary)

A fixed script of 18 tasks / 21 turns (15 single-turn Q1–Q15 + three two-turn threads) was run
once per grounding condition with five LLMs (Claude Sonnet 5, Gemini 3.6 Flash, Groq Llama 3.3 70B,
GPT-5.6 Terra, Gemma 4 26B via Ollama): 303 runs, 275 without an API error. See the paper for
accuracy tables and failure analysis. The evaluation script, prompts, and rubric are described
as supplemental materials of the paper.

## Prerequisites

- Python 3.10+ (developed on 3.13), `git`
- ~1GB free disk (large review CSV + RAG index), internet for the first RAG build and model downloads
- An LLM provider key (Groq/Google are free) **or** a local [Ollama](https://ollama.com) install

## Setup

```bash
git clone https://github.com/arlethzuri/food-health-viz.git
cd food-health-viz
git checkout main            # if you only see another branch: git fetch origin first
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Getting the data** — `data/processed/review-Utah_food.csv` (730MB) is too big for git;
grab it from the shared Drive link, unzip, and place it at that exact path. Everything
else needed to run the app is already in the repo.

**Build the DB** (seconds, no internet):
```bash
python scripts/load_duckdb.py
```

**Set up an LLM provider:**
```bash
cp app/.env.example app/.env
```
Edit `app/.env` and fill in one provider — Groq (free key, default) or Google
(free key), or set `LLM_PROVIDER=ollama` for a local model (no key, needs
`ollama serve` running). Full details in `app/README.md`.

**Run the app:**
```bash
streamlit run app/dashboard.py       # V1
streamlit run app/dashboard_v2.py    # V2, needs: python3 app/rag/ingest.py first
streamlit run app/dashboard_v3.py    # V3, needs the RAG index too
```

**Never commit secrets.** `app/.env`, API keys, `.venv/`, and local agent/editor tooling
(`.agents/`, `.cursor/`, `.claude/`, `CLAUDE.md`) are gitignored — only `app/.env.example` is tracked.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pathspec 'main' did not match` | Run `git fetch origin`, then `git checkout main`. |
| `db/food_health.duckdb` not found | Run `python scripts/load_duckdb.py`. |
| Missing `review-Utah_food.csv` | Download from the shared Drive link (see above) into `data/processed/`. |
| V2/V3 can't find RAG index | Run `python3 app/rag/ingest.py` (takes a few minutes, needs internet). |
| LLM auth / "API key" errors | Check `app/.env` has the key for the provider set in `LLM_PROVIDER`. |
| Ollama connection refused | Start it with `ollama serve` and pull the model named in `OLLAMA_MODEL`. |
| Import errors after pulling | Activate the venv and re-run `pip install -r requirements.txt`. |

## Repo layout

| Path | What it is |
|---|---|
| `data/processed/clean_processed.ipynb` | The pipeline: SLCHD ↔ Google Local entity resolution, geocoding, builds every table in `data/final/`. |
| `data/final/` | Schema deliverable CSVs, loaded into `db/food_health.duckdb` by `scripts/load_duckdb.py`. |
| `data/processed/`, `data/ucsd_google_local/` | Inputs to the pipeline above (SLCHD scrape output, Google Local raw export). |
| `db/` | `food_health.duckdb` (built artifact — regenerate with `scripts/load_duckdb.py`) + `schema.dbml` (schema doc). |
| `scripts/` | `load_duckdb.py` (build the DB), `merge_food_inspections.py`, `gen_establishment_keys.py`, `collectors/slchd/` (SLCHD scraper — historical, already run once). |
| `semantic/` | `ontology.json` + `data_dictionary.json` (schema for an LLM agent), `violation_map.csv` (violation → normalized type, built by `build_violation_map.py`), `percentiles.json` (real percentile thresholds used by the ontology and the app's Strictness slider). |
| `app/` | Streamlit dashboards (`dashboard*.py`) + LangChain agents (`agent*.py`) + UI components (`components/`) — see `app/README.md`. |
| `frontend/` | UI sketches (`sketches/`) the app's layout is built from. |

**Known gap, not yet reconciled:** `scripts/merge_food_inspections.py` reads
`data/processed/slc/*.csv`, which no longer exists — `data/processed/merged_food_inspections.csv`
is currently a static artifact, not regenerable from source until that input is restored or rebuilt.

## Research notes (working notes, partly planned/future scope)

- *Research Questions* (as in the paper)
	- RQ1: How does domain grounding change an LLM agent's answers compared with a database-only reasoning and acting (ReAct) agent?
	- RQ2: How can an agent's reasoning be externalized as an inspectable visual state, including tool calls, candidate sets, regulatory evidence, and typed support or contradiction?

- *Data Sources*
	- Government data:
		- SLC health inspections
	- Sentiment:
		- (live later) ANY reviews (google, yelp, tripadvisor)
		- (live later) Reddit
	- Is listed on food delivery reviews/option
		- (live later)
	- Whatever restaurant details are available ([utah business entity search](https://businessregistration.utah.gov/)):
		- Whether restaurant has multiple locations
		- Age of restaurant
		- Any sibling restaurants
		- Cuisine type
		- Allergens and menu
		- Location of restaurant
	- Marketing presence:
		- News / Food Critique coverage
			- common crawl, google trends
	- Spatial/demographic context
		- US Census/ACS
		- OSM
- *Knowledge sources*
	- All knowledge sources will be organized with a hand-made ontology.
	- Fact tables (populated by data tables) 
	- Restaurant Reviews data (live later, (RAG knowledge base or may need to be solely based on what LLM can search for bc there's no free/open API))
	- Domain knowledge (RAG, e.g. some sections from textbooks/CDC reports about food safety, SLCHD documentation, cuisine knowledge)
	- some potential tools/knowledge sources:
		- [GI Detection and Extraction from reviews](https://arxiv.org/pdf/2503.09743)
		- [Food Label Analyzer for Personalized Health Risk Insights](https://ieeexplore.ieee.org/document/11199271)
- *Knowledge Organization*
	- create fact tables
	- create RAG with SLCHD inspection definitions
- *Analytics and Data Usage*
	- Evidence gathering via:
		- RAG feature using a prebuilt knowledge source.
		- Provide agent the tools for engaging in knowledge retrieval via searching.
		- Have agent identify relevant trends, correlations, sentiment. 
	- Hypothesis generation using hand-written ontology:
		- Report hypotheses to user and be able to explain to user how the agentic system arrived to those conclusions.
- *Visualization and Report Generation*:
	- word cloud or some other visual showing sentiment
	- traditional info vis (line plots, bar plots, scatter)
	- standardized report showing summary of results to user (still unsure what it looks like)
	- chat enabling user to continue line of questioning with agentic system
- *Evaluation*
	- We will compare agentic system using RAG + ontology + hypothesis/evidence pipeline versus agentic system only accessing data NO RAG, ontology, or hypothesis/evidence pipeline. To compare them we will give them the same prompt to obtain a one-shot response.
	- we'll compare agent's ability to reason on its own with provided data versus agent 'taught' how to use ontology, interpreting it's own visualizations, and/or how to speak about restaurants
- *Potential software/tools to use*
	- LLM APIs
		- for initial development
			- llama, gemma, gemini 2.5 flash... any free LLMs
			- or [sentencetransformer](https://sbert.net/)
		- for final deployment/testing
			- OpenAI, Claude...whatever is used 
	- Langchain
	- Python for data analysis
	- d3, or other VIS respected visualization tools
	- [RAG tutorial](https://huggingface.co/blog/ngxson/make-your-own-rag)
	- Knowledge base 
		- ontology written in json
		- knowledge graph stored in json/networkx?

## Citation

> A. Salinas and I. J. Eliza. *Food Critic: An Agentic Visualization System for Auditable
> Restaurant-Safety Reasoning.* University of Utah, VisXGenAI workshop.
