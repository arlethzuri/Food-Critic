**sythesis of food agent proj (mvp)**

## `ontology-update` branch — what changed

Rebuilt the data pipeline into a normalized DuckDB schema (`db/food_health.duckdb`:
establishments, inspections, violations, violation_codes, reviews, ...), added the
semantic layer an LLM agent reads (`semantic/ontology.json` + `data_dictionary.json`),
and rebuilt `app/` on top of both — a Streamlit UI matching `frontend/sketches/`
(results/filters/map + chat, a Reasoning tab with strictness/timeline/evidence
visualizations, a restaurant detail card), across all 3 research variants (V1 data-only,
V2 +RAG, V3 +ontology hypothesis/evidence).

## Setup

```bash
conda env create -f environment.yml   # or: conda env update -f environment.yml --prune
conda activate food-health-viz
```

**Getting the data** — `data/processed/review-Utah_food.csv` (730MB) is too big for git;
grab it from the shared Drive link, unzip, and place it at that exact path. Everything
else needed to run the app is already in the repo.

**Build the DB** (seconds, no internet):
```bash
python scripts/load_duckdb.py
```

**Run the app** (needs an LLM provider — see `app/README.md` for Groq/Google/Ollama setup):
```bash
streamlit run app/dashboard.py       # V1
streamlit run app/dashboard_v2.py    # V2, needs: python3 app/rag/ingest.py first
streamlit run app/dashboard_v3.py    # V3, needs the RAG index too
```

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

- *Research Questions*
	- RQ1: Does an agent provided tooling, analytical guidance, and knowledge structure provide better suggestions for restaurants as opposed to an agent provided data only?
	- RQ2: Can an agent communicate how it uses provided analytical guidance and/or knowledge structures to a human and have a continued "conversation" with a human within this framework and does this provide clearer answers?

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